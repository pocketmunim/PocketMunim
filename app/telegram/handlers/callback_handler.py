from app.telegram.telegram_utils import edit_telegram_message
from app.dao.bulk_transaction_dao import BulkTransactionDAO

PENDING_BATCHES = {}

class CallbackHandler:
    @staticmethod
    def generate_duplicate_keyboard(batch_id: str, items: list) -> dict:
        keyboard = []
        for i, item in enumerate(items):
            icon = "☑️" if item["selected"] else "⬜️"
            keyboard.append([{"text": f"{icon} {item['desc']} (₹{item['amount']:,.2f})", "callback_data": f"btog_{batch_id}_{i}"}])
        keyboard.append([{"text": "✅ Confirm Selected", "callback_data": f"bconf_{batch_id}"}, {"text": "❌ Cancel All", "callback_data": f"bcanc_{batch_id}"}])
        return {"inline_keyboard": keyboard}

    @staticmethod
    async def handle(payload, supabase_admin):
        cb = payload["callback_query"]
        chat_id, message_id, user_id, data = cb["message"]["chat"]["id"], cb["message"]["message_id"], str(cb["from"]["id"]), cb["data"]

        import httpx
        import os
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{os.getenv('TELEGRAM_BOT_TOKEN')}/answerCallbackQuery", json={"callback_query_id": cb["id"]})

        if data.startswith("btog_"):
            parts = data.split("_")
            batch_id, item_id = parts[1], int(parts[2])
            if batch_id in PENDING_BATCHES:
                PENDING_BATCHES[batch_id]["items"][item_id]["selected"] = not PENDING_BATCHES[batch_id]["items"][item_id]["selected"]
                await edit_telegram_message(chat_id, message_id, reply_markup=CallbackHandler.generate_duplicate_keyboard(batch_id, PENDING_BATCHES[batch_id]["items"]))
        elif data.startswith("bconf_"):
            batch_id = data.split("_")[1]
            if batch_id in PENDING_BATCHES:
                batch = PENDING_BATCHES[batch_id]
                selected_items = [item for item in batch["items"] if item["selected"]]
                if not selected_items:
                    await edit_telegram_message(chat_id, message_id, text="❌ No duplicates selected. Batch discarded.")
                else:
                    dao = BulkTransactionDAO(supabase_admin, user_id)
                    selected_payloads = [i["payload"] for i in selected_items]
                    acc_res = supabase_admin.table('accounts').select('*').eq('id', batch["account_id"]).execute()
                    if acc_res.data:
                        default_acc_name, current_bal = acc_res.data[0]['account_name'], float(acc_res.data[0]['balance'])
                        total_deduction = sum(p["amount"] for p in selected_payloads if p["source_account"] == default_acc_name)
                        total_addition = sum(p["amount"] for p in selected_payloads if p["destination_account"] == default_acc_name)
                        if (current_bal - total_deduction + total_addition) < 0:
                            await edit_telegram_message(chat_id, message_id, text="❌ Insufficient balance to save selected duplicates.")
                        else:
                            dao.execute_bulk_commit(batch["account_id"], selected_payloads, total_deduction, total_addition, current_bal)
                            await edit_telegram_message(chat_id, message_id, text=f"✅ {len(selected_payloads)} duplicate transactions confirmed and saved.")
                del PENDING_BATCHES[batch_id]
        elif data.startswith("bcanc_"):
            batch_id = data.split("_")[1]
            if batch_id in PENDING_BATCHES: del PENDING_BATCHES[batch_id]
            await edit_telegram_message(chat_id, message_id, text="❌ All duplicate transactions discarded.")
        return {"ok": True}
