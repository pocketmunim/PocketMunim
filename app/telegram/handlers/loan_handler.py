from datetime import datetime
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply
from app.services.loan_service import LoanService
from app.ai.loan_extraction_service import LoanExtractionService

class LoanHandler:
    @staticmethod
    async def get_loans(supabase_admin, chat_id, user_id, text=""):
        query_arg = text.replace("/getloans", "").strip()
        db_query = supabase_admin.table('loans').select('*, emi_schedules(*)').eq('user_id', user_id).eq('is_active', True)
        if query_arg:
            db_query = db_query.ilike('lender', f"%{query_arg}%")
        loans_res = db_query.execute()
        loans = loans_res.data
        
        if not loans:
            await send_telegram_reply(chat_id, "🎉 *No Active Loans*\nYou are completely debt-free!")
            return

        current_dt = datetime.now(TZ_IST)
        curr_year_month = current_dt.strftime("%Y-%m")
        
        # Premium UI Header
        await send_telegram_reply(chat_id, "🏦 *YOUR ACTIVE LOAN PORTFOLIO*\n_Live Amortization Analytics_")
        
        for loan in loans:
            schedules = sorted(loan.get('emi_schedules', []), key=lambda x: x['installment_number'])
            pending_emis = [e for e in schedules if e['status'] == 'PENDING']
            total_emi = len(schedules)
            completed_emi = total_emi - len(pending_emis)
            
            # Calculate Progress
            progress = (completed_emi / total_emi * 100) if total_emi > 0 else 0
            
            # --- THERMAL DARK-TO-LIGHT LED BAR UI ---
            total_blocks = 10
            
            if progress >= 100:
                bar_ui = "🟩" * total_blocks
                status_color = "✅"
            else:
                # Math Fix: Guarantee at least 1 lit block if they have paid something
                filled_blocks = int(round(progress / 10))
                if completed_emi > 0 and filled_blocks == 0:
                    filled_blocks = 1
                    
                # 3 Colors fading Dark to Light: Deep Red -> Vibrant Orange -> Bright Yellow
                gradient = ["🟥", "🟥", "🟥", "🟧", "🟧", "🟧", "🟧", "🟨", "🟨", "🟨"]
                filled_ui = "".join(gradient[:filled_blocks])
                
                # Replaced black blocks with crisp white blocks for contrast
                empty_ui = "⬜" * (total_blocks - filled_blocks)
                bar_ui = f"{filled_ui}{empty_ui}"
                status_color = "🔴" if progress < 33 else ("🟠" if progress < 66 else "🟡")

            # Calculate actual remaining principal accurately
            paid_emis = [e for e in schedules if e['status'] == 'PAID']
            if paid_emis:
                remaining_principal = float(paid_emis[-1]['remaining_balance'])
            else:
                remaining_principal = float(loan['principal_amount'])
            
            current_month_paid = any(sched['due_date'].startswith(curr_year_month) and sched['status'] == 'PAID' for sched in schedules)

            # Construct the sleek data card
            msg = [
                f"🏦 *{loan['lender'].upper()}*",
                f"──────────────────────",
                f"{status_color} *Repayment Progress:* `{progress:05.2f}%`",
                f"{bar_ui}",
                f"  _({completed_emi} out of {total_emi} EMIs Settled)_",
                f"",
                f"📊 *Amortization Snapshot*",
                f"💸 *Original Principal:* `₹{float(loan['principal_amount']):,.2f}`",
                f"🎯 *Principal Left:* `₹{remaining_principal:,.2f}`",
                f"📈 *Interest Rate:* `{float(loan['annual_interest_rate'])}%`"
            ]
            
            keyboard = None
            if pending_emis and not current_month_paid:
                next_emi = pending_emis[0]
                msg.append(f"")
                msg.append(f"📅 *Next EMI Due:* `{next_emi['due_date']}`")
                msg.append(f"💳 *Amount:* `₹{float(next_emi['emi_amount']):,.2f}`")
                keyboard = {
                    "inline_keyboard": [[{"text": f"💳 Pay ₹{float(next_emi['emi_amount']):,.2f} Now", "callback_data": f"payemi_{loan['loan_id']}"}]]
                }
            elif current_month_paid:
                msg.append(f"")
                msg.append("✅ _Current month EMI is successfully paid._")
                
            await send_telegram_reply(chat_id, "\n".join(msg), reply_markup=keyboard)

    @staticmethod
    async def handle_loan_text(supabase_admin, chat_id, user_id, text) -> str:
        extractor = LoanExtractionService(supabase_admin)
        loan_service = LoanService(supabase_admin, user_id)
        
        try:
            parsed_actions, leftover_text = await extractor.parse_loan_text(text)
            response_messages = []
            keyboard = None
            
            for parsed in parsed_actions:
                if parsed.action == "CREATE":
                    msg, _ = await loan_service.create_loan(parsed)
                    response_messages.append(msg)
                    
                elif parsed.action == "PAY_EMI":
                    lender_search = parsed.lender_name.strip() if parsed.lender_name else ""
                    if not lender_search:
                        response_messages.append("⚠️ Missing lender name for EMI payment.")
                        continue
                        
                    loan_lookup = supabase_admin.table("loans").select("loan_id").eq("user_id", user_id).ilike("lender", f"%{lender_search}%").eq("is_active", True).execute()
                    
                    if not loan_lookup.data:
                        response_messages.append(f"⚠️ No active loan found matching '{lender_search}'.")
                    elif len(loan_lookup.data) > 1:
                        response_messages.append(f"⚠️ Multiple active loans match '{lender_search}'. Please clarify.")
                    else:
                        target_loan_id = loan_lookup.data[0]['loan_id']
                        payment_amt = parsed.payment_amount or parsed.emi_amount
                        
                        msg, result_data = await loan_service.process_emi_payment_by_id(
                            loan_id=target_loan_id,
                            payment_amount=payment_amt,
                            payment_date_str=parsed.payment_date
                        )
                        
                        if isinstance(result_data, dict) and result_data.get("requires_confirmation"):
                            keyboard = {
                                "inline_keyboard": [[
                                    {"text": "⏩ Yes, Pay Next Month", "callback_data": f"payemiadv_{target_loan_id}"},
                                    {"text": "❌ Cancel", "callback_data": "cancel_action"}
                                ]]
                            }
                        response_messages.append(msg)

            if response_messages:
                await send_telegram_reply(chat_id, "\n\n".join(response_messages), reply_markup=keyboard)
                
            return leftover_text
            
        except Exception as e:
            await send_telegram_reply(chat_id, f"⚠️ Loan Batch Error: `{str(e)}`")
            return ""

    @staticmethod
    async def generate_loan_report_link(base_url: str, chat_id: int, user_id: str):
        """Generates the magic link for the advanced Loan Dashboard and sends it via Telegram."""
        from app.telegram.handlers.report_handler import ReportHandler
        from app.interfaces.notification_gateway import TelegramNotificationAdapter
        
        gateway = TelegramNotificationAdapter()
        token = ReportHandler._create_magic_token(user_id)
        
        # Clean the base URL and append the new route
        clean_url = str(base_url).split('/webhook')[0].split('/process-task')[0].rstrip('/')
        dashboard_url = f"{clean_url}/loans/view/{token}"
        
        message = (
            "🏦 *Advanced Amortization Engine Ready*\n"
            "_Equipped with debt burndown charts, portfolio analysis, and combined EMI ledgers._\n\n"
            "🔒 *Security Notice:* This magic link is cryptographically signed and expires in 60 minutes."
        )
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "📊 Open Debt Analytics", "url": dashboard_url}]
            ]
        }
        await gateway.send_message(str(chat_id), message, reply_markup=keyboard)
