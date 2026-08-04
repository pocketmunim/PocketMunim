import datetime
from dateutil.relativedelta import relativedelta

class BusinessCalendarService:
    def __init__(self, db_session):
        self.db = db_session

    def is_holiday(self, target_date: datetime.date) -> bool:
        # Executes SELECT 1 FROM bank_holidays WHERE holiday_date = target_date
        pass

    def get_actual_salary_date(self, year: int, month: int, expected_day: int) -> datetime.date:
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
