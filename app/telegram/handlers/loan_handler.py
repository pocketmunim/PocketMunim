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

            # Calculate remaining principal from last paid or initial principal
            paid_emis = [e for e in schedules if e['status'] == 'PAID']
            if paid_emis:
                last_paid = max(paid_emis, key=lambda x: x['installment_number'])
                remaining_principal = float(last_paid['remaining_balance'])
            else:
                remaining_principal = float(loan['principal_amount'])

            pending_tenure_months = len(pending_emis)

            msg = [
                f"🏦 **{loan['lender']}**",
                f"{progress_bar} **{int(progress)}% Paid** ({completed_emi}/{total_emi} EMIs)",
                f"⏳ **Remaining Tenure:** {pending_tenure_months} Months",
                f"📉 **Remaining Principal:** ₹{remaining_principal:,.2f}",
                f"💰 Original: ₹{float(loan['principal_amount']):,.2f} | Rate: {float(loan['annual_interest_rate'])}%"
            ]

            if pending_emis:
                next_emi = pending_emis[0]
                msg.append(f"📅 **Next Due**: {next_emi['due_date']} — ₹{float(next_emi['emi_amount']):,.2f}")

            # Interactive Pay EMI button linked directly to this loan ID
            keyboard = {
                "inline_keyboard": [
                    [{
                         "text": f"💳 Pay EMI (₹{float(pending_emis[0]['emi_amount']):,.2f})" if pending_emis else "💳 Pay EMI",
                         "callback_data": f"payemi_{loan['loan_id']}"}]
                ]
            } if pending_emis else None

            await send_telegram_reply(chat_id, "\n".join(msg), reply_markup=keyboard)

    @staticmethod
    async def handle_loan_text(supabase_admin, chat_id, user_id, text):
        extractor = LoanExtractionService(supabase_admin)
        loan_service = LoanService(supabase_admin, user_id)

        try:
            parsed_actions = await extractor.parse_loan_text(text)
            response_messages = []

            for parsed in parsed_actions:
                if parsed.action == "CREATE":
                    msg, success = await loan_service.create_loan(parsed)
                    response_messages.append(msg)
                elif parsed.action == "PAY_EMI":
                    msg, success = await loan_service.process_emi_payment(
                        lender_name=parsed.lender_name,
                        payment_amount=parsed.payment_amount,
                        target_period=parsed.target_period
                    )
                    response_messages.append(msg)

            if response_messages:
                await send_telegram_reply(chat_id, "\n\n".join(response_messages))
        except Exception as e:
            await send_telegram_reply(chat_id, f"⚠️ **Batch Processing Error**\n`{str(e)}`")