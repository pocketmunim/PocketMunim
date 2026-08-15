import datetime
from dateutil.relativedelta import relativedelta

class BusinessCalendarService:
    def __init__(self, db_client):
        self.db = db_client

    def is_holiday(self, target_date: datetime.date) -> bool:
        if not self.db:
            return False
        try:
            res = self.db.table('bank_holidays').select('*').eq('holiday_date', target_date.isoformat()).eq('is_active', True).execute()
            return bool(res.data)
        except Exception:
            return False

    def get_actual_salary_date(self, year: int, month: int, expected_day: int = 31) -> datetime.date:
        try:
            target_date = datetime.date(year, month, expected_day)
        except ValueError:
            target_date = datetime.date(year, month, 1) + relativedelta(months=1, days=-1)

        while True:
            is_weekend = target_date.weekday() >= 5 
            if is_weekend or self.is_holiday(target_date):
                target_date -= datetime.timedelta(days=1)
            else:
                break
        return target_date
