from app.services.business_calendar_service import BusinessCalendarService

class SalaryService:
    def __init__(self, db_session, user_id: str):
        self.db = db_session
        self.user_id = user_id
        self.calendar = BusinessCalendarService(db_session)

    def process_salary_credit(self, nlp_intent_date):
        # 1. Fetch user's expected salary configuration for the current year.
        # 2. Check JSONB overrides for the current month.
        # 3. Calculate exact credit date via BusinessCalendarService.
        # 4. Generate transaction record linked to primary account.
        # 5. Commit to ledger.
        pass
