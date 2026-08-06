import os


def create_workspace():
    print("Executing Enterprise Decoupling: Routing Business Logic to Handlers...")

    files = {
        "app/utils/constants.py": """\
from datetime import timezone, timedelta

# Timezone Helper
TZ_IST = timezone(timedelta(hours=5, minutes=30))
""",

        "app/telegram/telegram_utils.py": """\
import os
import httpx

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def send_telegram_reply(chat_id: int, text: str, reply_markup: dict = None):
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)

async def edit_telegram_message(chat_id: int, message_id: int, text: str = None, reply_markup: dict = None):
    if not TELEGRAM_BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"
    payload = {"chat_id": chat_id, "message_id": message_id}
    if reply_markup: payload["reply_markup"] = reply_markup
    if text:
        url += "editMessageText"
        payload["text"] = text
        payload["parse_mode"] = "Markdown"
    else:
        url += "editMessageReplyMarkup"
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)
""",

        "app/telegram/handlers/user_handler.py": """\
import re
import calendar
from datetime import datetime
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply

MALICIOUS_PATTERN = re.compile(
    r"(DROP\s+TABLE|SELECT\s+\\*|OR\s+1=1|<script>|<img|jndi:ldap|rm\s+-rf|;/|{{.*}}|\\.\\./\\.\\./|\\"\\s*OR\\s*\\"\")",
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
                await send_telegram_reply(chat_id, "🚨 *ACCOUNT BLOCKED*\\n\\nMultiple malicious inputs detected. Your account has been suspended.")
            else:
                await send_telegram_reply(chat_id, f"⚠️ *SECURITY WARNING ({new_strikes}/3)*\\n\\nMalicious input detected. Your account will be blocked after 3 strikes.")
            return False, False

        user_res = supabase_admin.table('users').select('*').eq('telegram_id', chat_id).execute()
        user_exists = bool(user_res.data)

        if user_exists and user_res.data[0].get('security_strikes', 0) >= 3:
            await send_telegram_reply(chat_id, "🚨 *ACCOUNT BLOCKED*\\n\\nYour account is suspended due to security violations.")
            return False, user_exists

        return True, user_exists

    @staticmethod
    async def prompt_registration(chat_id):
        copyable_form = "```text\\n/register\\nName: [Your Name]\\nCurrency: INR\\nMonthly Salary: [Amount]\\nBank Account: [Bank Name]\\nCurrent Balance: [Amount]\\n```"
        await send_telegram_reply(chat_id, f"🚨 *Registration Mandatory*\\n\\nTo use PocketMunim, you must register your account first.\\n\\n📋 *Copy, fill, and send the exact form below:*\\n{copyable_form}")

    @staticmethod
    async def register(supabase_admin, chat_id, user_id, text, user_exists):
        if "[" in text or "]" in text or "Your Name" in text or len(text.replace("/register", "").strip()) < 10:
            await send_telegram_reply(chat_id, "⚠️ *Invalid Registration Form*\\n\\nPlease fill in all required fields without brackets.")
            return

        lines = text.split("\\n")
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
            await send_telegram_reply(chat_id, "❌ *Registration Failed*\\n\\nMissing required fields.")
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

                await send_telegram_reply(chat_id, f"✅ *Registration Successful!*\\n\\nWelcome to PocketMunim, *{name}*!\\nYour **{bank_name}** account balance is **₹{final_balance:,.2f}**.")
            except Exception as e:
                await send_telegram_reply(chat_id, f"❌ Registration failed: {str(e)}")
        else:
            await send_telegram_reply(chat_id, "ℹ️ You are already registered with PocketMunim!")
""",

        "app/telegram/handlers/account_handler.py": """\
from app.telegram.telegram_utils import send_telegram_reply

class AccountHandler:
    @staticmethod
    def get_account_from_list(accounts_list, target_name=None):
        if not accounts_list: return None
        if target_name:
            target_clean = target_name.strip().lower()
            for acc in accounts_list:
                if acc['account_name'].lower() == target_clean:
                    return acc
            return None
        for acc in accounts_list:
            if acc.get('is_default'): return acc
        return accounts_list[0]

    @staticmethod
    async def add_account(supabase_admin, chat_id, user_id, text):
        parts = text.replace("/addaccount", "").strip().split()
        if len(parts) < 2:
            await send_telegram_reply(chat_id, "⚠️ Use: `/addaccount [BankName] [Balance]`")
            return

        acc_name = " ".join(parts[:-1]).title()
        try:
            acc_bal = float(parts[-1])
        except ValueError:
            await send_telegram_reply(chat_id, "⚠️ Invalid balance amount.")
            return

        existing_accs = supabase_admin.table('accounts').select('id').eq('user_id', user_id).execute()
        is_first = len(existing_accs.data) == 0
        try:
            supabase_admin.table('accounts').insert({
                "user_id": user_id, "account_name": acc_name, "balance": acc_bal, "is_default": is_first
            }).execute()
            await send_telegram_reply(chat_id, f"🏦 *Account Added*\\nName: {acc_name}\\nBalance: ₹{acc_bal:,.2f}")
        except Exception as e:
            await send_telegram_reply(chat_id, f"❌ Failed to add account: {str(e)}")

    @staticmethod
    async def set_default(supabase_admin, chat_id, user_id, text):
        acc_name = text.replace("/setdefault", "").strip().title()
        if not acc_name:
            await send_telegram_reply(chat_id, "⚠️ Please provide an account name.")
            return

        acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).ilike('account_name', acc_name).execute()
        if not acc_res.data:
            await send_telegram_reply(chat_id, f"❌ Account '{acc_name}' not found.")
            return

        try:
            supabase_admin.table('accounts').update({"is_default": False}).eq('user_id', user_id).execute()
            supabase_admin.table('accounts').update({"is_default": True}).eq('id', acc_res.data[0]['id']).execute()
            await send_telegram_reply(chat_id, f"✅ '{acc_res.data[0]['account_name']}' is now your default account.")
        except Exception as e:
            await send_telegram_reply(chat_id, f"❌ Failed to set default: {str(e)}")
""",

        "app/telegram/handlers/salary_handler.py": """\
import calendar
from datetime import datetime
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply

class SalaryHandler:
    @staticmethod
    async def set_salary(supabase_admin, chat_id, user_id, text):
        parts = text.replace("/setsalary", "").strip().split()
        if len(parts) < 2:
            await send_telegram_reply(chat_id, "⚠️ Use format: `/setsalary [Month] [Amount]`")
            return

        timeframe = parts[0].strip().lower()
        try: new_amount = float(parts[1].replace(",", ""))
        except: 
            await send_telegram_reply(chat_id, "⚠️ Invalid amount.")
            return

        current_dt = datetime.now(TZ_IST)
        target_year = current_dt.year

        month_map = {"1":"1", "jan":"1", "january":"1", "2":"2", "feb":"2", "february":"2", "3":"3", "mar":"3", "march":"3", "4":"4", "apr":"4", "april":"4", "5":"5", "may":"5", "6":"6", "jun":"6", "june":"6", "7":"7", "jul":"7", "july":"7", "8":"8", "aug":"8", "august":"8", "9":"9", "sep":"9", "september":"9", "10":"10", "oct":"10", "october":"10", "11":"11", "nov":"11", "november":"11", "12":"12", "dec":"12", "december":"12"}

        if timeframe.isdigit() and len(timeframe) == 4:
            target_year = int(timeframe)
            target_months = list(range(1, 13))
        elif timeframe in month_map:
            target_months = [int(month_map[timeframe])]
        else:
            await send_telegram_reply(chat_id, f"⚠️ Unknown month or year: '{timeframe}'")
            return

        acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).eq('is_default', True).execute()
        if not acc_res.data:
            await send_telegram_reply(chat_id, "❌ No default account found.")
            return
        default_acc = acc_res.data[0]
        balance_adjustment = 0.0

        for m in target_months:
            last_day = calendar.monthrange(target_year, m)[1]
            salary_date = current_dt.replace(year=target_year, month=m, day=last_day, hour=23, minute=59, second=59)
            month_name = salary_date.strftime('%b %Y')

            sal_check = supabase_admin.table('salaries').select('*').eq('user_id', user_id).eq('year', target_year).eq('month_number', m).execute()

            if sal_check.data:
                sal_id = sal_check.data[0]['id']
                old_amount = float(sal_check.data[0]['amount'])
                if sal_check.data[0]['is_deducted']:
                    await send_telegram_reply(chat_id, f"⚠️ Salary for {month_name} already deducted.")
                    continue
                diff = new_amount - old_amount
                balance_adjustment += diff
                supabase_admin.table('salaries').update({"amount": new_amount}).eq("id", sal_id).execute()
                supabase_admin.table('transactions').update({"amount": new_amount}).eq('user_id', user_id).eq('subcategory', 'Salary').eq('date', salary_date.isoformat()).execute()
            else:
                balance_adjustment += new_amount
                supabase_admin.table('salaries').insert({"user_id": user_id, "year": target_year, "month_number": m, "month_name": month_name, "amount": new_amount, "is_deducted": False}).execute()
                supabase_admin.table('transactions').insert({"user_id": user_id, "amount": new_amount, "txn_type": "income", "description": f"Salary for {month_name}", "intent": "income", "category": "Income", "subcategory": "Salary", "date": salary_date.isoformat(), "destination_account": default_acc['account_name'], "soft_deleted": False}).execute()

        new_bal = float(default_acc['balance']) + balance_adjustment
        supabase_admin.table('accounts').update({"balance": new_bal}).eq("id", default_acc['id']).execute()

        if balance_adjustment != 0:
            supabase_admin.table('account_logs').insert({"account_id": default_acc['id'], "user_id": user_id, "log_type": "CREDIT" if balance_adjustment >= 0 else "DEBIT", "amount": abs(balance_adjustment), "balance_after": new_bal, "description": f"Salary Update ({timeframe})"}).execute()

        await send_telegram_reply(chat_id, f"✅ Salary updated successfully for {timeframe.title()}.\\nNew Balance: ₹{new_bal:,.2f}")

    @staticmethod
    async def deduct_all(supabase_admin, chat_id, user_id, match):
        month_str = match.group(1).lower()
        month_map = {"jan":"1", "january":"1", "feb":"2", "february":"2", "mar":"3", "march":"3", "apr":"4", "april":"4", "may":"5", "jun":"6", "june":"6", "jul":"7", "july":"7", "aug":"8", "august":"8", "sep":"9", "september":"9", "oct":"10", "october":"10", "nov":"11", "november":"11", "dec":"12", "december":"12"}
        if month_str not in month_map:
            await send_telegram_reply(chat_id, "⚠️ Invalid month.")
            return

        target_m = int(month_map[month_str])
        current_dt = datetime.now(TZ_IST)
        target_year = current_dt.year

        sal_res = supabase_admin.table('salaries').select('*').eq('user_id', user_id).eq('year', target_year).eq('month_number', target_m).execute()
        if not sal_res.data:
            await send_telegram_reply(chat_id, f"❌ No salary record found for {month_str.title()} {target_year}.")
            return

        sal_record = sal_res.data[0]
        if sal_record['is_deducted']:
            await send_telegram_reply(chat_id, f"❌ *Hard Block Activated*\\nSalary for **{month_str.title()} {target_year}** already fully deducted.")
            return

        salary_amount = float(sal_record['amount'])
        acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).eq('is_default', True).execute()
        if not acc_res.data: return

        default_acc = acc_res.data[0]
        current_bal = float(default_acc['balance'])

        if current_bal < salary_amount:
            await send_telegram_reply(chat_id, f"❌ Insufficient balance to deduct ₹{salary_amount:,.2f}.")
            return

        last_day = calendar.monthrange(target_year, target_m)[1]
        expense_date = current_dt.replace(year=target_year, month=target_m, day=last_day, hour=23, minute=59, second=59)

        supabase_admin.table('transactions').insert({"user_id": user_id, "amount": salary_amount, "txn_type": "expense", "description": f"Deducted all amount of {month_str.title()}", "intent": "expense", "category": "Miscellaneous", "subcategory": "Monthly Clear", "date": expense_date.isoformat(), "source_account": default_acc['account_name'], "soft_deleted": False}).execute()
        supabase_admin.table('salaries').update({"is_deducted": True}).eq("id", sal_record['id']).execute()

        new_bal = current_bal - salary_amount
        supabase_admin.table('accounts').update({"balance": new_bal}).eq("id", default_acc['id']).execute()
        supabase_admin.table('account_logs').insert({"account_id": default_acc['id'], "user_id": user_id, "log_type": "DEBIT", "amount": salary_amount, "balance_after": new_bal, "description": f"Deducted all amount of {month_str.title()}"}).execute()

        await send_telegram_reply(chat_id, f"✅ Deducted ₹{salary_amount:,.2f} for {month_str.title()} successfully.\\nNew Balance: ₹{new_bal:,.2f}")
""",

        "app/telegram/handlers/report_handler.py": """\
import uuid
from datetime import datetime, timedelta
from fastapi import HTTPException
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply

REPORT_TOKENS = {}

class ReportHandler:
    @staticmethod
    async def generate_report_link(request_url, chat_id, user_id):
        token = str(uuid.uuid4())
        expires_at = datetime.now(TZ_IST) + timedelta(hours=1)
        REPORT_TOKENS[token] = {"user_id": user_id, "expires_at": expires_at}

        base_url = str(request_url).split('/webhook')[0]
        report_url = f"{base_url}/report/view/{token}"

        response_msg = (
            f"📊 *Next-Level AI Financial Report Generated*\\n\\n"
            f"Your interactive HTML report is ready with phase-by-phase analytics.\\n\\n"
            f"🔗 [View Downloadable Report]({report_url})\\n\\n"
            f"⏰ *Note:* This secure link will automatically expire in **1 hour**."
        )
        await send_telegram_reply(chat_id, response_msg)

    @staticmethod
    async def get_html_report(token: str, supabase_admin):
        token_data = REPORT_TOKENS.get(token)
        if not token_data: raise HTTPException(status_code=404, detail="Report link expired or invalid.")
        if datetime.now(TZ_IST) > token_data["expires_at"]:
            del REPORT_TOKENS[token]
            raise HTTPException(status_code=410, detail="Report link has expired.")

        user_id = token_data["user_id"]
        user_res = supabase_admin.table('users').select('*').eq('id', user_id).execute()
        user_name = user_res.data[0]['full_name'] if user_res.data else "Valued User"

        acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
        accounts = acc_res.data or []
        total_balance = sum(float(a['balance']) for a in accounts)

        txn_res = supabase_admin.table('transactions').select('*').eq('user_id', user_id).eq('soft_deleted', False).order('date', desc=True).execute()
        txns = txn_res.data or []

        total_income = sum(float(t['amount']) for t in txns if t['txn_type'] == 'income')
        total_expense = sum(float(t['amount']) for t in txns if t['txn_type'] == 'expense')
        net_savings = total_income - total_expense

        accounts_html = "".join([f'<div class="bg-slate-950 border border-slate-800 p-4 rounded-xl flex justify-between items-center"><span class="font-semibold text-slate-200">{acc["account_name"]}</span><span class="font-mono text-emerald-400">₹{float(acc["balance"]):,.2f}</span></div>' for acc in accounts])

        txns_html = "".join([f'<tr class="hover:bg-slate-800/50"><td class="py-3 px-4 text-slate-400">{datetime.fromisoformat(t["date"].replace("Z", "+00:00")).astimezone(TZ_IST).strftime("%d %b %Y")}</td><td class="py-3 px-4 font-medium text-white">{t["description"]}</td><td class="py-3 px-4 text-slate-400">{t["category"] or "Unassigned"}</td><td class="py-3 px-4"><span class="px-2 py-1 rounded-full text-xs font-semibold {"bg-emerald-500/20 text-emerald-300" if t["txn_type"] == "income" else "bg-rose-500/20 text-rose-300"}">{t["txn_type"].upper()}</span></td><td class="py-3 px-4 text-right font-mono {"text-emerald-400" if t["txn_type"] == "income" else "text-rose-400"}">{"+" if t["txn_type"] == "income" else "-"}₹{float(t["amount"]):,.2f}</td></tr>' for t in txns[:50]])

        return f~TRIPLE_QUOTE~<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PocketMunim AI Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>body {{ font-family: sans-serif; }}</style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen py-10 px-4">
    <div class="max-w-5xl mx-auto space-y-8">
        <div class="bg-slate-900 border border-slate-800 rounded-3xl p-8 flex justify-between">
            <div>
                <h1 class="text-3xl font-bold text-white">Dashboard: {user_name}</h1>
            </div>
            <div class="text-right">
                <p class="text-xs text-slate-400">Net Worth / Balance</p>
                <p class="text-2xl font-extrabold text-emerald-400">₹{total_balance:,.2f}</p>
            </div>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-6">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 border-l-4 border-l-emerald-500">
                <p class="text-sm text-slate-400">Total Income</p>
                <p class="text-2xl font-bold text-emerald-400">₹{total_income:,.2f}</p>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 border-l-4 border-l-rose-500">
                <p class="text-sm text-slate-400">Total Expenses</p>
                <p class="text-2xl font-bold text-rose-400">₹{total_expense:,.2f}</p>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 border-l-4 border-l-cyan-500">
                <p class="text-sm text-slate-400">Net Savings</p>
                <p class="text-2xl font-bold text-cyan-400">₹{net_savings:,.2f}</p>
            </div>
        </div>
        <div class="bg-slate-900 border border-slate-800 rounded-3xl p-6">
            <h2 class="text-xl font-bold text-white mb-4">Linked Bank Accounts</h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">{accounts_html}</div>
        </div>
        <div class="bg-slate-900 border border-slate-800 rounded-3xl p-6">
            <h2 class="text-xl font-bold text-white mb-4">Transaction History</h2>
            <table class="w-full text-left text-sm text-slate-300">
                <tbody class="divide-y divide-slate-800">{txns_html}</tbody>
            </table>
        </div>
    </div>
</body>
</html>~TRIPLE_QUOTE~

    @staticmethod
    async def monthly_summary(supabase_admin, chat_id, user_id, text):
        parts = text.replace("/monthly", "").strip().split()
        if len(parts) < 2:
            await send_telegram_reply(chat_id, "⚠️ Use format: `/monthly [Month] [Year]`")
            return
        try:
            target_dt = datetime.strptime(f"1 {parts[0][:3]} {parts[1]}", "%d %b %Y")
            start_date = target_dt.strftime("%Y-%m-%d")
            end_dt = target_dt.replace(year=target_dt.year + 1, month=1) if target_dt.month == 12 else target_dt.replace(month=target_dt.month + 1)
            end_date = end_dt.strftime("%Y-%m-%d")

            txns = supabase_admin.table('transactions').select('amount, txn_type').eq('user_id', user_id).gte('date', start_date).lt('date', end_date).eq('soft_deleted', False).execute()

            total_income = sum(t['amount'] for t in txns.data if t['txn_type'] == 'income')
            total_expense = sum(t['amount'] for t in txns.data if t['txn_type'] == 'expense')

            reply = f"📊 *Monthly Report: {target_dt.strftime('%B %Y')}*\\n\\n🟢 *Total Income:* ₹{total_income:,.2f}\\n🔴 *Total Expense:* ₹{total_expense:,.2f}\\n------------------------\\n💰 *Net Saved:* ₹{(total_income - total_expense):,.2f}"
            await send_telegram_reply(chat_id, reply)
        except ValueError:
            await send_telegram_reply(chat_id, "⚠️ Invalid date format.")
""",

        "app/telegram/handlers/callback_handler.py": """\
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
""",

        "app/telegram/handlers/nlp_handler.py": """\
import json
import uuid
from decimal import Decimal
from datetime import datetime, timedelta
from app.ai.ai_provider import execute_resilient_ai
from app.ai.schemas import AITransactionExtraction
from app.cache.category_cache import CategoryCacheManager
from app.services.bulk_transaction_service import BulkTransactionService
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply
from app.telegram.handlers.account_handler import AccountHandler
from app.telegram.handlers.callback_handler import CallbackHandler, PENDING_BATCHES

def generate_recurrence_dates(start_date_str: str, frequency: str, current_dt: datetime) -> list:
    try: start_dt = datetime.strptime(start_date_str.split("T")[0], "%Y-%m-%d").replace(tzinfo=current_dt.tzinfo)
    except Exception: return []
    dates = []
    curr_iter = start_dt
    freq = frequency.lower() if frequency else ""
    while curr_iter <= current_dt:
        dates.append(curr_iter)
        if freq == 'monthly':
            try: curr_iter = curr_iter.replace(month=curr_iter.month + 1)
            except ValueError: curr_iter = curr_iter.replace(month=curr_iter.month + 1, day=28)
        else: break
    return dates

SYSTEM_PROMPT = ~TRIPLE_QUOTE~SYSTEM ROLE:
You are the PocketMunim Enterprise NLP Extraction Engine. Your exclusive mandate is to extract financial data, commands, and intents from unstructured multi-lingual text.

CRITICAL RULES (NON-NEGOTIABLE):
1. NO MATHEMATICS & NO SPLITTING: You are strictly forbidden from calculating totals, EMIs, balances, or splitting amounts.
2. NO HALLUCINATION: If a field is missing, return `null`. Never guess or assume default values.
3. MULTI-INTENT & SEQUENCING: A single message may contain multiple operations. Extract each as a separate object in the `transactions` array.
4. BULK DETECTION: If the user lists MORE THAN 1 item, set `metadata.bulk_operation = true` and `operation_type = "bulk"`.
5. UNKNOWN CATEGORIES: If you cannot confidently map an item to a standard category, set the transaction's `category` and `subcategory` to `null`.
6. LOAN PAYMENTS: A loan payment MUST generate two intents: an `expense`, AND a `loan_payment` intent.
7. EXACT DATES & CURRENCY: TODAY IS {CURRENT_DATE}. If no date is explicitly mentioned, ALWAYS assume the transaction occurred TODAY. DO NOT default to the 1st of the month.
8. CLARIFICATION STRICTNESS: You MUST NOT set needs_clarification = true unless the AMOUNT is missing. Never ask for missing accounts, categories, payment methods, or DATES.
9. JSON ONLY: Output NOTHING but valid JSON. No markdown wrappers.
10. PEER-TO-PEER TRANSFERS / INCOME SOURCES: If a user receives money, set intent to "income".
11. ACCOUNT ROUTING: If user specifies an account paid FROM, set `source_account`. If received INTO, set `destination_account`.
12. GENERIC NAMES: If a transaction involves a generic person term ("friend"), set `needs_clarification = true`.
13. PAST RECURRING: For inputs like "every month on 17th from jun 2025", set recurrence.enabled = true.
14. FULL PROCESSING MANDATE (ANTI-LAZINESS): You MUST extract and process EVERY SINGLE ITEM provided in the user's input. Do NOT truncate, skip, stop early, or group items. If the user lists 50 items, your `transactions` array MUST contain exactly 50 objects.

JSON OUTPUT SCHEMA:
{
  "metadata": {"operation_type": "string", "bulk_operation": false},
  "transactions": [
    {
      "intent": "expense", "amount": 0.0, "item": "string", "category": "string", "subcategory": "string",
      "source_account": "string", "destination_account": "string",
      "date": {"relative_date": "string"}, "recurrence": {"enabled": false}, "future": {"is_future": false},
      "needs_clarification": false, "clarification_fields": []
    }
  ],
  "loan": {"intent": "string", "lender": "string", "amount": 0.0}
}
~TRIPLE_QUOTE~

class NLPHandler:
    @staticmethod
    async def pull_categories(supabase_admin, chat_id, user_id, text, category_pull_service):
        query = text.replace("/categorypull", "").strip()
        await send_telegram_reply(chat_id, f"⏳ Pulling categories...")
        pull_result = category_pull_service.manual_category_pull(query, user_id)
        if pull_result.get("added", 0) > 0:
            CategoryCacheManager(supabase_admin, user_id).rebuild_cache()
            await send_telegram_reply(chat_id, f"✅ Successfully pulled {pull_result['added']} items.")
        else:
            await send_telegram_reply(chat_id, f"❌ Failed to pull categories: {pull_result.get('error')}")

    @staticmethod
    async def process_text(supabase_admin, supabase, chat_id, user_id, text, category_pull_service):
        try:
            current_dt = datetime.now(TZ_IST)
            dynamic_system_prompt = SYSTEM_PROMPT.replace("{CURRENT_DATE}", f"{current_dt.strftime('%Y-%m-%d')} ({current_dt.strftime('%A')})")

            raw_response_text = execute_resilient_ai(system_prompt=dynamic_system_prompt, user_prompt=text, db_client=supabase_admin, is_json=True)
            raw_json = json.loads(raw_response_text)
            validated_data = AITransactionExtraction(**raw_json)
            transactions_list = validated_data.transactions or []

            acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
            user_accounts = acc_res.data or []

            if not user_accounts and transactions_list:
                await send_telegram_reply(chat_id, "❌ *No Bank Accounts Configured*\\nUse `/addaccount [BankName] [Balance]`")
                return

            if not transactions_list:
                await send_telegram_reply(chat_id, "⚠️ No valid financial transactions were extracted.")
                return

            cache_manager = CategoryCacheManager(supabase, user_id)

            # ================= BULK TRANSACTION PIPELINE =================
            if len(transactions_list) > 1:
                default_acc = AccountHandler.get_account_from_list(user_accounts)
                bulk_service = BulkTransactionService(supabase_admin, user_id, cache_manager, category_pull_service)
                result = bulk_service.process_bulk_payload(transactions_list, default_acc)

                if result["unique"]:
                    current_bal = float(default_acc['balance'])
                    total_deduction = sum(p["amount"] for p in result["unique"] if p["source_account"] == default_acc['account_name'])
                    total_addition = sum(p["amount"] for p in result["unique"] if p["destination_account"] == default_acc['account_name'])

                    if (current_bal - total_deduction + total_addition) < 0:
                        await send_telegram_reply(chat_id, f"❌ *Insufficient Balance*")
                        return

                    bulk_service.dao.execute_bulk_commit(default_acc['id'], result["unique"], total_deduction, total_addition, current_bal)
                    bd_text = "\\n".join(result["breakdown"]) if result["breakdown"] else "No unique items."
                    receipt = f"🧾 *BULK TRANSACTION SAVED*\\n🔴 *EXPENSE* | 🟢 *INCOME* | 🔵 *TRANSFER*\\n\\n🔹 *Total Expenses:* ₹{result['totals']['expenses']:,.2f}\\n🔹 *Items Processed:* {len(result['unique'])}\\n🔹 *Primary Account:* {default_acc['account_name']}\\n🛒 *Receipt Breakdown:*\\n{bd_text}"
                    await send_telegram_reply(chat_id, receipt)

                if result["duplicates"]:
                    batch_id = uuid.uuid4().hex[:8]
                    PENDING_BATCHES[batch_id] = {"user_id": user_id, "account_id": default_acc['id'], "items": result["duplicates"]}
                    keyboard = CallbackHandler.generate_duplicate_keyboard(batch_id, result["duplicates"])
                    await send_telegram_reply(chat_id, f"⚠️ *Duplicate Entries Found ({len(result['duplicates'])} items)*\\nTap to select/save duplicates.", reply_markup=keyboard)
                return

            # ================= SINGLE TRANSACTION PIPELINE =================
            response_sections, committed_items = [], []
            for tx in transactions_list:
                amount = tx.amount if tx.amount else Decimal('0.00')
                description = str(tx.item or tx.merchant or text).title()

                if amount > Decimal('0.00'):
                    if tx.future and tx.future.is_future:
                        response_sections.append(f"🗓️ '{description}' identified as future plan.")
                        continue
                    if not tx.intent or tx.needs_clarification:
                        response_sections.append(f"⚠️ Could not process '{description}'. Clarify: {','.join(tx.clarification_fields or [])}")
                        continue

                    tx_dates = []
                    is_recurring_past = False
                    if tx.recurrence and tx.recurrence.enabled and tx.recurrence.start_date:
                        tx_dates = generate_recurrence_dates(tx.recurrence.start_date, tx.recurrence.frequency or "monthly", current_dt)
                        if tx_dates: is_recurring_past = True
                    if not is_recurring_past:
                        db_date_obj = current_dt
                        if tx.date and tx.date.relative_date:
                            try: db_date_obj = datetime.strptime(tx.date.relative_date.split("T")[0], "%Y-%m-%d").replace(tzinfo=TZ_IST)
                            except: pass
                        tx_dates = [db_date_obj]

                    num_occ = Decimal(len(tx_dates))
                    tot_amt = amount * num_occ
                    source_acc_obj = AccountHandler.get_account_from_list(user_accounts, tx.source_account) if tx.intent in ["expense", "transfer_other", "transfer_own"] else None
                    dest_acc_obj = AccountHandler.get_account_from_list(user_accounts, tx.destination_account) if tx.intent in ["income", "transfer_own"] else None

                    updates_to_make = []
                    if tot_amt > Decimal('0.00'):
                        if source_acc_obj:
                            current_bal = Decimal(str(source_acc_obj['balance']))
                            if current_bal < tot_amt:
                                response_sections.append(f"❌ *Insufficient Balance* in {source_acc_obj['account_name']}.")
                                continue
                            updates_to_make.append((source_acc_obj['id'], float(current_bal - tot_amt), "DEBIT", float(tot_amt)))
                        if dest_acc_obj:
                            updates_to_make.append((dest_acc_obj['id'], float(Decimal(str(dest_acc_obj['balance'])) + tot_amt), "CREDIT", float(tot_amt)))

                    for acc_id, new_bal, log_type, txn_amount in updates_to_make:
                        supabase_admin.table('accounts').update({"balance": new_bal}).eq("id", acc_id).execute()
                        try: supabase_admin.table('account_logs').insert({"account_id": acc_id, "user_id": user_id, "log_type": log_type, "amount": txn_amount, "balance_after": new_bal, "description": description}).execute()
                        except: pass

                    category = tx.category
                    subcategory = tx.subcategory
                    if not category:
                        cached = cache_manager.search_item(description)
                        if cached and cached.get("category"): category, subcategory = cached["category"], cached.get("subcategory")
                        else:
                            ai_cls = category_pull_service.classify_item(description, intent=tx.intent)
                            category, subcategory = ai_cls.get("category", "General"), ai_cls.get("subcategory", "Miscellaneous")

                    db_payloads = [{"user_id": user_id, "amount": float(amount), "txn_type": tx.intent, "description": description, "intent": tx.intent, "category": category, "subcategory": subcategory, "date": d.isoformat(), "source_account": source_acc_obj['account_name'] if source_acc_obj else None, "destination_account": dest_acc_obj['account_name'] if dest_acc_obj else None, "soft_deleted": False} for d in tx_dates]

                    try:
                        if len(db_payloads) == 1: supabase.table("transactions").insert(db_payloads[0]).execute()
                        elif len(db_payloads) > 1: supabase.table("transactions").insert(db_payloads).execute()
                    except: continue

                    committed_items.append(f"✅ *Transaction Saved*\\n🔹 {description}: ₹{float(amount):,.2f}")

            if committed_items: response_sections.append("\\n\\n".join(committed_items))
            if response_sections: await send_telegram_reply(chat_id, "\\n\\n".join(response_sections))
        except Exception as e:
            await send_telegram_reply(chat_id, f"Error processing text: {str(e)}")
""",

        "app/main.py": """\
import os
import re
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from supabase import create_client, Client

from app.security.auth import authenticate_telegram_request
from app.ai.category_pull_service import CategoryPullService
from app.telegram.telegram_utils import send_telegram_reply
from app.telegram.handlers.user_handler import UserHandler
from app.telegram.handlers.account_handler import AccountHandler
from app.telegram.handlers.salary_handler import SalaryHandler
from app.telegram.handlers.report_handler import ReportHandler
from app.telegram.handlers.callback_handler import CallbackHandler
from app.telegram.handlers.nlp_handler import NLPHandler

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else supabase

category_pull_service = CategoryPullService(None, supabase_admin)

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/")
def health_check():
    return {"status": "PocketMunim Enterprise API is live (Modular Architecture)", "status_code": 200}

@app.get("/report/view/{token}", response_class=HTMLResponse)
async def view_report(token: str):
    html_content = await ReportHandler.get_html_report(token, supabase_admin)
    return HTMLResponse(content=html_content)

@app.post("/webhook")
async def telegram_webhook(request: Request, authorized: bool = Depends(authenticate_telegram_request)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if "callback_query" in payload:
        return await CallbackHandler.handle(payload, supabase_admin)

    message = payload.get("message", payload.get("edited_message", {}))
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()

    if not text or not chat_id:
        return {"ok": True}

    user_id = str(request.state.telegram_id)

    is_safe, user_exists = await UserHandler.security_check(supabase_admin, chat_id, text)
    if not is_safe: return {"ok": True}

    if not user_exists and not text.startswith("/register"):
        await UserHandler.prompt_registration(chat_id)
        return {"ok": True}

    # ================= COMMAND ROUTING =================
    if text.startswith("/register"):
        await UserHandler.register(supabase_admin, chat_id, user_id, text, user_exists)
    elif text.startswith("/setsalary"):
        await SalaryHandler.set_salary(supabase_admin, chat_id, user_id, text)
    elif deduct_all_match := re.match(r"^deduct all amount of ([a-zA-Z]+)$", text, re.IGNORECASE):
        await SalaryHandler.deduct_all(supabase_admin, chat_id, user_id, deduct_all_match)
    elif text.startswith("/report"):
        await ReportHandler.generate_report_link(request.url, chat_id, user_id)
    elif text.startswith("/addaccount"):
        await AccountHandler.add_account(supabase_admin, chat_id, user_id, text)
    elif text.startswith("/setdefault"):
        await AccountHandler.set_default(supabase_admin, chat_id, user_id, text)
    elif text.startswith("/start"):
        await send_telegram_reply(chat_id, "Welcome to PocketMunim.\\n\\nYour automated financial intelligence system is active.")
    elif text.startswith("/categorypull"):
        await NLPHandler.pull_categories(supabase_admin, chat_id, user_id, text, category_pull_service)
    elif text.startswith("/history"):
        await send_telegram_reply(chat_id, "📋 *Historical Data Auto-Template*\\n...")
    elif text.startswith("/monthly"):
        await ReportHandler.monthly_summary(supabase_admin, chat_id, user_id, text)
    else:
        await NLPHandler.process_text(supabase_admin, supabase, chat_id, user_id, text, category_pull_service)

    return {"ok": True}
"""
    }

    for filepath, content in files.items():
        dir_name = os.path.dirname(filepath)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        # Remove literal triple-quotes replacement to generate safely
        final_content = content.replace("~TRIPLE_QUOTE~", '\"\"\"')
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(final_content)
        print(f"  [+] Updated/Created: {filepath}")

    print("\\n[SUCCESS] Business Logic completely decoupled. Handlers deployed.")


if __name__ == "__main__":
    create_workspace()