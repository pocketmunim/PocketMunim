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

        await send_telegram_reply(chat_id, f"✅ Salary updated successfully for {timeframe.title()}.\nNew Balance: ₹{new_bal:,.2f}")

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
            await send_telegram_reply(chat_id, f"❌ *Hard Block Activated*\nSalary for **{month_str.title()} {target_year}** already fully deducted.")
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

        await send_telegram_reply(chat_id, f"✅ Deducted ₹{salary_amount:,.2f} for {month_str.title()} successfully.\nNew Balance: ₹{new_bal:,.2f}")
