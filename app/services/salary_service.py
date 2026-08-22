from supabase import Client
from datetime import date
import calendar


class SalaryService:
    @staticmethod
    def seed_annual_salaries(
            db: Client,
            user_id: str,
            account_id: str,
            salary_amount: float,
            salary_date: int,
            year: int = None
    ):
        if not year:
            year = date.today().year

        today = date.today()

        for m in range(1, 13):
            max_days = calendar.monthrange(year, m)[1]
            day = min(salary_date, max_days)
            payout_dt = date(year, m, day)

            is_past = payout_dt <= today
            sal_status = "PAID" if is_past else "SCHEDULED"
            tx_status = "CREDITED" if is_past else "SCHEDULED"
            paid_timestamp = f"{payout_dt}T00:00:00Z" if is_past else None

            # 1. Upsert salary month row
            sal_res = db.table('salaries').upsert({
                "user_id": user_id,
                "account_id": account_id,
                "year": year,
                "month": m,
                "base_amount": salary_amount,
                "actual_amount": salary_amount,
                "payout_date": str(payout_dt),
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
                    "transaction_date": str(payout_dt),
                    "status": tx_status,
                    "description": f"Automated Salary Allocation - {calendar.month_name[m]} {year}"
                }).execute()