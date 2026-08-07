import os
import httpx
from decimal import Decimal
from app.telegram.telegram_utils import edit_telegram_message
from app.dao.bulk_transaction_dao import BulkTransactionDAO
from app.dao.pending_batch_dao import PendingBatchDAO


class CallbackHandler:
    @staticmethod
    def generate_duplicate_keyboard(batch_id: str, items: list) -> dict:
        keyboard = []
        for i, item in enumerate(items):
            icon = "✅" if item.get("selected") else "❌"
            keyboard.append([{
                "text": f"{icon} {item['desc']} (₹{float(item['amount']):,.2f})",
                "callback_data": f"btog_{batch_id}_{i}"
            }])
        keyboard.append([
            {"text": "✅ Confirm Selected", "callback_data": f"bconf_{batch_id}"},
            {"text": "❌ Cancel All", "callback_data": f"bcanc_{batch_id}"}
        ])
        return {"inline_keyboard": keyboard}

    @staticmethod
    async def handle(payload: dict, supabase_admin):
        cb = payload["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        message_id = cb["message"]["message_id"]
        user_id = str(cb["from"]["id"])
        data = cb["data"]

        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if telegram_token:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{telegram_token}/answerCallbackQuery",
                    json={"callback_query_id": cb["id"]}
                )

        batch_dao = PendingBatchDAO(supabase_admin)

        if data.startswith("btog_"):
            parts = data.split("_")
            batch_id, item_id = parts[1], int(parts[2])
            batch = batch_dao.get_batch(batch_id)
            if batch and "items" in batch and 0 <= item_id < len(batch["items"]):
                items = batch["items"]
                items[item_id]["selected"] = not items[item_id]["selected"]
                batch_dao.update_batch_items(batch_id, items)
                await edit_telegram_message(
                    chat_id,
                    message_id,
                    reply_markup=CallbackHandler.generate_duplicate_keyboard(batch_id, items)
                )
        elif data.startswith("bconf_"):
            batch_id = data.split("_")[1]
            batch = batch_dao.get_batch(batch_id)
            if batch and "items" in batch:
                selected_items = [item for item in batch["items"] if item.get("selected")]
                if not selected_items:
                    await edit_telegram_message(chat_id, message_id, text="ℹ️ No duplicates selected. Batch discarded.")
                else:
                    dao = BulkTransactionDAO(supabase_admin, user_id)
                    selected_payloads = [i["payload"] for i in selected_items]
                    acc_res = supabase_admin.table('accounts').select('*').eq('id', batch["account_id"]).execute()
                    if acc_res.data:
                        default_acc_name = acc_res.data[0]['account_name']
                        total_deduction = sum(Decimal(str(p["amount"])) for p in selected_payloads if
                                              p.get("source_account") == default_acc_name)
                        total_addition = sum(Decimal(str(p["amount"])) for p in selected_payloads if
                                             p.get("destination_account") == default_acc_name)
                        try:
                            dao.execute_bulk_commit(
                                batch["account_id"], selected_payloads, total_deduction, total_addition
                            )
                            await edit_telegram_message(chat_id, message_id,
                                                        text=f"✅ {len(selected_payloads)} duplicate transactions confirmed and saved.")
                        except Exception as e:
                            error_msg = str(e).lower()
                            if "insufficient" in error_msg or "p0001" in error_msg:
                                await edit_telegram_message(chat_id, message_id,
                                                            text="🚫 Insufficient balance to save selected duplicates.")
                            else:
                                await edit_telegram_message(chat_id, message_id, text=f"⚠️ Database Error: `{str(e)}`")
                batch_dao.delete_batch(batch_id)
            else:
                await edit_telegram_message(chat_id, message_id, text="⚠️ Batch session expired or already processed.")
        elif data.startswith("bcanc_"):
            batch_id = data.split("_")[1]
            batch_dao.delete_batch(batch_id)
            await edit_telegram_message(chat_id, message_id, text="ℹ️ All duplicate transactions discarded.")
        elif data.startswith("payemi_"):
            loan_id = data.split("_")[1]
            from app.services.loan_service import LoanService
            service = LoanService(supabase_admin, user_id)
            result_msg, success = await service.process_emi_payment_by_id(loan_id)
            await edit_telegram_message(chat_id, message_id, text=result_msg)
            return {"ok": True}

        return {"ok": True}