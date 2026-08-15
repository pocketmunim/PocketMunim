from datetime import datetime
from app.utils.constants import TZ_IST
from app.services.business_calendar_service import BusinessCalendarService
from app.interfaces.notification_gateway import TelegramNotificationAdapter


class CronHandler:
    @staticmethod
    async def process_daily_paydays(supabase_admin):
        current_dt = datetime.now(TZ_IST)
        today_date = current_dt.date()
        current_year = current_dt.year
        current_month = current_dt.month

        cal_service = BusinessCalendarService(supabase_admin)
        gateway = TelegramNotificationAdapter()

        # 1. Fetch all salaries configured for the current active month
        sal_res = supabase_admin.table('salaries').select('*').eq('year', current_year).eq('month_number',
                                                                                           current_month).execute()

        if not sal_res.data:
            return {"status": "no_salaries_configured"}

        processed_count = 0

        for sal in sal_res.data:
            user_id = sal['user_id']
            expected_day = sal.get('expected_day', 31)
            amount = float(sal['amount'])
            month_name = sal['month_name']

            # 2. Calculate the exact actual payday
            actual_date = cal_service.get_actual_salary_date(current_year, current_month, expected_day)

            # 3. IF today is payday, execute the deposit
            if actual_date == today_date:
                # Security Check: Ensure we don't double-pay if Cron runs twice
                txn_check = supabase_admin.table('transactions').select('txn_id') \
                    .eq('user_id', user_id).eq('subcategory', 'Salary') \
                    .like('description', f"Salary for {month_name}").execute()
                if txn_check.data:
                    continue

                acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).eq('is_default',
                                                                                                 True).execute()
                user_res = supabase_admin.table('users').select('telegram_id').eq('id', user_id).execute()

                if acc_res.data and user_res.data:
                    default_acc = acc_res.data[0]
                    chat_id = str(user_res.data[0]['telegram_id'])
                    new_bal = float(default_acc['balance']) + amount

                    # Ledger Updates
                    supabase_admin.table('accounts').update({"balance": new_bal}).eq("id", default_acc['id']).execute()
                    salary_dt = datetime.combine(actual_date, datetime.max.time()).replace(tzinfo=TZ_IST)

                    supabase_admin.table('transactions').insert({
                        "user_id": user_id, "amount": amount, "txn_type": "income",
                        "description": f"Salary for {month_name}", "intent": "income",
                        "category": "Income", "subcategory": "Salary",
                        "date": salary_dt.isoformat(),
                        "destination_account": default_acc['account_name'],
                        "soft_deleted": False
                    }).execute()

                    supabase_admin.table('account_logs').insert({
                        "account_id": default_acc['id'], "user_id": user_id, "log_type": "CREDIT",
                        "amount": amount, "balance_after": new_bal,
                        "description": f"Automated Salary Deposit ({month_name})"
                    }).execute()

                    # Push Notification via Abstract Gateway
                    msg = f"  *Happy Payday!*\n\n ₹{amount:,.2f} for {month_name} has been successfully credited to your {default_acc['account_name']} account.\n\nNew Balance: ₹{new_bal:,.2f}"
                    await gateway.send_message(chat_id, msg)
                    processed_count += 1

        return {"status": "success", "paydays_processed": processed_count}