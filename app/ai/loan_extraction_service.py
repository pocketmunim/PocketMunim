import json
from app.ai.ai_provider import execute_resilient_ai
from app.schemas.loan_schema import LoanNLPData

class LoanExtractionService:
    def __init__(self, admin_db_client):
        self.db = admin_db_client

    async def parse_loan_text(self, text: str) -> LoanNLPData:
        system_prompt = """You are the PocketMunim Loan NLP Engine.
        Analyze the user text and determine if they are:
        1. CREATING/TAKING a loan (action: "CREATE")
        2. PAYING an EMI (action: "PAY_EMI")

        Return ONLY valid JSON matching this schema:
        {
          "action": "CREATE|PAY_EMI",
          "lender_name": "string or null",
          "principal": number or null,
          "annual_interest_rate": number or null,
          "tenure_years": integer or null,
          "disbursement_date": "YYYY-MM-DD or null",
          "first_emi_date": "YYYY-MM-DD or null",
          "emi_amount": number or null,
          "payment_amount": number or null,
          "target_period": "string or null (e.g. last month, current month)"
        }
        Current date is 2026. Resolve relative dates accurately.
        """
        raw_json, _ = await execute_resilient_ai(
            system_prompt=system_prompt,
            user_prompt=text,
            db_client=self.db,
            is_json=True
        )
        data = json.loads(raw_json)
        return LoanNLPData(**data)