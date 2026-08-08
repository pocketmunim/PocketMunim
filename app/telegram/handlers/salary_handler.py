import re
from datetime import datetime
from decimal import Decimal
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply


class SalaryHandler:
    # ... your existing methods (set_salary, deduct_all) are here ...

    @staticmethod
    async def settle_salary(supabase_admin, chat_id, user_id, text: str):
        # Parses formats like "/settle jan", "/settle january", "/settle jan 2025", "/settle jan 25"
        match = re.match(r"^/settle\s+([a-zA-Z]+)(?:\s+(\d{2,4}))?$", text.strip(), re.IGNORECASE)
        if not match:
            await send_telegram_reply(chat_id,
                                      "⚠️ *Invalid format.*\nUse: `/settle [month]` or `/settle [month] [year]`\nExample: `/settle jan` or `/settle jan 2025`")
            return

        month_str = match.group(1).lower()
        year_str = match.group(2)

        # Map string to month number
        month_map = {
            'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
            'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6,
            'jul': 7, 'july': 7, 'aug': 8, 'august': 8, 'sep': 9, 'september': 9,
            'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12
        }

        if month_str not in month_map:
            await send_telegram_reply(chat_id, f"⚠️ Unknown month: '{match.group(1)}'.")
            return

        month_num = month_map[month_str]
        month_name_full = datetime(2000, month_num, 1).strftime('%B')

        # Dynamic Year Logic
        current_year = datetime.now(TZ_IST).year
        if year_str:
            if len(year_str) == 2:
                target_year = 2000 + int(year_str)
            else:
                target_year = int(year_str)
        else:
            target_year = current_year

        # 1. Fetch Salary
        sal_res = supabase_admin.table('salaries').select('*').eq('user_id', user_id).eq('year', target_year).eq(
            'month_number', month_num).execute()
        if not sal_res.data:
            await send_telegram_reply(chat_id, f"⚠️ No salary record found for *{month_name_full} {target_year}*.")
            return

        salary = sal_res.data[0]
        if salary.get('is_deducted'):
            await send_telegram_reply(chat_id,
                                      f"ℹ️ Salary for *{month_name_full} {target_year}* is already settled/deducted.")
            return

        amount = Decimal(str(salary['amount']))

        # 2. Fetch Default Account
        acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).eq('is_default', True).execute()
        if not acc_res.data:
            await send_telegram_reply(chat_id, "⚠️ No default account found to process settlement. Please add one.")
            return

        default_acc = acc_res.data[0]
        new_balance = Decimal(str(default_acc['balance'])) - amount

        # 3. Perform Updates across all tables
        try:
            # A. Deduct account balance
            supabase_admin.table('accounts').update({"balance": float(new_balance)}).eq('id',
                                                                                        default_acc['id']).execute()

            # B. Mark salary as deducted
            supabase_admin.table('salaries').update({"is_deducted": True}).eq('id', salary['id']).execute()

            desc = f"Manual Settlement for {month_name_full} {target_year}"
            now_iso = datetime.now(TZ_IST).isoformat()

            # C. Insert Transaction (so it shows in Reports beautifully)
            supabase_admin.table('transactions').insert({
                "user_id": user_id,
                "amount": float(amount),
                "txn_type": "expense",
                "intent": "settlement",
                "category": "Settlement",
                "subcategory": "Monthly Settlement",
                "source_account": default_acc['account_name'],
                "description": desc,
                "date": now_iso,
                "soft_deleted": False
            }).execute()

            # D. Insert Account Log
            supabase_admin.table('account_logs').insert({
                "account_id": default_acc['id'],
                "user_id": user_id,
                "log_type": "debit",
                "amount": float(amount),
                "balance_after": float(new_balance),
                "description": desc,
                "created_at": now_iso
            }).execute()

            await send_telegram_reply(
                chat_id,
                f"✅ *Settlement Successful!*\n\n"
                f"🧹 Salary of ₹{float(amount):,.2f} for *{month_name_full} {target_year}* has been settled.\n"
                f"📉 Deducted from: *{default_acc['account_name']}*\n"
                f"📊 Transactions & Logs updated."
            )

        except Exception as e:
            await send_telegram_reply(chat_id, f"⚠️ Error processing settlement: `{str(e)}`")