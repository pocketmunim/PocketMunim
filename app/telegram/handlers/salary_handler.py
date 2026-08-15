import re
from datetime import datetime
from decimal import Decimal
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply
from app.services.business_calendar_service import BusinessCalendarService


class SalaryHandler:
    @staticmethod
    async def set_salary(supabase_admin, chat_id, user_id, text):
        parts = text.replace("/setsalary", "").strip().split()
        if len(parts) < 2:
            await send_telegram_reply(chat_id, "💡 Use format: `/setsalary [Month/Year] [Amount] [Optional: Day]`")
            return

        timeframe = parts[0].strip().lower()
        try:
            new_amount = float(parts[1].replace(",", ""))
        except ValueError:
            await send_telegram_reply(chat_id, "⚠️ Invalid amount.")
            return

        expected_day = None
        if len(parts) >= 3:
            try:
                parsed_day = int(parts[2])
                if 1 <= parsed_day <= 31:
                    expected_day = parsed_day
            except ValueError:
                pass

        current_dt = datetime.now(TZ_IST)
        today_date = current_dt.date()
        current_year = current_dt.year
        target_year = current_year

        month_map = {"1": "1", "jan": "1", "january": "1", "2": "2", "feb": "2", "february": "2", "mar": "3",
                     "march": "3", "apr": "4", "april": "4", "may": "5", "jun": "6", "june": "6", "jul": "7",
                     "july": "7", "aug": "8", "august": "8", "sep": "9", "september": "9", "oct": "10", "october": "10",
                     "nov": "11", "november": "11", "dec": "12", "december": "12"}

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
        updated_months_count = 0
        past_months_affected = 0

        cal_service = BusinessCalendarService(supabase_admin)

        for m in target_months:
            sal_check = supabase_admin.table('salaries').select('*').eq('user_id', user_id).eq('year', target_year).eq(
                'month_number', m).execute()

            # Use existing expected_day if not explicitly provided in the command
            month_expected_day = expected_day if expected_day is not None else (
                sal_check.data[0].get('expected_day', 31) if sal_check.data else 31)

            actual_date = cal_service.get_actual_salary_date(target_year, m, month_expected_day)
            salary_date = datetime.combine(actual_date, datetime.max.time()).replace(tzinfo=TZ_IST)
            month_name = salary_date.strftime('%b %Y')

            if target_year < current_year:
                is_past_month = True
            elif target_year == current_year:
                is_past_month = actual_date <= today_date
            else:
                is_past_month = False

            start_date = f"{target_year}-{m:02d}-01"
            end_date = f"{target_year + 1}-01-01" if m == 12 else f"{target_year}-{m + 1:02d}-01"

            # Check if a transaction already exists in the ledger for this month
            txn_res = supabase_admin.table('transactions').select('*') \
                .eq('user_id', user_id) \
                .eq('subcategory', 'Salary') \
                .gte('date', start_date) \
                .lt('date', end_date) \
                .execute()

            existing_txn = txn_res.data[0] if txn_res.data else None

            if sal_check.data:
                sal_id = sal_check.data[0]['id']
                old_amount = float(sal_check.data[0]['amount'])

                if sal_check.data[0]['is_deducted']:
                    if len(target_months) == 1:
                        await send_telegram_reply(chat_id, f"💡 Salary for {month_name} already settled. Cannot modify.")
                    continue

                supabase_admin.table('salaries').update({"amount": new_amount, "expected_day": month_expected_day}).eq(
                    "id", sal_id).execute()

                if is_past_month:
                    past_months_affected += 1
                    if existing_txn:
                        # Transaction already existed, calculate exact delta
                        old_txn_amount = float(existing_txn['amount'])
                        diff = new_amount - old_txn_amount
                        balance_adjustment += diff
                        supabase_admin.table('transactions').update(
                            {"amount": new_amount, "date": salary_date.isoformat()}).eq("txn_id", existing_txn[
                            'txn_id']).execute()
                    else:
                        # Shifted from future to past: add full amount
                        balance_adjustment += new_amount
                        supabase_admin.table('transactions').insert({
                            "user_id": user_id, "amount": new_amount, "txn_type": "income",
                            "description": f"Salary for {month_name}", "intent": "income", "category": "Income",
                            "subcategory": "Salary", "date": salary_date.isoformat(),
                            "destination_account": default_acc['account_name'], "soft_deleted": False
                        }).execute()
                else:
                    # Shifted from past to future: remove existing transaction if any
                    if existing_txn:
                        balance_adjustment -= float(existing_txn['amount'])
                        supabase_admin.table('transactions').delete().eq("txn_id", existing_txn['txn_id']).execute()

                updated_months_count += 1
            else:
                supabase_admin.table('salaries').insert({
                    "user_id": user_id, "year": target_year, "month_number": m,
                    "month_name": month_name, "amount": new_amount, "is_deducted": False,
                    "expected_day": month_expected_day
                }).execute()

                if is_past_month:
                    balance_adjustment += new_amount
                    past_months_affected += 1
                    supabase_admin.table('transactions').insert({
                        "user_id": user_id, "amount": new_amount, "txn_type": "income",
                        "description": f"Salary for {month_name}", "intent": "income", "category": "Income",
                        "subcategory": "Salary", "date": salary_date.isoformat(),
                        "destination_account": default_acc['account_name'], "soft_deleted": False
                    }).execute()

                updated_months_count += 1

        if updated_months_count == 0:
            if len(target_months) > 1:
                await send_telegram_reply(chat_id, "💡 All specified months are already settled. No changes made.")
            return

        new_bal = float(default_acc['balance']) + balance_adjustment

        if past_months_affected > 0 or balance_adjustment != 0:
            supabase_admin.table('accounts').update({"balance": new_bal}).eq("id", default_acc['id']).execute()

        if balance_adjustment != 0:
            supabase_admin.table('account_logs').insert({
                "account_id": default_acc['id'], "user_id": user_id,
                "log_type": "CREDIT" if balance_adjustment >= 0 else "DEBIT",
                "amount": abs(balance_adjustment), "balance_after": new_bal,
                "description": f"Salary Update ({timeframe.title()})"
            }).execute()

        await send_telegram_reply(chat_id,
                                  f"✅ *Salary Updated*\nConfig updated and ledger synchronized.\nNew Account Balance: ₹{new_bal:,.2f}")

    @staticmethod
    async def settle_salary(supabase_admin, chat_id, user_id, text: str):
        match = re.match(r"^/settle\s+([a-zA-Z]+)(?:\s+(\d{2,4}))?$", text.strip(), re.IGNORECASE)
        if not match:
            await send_telegram_reply(chat_id,
                                      "💡 Format: `/settle [month]` or `/settle [month] [year]`\nExample: `/settle jan`")
            return

        month_str = match.group(1).lower()
        year_str = match.group(2)

        month_map = {
            'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
            'apr': 4, 'april': 4, 'may': 5, 'june': 6, 'jun': 6,
            'jul': 7, 'july': 7, 'aug': 8, 'august': 8, 'sep': 9, 'september': 9,
            'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12
        }

        if month_str not in month_map:
            await send_telegram_reply(chat_id, f"⚠️ Unknown month: '{match.group(1)}'.")
            return

        month_num = month_map[month_str]
        month_name_full = datetime(2000, month_num, 1).strftime('%B')

        current_dt = datetime.now(TZ_IST)
        current_year = current_dt.year

        target_year = int(year_str) if year_str else current_year
        if year_str and len(year_str) == 2:
            target_year = 2000 + int(year_str)

        sal_res = supabase_admin.table('salaries').select('*').eq('user_id', user_id).eq('year', target_year).eq(
            'month_number', month_num).execute()
        if not sal_res.data:
            await send_telegram_reply(chat_id, f"⚠️ No salary record found for *{month_name_full} {target_year}*.")
            return

        salary = sal_res.data[0]
        cal_service = BusinessCalendarService(supabase_admin)
        actual_date = cal_service.get_actual_salary_date(target_year, month_num, salary.get('expected_day', 31))

        is_past_month = (target_year < current_year) or (
                    target_year == current_year and actual_date <= current_dt.date())

        if not is_past_month:
            await send_telegram_reply(chat_id,
                                      f"⚠️ *Settlement Blocked*\nYou cannot settle the salary for {month_name_full} {target_year} until {actual_date.strftime('%b %d')}.")
            return

        if salary.get('is_deducted'):
            await send_telegram_reply(chat_id, f"💡 Salary for *{month_name_full} {target_year}* is already settled.")
            return

        amount = Decimal(str(salary['amount']))
        acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).eq('is_default', True).execute()
        if not acc_res.data:
            await send_telegram_reply(chat_id, "❌ Default bank account missing.")
            return

        default_acc = acc_res.data[0]
        new_balance = Decimal(str(default_acc['balance'])) - amount

        try:
            supabase_admin.table('accounts').update({"balance": float(new_balance)}).eq('id',
                                                                                        default_acc['id']).execute()
            supabase_admin.table('salaries').update({"is_deducted": True}).eq('id', salary['id']).execute()

            desc = f"Settlement for {month_name_full} {target_year}"
            now_iso = datetime.now(TZ_IST).isoformat()

            supabase_admin.table('transactions').insert({
                "user_id": user_id, "amount": float(amount), "txn_type": "expense",
                "intent": "settlement", "category": "Settlement", "subcategory": "Monthly Settlement",
                "source_account": default_acc['account_name'], "description": desc, "date": now_iso,
                "soft_deleted": False
            }).execute()

            supabase_admin.table('account_logs').insert({
                "account_id": default_acc['id'], "user_id": user_id, "log_type": "DEBIT",
                "amount": float(amount), "balance_after": float(new_balance), "description": desc
            }).execute()

            await send_telegram_reply(chat_id,
                                      f"✅ *Settlement Successful*\nSalary of ₹{float(amount):,.2f} for *{month_name_full} {target_year}* settled.\nDeducted from: *{default_acc['account_name']}*")
        except Exception as e:
            await send_telegram_reply(chat_id, f"❌ Error executing settlement: `{str(e)}`")