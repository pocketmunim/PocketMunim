import calendar
from datetime import datetime
from decimal import Decimal
from app.utils.constants import TZ_IST
from app.services.business_calendar_service import BusinessCalendarService

class SalaryService:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id
        self.calendar_service = BusinessCalendarService(db_client)

    def set_monthly_salary_config(self, year: int, default_amount: float, expected_day: int = 31):
        payload = {
            "user_id": self.user_id,
            "year": year,
            "amount": default_amount,
            "updated_at": datetime.now(TZ_IST).isoformat()
        }
        res = self.db.table('salaries').upsert(payload).execute()
        return res.data
