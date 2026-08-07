from app.telegram.telegram_utils import send_telegram_reply
from app.services.loan_service import LoanService
from app.ai.loan_extraction_service import LoanExtractionService


class LoanHandler:
    @staticmethod
    async def get_loans(supabase_admin, chat_id, user_id, text=""):
        query = text.replace("/getloans", "").strip()
        q = supabase_admin.table('loans').select('*, emi_schedules(*)').eq('user_id', user_id).eq('is_active', True)
        if query: q = q.ilike('lender', f"%{query}%")
        loans = q.execute().data

        if not loans:
            await send_telegram_reply(chat_id, "ℹ️ No active loans found.")
            return

        for loan in loans:
            pending = [e for e in loan['emi_schedules'] if e['status'] == 'PENDING']
            msg = [f"🏦 *{loan['lender']}*", f"💰 Principal: ₹{float(loan['principal_amount']):,.2f}"]
            if pending:
                msg.append(f"📅 *Next Due*: {pending[0]['due_date']} — ₹{float(pending[0]['emi_amount']):,.2f}")
                kbd = {"inline_keyboard": [[{"text": "💳 Pay EMI", "callback_data": f"payemi_{loan['loan_id']}"}]]}
            else:
                kbd = None
            await send_telegram_reply(chat_id, "\n".join(msg), reply_markup=kbd)

    @staticmethod
    async def handle_loan_text(supabase_admin, chat_id, user_id, text):
        extractor = LoanExtractionService(supabase_admin)
        loan_service = LoanService(supabase_admin, user_id)

        parsed = await extractor.parse_loan_text(text)
        for p in parsed:
            if p.action == "CREATE":
                msg, _ = await loan_service.create_loan(p)
                await send_telegram_reply(chat_id, msg)
            elif p.action == "PAY_EMI":
                msg, res = await loan_service.process_emi_payment(p.lender_name)
                if isinstance(res, dict) and res.get("status") == "NEXT_EMI_CONFIRM":
                    kbd = {"inline_keyboard": [[{"text": "✅ Yes, Pay Next",
                                                 "callback_data": f"paynext_{res['loan_id']}_{res['next_schedule_id']}"}]]}
                    await send_telegram_reply(chat_id, msg, reply_markup=kbd)
                else:
                    await send_telegram_reply(chat_id, msg)