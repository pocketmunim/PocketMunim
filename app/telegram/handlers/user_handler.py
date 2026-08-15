import re
from datetime import datetime
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply
from app.services.business_calendar_service import BusinessCalendarService

MALICIOUS_PATTERN = re.compile(
    r'(DROP\s+TABLE|SELECT\s+\*|OR\s+1=1|<script>|<img|jndi:ldap|rm\s+-rf|;/|{{.*}}|\.\./\.\./|"\s*OR\s*")',
    re.IGNORECASE
)


class UserHandler:
    @staticmethod
    async def security_check(supabase_admin, chat_id, text):
        if MALICIOUS_PATTERN.search(text):
            return False, False
        try:
            user_res = supabase_admin.table('users').select('*').eq('telegram_id', chat_id).execute()
            user_exists = bool(user_res.data)
            return True, user_exists
        except Exception:
            return False, False

    @staticmethod
    async def prompt_registration(chat_id):
        copyable_form = "```text\n/register\nName: [Your Name]\nMonthly Salary: [Amount]\nSalary Date: [e.g., 5 or 31]\nBank Account: [Bank Name]\nCurrent Balance: [Amount]\n```"
        await send_telegram_reply(chat_id,
                                  f"📝 *Registration Mandatory*\n\nSend the completed form below:\n\n{copyable_form}")

    @staticmethod
    async def register(supabase_admin, chat_id, user_id, text, user_exists):
        if "[" in text or len(text.replace("/register", "").strip()) < 10:
            await send_telegram_reply(chat_id, "⚠️ *Invalid Form*")
            return

        lines = text.split("\n")
        name, bank_name, currency = "", "", "INR"
        monthly_salary = current_balance = None
        expected_day = 31

        for line in lines:
            if "Name:" in line: name = line.split("Name:")[1].strip().title()
            if "Monthly Salary:" in line:
                try:
                    monthly_salary = float(line.split("Monthly Salary:")[1].strip().replace(",", ""))
                except:
                    pass
            if "Salary Date:" in line:
                try:
                    expected_day = int(line.split("Salary Date:")[1].strip())
                except:
                    pass
            if "Bank Account:" in line: bank_name = line.split("Bank Account:")[1].strip().title()
            if "Current Balance:" in line:
                try:
                    current_balance = float(line.split("Current Balance:")[1].strip().replace(",", ""))
                except:
                    pass

        if not user_exists:
            try:
                supabase_admin.table('users').insert({
                    "id": user_id, "telegram_id": chat_id, "full_name": name, "currency": currency,
                    "security_strikes": 0
                }).execute()

                acc_res = supabase_admin.table('accounts').insert({
                    "user_id": user_id, "account_name": bank_name, "balance": current_balance, "is_default": True
                }).execute()

                acc_id = acc_res.data[0]['id']
                current_dt = datetime.now(TZ_IST)
                today_date = current_dt.date()
                current_year = current_dt.year
                total_salary_added = 0.0

                if monthly_salary > 0:
                    cal_service = BusinessCalendarService(supabase_admin)
                    # FIX: Loop full year, strictly check exact date against today
                    for m in range(1, 13):
                        actual_date = cal_service.get_actual_salary_date(current_year, m, expected_day)
                        salary_date = datetime.combine(actual_date, datetime.max.time()).replace(tzinfo=TZ_IST)
                        month_name = salary_date.strftime('%b %Y')

                        is_past_or_today = actual_date <= today_date

                        supabase_admin.table('salaries').insert({
                            "user_id": user_id, "year": current_year, "month_number": m,
                            "month_name": month_name, "amount": monthly_salary, "is_deducted": False,
                            "expected_day": expected_day
                        }).execute()

                        if is_past_or_today:
                            supabase_admin.table('transactions').insert({
                                "user_id": user_id, "amount": monthly_salary, "txn_type": "income",
                                "description": f"Salary for {month_name}", "intent": "income", "category": "Income",
                                "subcategory": "Salary", "date": salary_date.isoformat(),
                                "destination_account": bank_name,
                                "soft_deleted": False
                            }).execute()
                            total_salary_added += monthly_salary

                final_balance = current_balance + total_salary_added
                supabase_admin.table('accounts').update({"balance": final_balance}).eq("id", acc_id).execute()

                if total_salary_added > 0:
                    supabase_admin.table('account_logs').insert({
                        "account_id": acc_id, "user_id": user_id, "log_type": "CREDIT",
                        "amount": total_salary_added, "balance_after": final_balance,
                        "description": "Retroactive Salary Generation"
                    }).execute()

                await send_telegram_reply(chat_id,
                                          f"🎉 *Registration Successful!*\nWelcome, {name}!\nPrimary Account: {bank_name}\nInitial Balance: ₹{final_balance:,.2f}")
            except Exception as e:
                await send_telegram_reply(chat_id, f"❌ Registration failed: `{str(e)}`")

        # RESTORED MISSING ELSE BLOCK
        else:
            await send_telegram_reply(chat_id, "⚠️ You are already registered with PocketMunim!")