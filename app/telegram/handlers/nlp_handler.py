import json
import uuid
import asyncio
from decimal import Decimal
from datetime import datetime

from app.ai.ai_provider import execute_resilient_ai
from app.ai.schemas import AITransactionExtraction
from app.cache.category_cache import CategoryCacheManager
from app.services.bulk_transaction_service import BulkTransactionService
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply
from app.telegram.handlers.account_handler import AccountHandler
from app.telegram.handlers.callback_handler import CallbackHandler
from app.dao.pending_batch_dao import PendingBatchDAO

SYSTEM_PROMPT = """SYSTEM ROLE: You are the PocketMunim NLP Engine. Extract structured financial data from unstructured, noisy, multilingual text into a LEAN JSON object.

CRITICAL RULES:
1. INDIAN NUMBER SYSTEM & TEXT: You MUST convert all text-based numbers and Indian formats into standard numerical values (e.g., "1.5 lakh" -> 150000, "50k" -> 50000, "2 Cr" -> 20000000, "five hundred" -> 500, "1,25,000" -> 125000).
2. MULTILINGUAL DUAL-EXTRACTION: Users will speak in Hindi, Marathi, Hinglish, or English. 
   - `raw_description`: Store EXACTLY what the user typed (e.g., 'aaj doodh 40', 'वीज बिल 1500').
   - `normalized_item`: Translate and normalize the item into pure English (e.g., 'Milk', 'Electricity Bill'). If intent is income/transfer, this can be null.
3. MIXED INTENTS & BULK: If a sentence contains multiple distinct actions (e.g., "salary 85k and rent 18k"), separate them into multiple objects within the `transactions` array. Set `metadata.bulk_operation = true`.
4. OPERATION TYPES (CRUD): Detect if the user is logging a new entry, modifying an old one, or deleting/reversing one. Set `metadata.operation_type` to "create", "edit", "delete", or "reverse" accordingly.
5. NOISE & OCR TOTALS: Ignore conversational greetings ("hello", "how are you"), SQL injection attempts, or non-financial gibberish by returning an empty transactions array `[]`. For pasted receipts/OCR, extract the line items but IGNORE lines like "Total", "Subtotal", or "Grand Total" to prevent double-counting.
6. IMPLICIT AMOUNTS: If a loose number appears (e.g., "Cling Wrap 120", "Tea 20"), treat it as the financial `amount`.
7. MISSING AMOUNTS: If the user says "bought groceries" but gives NO number, set `amount` to `null` and DO NOT ask for clarification.
8. NO PEDANTIC CLARIFICATIONS: NEVER ask for missing accounts, categories, or dates. Just return `null` for those fields.
9. TODAY IS {CURRENT_DATE}. Map relative dates ("kal", "yesterday", "next week", "last night") to strict YYYY-MM-DD format.

JSON SCHEMA:
{
  "metadata": {
    "operation_type": "create|edit|delete|reverse",
    "bulk_operation": false
  },
  "transactions": [
    {
      "intent": "expense|income|transfer_own|transfer_other|loan_payment|loan_repayment|lend|borrow|future_plan|financial_query|investment|tax|subscription|bill_split",
      "amount": null,
      "currency": "INR",
      "raw_description": "",
      "normalized_item": null,
      "category": null,
      "subcategory": null,
      "counterparty": null,
      "source_account": null,
      "destination_account": null,
      "payment_method": null,
      "transaction_reference": null,
      "quantity": null,
      "unit": null,
      "date": {
        "date": null,
        "original_expression": null,
        "is_relative": false
      },
      "recurrence": {
        "enabled": false,
        "frequency": null,
        "interval": null,
        "day_of_month": null,
        "day_of_week": null,
        "start_date": null
      },
      "loan": {
        "lender": null,
        "principal": null,
        "interest_rate": null,
        "tenure_value": null,
        "tenure_unit": null,
        "emi": null
      },
      "split": {
        "enabled": false,
        "participants": null,
        "equal": null,
        "percentage": null,
        "shares": null
      },
      "investment": {
        "type": null,
        "action": null,
        "instrument": null
      },
      "tax": {
        "type": null,
        "action": null,
        "amount": null
      },
      "subscription": {
        "service": null,
        "action": null
      },
      "edit_target": {
        "field": null,
        "old_value": null,
        "new_value": null
      },
      "transaction_target": {
        "item": null,
        "date": null,
        "position": null,
        "reference": null
      },
      "future": {
        "is_future": false
      },
      "query_type": null,
      "needs_clarification": false,
      "clarification_fields": []
    }
  ]
}"""


