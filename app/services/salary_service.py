from supabase import Client
from datetime import date
import calendar
from app.services.holiday_service import HolidayService


class SalaryService:
    @staticmethod
    async def seed_annual_salaries(
            db: Client,
            user_id: str,
            account_id: str,
            salary_amount: float,
            salary_date: int,
            year: int = None
    ) -> float:
        """
        Seeds 12 months of salaries and transactions.
        Credits all past/today salaries to the bank account and logs each in account_logs.
        Returns the total accumulated past salary credited.
        """
        if not year:
            year = date.today().year

        today = date.today()
        total_past_salaries_credited = 0.0

        for m in range(1, 13):
            max_days = calendar.monthrange(year, m)[1]
            day = min(salary_date, max_days)
            raw_payout_dt = date(year, m, day)

            # Auto-shift if payout falls on Weekend or Bank Holiday
            effective_payout_dt = await HolidayService.get_effective_payout_date(raw_payout_dt)

            is_past = effective_payout_dt <= today
            sal_status = "PAID" if is_past else "SCHEDULED"
            tx_status = "CREDITED" if is_past else "SCHEDULED"
            paid_timestamp = f"{effective_payout_dt}T00:00:00Z" if is_past else None

            # 1. Upsert salary month row
            sal_res = db.table('salaries').upsert({
                "user_id": user_id,
                "account_id": account_id,
                "year": year,
                "month": m,
                "base_amount": salary_amount,
                "actual_amount": salary_amount,
                "payout_date": str(effective_payout_dt),
                "status": sal_status,
                "paid_at": paid_timestamp,
                "is_custom_override": False
            }, on_conflict="user_id,year,month").execute()

            if sal_res.data:
                sal_id = sal_res.data[0]['salary_id']

                # 2. Insert corresponding transaction
                db.table('transactions').insert({
                    "user_id": user_id,
                    "account_id": account_id,
                    "salary_id": sal_id,
                    "type": "SALARY",
                    "category": "Salary",
                    "amount": salary_amount,
                    "transaction_date": str(effective_payout_dt),
                    "status": tx_status,
                    "description": f"Salary Credit - {calendar.month_name[m]} {year}"
                }).execute()

                # 3. If past, record account log entry and tally total
                if is_past:
                    total_past_salaries_credited += salary_amount
                    db.table('account_logs').insert({
                        "user_id": user_id,
                        "account_id": account_id,
                        "event_type": "SALARY_HISTORICAL_CREDIT",
                        "amount": salary_amount,
                        "description": f"Historical salary credit for {calendar.month_name[m]} {year} (Paid on {effective_payout_dt})."
                    }).execute()

        # Update account balance to include all disbursed past salaries
        if total_past_salaries_credited > 0:
            acc_res = db.table('accounts').select('balance').eq('account_id', account_id).execute()
            if acc_res.data:
                current_bal = float(acc_res.data[0]['balance'])
                db.table('accounts').update({
                    "balance": current_bal + total_past_salaries_credited
                }).eq('account_id', account_id).execute()

        return total_past_salaries_credited