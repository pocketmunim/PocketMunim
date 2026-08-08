from datetime import datetime
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply
from app.services.loan_service import LoanService
from app.ai.loan_extraction_service import LoanExtractionService


class LoanHandler:
    @staticmethod
    async def get_loans(supabase_admin, chat_id, user_id, text=""):
        query_arg = text.replace("/getloans", "").strip()
        db_query = supabase_admin.table('loans').select('*, emi_schedules(*)').eq('user_id', user_id).eq('is_active',
                                                                                                         True)
        if query_arg:
            db_query = db_query.ilike('lender', f"%{query_arg}%")
        loans_res = db_query.execute()
        loans = loans_res.data

        if not loans:
            if query_arg:
                await send_telegram_reply(chat_id, f"ℹ️ No active loans found matching '{query_arg}'.")
            else:
                await send_telegram_reply(chat_id, "ℹ️ You have no active loans.")
            return

        current_dt = datetime.now(TZ_IST)
        curr_year_month = current_dt.strftime("%Y-%m")

        for loan in loans:
            schedules = sorted(loan.get('emi_schedules', []), key=lambda x: x['installment_number'])
            pending_emis = [e for e in schedules if e['status'] == 'PENDING']
            total_emi = len(schedules)
            completed_emi = total_emi - len(pending_emis)

            progress = (completed_emi / total_emi * 100) if total_emi > 0 else 0

            if progress < 50:
                bar_color = "🟩"
            elif progress < 85:
                bar_color = "🟨"
            else:
                bar_color = "🟥"

            filled_blocks = int(progress / 10)
            progress_bar = f"{bar_color} {'█' * filled_blocks}{'░' * (10 - filled_blocks)}"

            paid_emis = [e for e in schedules if e['status'] == 'PAID']
            if paid_emis:
                last_paid = max(paid_emis, key=lambda x: x['installment_number'])
                remaining_principal = float(last_paid['remaining_balance'])
            else:
                remaining_principal = float(loan['principal_amount'])

            pending_tenure_months = len(pending_emis)

            current_month_paid = False
            for sched in schedules:
                if sched['due_date'].startswith(curr_year_month) and sched['status'] == 'PAID':
                    current_month_paid = True
                    break

            msg = [
                f"🏦 *{loan['lender']}*",
                f"{progress_bar} *{int(progress)}% Paid* ({completed_emi}/{total_emi} EMIs)",
                f"⏳ *Remaining Tenure:* {pending_tenure_months} Months",
                f"📉 *Remaining Principal:* ₹{remaining_principal:,.2f}",
                f"💰 Original: ₹{float(loan['principal_amount']):,.2f} | Rate: {float(loan['annual_interest_rate'])}%"
            ]

            if pending_emis:
                next_emi = pending_emis[0]
                msg.append(f"📅 *Next Due*: {next_emi['due_date']} — ₹{float(next_emi['emi_amount']):,.2f}")

            keyboard = None
            if pending_emis and not current_month_paid:
                keyboard = {
                    "inline_keyboard": [
                        [{"text": f"💳 Pay EMI (₹{float(pending_emis[0]['emi_amount']):,.2f})",
                          "callback_data": f"payemi_{loan['loan_id']}"}]
                    ]
                }
            elif current_month_paid:
                msg.append("✅ *Current month EMI already paid.*")

            await send_telegram_reply(chat_id, "\n".join(msg), reply_markup=keyboard)

    @staticmethod
    async def handle_loan_text(supabase_admin, chat_id, user_id, text) -> str:
        extractor = LoanExtractionService(supabase_admin)
        loan_service = LoanService(supabase_admin, user_id)

        try:
            # Now returns a tuple: (actions, leftover_text)
            parsed_actions, leftover_text = await extractor.parse_loan_text(text)
            response_messages = []

            for parsed in parsed_actions:
                if parsed.action == "CREATE":
                    msg, success = await loan_service.create_loan(parsed)
                    response_messages.append(msg)
                elif parsed.action == "PAY_EMI":
                    msg, res_status = await loan_service.process_emi_payment(
                        lender_name=parsed.lender_name,
                        payment_amount=parsed.payment_amount,
                        target_period=parsed.target_period
                    )

                    if isinstance(res_status, dict) and res_status.get("status") == "NEXT_EMI_CONFIRM":
                        next_sched_id = res_status["next_schedule_id"]
                        loan_id = res_status["loan_id"]
                        keyboard = {
                            "inline_keyboard": [
                                [{"text": "Pay Next Month EMI", "callback_data": f"paynext_{loan_id}_{next_sched_id}"}],
                                [{"text": "Cancel", "callback_data": "cancelpay"}]
                            ]
                        }
                        await send_telegram_reply(chat_id, msg, reply_markup=keyboard)
                    else:
                        response_messages.append(msg)

            if response_messages:
                await send_telegram_reply(chat_id, "\n\n".join(response_messages))

            # Return the non-loan text so main.py can process it
            return leftover_text
        except Exception as e:
            await send_telegram_reply(chat_id, f"⚠️ Batch Processing Error: {str(e)}")
            return ""