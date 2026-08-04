from app.services.amortization_engine import AmortizationEngine

class LoanService:
    def __init__(self, db_session, user_id: str):
        self.db = db_session
        self.user_id = user_id

    def process_loan_payment(self, nlp_loan_intent, transaction_amount):
        # 1. Fetch expected EMI from emi_schedules
        # 2. If transaction_amount > expected EMI, detect Part-Prepayment
        # 3. Trigger User Choice Request via UI/Telegram (Reduce EMI vs. Reduce Tenure)
        # 4. Await response -> Execute AmortizationEngine.recalculate_after_prepayment()
        # 5. Commit updated schedule
        pass
