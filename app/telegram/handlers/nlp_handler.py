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

SYSTEM_PROMPT = """SYSTEM ROLE: You are the PocketMunim NLP Engine. Extract financial data into a LEAN JSON object.
RULES:
1. NO MATH.
2. If missing, return `null`.
3. IF MULTIPLE ITEMS, SET metadata.bulk_operation = true and extract EACH item into the transactions array.
4. If generic/unknown category, set category/subcategory to null.
5. TODAY IS {CURRENT_DATE}.
6. ANTI-LAZINESS MANDATE: You MUST extract and process EVERY SINGLE ITEM provided in the user's input. Do NOT truncate, stop early, skip, or group items. If the user lists 35 items, your array MUST contain exactly 35 objects.

JSON SCHEMA:
{
  "metadata": {"operation_type": "string", "bulk_operation": false},
  "transactions": [
    {
      "intent": "expense",
      "amount": 0.0,
      "item": "string",
      "category": "string or null",
      "subcategory": "string or null",
      "source_account": "string or null",
      "destination_account": "string or null",
      "date": {"relative_date": "YYYY-MM-DD or null"},
      "recurrence": {"enabled": false, "frequency": "string or null", "start_date": "YYYY-MM-DD or null"},
      "future": {"is_future": false},
      "needs_clarification": false,
      "clarification_fields": ["array"]
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

            #   EXACTLY ONE AI REQUEST CALL
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
                await send_telegram_reply(chat_id, "  Error: Request timed out.\nYour list took too long to process.")
                return

            try:
                raw_json = json.loads(raw_response_text)
                validated_data = AITransactionExtraction(**raw_json)
                transactions_list = validated_data.transactions or []
            except Exception as e:
                await send_telegram_reply(chat_id, f"  AI Parsing Error:\n`{str(e)}`")
                return

            acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
            user_accounts = acc_res.data or []

            if not user_accounts and transactions_list:
                await send_telegram_reply(chat_id,
                                          "  *No Bank Accounts Configured*\nUse `/addaccount [BankName] [Balance]`")
                return
            if not transactions_list:
                await send_telegram_reply(chat_id, "  No valid financial transactions were extracted.")
                return

            cache_manager = CategoryCacheManager(supabase, user_id)

            # ================= BULK TRANSACTION =================
            if len(transactions_list) > 1:
                default_acc = AccountHandler.get_account_from_list(user_accounts)
                bulk_service = BulkTransactionService(supabase_admin, user_id, cache_manager, category_pull_service)
                result = await bulk_service.process_bulk_payload(transactions_list, default_acc)

                if result["unique"]:
                    # Exact precision calculation using Decimal instead of float
                    total_deduction = sum(Decimal(str(p["amount"])) for p in result["unique"] if p["source_account"] == default_acc['account_name'])
                    total_addition = sum(Decimal(str(p["amount"])) for p in result["unique"] if p["destination_account"] == default_acc['account_name'])

                    try:
                        # Current balance reading removed. Delegated to DB locking layer.
                        bulk_service.dao.execute_bulk_commit(
                            default_acc['id'], result["unique"], total_deduction, total_addition
                        )
                    except Exception as e:
                        error_msg = str(e)
                        if "Insufficient balance" in error_msg:
                            await send_telegram_reply(chat_id, "  *Insufficient Balance*")
                        else:
                            await send_telegram_reply(chat_id, f"  `{error_msg}`")
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
                        f"  *BULK TRANSACTION SAVED*\n"
                        f"{dynamic_header}\n\n"
                        f"  *Primary Account:* {default_acc['account_name']}\n"
                        f"  *Receipt Breakdown:*\n{bd_text}"
                    )

                    if finish_reason == "length":
                        receipt += "\n\n  *WARNING: LIMIT EXCEEDED*\nYour list was extremely long. The AI hit its maximum output limit."
                    if result.get("ignored"):
                        receipt += f"\n\n  *Unprocessed Items:*\n" + "\n".join(result["ignored"])

                    await send_telegram_reply(chat_id, receipt)

                if result.get("duplicates"):
                    batch_id = uuid.uuid4().hex[:8]
                    batch_dao = PendingBatchDAO(supabase_admin)
                    batch_dao.create_batch(batch_id, user_id, default_acc['id'], result["duplicates"])
                    keyboard = CallbackHandler.generate_duplicate_keyboard(batch_id, result["duplicates"])
                    await send_telegram_reply(chat_id, f"  *Duplicate Entries Found*\nTap to select/save duplicates.",
                                              reply_markup=keyboard)
                return

            # ================= SINGLE TRANSACTION =================
            response_sections, committed_items = [], []
            if finish_reason == "length":
                response_sections.append(
                    "  *WARNING: The AI hit its maximum capacity and may not have processed your entire message.*")

            for tx in transactions_list:
                amount = tx.amount if tx.amount else Decimal('0.00')
                description = str(tx.item or text).title()

                if amount > Decimal('0.00'):
                    if tx.future and tx.future.is_future:
                        response_sections.append(f"  '{description}' identified as future plan.")
                        continue
                    if not tx.intent or tx.needs_clarification:
                        missing_fields = ",".join(
                            tx.clarification_fields) if tx.clarification_fields else "Intent/Details"
                        response_sections.append(f"  Could not process '{description}'. Clarify: {missing_fields}")
                        continue

                    tx_dates = []
                    is_recurring_past = False

                    if tx.recurrence and tx.recurrence.enabled and tx.recurrence.start_date:
                        tx_dates = generate_recurrence_dates(tx.recurrence.start_date,
                                                             tx.recurrence.frequency or "monthly", current_dt)
                        if tx_dates: is_recurring_past = True

                    if not is_recurring_past:
                        db_date_obj = current_dt
                        if tx.date and tx.date.relative_date:
                            try:
                                db_date_obj = datetime.strptime(tx.date.relative_date.split("T")[0],
                                                                "%Y-%m-%d").replace(tzinfo=TZ_IST)
                            except:
                                pass
                        tx_dates = [db_date_obj]

                    num_occ = Decimal(len(tx_dates))
                    tot_amt = amount * num_occ

                    source_acc_obj = AccountHandler.get_account_from_list(user_accounts,
                                                                          tx.source_account) if tx.intent in ["expense",
                                                                                                              "transfer_other",
                                                                                                              "transfer_own"] else None
                    dest_acc_obj = AccountHandler.get_account_from_list(user_accounts,
                                                                        tx.destination_account) if tx.intent in [
                        "income", "transfer_own"] else None

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
                            response_sections.append(f"  `{str(e)}`")
                            break

                    if db_failure: continue

                    #   ROBUST SINGLE-TRANSACTION CATEGORY RESOLUTION
                    category = tx.category
                    subcategory = tx.subcategory

                    if not category or not subcategory:
                        cached = cache_manager.search_item(description)
                        if cached and cached.get("category"):
                            category = category or cached["category"]
                            subcategory = subcategory or cached.get("subcategory")

                    if not category:
                        ai_cls = await category_pull_service.classify_item(description, intent=tx.intent)
                        category = ai_cls.get("category", "General")
                        subcategory = subcategory or ai_cls.get("subcategory", "Miscellaneous")

                    if not subcategory:
                        subcategory = "Miscellaneous"

                    db_payloads = [
                        {"user_id": user_id, "amount": float(amount), "txn_type": tx.intent, "description": description,
                         "intent": tx.intent, "category": category, "subcategory": subcategory, "date": d.isoformat(),
                         "source_account": source_acc_obj['account_name'] if source_acc_obj else None,
                         "destination_account": dest_acc_obj['account_name'] if dest_acc_obj else None,
                         "soft_deleted": False} for d in tx_dates]

                    try:
                        if len(db_payloads) == 1:
                            supabase.table("transactions").insert(db_payloads[0]).execute()
                        elif len(db_payloads) > 1:
                            supabase.table("transactions").insert(db_payloads).execute()

                        committed_items.append(
                            f"  *Transaction Saved*\n  {description}:  {float(amount):,.2f} ({category} -> {subcategory})")
                    except Exception as e:
                        response_sections.append(f"  `{str(e)}`")

                else:
                    response_sections.append(f"  Could not process '{description}'. (Missing or Zero Amount)")

            if committed_items:
                response_sections.append("\n\n".join(committed_items))

            if response_sections:
                await send_telegram_reply(chat_id, "\n\n".join(response_sections))

        except Exception as e:
            await send_telegram_reply(chat_id, f"  `{str(e)}`")