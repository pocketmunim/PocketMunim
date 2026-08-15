import os
import json
import uuid
import asyncio
from decimal import Decimal
from datetime import datetime
from qstash import QStash

from app.ai.ai_provider import execute_resilient_ai
from app.ai.schemas import AITransactionExtraction
from app.ai.prompt_registry import PromptRegistry
from app.cache.category_cache import CategoryCacheManager
from app.services.bulk_transaction_service import BulkTransactionService
from app.utils.constants import TZ_IST

from app.interfaces.notification_gateway import TelegramNotificationAdapter
from app.telegram.handlers.account_handler import AccountHandler
from app.telegram.handlers.callback_handler import CallbackHandler
from app.dao.pending_batch_dao import PendingBatchDAO
from app.dao.bulk_transaction_dao import BulkTransactionDAO


class NLPHandler:
    @staticmethod
    async def handle_duplicate_timeout(supabase_admin, batch_id: str, chat_id: str, message_id: int):
        batch_dao = PendingBatchDAO(supabase_admin)
        batch = batch_dao.get_batch(batch_id)

        if batch:
            items = batch.get("items", [])
            batch_dao.delete_batch(batch_id)

            gateway = TelegramNotificationAdapter()
            await gateway.edit_message(
                chat_id,
                message_id,
                "⏳ *Duplicate Confirmation Expired*\n_No action taken within 1 minute._"
            )

            if items:
                discarded_text = "\n".join([f"• {i['desc']} (₹{float(i['amount']):,.2f})" for i in items])
                if len(discarded_text) > 3000:
                    discarded_text = discarded_text[:3000] + "\n... [Truncated]"

                await gateway.send_message(
                    chat_id,
                    f"❌ *Automatically Discarded (Timeout):*\n{discarded_text}"
                )

    @staticmethod
    async def process_text(supabase_admin, supabase, chat_id, user_id, text, category_pull_service, request_url=""):
        gateway = TelegramNotificationAdapter()

        def get_progress_ui(pct: int, phase: str) -> str:
            filled = int(pct / 10)
            neon_gradient = ["🟣", "🟣", "🔵", "🔵", "🩵", "🟢", "🟢", "🟡", "🟠", "🔴"]
            active_leds = "".join(neon_gradient[:filled])
            unlit_track = "⚫" * (10 - filled)
            return f"⚡ *PocketMunim AI*\n_{phase}_\n\n{active_leds}{unlit_track} `{pct}%`"

        status_msg_id = await gateway.send_message(
            str(chat_id),
            get_progress_ui(10, "Reading your message...")
        )

        try:
            current_dt = datetime.now(TZ_IST)
            dynamic_system_prompt = PromptRegistry.NLP_CONSTITUTION.replace(
                "{CURRENT_DATE}",
                f"{current_dt.strftime('%Y-%m-%d')} ({current_dt.strftime('%A')})"
            )

            lines = [line.strip() for line in text.split('\n') if line.strip()]
            CHUNK_SIZE = 10
            chunks = ["\n".join(lines[i:i + CHUNK_SIZE]) for i in range(0, len(lines), CHUNK_SIZE)] if len(
                lines) > CHUNK_SIZE else [text]

            transactions_list = []
            failed_chunks = 0
            total_chunks = len(chunks)

            async def fetch_chunk(chunk_str):
                try:
                    raw_response_text, finish_reason = await execute_resilient_ai(
                        system_prompt=dynamic_system_prompt,
                        user_prompt=chunk_str,
                        db_client=supabase_admin,
                        is_json=True
                    )
                    raw_json = json.loads(raw_response_text)
                    return AITransactionExtraction(**raw_json)
                except Exception as e:
                    return e

            results = await asyncio.gather(*[fetch_chunk(c) for c in chunks])

            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    failed_chunks += 1
                    print(f"Chunk AI Error: {res}")
                elif res and res.transactions:
                    transactions_list.extend(res.transactions)

                if status_msg_id:
                    progress_pct = 10 + int(((i + 1) / total_chunks) * 60)
                    await gateway.edit_message(str(chat_id), status_msg_id,
                                               get_progress_ui(progress_pct, "Analyzing transactions..."))

            # --- EXPLICIT INTENT & PARAMETER ERROR HANDLING ---
            if not transactions_list:
                if status_msg_id:
                    await gateway.delete_message(str(chat_id), status_msg_id)
                await gateway.send_message(
                    str(chat_id),
                    "❌ *Transaction Error: Missing Financial Intent*\n"
                    "The AI could not parse a valid transaction from your message.\n\n"
                    "🔍 *Missing Intent / Parameters:*\n"
                    "• Amount (e.g., `₹500`)\n"
                    "• Action / Context (e.g., `paid`, `spent`, `salary`)\n\n"
                    "💡 *Example:* `Paid Sushma 500`"
                )
                return

            valid_transactions = []
            for tx in transactions_list:
                amt = getattr(tx, 'amount', None)
                intent = getattr(tx, 'intent', '').lower()
                norm_item_val = getattr(tx, 'normalized_item', getattr(tx, 'item', text)).title()

                if intent == "unrecognized":
                    if status_msg_id:
                        await gateway.delete_message(str(chat_id), status_msg_id)
                    amt_display = f" (₹{float(amt):,.2f})" if amt and Decimal(str(amt)) > 0 else ""
                    await gateway.send_message(
                        str(chat_id),
                        f"❌ *Clarification Needed*\nI noticed '{norm_item_val}'{amt_display}, but I don't recognize this word or acronym. Could you please clarify what this transaction was for?"
                    )
                    return

                if amt is None or Decimal(str(amt)) <= Decimal('0.00'):
                    if status_msg_id:
                        await gateway.delete_message(str(chat_id), status_msg_id)
                    await gateway.send_message(
                        str(chat_id),
                        f"❌ *Transaction Error: Missing Amount*\n"
                        f"Target Mentioned: _{text}_\n\n"
                        f"🔍 *Missing Intent / Parameters:*\n"
                        f"• Amount is required (e.g., `Paid Sushma 500`)\n\n"
                        f"💡 Please specify how much was paid or received."
                    )
                    return
                valid_transactions.append(tx)

            transactions_list = valid_transactions
            # --------------------------------------------------

            acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
            user_accounts = acc_res.data or []

            if not user_accounts:
                if status_msg_id:
                    await gateway.delete_message(str(chat_id), status_msg_id)
                await gateway.send_message(str(chat_id),
                                           "❌ *No Bank Accounts Configured*\nUse `/addaccount [BankName] [Balance]`")
                return

            cache_manager = CategoryCacheManager(supabase, user_id)

            if status_msg_id:
                await gateway.edit_message(str(chat_id), status_msg_id, get_progress_ui(80, "Organizing categories..."))

            # ==========================================
            # BULK PROCESSING BRANCH
            # ==========================================
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
                        if status_msg_id:
                            await gateway.edit_message(str(chat_id), status_msg_id,
                                                       get_progress_ui(90, "Saving to your ledger..."))
                            await asyncio.sleep(0.3)

                        bulk_service.dao.execute_bulk_commit(default_acc['id'], result["unique"], total_deduction,
                                                             total_addition)

                        if status_msg_id:
                            await gateway.edit_message(str(chat_id), status_msg_id,
                                                       get_progress_ui(100, "Finalizing..."))
                            await asyncio.sleep(0.3)

                    except Exception as e:
                        await gateway.send_message(str(chat_id), f"⚠️ Bulk Transaction Failed: `{str(e)}`")
                        if status_msg_id:
                            await gateway.delete_message(str(chat_id), status_msg_id)
                        return

                    bd_text = "\n".join(result["breakdown"][:40]) if result["breakdown"] else "None"
                    if len(result["breakdown"]) > 40:
                        bd_text += f"\n... and {len(result['breakdown']) - 40} more items."

                    warning = f"\n\n⚠️ *Taxonomy DB Error*: `{result['taxonomy_error']}`" if result.get(
                        'taxonomy_error') else ""
                    if failed_chunks > 0:
                        warning += f"\n⚠️ *Data Loss*: {failed_chunks} text blocks were dropped due to AI rate limiting."

                    receipt = (
                        f"✅ *BULK TRANSACTION SAVED*\n"
                        f"📊 Unique Items: {len(result['unique'])}\n"
                        f"🏦 Primary Account: {default_acc['account_name']}\n\n"
                        f"*Breakdown:*\n{bd_text}{warning}"
                    )
                    await gateway.send_message(str(chat_id), receipt)

                if result.get("duplicates"):
                    batch_id = uuid.uuid4().hex[:8]
                    batch_dao = PendingBatchDAO(supabase_admin)

                    if len(result["duplicates"]) > 30:
                        await gateway.send_message(
                            str(chat_id),
                            f"⚠️ *{len(result['duplicates'])} Duplicate Items Found*\nTo protect Telegram interface limits, this massive block of duplicates has been automatically discarded. Please verify your ledger."
                        )
                    else:
                        batch_dao.create_batch(batch_id, user_id, default_acc['id'], result["duplicates"])
                        keyboard = CallbackHandler.generate_duplicate_keyboard(batch_id, result["duplicates"])
                        dup_msg_id = await gateway.send_message(str(chat_id),
                                                                "⚠️ *Duplicate Items Found*\nTap below to select duplicates to keep (Expires in 1 min):",
                                                                reply_markup=keyboard)

                        if dup_msg_id:
                            qstash_token = os.getenv("QSTASH_TOKEN")
                            if qstash_token and request_url:
                                client = QStash(qstash_token)
                                base_url = str(request_url).split('/webhook')[0].split('/process-task')[0]
                                try:
                                    client.message.publish_json(
                                        url=f"{base_url}/process-task",
                                        body={
                                            "internal_task": "duplicate_timeout",
                                            "batch_id": batch_id,
                                            "chat_id": str(chat_id),
                                            "message_id": dup_msg_id
                                        },
                                        delay="60s",
                                        headers={"x-pocketmunim-user": user_id}
                                    )
                                except Exception as e:
                                    print(f"Failed to queue QStash timeout: {e}")

                if status_msg_id:
                    await gateway.delete_message(str(chat_id), status_msg_id)
                return

            # ==========================================
            # SINGLE TRANSACTION PROCESSING BRANCH
            # ==========================================
            tx = transactions_list[0]
            amount = getattr(tx, 'amount', None) or Decimal('0.00')
            raw_desc = getattr(tx, 'raw_description', None) or getattr(tx, 'item', text)
            description = str(raw_desc).title()
            norm_val = getattr(tx, 'normalized_item', None) or description
            norm_item = str(norm_val).title()

            tx_date_obj = getattr(tx, 'date', None)
            final_date_iso = current_dt.isoformat()
            if tx_date_obj and getattr(tx_date_obj, 'date', None):
                try:
                    parsed_date = datetime.strptime(tx_date_obj.date, "%Y-%m-%d").date()
                    final_date_iso = current_dt.replace(year=parsed_date.year, month=parsed_date.month,
                                                        day=parsed_date.day).isoformat()
                except ValueError:
                    pass

            intent = getattr(tx, 'intent', 'expense').lower()
            tx_future = getattr(tx, 'future', None)

            if (tx_future and getattr(tx_future, 'is_future', False)) or intent in ['future_plan', 'financial_query']:
                await gateway.send_message(
                    str(chat_id),
                    f"🔮 *Financial Planning*\nThis looks like a future plan or budget query: {norm_item} (₹{float(amount):,.2f}). Future transactions are not saved to the historical ledger."
                )
                if status_msg_id:
                    await gateway.delete_message(str(chat_id), status_msg_id)
                return

            if amount > Decimal('0.00'):
                # --- TRANSFER HANDLING ---
                if intent in ["transfer_own", "transfer"]:
                    src_name = getattr(tx, 'source_account', None)
                    dst_name = getattr(tx, 'destination_account', None)

                    src_acc = AccountHandler.get_account_from_list(user_accounts, src_name)
                    dst_acc = AccountHandler.get_account_from_list(user_accounts, dst_name)

                    if not src_acc or not dst_acc:
                        await gateway.send_message(str(chat_id),
                                                   f"❌ Could not complete transfer. Ensure both accounts exist.")
                        if status_msg_id:
                            await gateway.delete_message(str(chat_id), status_msg_id)
                        return

                    if src_acc['id'] == dst_acc['id']:
                        await gateway.send_message(str(chat_id),
                                                   f"❌ Source and destination accounts cannot be the same.")
                        if status_msg_id:
                            await gateway.delete_message(str(chat_id), status_msg_id)
                        return

                    src_bal = Decimal(str(src_acc['balance']))
                    if src_bal < amount:
                        await gateway.send_message(str(chat_id),
                                                   f"❌ Insufficient balance in {src_acc['account_name']} (Current: ₹{src_bal:,.2f}).")
                        if status_msg_id:
                            await gateway.delete_message(str(chat_id), status_msg_id)
                        return

                    if status_msg_id:
                        await gateway.edit_message(str(chat_id), status_msg_id,
                                                   get_progress_ui(90, "Saving to your ledger..."))
                        await asyncio.sleep(0.3)

                    new_src_bal = supabase_admin.rpc('atomic_balance_update', {'p_account_id': src_acc['id'],
                                                                               'p_amount': -float(
                                                                                   amount)}).execute().data
                    new_dst_bal = supabase_admin.rpc('atomic_balance_update', {'p_account_id': dst_acc['id'],
                                                                               'p_amount': float(
                                                                                   amount)}).execute().data

                    supabase.table("transactions").insert({
                        "user_id": user_id, "amount": float(amount), "txn_type": "transfer_own",
                        "description": f"Transfer from {src_acc['account_name']} to {dst_acc['account_name']}",
                        "normalized_item": "Account Transfer", "intent": "transfer_own",
                        "category": "Transfer", "subcategory": "Self Transfer", "date": final_date_iso,
                        "source_account": src_acc['account_name'], "destination_account": dst_acc['account_name'],
                        "soft_deleted": False
                    }).execute()

                    supabase_admin.table('account_logs').insert([
                        {"account_id": src_acc['id'], "user_id": user_id, "log_type": "DEBIT", "amount": float(amount),
                         "balance_after": new_src_bal, "description": f"Transfer to {dst_acc['account_name']}"},
                        {"account_id": dst_acc['id'], "user_id": user_id, "log_type": "CREDIT", "amount": float(amount),
                         "balance_after": new_dst_bal, "description": f"Transfer from {src_acc['account_name']}"}
                    ]).execute()

                    if status_msg_id:
                        await gateway.edit_message(str(chat_id), status_msg_id, get_progress_ui(100, "Finalizing..."))
                        await asyncio.sleep(0.3)
                        await gateway.delete_message(str(chat_id), status_msg_id)

                    await gateway.send_message(
                        str(chat_id),
                        f"🔄 *Transfer Successful*\nTransferred ₹{float(amount):,.2f} from *{src_acc['account_name']}* to *{dst_acc['account_name']}*.\n\n"
                        f"🏦 {src_acc['account_name']} Balance: ₹{new_src_bal:,.2f}\n"
                        f"🏦 {dst_acc['account_name']} Balance: ₹{new_dst_bal:,.2f}"
                    )
                    return

                # --- STANDARD EXPENSE / INCOME HANDLING ---
                is_debit = intent in ["expense", "transfer_other", "loan_payment", "lend"]
                is_credit = intent in ["income", "borrow"]

                extracted_acc_name = getattr(tx, 'source_account', None) if is_debit else getattr(tx,
                                                                                                  'destination_account',
                                                                                                  None)
                target_acc = None

                if extracted_acc_name:
                    target_acc = AccountHandler.get_account_from_list(user_accounts, extracted_acc_name)
                    if not target_acc:
                        await gateway.send_message(str(chat_id),
                                                   f"❌ *Transaction Failed*\nAccount '{extracted_acc_name}' does not exist.")
                        if status_msg_id:
                            await gateway.delete_message(str(chat_id), status_msg_id)
                        return
                else:
                    target_acc = AccountHandler.get_account_from_list(user_accounts)

                if is_debit and Decimal(str(target_acc['balance'])) < amount:
                    await gateway.send_message(str(chat_id),
                                               f"❌ *Transaction Failed*\nInsufficient balance in {target_acc['account_name']} (Current: ₹{float(target_acc['balance']):,.2f}).")
                    if status_msg_id:
                        await gateway.delete_message(str(chat_id), status_msg_id)
                    return

                cached_item = cache_manager.search_item(norm_item)
                primary_cat = getattr(tx, 'category', None)
                primary_sub = getattr(tx, 'subcategory', None)
                category = None
                subcategory = None
                taxonomy_err = None

                if cached_item:
                    category = cached_item.get("category")
                    subcategory = cached_item.get("subcategory")
                else:
                    if primary_cat and primary_sub and primary_cat.lower() != primary_sub.lower() and primary_cat.lower() not in [
                        "general", "miscellaneous", "unclassified", "uncategorized"]:
                        category = primary_cat
                        subcategory = primary_sub
                    else:
                        ai_class = await category_pull_service.classify_item(norm_item, intent)
                        category = ai_class.get("category")
                        subcategory = ai_class.get("subcategory")

                    if not category or category.lower() in ["general", "miscellaneous", "unclassified",
                                                            "uncategorized"]:
                        category = "Income" if is_credit else "Miscellaneous"
                    if not subcategory or subcategory.lower() in ["general", "miscellaneous", "unclassified",
                                                                  "uncategorized"] or subcategory.lower() == category.lower():
                        subcategory = "Uncategorized" if category == "Miscellaneous" else f"{category} Specifics"

                    taxonomy_err = await category_pull_service.bulk_add_items_to_taxonomy([{
                        "category": category, "subcategory": subcategory, "item": norm_item
                    }], user_id)
                    cache_manager.rebuild_cache()

                # --- DUPLICATE INTERCEPTOR FOR SINGLE TRANSACTIONS ---
                is_salary_or_income = intent == "income" or (category and category.lower() == "income")
                dao = BulkTransactionDAO(supabase_admin, user_id)

                is_duplicate = False if is_salary_or_income else dao.check_transaction_exists(str(amount), norm_item,
                                                                                              intent, final_date_iso)

                if is_duplicate:
                    batch_id = uuid.uuid4().hex[:8]
                    batch_dao = PendingBatchDAO(supabase_admin)

                    payload = {
                        "user_id": user_id, "amount": str(amount), "txn_type": intent,
                        "description": description, "normalized_item": norm_item, "intent": intent,
                        "category": category, "subcategory": subcategory, "date": final_date_iso,
                        "source_account": target_acc['account_name'] if is_debit else None,
                        "destination_account": target_acc['account_name'] if is_credit else None,
                        "soft_deleted": False
                    }

                    duplicate_item = [{
                        "payload": payload, "selected": False, "desc": norm_item, "amount": str(amount),
                        "txn_type": intent
                    }]

                    batch_dao.create_batch(batch_id, user_id, target_acc['id'], duplicate_item)
                    keyboard = CallbackHandler.generate_duplicate_keyboard(batch_id, duplicate_item)

                    if status_msg_id:
                        await gateway.edit_message(str(chat_id), status_msg_id,
                                                   get_progress_ui(100, "Duplicate check complete."))
                        await asyncio.sleep(0.3)
                        await gateway.delete_message(str(chat_id), status_msg_id)

                    dup_msg_id = await gateway.send_message(
                        str(chat_id),
                        f"⚠️ *Duplicate Transaction Detected*\n`{norm_item}` for ₹{float(amount):,.2f} already exists on this day.\nDo you want to save it anyway? (Expires in 1 min)",
                        reply_markup=keyboard
                    )

                    if dup_msg_id:
                        qstash_token = os.getenv("QSTASH_TOKEN")
                        if qstash_token and request_url:
                            client = QStash(qstash_token)
                            base_url = str(request_url).split('/webhook')[0].split('/process-task')[0]
                            try:
                                client.message.publish_json(
                                    url=f"{base_url}/process-task",
                                    body={
                                        "internal_task": "duplicate_timeout",
                                        "batch_id": batch_id,
                                        "chat_id": str(chat_id),
                                        "message_id": dup_msg_id
                                    },
                                    delay="60s",
                                    headers={"x-pocketmunim-user": user_id}
                                )
                            except Exception as e:
                                print(f"Failed to queue QStash timeout: {e}")
                    return

                if status_msg_id:
                    await gateway.edit_message(str(chat_id), status_msg_id,
                                               get_progress_ui(90, "Saving to your ledger..."))
                    await asyncio.sleep(0.3)

                net_change = -float(amount) if is_debit else float(amount)
                res = supabase_admin.rpc('atomic_balance_update',
                                         {'p_account_id': target_acc['id'], 'p_amount': net_change}).execute()
                new_bal = res.data

                supabase.table("transactions").insert({
                    "user_id": user_id, "amount": float(amount), "txn_type": intent,
                    "description": description, "normalized_item": norm_item, "intent": intent,
                    "category": category, "subcategory": subcategory, "date": final_date_iso,
                    "source_account": target_acc['account_name'] if is_debit else None,
                    "destination_account": target_acc['account_name'] if is_credit else None,
                    "soft_deleted": False
                }).execute()

                supabase_admin.table('account_logs').insert({
                    "account_id": target_acc['id'], "user_id": user_id,
                    "log_type": "DEBIT" if is_debit else "CREDIT", "amount": float(amount),
                    "balance_after": new_bal, "description": description
                }).execute()

                if status_msg_id:
                    await gateway.edit_message(str(chat_id), status_msg_id, get_progress_ui(100, "Finalizing..."))
                    await asyncio.sleep(0.3)
                    await gateway.delete_message(str(chat_id), status_msg_id)

                cat_display = f"{category.title()} -> {subcategory.title()}" if category and subcategory and category.lower() != subcategory.lower() else (
                    category.title() if category else "Uncategorized")
                warning = f"\n⚠️ *Taxonomy Warning*: `{taxonomy_err}`" if taxonomy_err else ""

                await gateway.send_message(
                    str(chat_id),
                    f"✅ *Transaction Saved*\n"
                    f"🛒 {norm_item}: ₹{float(amount):,.2f}\n"
                    f"📁 Category: *{cat_display}*{warning}\n"
                    f"🏦 Account: {target_acc['account_name']} (New Balance: ₹{new_bal:,.2f})"
                )

        except Exception as e:
            await gateway.send_message(str(chat_id), f"❌ Execution Error: `{str(e)}`")
            if 'status_msg_id' in locals() and status_msg_id:
                await gateway.delete_message(str(chat_id), status_msg_id)