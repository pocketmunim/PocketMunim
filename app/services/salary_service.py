from supabase import Client
from datetime import date
import calendar
from decimal import Decimal
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
        Uses exact Decimal math and Atomic RPC for ledger synchronization.
        """
        if not year:
            year = date.today().year

        today = date.today()
        total_past_salaries_credited = Decimal('0.00')
        exact_salary_amt = Decimal(str(salary_amount))

        acc_res = db.table('accounts').select('account_name').eq('account_id', account_id).execute()
        if not acc_res.data:
            raise ValueError("Account vault not found or inactive.")

        account_name = acc_res.data[0]['account_name']

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
                "base_amount": float(exact_salary_amt),
                "actual_amount": float(exact_salary_amt),
                "payout_date": str(effective_payout_dt),
                "status": sal_status,
                "paid_at": paid_timestamp,
                "is_custom_override": False
            }, on_conflict="user_id,year,month").execute()

            if sal_res.data and is_past:
                sal_id = sal_res.data[0]['salary_id']
                total_past_salaries_credited += exact_salary_amt

                db.table('transactions').insert({
                    "user_id": user_id,
                    "account_id": account_id,
                    "account_name": account_name,
                    "salary_id": sal_id,
                    "type": "CREDIT",
                    "category": "Salary",
                    "amount": float(exact_salary_amt),
                    "transaction_date": str(effective_payout_dt),
                    "status": "CREDITED",
                    "description": f"Salary Credit - {calendar.month_name[m]} {year}"
                }).execute()

                db.table('account_logs').insert({
                    "user_id": user_id,
                    "account_id": account_id,
                    "event_type": "SALARY_HISTORICAL_CREDIT",
                    "amount": float(exact_salary_amt),
                    "description": f"Historical salary credit for {calendar.month_name[m]} {year} (Paid on {effective_payout_dt})."
                }).execute()

        # DELEGATE TO ATOMIC RPC TO PREVENT TOCTOU RACE CONDITIONS
        if total_past_salaries_credited > Decimal('0.00'):
            db.rpc('atomic_balance_update', {
                'p_account_id': account_id,
                'p_amount': float(total_past_salaries_credited)
            }).execute()

        return float(total_past_salaries_credited)