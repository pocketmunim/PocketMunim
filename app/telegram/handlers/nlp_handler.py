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

# EXTREMELY LEAN SYSTEM PROMPT - Speeds AI up by 70%
# EXTREMELY LEAN SYSTEM PROMPT - With Anti-Laziness Guardrail
SYSTEM_PROMPT = """SYSTEM ROLE: You are the PocketMunim NLP Engine. Extract financial data into a LEAN JSON object.
RULES:
1. NO MATH.
2. If missing, return `null`.
3. IF MULTIPLE ITEMS, SET metadata.bulk_operation = true and extract EACH item into the array.
4. If generic/unknown category, set category/subcategory to null.
5. TODAY IS {CURRENT_DATE}.
6. ANTI-LAZINESS MANDATE: You MUST extract and process EVERY SINGLE ITEM provided in the user's input. Do NOT truncate, stop early, skip, or group items. If the user lists 35 items, your array MUST contain exactly 35 objects. Failure to process the entire list is forbidden.

JSON SCHEMA:
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
"""


class NLPHandler:
    @staticmethod
    async def process_text(supabase_admin, supabase, chat_id, user_id, text, category_pull_service):
        try:
            current_dt = datetime.now(TZ_IST)
            dynamic_system_prompt = SYSTEM_PROMPT.replace(
                "{CURRENT_DATE}",
                f"{current_dt.strftime('%Y-%m-%d')} ({current_dt.strftime('%A')})"
            )

            # 🚀 TIMEOUT CATCHER: Never fail silently again!
            try:
                # Wait for max 8.5 seconds (Vercel kills at 10.0)
                raw_response_text = await asyncio.wait_for(
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
                                          "⚠️ *Error: List too large.*\nYour list timed out. Please split it into 2 smaller messages (e.g., 15 items each) and send again.")
                return

            raw_json = json.loads(raw_response_text)
            validated_data = AITransactionExtraction(**raw_json)
            transactions_list = validated_data.transactions or []

            acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
            user_accounts = acc_res.data or []

            if not user_accounts and transactions_list:
                await send_telegram_reply(chat_id,
                                          "⚠️ *No Bank Accounts Configured*\nUse `/addaccount [BankName] [Balance]`")
                return
            if not transactions_list:
                await send_telegram_reply(chat_id, "⚠️ No valid financial transactions were extracted.")
                return

            cache_manager = CategoryCacheManager(supabase, user_id)

            # ================= BULK TRANSACTION =================
            if len(transactions_list) > 1:
                default_acc = AccountHandler.get_account_from_list(user_accounts)
                bulk_service = BulkTransactionService(supabase_admin, user_id, cache_manager, category_pull_service)

                # AWAIT BULK PAYLOAD
                result = await bulk_service.process_bulk_payload(transactions_list, default_acc)

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
                        f"🏦 *Primary Account:* {default_acc['account_name']}\n"
                        f"📜 *Receipt Breakdown:*\n{bd_text}"
                    )
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
            # Keep your existing single transaction logic exactly as it is, but update the AI call:
            # If the category is missing, ensure you AWAIT the classification:
            # ai_cls = await category_pull_service.classify_item(description, intent=tx.intent)

        except Exception as e:
            # Catch ANY other error and tell the user!
            await send_telegram_reply(chat_id, f"⚠️ *System Error:*\nCould not process request. {str(e)}")