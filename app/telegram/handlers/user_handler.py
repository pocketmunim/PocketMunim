import re
import calendar
from datetime import datetime
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply

MALICIOUS_PATTERN = re.compile(
    r"(DROP\s+TABLE|SELECT\s+\*|OR\s+1=1|<script>|<img|jndi:ldap|rm\s+-rf|;/|{{.*}}|\.\./\.\./|\"\s*OR\s*\"")",
    re.IGNORECASE
)

class UserHandler:
    @staticmethod
    async def security_check(supabase_admin, chat_id, text):
        if MALICIOUS_PATTERN.search(text):
            user_res = supabase_admin.table('users').select('security_strikes').eq('telegram_id', chat_id).execute()
            current_strikes = user_res.data[0].get('security_strikes', 0) if user_res.data else 0
            new_strikes = current_strikes + 1
            supabase_admin.table('users').update({'security_strikes': new_strikes}).eq('telegram_id', chat_id).execute()

            if new_strikes >= 3:
                await send_telegram_reply(chat_id, "🚨 *ACCOUNT BLOCKED*\n\nMultiple malicious inputs detected. Your account has been suspended.")
            else:
                await send_telegram_reply(chat_id, f"⚠️ *SECURITY WARNING ({new_strikes}/3)*\n\nMalicious input detected. Your account will be blocked after 3 strikes.")
            return False, False

        user_res = supabase_admin.table('users').select('*').eq('telegram_id', chat_id).execute()
        user_exists = bool(user_res.data)

        if user_exists and user_res.data[0].get('security_strikes', 0) >= 3:
            await send_telegram_reply(chat_id, "🚨 *ACCOUNT BLOCKED*\n\nYour account is suspended due to security violations.")
            return False, user_exists

        return True, user_exists

    @staticmethod
    async def prompt_registration(chat_id):
        copyable_form = "```text\n/register\nName: [Your Name]\nCurrency: INR\nMonthly Salary: [Amount]\nBank Account: [Bank Name]\nCurrent Balance: [Amount]\n```"
        await send_telegram_reply(chat_id, f"🚨 *Registration Mandatory*\n\nTo use PocketMunim, you must register your account first.\n\n📋 *Copy, fill, and send the exact form below:*\n{copyable_form}")

    @staticmethod
    async def register(supabase_admin, chat_id, user_id, text, user_exists):
        if "[" in text or "]" in text or "Your Name" in text or len(text.replace("/register", "").strip()) < 10:
            await send_telegram_reply(chat_id, "⚠️ *Invalid Registration Form*\n\nPlease fill in all required fields without brackets.")
            return

        lines = text.split("\n")
        name, currency, bank_name = "", "INR", ""
        monthly_salary = current_balance = None

        for line in lines:
            if "Name:" in line: name = line.split("Name:")[1].strip().title()
            if "Currency:" in line: currency = line.split("Currency:")[1].strip().upper()
            if "Monthly Salary:" in line:
                try: monthly_salary = float(line.split("Monthly Salary:")[1].strip().replace(",", ""))
                except: pass
            if "Bank Account:" in line: bank_name = line.split("Bank Account:")[1].strip().title()
            if "Current Balance:" in line:
                try: current_balance = float(line.split("Current Balance:")[1].strip().replace(",", ""))
                except: pass

        if not name or monthly_salary is None or not bank_name or current_balance is None:
            await send_telegram_reply(chat_id, "❌ *Registration Failed*\n\nMissing required fields.")
            return

        if not user_exists:
            try:
                supabase_admin.table('users').insert(
                    {"id": user_id, "telegram_id": chat_id, "full_name": name, "currency": currency, "security_strikes": 0}
                ).execute()

                acc_res = supabase_admin.table('accounts').insert({
                    "user_id": user_id, "account_name": bank_name, "balance": current_balance, "is_default": True
                }).execute()
                acc_id = acc_res.data[0]['id']

                current_dt = datetime.now(TZ_IST)
                current_year = current_dt.year
                current_month = current_dt.month
                total_salary_added = 0.0

                if monthly_salary > 0:
                    for m in range(1, current_month):
                        last_day = calendar.monthrange(current_year, m)[1]
                        salary_date = current_dt.replace(year=current_year, month=m, day=last_day, hour=23, minute=59, second=59)
                        month_name = salary_date.strftime('%b %Y')

                        supabase_admin.table('salaries').insert({
                            "user_id": user_id, "year": current_year, "month_number": m,
                            "month_name": month_name, "amount": monthly_salary, "is_deducted": False
                        }).execute()

                        supabase_admin.table('transactions').insert({
                            "user_id": user_id, "amount": monthly_salary, "txn_type": "income",
                            "description": f"Salary for {month_name}", "intent": "income", "category": "Income",
                            "subcategory": "Salary", "date": salary_date.isoformat(), "destination_account": bank_name,
                            "soft_deleted": False
                        }).execute()
                        total_salary_added += monthly_salary

                final_balance = current_balance + total_salary_added
                supabase_admin.table('accounts').update({"balance": final_balance}).eq("id", acc_id).execute()

                if total_salary_added > 0:
                    supabase_admin.table('account_logs').insert({
                        "account_id": acc_id, "user_id": user_id, "log_type": "CREDIT",
                        "amount": total_salary_added, "balance_after": final_balance,
                        "description": "Retroactive Salary Structuring"
                    }).execute()

                await send_telegram_reply(chat_id, f"✅ *Registration Successful!*\n\nWelcome to PocketMunim, *{name}*!\nYour **{bank_name}** account balance is **₹{final_balance:,.2f}**.")
            except Exception as e:
                await send_telegram_reply(chat_id, f"❌ Registration failed: {str(e)}")
        else:
            await send_telegram_reply(chat_id, "ℹ️ You are already registered with PocketMunim!")
