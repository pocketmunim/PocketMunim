import json
import uuid
from decimal import Decimal
from datetime import datetime, timedelta
from app.ai.ai_provider import execute_resilient_ai
from app.ai.schemas import AITransactionExtraction
from app.cache.category_cache import CategoryCacheManager
from app.services.bulk_transaction_service import BulkTransactionService
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply
from app.telegram.handlers.account_handler import AccountHandler
from app.telegram.handlers.callback_handler import CallbackHandler
from app.dao.pending_batch_dao import PendingBatchDAO

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

SYSTEM_PROMPT = """SYSTEM ROLE: You are the PocketMunim Enterprise NLP Extraction Engine. Your exclusive mandate is to extract financial data, commands, and intents from unstructured multi-lingual text (English, Hindi, Marathi, Hinglish) and output a STRICT, heavily nested JSON object. CRITICAL RULES (NON-NEGOTIABLE): 1. NO MATHEMATICS & NO SPLITTING: You are strictly forbidden from calculating totals, EMIs, balances, or splitting amounts. (e.g., 'paid 4000 split between 4' MUST be logged as a 4000/4 transaction). 2. NO HALLUCINATION: If a field is missing, return `null`. Never guess or assume default values. 3. MULTI-INTENT & SEQUENCING: A single message may contain multiple operations. Extract each as a separate object in the `transactions` array. Assign a chronological `execution_order`. 4. BULK DETECTION: If the user lists MORE THAN 1 item (e.g., 2 or more items in a list), set `metadata.bulk_operation = true` and `operation_type = "bulk"`. 5. UNKNOWN CATEGORIES: If you cannot confidently map an item to a standard category, set the transaction's `category` and `subcategory` to `null`, AND strictly set `metadata.category_lookup_required = true`. 6. LOAN PAYMENTS: A loan payment MUST generate two intents: an `expense` (to deduct the bank balance) in the `transactions` array, AND a `loan_payment` intent in the `loan` object. 7. EXACT DATES & CURRENCY: TODAY IS {CURRENT_DATE}. If no date is explicitly mentioned, ALWAYS assume the transaction occurred TODAY. Calculate relative dates strictly in YYYY-MM-DD. For "last month", "last year", or "last week", subtract exactly that interval from today. DO NOT default to the 1st of the month. 8. CLARIFICATION STRICTNESS: You MUST NOT set needs_clarification = true unless the AMOUNT is missing or Rule 12 applies. Never ask for missing accounts, categories, payment methods, or DATES. 9. JSON ONLY: Output NOTHING but valid JSON. No markdown wrappers. 10. PEER-TO-PEER TRANSFERS / INCOME SOURCES: If a user receives money (e.g., "got 10k from raj" or "received extra income of 50"), set intent to "income". If the source name/person is missing (e.g., generic "extra income" without a donor/company), you MUST set `needs_clarification = true` and `clarification_fields = ["source name"]`. 11. ACCOUNT ROUTING:      - If user specifies an account paid FROM (e.g., "bought milk from Kotak"), set `source_account` to "Kotak".     - If user specifies an account received INTO, set `destination_account`.     - If transfer between OWN accounts ("send 10k from SBI to Axis"), intent is `transfer_own`, `source_account` is "SBI", `destination_account` is "Axis". 12. GENERIC NAMES: If a transaction involves a person but uses a generic term (e.g., "friend", "brother", "mitra", "dost", "vendor") instead of a specific name, you MUST set `needs_clarification = true` and ask for the specific name. 13. PAST RECURRING: For inputs like "every month on 17th from jun 2025", set recurrence.enabled = true, extract frequency (e.g. 'monthly'), and set start_date strictly in YYYY-MM-DD. 14. FULL PROCESSING MANDATE (ANTI-LAZINESS): You MUST extract and process EVERY SINGLE ITEM provided in the user's input. Do NOT truncate, skip, stop early, or group items. If the user lists 50 items, your `transactions` array MUST contain exactly 50 objects. JSON OUTPUT SCHEMA:   "metadata": {     "raw_user_text": "string",     "operation_type": "enum: [single, bulk, mixed, command, query, unsupported]",     "language": "string",     "entry_source": "enum: [telegram, api, manual, ocr, voice, import]",     "bulk_operation": "boolean",     "category_lookup_required": "boolean",     "unsupported_chat": "boolean",     "account_required": "boolean"   },   "transactions": [     {       "client_transaction_id": "string or null",       "transaction_sequence": "integer",       "execution_order": "integer",       "intent": "enum: [expense, income, transfer_own, transfer_other]",       "amount": "float or null",       "original_currency": "string",       "normalized_currency": "string (default: INR)",       "merchant": "string or null",       "payment_method": "string or null",       "item": "string or null",       "quantity": "float or null",       "unit": "string or null",       "category": "string or null",       "subcategory": "string or null",       "matched_from": "string or null",       "source_account": "string or null",       "destination_account": "string or null",       "date": {         "raw_expression": "string",         "relative_date": "string or null",         "date_type": "string or null"       },       "recurrence": {         "enabled": "boolean",         "frequency": "string or null",         "start_date": "string or null",         "end_date": "string or null"       },       "future": {         "is_future": "boolean",         "budget_check_required": "boolean",         "should_save": "boolean"       },       "validation": {         "amount_valid": "boolean",         "date_valid": "boolean",         "item_valid": "boolean",         "account_valid": "boolean"       },       "duplicate_detection": {         "possible_duplicate": "boolean",         "duplicate_reference": "string or null"       },       "needs_clarification": "boolean",       "clarification_fields": ["array"],       "confidence": {         "intent_confidence": "float",         "amount_confidence": "float",         "date_confidence": "float",         "account_confidence": "float",         "overall_confidence": "float"       }     }   ],   "query": { "is_query": "boolean", "query_type": "string or null", "target": "string or null" },   "loan": { "intent": "string or null", "lender": "string or null", "amount": "float or null" },   "salary": { "intent": "string or null", "month": "string or null", "amount": "float or null" },   "account": { "intent": "string or null", "account_name": "string or null", "account_type": "string or null" },   "delete": { "intent": "string or null", "selection_mode": "string or null", "target_date": "string or null" },   "report": { "intent": "string or null", "format": "string or null", "period": "string or null" }"""

