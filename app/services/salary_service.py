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
        Seeds 12 months of salaries for the specified calendar year.
        Uses calendar.monthrange to calculate exact month days dynamically.
        """
        if not year:
            year = date.today().year

        today = date.today()
        total_past_salaries_credited = 0.0

        acc_res = db.table('accounts').select('account_name, balance').eq('account_id', account_id).execute()
        if not acc_res.data:
            raise ValueError("Account vault not found or inactive.")

        account_name = acc_res.data[0]['account_name']
        current_bal = float(acc_res.data[0]['balance'])

        for m in range(1, 13):
            _, days_in_month = calendar.monthrange(year, m)
            day = min(salary_date, days_in_month)
            raw_payout_dt = date(year, m, day)

            effective_payout_dt = await HolidayService.get_effective_payout_date(raw_payout_dt)
            is_past = effective_payout_dt <= today

            sal_status = "PAID" if is_past else "SCHEDULED"
            paid_timestamp = f"{effective_payout_dt}T00:00:00Z" if is_past else None

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

            if sal_res.data and is_past:
                sal_id = sal_res.data[0]['salary_id']
                total_past_salaries_credited += salary_amount

                db.table('transactions').insert({
                    "user_id": user_id,
                    "account_id": account_id,
                    "account_name": account_name,
                    "salary_id": sal_id,
                    "type": "CREDIT",
                    "category": "Salary",
                    "amount": salary_amount,
                    "transaction_date": str(effective_payout_dt),
                    "status": "CREDITED",
                    "description": f"Salary Credit - {calendar.month_name[m]} {year}"
                }).execute()

                db.table('account_logs').insert({
                    "user_id": user_id,
                    "account_id": account_id,
                    "event_type": "SALARY_HISTORICAL_CREDIT",
                    "amount": salary_amount,
                    "description": f"Historical salary credit for {calendar.month_name[m]} {year} (Paid on {effective_payout_dt})."
                }).execute()

        # FIXED: Removed the block that updates the account balance.
        # The user's manually inputted current balance at onboarding is already accurate.

        return total_past_salaries_credited