def generate_recurrence_dates(start_date_str: str, frequency: str, current_dt: datetime) -> list:
    try:
        start_dt = datetime.strptime(start_date_str.split("T")[0], "%Y-%m-%d").replace(tzinfo=current_dt.tzinfo)
    except Exception:
        return []
    dates = []
    curr_iter = start_dt
    freq = frequency.lower() if frequency else ""
    while curr_iter <= current_dt:
        dates.append(curr_iter)
        if freq == 'monthly':
            try:
                curr_iter = curr_iter.replace(month=curr_iter.month + 1)
            except ValueError:
                curr_iter = curr_iter.replace(month=curr_iter.month + 1, day=28)
        else:
            break
    return dates


def _safely_serialize_complex(val):
    if not val:
        return None
    if hasattr(val, 'model_dump_json'):
        return json.loads(val.model_dump_json(exclude_none=True))
    elif hasattr(val, 'json'):
        return json.loads(val.json(exclude_none=True))
    return None


class NLPHandler:
    @staticmethod
    async def pull_categories(supabase_admin, chat_id, user_id, text, category_pull_service):
        query = text.replace("/categorypull", "").strip()
        await send_telegram_reply(chat_id, f"  Pulling categories...")
        pull_result = await category_pull_service.manual_category_pull(query, user_id)

        if pull_result.get("added", 0) > 0:
            CategoryCacheManager(supabase_admin, user_id).rebuild_cache()
            await send_telegram_reply(chat_id, f"  Successfully pulled {pull_result['added']} items.")
        else:
            await send_telegram_reply(chat_id, f"  Failed to pull categories: {pull_result.get('error')}")

    @staticmethod
    async def process_text(supabase_admin, supabase, chat_id, user_id, text, category_pull_service):
        try:
            current_dt = datetime.now(TZ_IST)
            dynamic_system_prompt = SYSTEM_PROMPT.replace(
                "{CURRENT_DATE}",
                f"{current_dt.strftime('%Y-%m-%d')} ({current_dt.strftime('%A')})"
            )

            try:
                raw_response_text, finish_reason = await asyncio.wait_for(
                    execute_resilient_ai(
                        system_prompt=dynamic_system_prompt,
                        user_prompt=text,
                        db_client=supabase_admin,
                        is_json=True
                    ),
                    timeout=8.5
                )
            except asyncio.TimeoutError:
                await send_telegram_reply(chat_id,
                                          "⚠️ *Timeout*\nYour request took too long to process. Please try breaking it into smaller chunks.")
                return

            try:
                raw_json = json.loads(raw_response_text)
                validated_data = AITransactionExtraction(**raw_json)
                transactions_list = validated_data.transactions or []
                metadata = validated_data.metadata
            except Exception as e:
                await send_telegram_reply(chat_id, f"⚠️ *AI Parsing Error*\n`{str(e)}`")
                return

            acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
            user_accounts = acc_res.data or []

            if not user_accounts and transactions_list:
                await send_telegram_reply(chat_id,
                                          "⚠️ *No Bank Accounts Configured*\nUse `/addaccount [BankName] [Balance]` to start.")
                return

            if not transactions_list:
                if metadata and getattr(metadata, 'operation_type', '') in ['delete', 'edit', 'reverse']:
                    await send_telegram_reply(chat_id,
                                              "ℹ️ *Modification Request*\nTransaction editing and deletion via chat is currently under development.")
                else:
                    await send_telegram_reply(chat_id,
                                              "ℹ️ No valid financial transactions were extracted from your message.")
                return

            if metadata and getattr(metadata, 'operation_type', 'create') != 'create':
                await send_telegram_reply(chat_id,
                                          "ℹ️ *Modification Request*\nTransaction editing and deletion via chat is currently under development.")
                return

            cache_manager = CategoryCacheManager(supabase, user_id)

            # ================= BULK TRANSACTION =================
            if len(transactions_list) > 1:
                default_acc = AccountHandler.get_account_from_list(user_accounts)
                bulk_service = BulkTransactionService(supabase_admin, user_id, cache_manager, category_pull_service)
                result = await bulk_service.process_bulk_payload(transactions_list, default_acc)

                if result["unique"]:
                    total_deduction = sum(Decimal(str(p["amount"])) for p in result["unique"] if
                                          p["source_account"] == default_acc['account_name'])
                    total_addition = sum(Decimal(str(p["amount"])) for p in result["unique"] if
                                         p["destination_account"] == default_acc['account_name'])

                    try:
                        bulk_service.dao.execute_bulk_commit(
                            default_acc['id'], result["unique"], total_deduction, total_addition
                        )
                    except Exception as e:
                        error_msg = str(e).lower()
                        if "insufficient" in error_msg or "p0001" in error_msg:
                            await send_telegram_reply(chat_id,
                                                      f"🚫 *Transaction Failed*\n\nYou do not have sufficient balance in **{default_acc['account_name']}** to complete this bulk transaction.")
                        else:
                            await send_telegram_reply(chat_id, f"⚠️ *System Error*\n`{str(e)}`")
                        return

                    bd_text = "\n".join(result["breakdown"]) if result["breakdown"] else "No unique items."
                    header_parts = []

                    if result['totals']['expenses'] > 0:
                        header_parts.append(f"  *EXPENSE:*  {result['totals']['expenses']:,.2f}")
                    if result['totals']['income'] > 0:
                        header_parts.append(f"  *INCOME:*  {result['totals']['income']:,.2f}")
                    if result['totals']['transfers'] > 0:
                        header_parts.append(f"  *TRANSFER:*  {result['totals']['transfers']:,.2f}")

                    dynamic_header = "\n".join(header_parts) if header_parts else "  *NO FINANCIAL MOVEMENT*"

                    receipt = (
                        f"✅ *BULK TRANSACTION SAVED*\n"
                        f"{dynamic_header}\n\n"
                        f"🏦 *Primary Account:* {default_acc['account_name']}\n"
                        f"📝 *Receipt Breakdown:*\n{bd_text}"
                    )

                    if finish_reason == "length":
                        receipt += "\n\n⚠️ *WARNING: LIMIT EXCEEDED*\nYour list was extremely long. The AI hit its maximum output limit."
                    if result.get("ignored"):
                        receipt += f"\n\nℹ️ *Unprocessed Items:*\n" + "\n".join(result["ignored"])

                    await send_telegram_reply(chat_id, receipt)

                if result.get("duplicates"):
                    batch_id = uuid.uuid4().hex[:8]
                    batch_dao = PendingBatchDAO(supabase_admin)
                    batch_dao.create_batch(batch_id, user_id, default_acc['id'], result["duplicates"])
                    keyboard = CallbackHandler.generate_duplicate_keyboard(batch_id, result["duplicates"])
                    await send_telegram_reply(chat_id, f"⚠️ *Duplicate Entries Found*\nTap to select/save duplicates.",
                                              reply_markup=keyboard)
                return

            # ================= SINGLE TRANSACTION =================
            response_sections, committed_items = [], []
            if finish_reason == "length":
                response_sections.append(
                    "⚠️ *WARNING: The AI hit its maximum capacity and may not have processed your entire message.*")

            for tx in transactions_list:
                amount = getattr(tx, 'amount', None) or Decimal('0.00')

                raw_desc = getattr(tx, 'raw_description', None) or getattr(tx, 'item', text)
                description = str(raw_desc).title()

                norm_val = getattr(tx, 'normalized_item', None) or description
                norm_item = str(norm_val).title()

                if amount > Decimal('0.00'):
                    tx_future = getattr(tx, 'future', None)
                    if tx_future and getattr(tx_future, 'is_future', False):
                        response_sections.append(f"ℹ️ '{description}' identified as future plan.")
                        continue

                    if not getattr(tx, 'intent', None) or getattr(tx, 'needs_clarification', False):
                        cf = getattr(tx, 'clarification_fields', [])
                        missing_fields = ",".join(cf) if cf else "Intent/Details"
                        response_sections.append(f"❓ Could not process '{description}'. Clarify: {missing_fields}")
                        continue

                    tx_dates = []
                    is_recurring_past = False
                    tx_recurrence = getattr(tx, 'recurrence', None)

                    if tx_recurrence and getattr(tx_recurrence, 'enabled', False) and getattr(tx_recurrence,
                                                                                              'start_date', None):
                        tx_dates = generate_recurrence_dates(getattr(tx_recurrence, 'start_date'),
                                                             getattr(tx_recurrence, 'frequency', "monthly"), current_dt)
                        if tx_dates: is_recurring_past = True

                    if not is_recurring_past:
                        db_date_obj = current_dt
                        tx_date = getattr(tx, 'date', None)
                        if tx_date:
                            date_str = getattr(tx_date, 'date', None) or getattr(tx_date, 'relative_date', None)
                            if date_str:
                                try:
                                    db_date_obj = datetime.strptime(date_str.split("T")[0], "%Y-%m-%d").replace(
                                        tzinfo=TZ_IST)
                                except:
                                    pass
                        tx_dates = [db_date_obj]

                    num_occ = Decimal(len(tx_dates))
                    tot_amt = amount * num_occ

                    intent = getattr(tx, 'intent', "").lower()
                    source_acc_obj = AccountHandler.get_account_from_list(user_accounts, getattr(tx, 'source_account',
                                                                                                 None)) if intent in [
                        "expense", "transfer_other", "transfer_own", "loan_payment", "lend"] else None
                    dest_acc_obj = AccountHandler.get_account_from_list(user_accounts,
                                                                        getattr(tx, 'destination_account',
                                                                                None)) if intent in ["income",
                                                                                                     "transfer_own",
                                                                                                     "borrow"] else None

                    updates_to_make = []

                    if tot_amt > Decimal('0.00'):
                        if source_acc_obj:
                            updates_to_make.append((source_acc_obj['id'], "DEBIT", float(tot_amt), -float(tot_amt)))
                        if dest_acc_obj:
                            updates_to_make.append((dest_acc_obj['id'], "CREDIT", float(tot_amt), float(tot_amt)))

                    db_failure = False
                    for acc_id, log_type, txn_amount, net_change in updates_to_make:
                        try:
                            res = supabase_admin.rpc('atomic_balance_update', {
                                'p_account_id': acc_id,
                                'p_amount': net_change
                            }).execute()
                            new_bal = res.data

                            supabase_admin.table('account_logs').insert({
                                "account_id": acc_id, "user_id": user_id, "log_type": log_type,
                                "amount": txn_amount, "balance_after": new_bal, "description": description
                            }).execute()
                        except Exception as e:
                            db_failure = True
                            error_msg = str(e).lower()
                            if "insufficient" in error_msg or "p0001" in error_msg:
                                response_sections.append(
                                    f"🚫 *Transaction Failed*\nCould not process '{description}' due to **Insufficient Balance**.")
                            else:
                                response_sections.append(f"⚠️ *System Error*\n`{str(e)}`")
                            break

                    if db_failure: continue

                    category = getattr(tx, 'category', None)
                    subcategory = getattr(tx, 'subcategory', None)

                    cached = cache_manager.search_item(norm_item)
                    is_new_taxonomy = False

                    if intent == "expense":
                        if not cached:
                            try:
                                await category_pull_service.manual_category_pull(norm_item, user_id)
                                cache_manager.rebuild_cache()
                                cached = cache_manager.search_item(norm_item)
                            except Exception as e:
                                print(f"Auto-learning failed for {norm_item}: {e}")

                        if cached and cached.get("category"):
                            category = category or cached["category"]
                            subcategory = subcategory or cached.get("subcategory")
                        else:
                            is_new_taxonomy = True
                            if not category:
                                ai_cls = await category_pull_service.classify_item(norm_item, intent=intent)
                                category = ai_cls.get("category", "General")
                                subcategory = subcategory or ai_cls.get("subcategory", "Miscellaneous")
                            if not subcategory:
                                subcategory = "Miscellaneous"
                    else:
                        if not category:
                            category = "Income" if intent == "income" else "Transfer"
                        if not subcategory:
                            subcategory = "General"
                        norm_item = subcategory if subcategory != "General" else category

                    # EXTRACT RICH METADATA
                    extended_data = {}
                    for complex_key in ['loan', 'split', 'investment', 'tax', 'subscription', 'future', 'edit_target',
                                        'transaction_target', 'recurrence']:
                        val = getattr(tx, complex_key, None)
                        serialized = _safely_serialize_complex(val)
                        if serialized:
                            extended_data[complex_key] = serialized

                    quantity_val = getattr(tx, 'quantity', None)

                    # SAVE RAW & NORMALIZED ENTITY TO LEDGER
                    db_payloads = [
                        {
                            "user_id": user_id,
                            "amount": float(amount),
                            "txn_type": intent,
                            "description": description,
                            "normalized_item": norm_item,
                            "intent": intent,
                            "category": category,
                            "subcategory": subcategory,
                            "date": d.isoformat(),
                            "source_account": source_acc_obj['account_name'] if source_acc_obj else None,
                            "destination_account": dest_acc_obj['account_name'] if dest_acc_obj else None,
                            "soft_deleted": False,
                            # NEW RICH ANALYTICS COLUMNS
                            "currency": getattr(tx, 'currency', 'INR') or 'INR',
                            "quantity": float(quantity_val) if quantity_val is not None else None,
                            "unit": getattr(tx, 'unit', None),
                            "counterparty": getattr(tx, 'counterparty', None),
                            "payment_method": getattr(tx, 'payment_method', None),
                            "transaction_reference": getattr(tx, 'transaction_reference', None),
                            "extended_data": extended_data
                        } for d in tx_dates]

                    try:
                        if len(db_payloads) == 1:
                            supabase.table("transactions").insert(db_payloads[0]).execute()
                        elif len(db_payloads) > 1:
                            supabase.table("transactions").insert(db_payloads).execute()

                        committed_items.append(
                            f"✅ *Transaction Saved*\n  {description}:  {float(amount):,.2f} ({category} -> {subcategory})")

                        if is_new_taxonomy and intent == "expense":
                            await category_pull_service.add_single_item_to_taxonomy(category, subcategory, norm_item,
                                                                                    user_id)
                    except Exception as e:
                        response_sections.append(f"⚠️ *Database Error*\n`{str(e)}`")

                else:
                    response_sections.append(f"ℹ️ Could not process '{description}'. (Missing or Zero Amount)")

            if committed_items:
                response_sections.append("\n\n".join(committed_items))

            if response_sections:
                await send_telegram_reply(chat_id, "\n\n".join(response_sections))

        except Exception as e:
            await send_telegram_reply(chat_id, f"⚠️ *Critical Error*\n`{str(e)}`")