class NLPHandler:
    @staticmethod
    async def pull_categories(supabase_admin, chat_id, user_id, text, category_pull_service):
        query = text.replace("/categorypull", "").strip()
        await send_telegram_reply(chat_id, f"🔄 Pulling categories...")
        pull_result = category_pull_service.manual_category_pull(query, user_id)
        if pull_result.get("added", 0) > 0:
            CategoryCacheManager(supabase_admin, user_id).rebuild_cache()
            await send_telegram_reply(chat_id, f"✅ Successfully pulled {pull_result['added']} items.")
        else:
            await send_telegram_reply(chat_id, f"❌ Failed to pull categories: {pull_result.get('error')}")

    @staticmethod
    async def process_text(supabase_admin, supabase, chat_id, user_id, text, category_pull_service):
        try:
            current_dt = datetime.now(TZ_IST)
            dynamic_system_prompt = SYSTEM_PROMPT.replace(
                "{CURRENT_DATE}",
                f"{current_dt.strftime('%Y-%m-%d')} ({current_dt.strftime('%A')})"
            )
            raw_response_text = execute_resilient_ai(
                system_prompt=dynamic_system_prompt,
                user_prompt=text,
                db_client=supabase_admin,
                is_json=True
            )
            raw_json = json.loads(raw_response_text)
            validated_data = AITransactionExtraction(**raw_json)
            transactions_list = validated_data.transactions or []
            acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
            user_accounts = acc_res.data or []
            if not user_accounts and transactions_list:
                await send_telegram_reply(chat_id, "⚠️ *No Bank Accounts Configured*\nUse `/addaccount [BankName] [Balance]`")
                return
            if not transactions_list:
                await send_telegram_reply(chat_id, "⚠️ No valid financial transactions were extracted.")
                return
            cache_manager = CategoryCacheManager(supabase, user_id)
            # ================= BULK TRANSACTION PIPELINE =================
            if len(transactions_list) > 1:
                default_acc = AccountHandler.get_account_from_list(user_accounts)
                bulk_service = BulkTransactionService(supabase_admin, user_id, cache_manager, category_pull_service)
                result = bulk_service.process_bulk_payload(transactions_list, default_acc)
                if result["unique"]:
                    current_bal = float(default_acc['balance'])
                    total_deduction = sum(
                        p["amount"] for p in result["unique"] if p["source_account"] == default_acc['account_name'])
                    total_addition = sum(p["amount"] for p in result["unique"] if
                                         p["destination_account"] == default_acc['account_name'])
                    if (current_bal - total_deduction + total_addition) < 0:
                        await send_telegram_reply(chat_id, f"⚠️ *Insufficient Balance*")
                        return
                    bulk_service.dao.execute_bulk_commit(default_acc['id'], result["unique"], total_deduction,
                                                         total_addition, current_bal)
                    bd_text = "\n".join(result["breakdown"]) if result["breakdown"] else "No unique items."
                    receipt = (
                        f"🧾 *BULK TRANSACTION SAVED*\n"
                        f"🔴 *EXPENSE* | 🟢 *INCOME* | 🔵 *TRANSFER*\n\n"
                        f"📊 *Expenses:* ₹{result['totals']['expenses']:,.2f} ({result['counts'].get('expenses', 0)} items)\n"
                        f"📊 *Income:* ₹{result['totals']['income']:,.2f} ({result['counts'].get('income', 0)} items)\n"
                        f"📊 *Transfers:* ₹{result['totals']['transfers']:,.2f} ({result['counts'].get('transfers', 0)} items)\n\n"
                        f"🏦 *Primary Account:* {default_acc['account_name']}\n"
                        f"📜 *Receipt Breakdown:*\n{bd_text}"
                    )
                    if result.get("ignored"):
                        receipt += f"\n\n⚠️ *Ignored Items:*\n" + "\n".join(result["ignored"])
                    await send_telegram_reply(chat_id, receipt)
                if result.get("duplicates"):
                    batch_id = uuid.uuid4().hex[:8]
                    batch_dao = PendingBatchDAO(supabase_admin)
                    batch_dao.create_batch(batch_id, user_id, default_acc['id'], result["duplicates"])
                    keyboard = CallbackHandler.generate_duplicate_keyboard(batch_id, result["duplicates"])
                    await send_telegram_reply(
                        chat_id,
                        f"⚠️ *Duplicate Entries Found ({len(result['duplicates'])} items)*\nTap to select/save duplicates.",
                        reply_markup=keyboard
                    )
                return
            # ================= SINGLE TRANSACTION PIPELINE =================
            response_sections, committed_items = [], []
            for tx in transactions_list:
                amount = tx.amount if tx.amount else Decimal('0.00')
                description = str(tx.item or tx.merchant or text).title()
                if amount > Decimal('0.00'):
                    if tx.future and tx.future.is_future:
                        response_sections.append(f"🔮 '{description}' identified as future plan.")
                        continue
                    if not tx.intent or tx.needs_clarification:
                        missing_fields = ",".join(
                            tx.clarification_fields) if tx.clarification_fields else "Intent/Details"
                        response_sections.append(f"⚠️ Could not process '{description}'. Clarify: {missing_fields}")
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
                            current_bal = Decimal(str(source_acc_obj['balance']))
                            if current_bal < tot_amt:
                                response_sections.append(
                                    f"⚠️ *Insufficient Balance* in {source_acc_obj['account_name']}.")
                                continue
                            updates_to_make.append(
                                (source_acc_obj['id'], float(current_bal - tot_amt), "DEBIT", float(tot_amt)))
                        if dest_acc_obj:
                            updates_to_make.append(
                                (dest_acc_obj['id'], float(Decimal(str(dest_acc_obj['balance'])) + tot_amt), "CREDIT",
                                 float(tot_amt)))
                    for acc_id, new_bal, log_type, txn_amount in updates_to_make:
                        supabase_admin.table('accounts').update({"balance": new_bal}).eq("id", acc_id).execute()
                        try:
                            supabase_admin.table('account_logs').insert(
                                {"account_id": acc_id, "user_id": user_id, "log_type": log_type, "amount": txn_amount,
                                 "balance_after": new_bal, "description": description}).execute()
                        except:
                            pass
                    category = tx.category
                    subcategory = tx.subcategory
                    if not category:
                        cached = cache_manager.search_item(description)
                        if cached and cached.get("category"):
                            category, subcategory = cached["category"], cached.get("subcategory")
                        else:
                            ai_cls = category_pull_service.classify_item(description, intent=tx.intent)
                            category, subcategory = ai_cls.get("category", "General"), ai_cls.get("subcategory",
                                                                                                  "Miscellaneous")
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
                    except:
                        continue
                    committed_items.append(f"✅ *Transaction Saved*\n  {description}: ₹{float(amount):,.2f}")
            if committed_items:
                response_sections.append("\n\n".join(committed_items))
            if response_sections:
                await send_telegram_reply(chat_id, "\n\n".join(response_sections))
        except Exception as e:
            await send_telegram_reply(chat_id, f"Error processing text: {str(e)}")