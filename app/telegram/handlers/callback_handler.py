from app.telegram.telegram_utils import edit_telegram_message


class CallbackHandler:
    @staticmethod
    async def handle(payload: dict, supabase_admin):
        cb = payload["callback_query"]
        data = cb["data"]
        loan_id = data.split("_")[1]
        user_id = str(cb["from"]["id"])

        from app.services.loan_service import LoanService
        service = LoanService(supabase_admin, user_id)

        if data.startswith("payemi_"):
            msg, _ = await service.process_emi_payment_by_id(loan_id)
            await edit_telegram_message(cb["message"]["chat"]["id"], cb["message"]["message_id"], text=msg)
        elif data.startswith("paynext_"):
            sched_id = data.split("_")[2]
            msg, _ = await service.process_emi_payment_by_id(loan_id, force_schedule_id=sched_id)
            await edit_telegram_message(cb["message"]["chat"]["id"], cb["message"]["message_id"], text=msg)

        return {"ok": True}