from app.telegram.telegram_utils import send_telegram_reply
from app.services.loan_service import LoanService
from app.ai.loan_extraction_service import LoanExtractionService


class LoanHandler:
    @staticmethod
    async def get_loans(supabase_admin, chat_id, user_id):
        loans_res = supabase_admin.table('loans').select('*, emi_schedules(*)').eq('user_id', user_id).eq('is_active',
                                                                                                          True).execute()
        loans = loans_res.data

        if not loans:
            await send_telegram_reply(chat_id, "ℹ️ You have no active loans.")
            return

        msg = ["🏦 Active Loans Dashboard\n"]
        for loan in loans:
            schedules = sorted(loan.get('emi_schedules', []), key=lambda x: x['installment_number'])
            pending_emis = [e for e in schedules if e['status'] == 'PENDING']
            total_emi = len(schedules)
            completed_emi = total_emi - len(pending_emis)

            progress = (completed_emi / total_emi * 100) if total_emi > 0 else 0

            # Color-coded progress bar rules
            if progress < 50:
                bar_color = "🟩"
            elif progress < 85:
                bar_color = "🟨"
            else:
                bar_color = "🟥"

            filled_blocks = int(progress / 10)
            progress_bar = f"{bar_color} {'█' * filled_blocks}{'░' * (10 - filled_blocks)}"

            msg.append(f"🏦 {loan['lender']}")
            msg.append(f"{progress_bar} {int(progress)}% Paid ({completed_emi}/{total_emi} EMIs)")
            msg.append(
                f"💰 Principal: ₹{float(loan['principal_amount']):,.2f} | Rate: {float(loan['annual_interest_rate'])}%")

            if pending_emis:
                next_emi = pending_emis[0]
                msg.append(f"📅 Next Due: {next_emi['due_date']} — ₹{float(next_emi['emi_amount']):,.2f}")
            msg.append("────────────────────────")

        await send_telegram_reply(chat_id, "\n".join(msg))

    @staticmethod
    async def handle_loan_text(supabase_admin, chat_id, user_id, text):
        extractor = LoanExtractionService(supabase_admin)
        loan_service = LoanService(supabase_admin, user_id)

        try:
            parsed = await extractor.parse_loan_text(text)
            if parsed.action == "CREATE":
                res = await loan_service.create_loan(parsed)
                await send_telegram_reply(
                    chat_id,
                    f"✅ Loan Registered Successfully\n"
                    f"Lender: {parsed.lender_name.title()}\n"
                    f"Principal: ₹{float(parsed.principal):,.2f}\n"
                    f"Calculated EMI: ₹{res['emi']:,.2f}\n"
                    f"Tenure: {parsed.tenure_years} Years ({res['tenure_months']} months)"
                )
            elif parsed.action == "PAY_EMI":
                result_msg = await loan_service.process_emi_payment(
                    lender_name=parsed.lender_name,
                    payment_amount=parsed.payment_amount,
                    target_period=parsed.target_period
                )
                await send_telegram_reply(chat_id, result_msg)
        except ValueError as ve:
            await send_telegram_reply(chat_id, str(ve))
        except Exception as e:
            await send_telegram_reply(chat_id, f"⚠️ Loan Processing Error\n`{str(e)}`")