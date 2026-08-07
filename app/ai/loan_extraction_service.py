import json
from typing import List
from app.ai.ai_provider import execute_resilient_ai
from app.schemas.loan_schema import LoanNLPData


class LoanExtractionService:
    def __init__(self, admin_db_client):
        self.db = admin_db_client

    async def parse_loan_text(self, text: str) -> List[LoanNLPData]:
        system_prompt = """You are the PocketMunim Loan NLP Engine.
        The user may provide one or multiple loan creation or EMI payment instructions in the text.
        Analyze the text and extract all individual actions into an array.

        Return ONLY valid JSON matching this schema:
        {
          "actions": [
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
          ]
        }
        Current date is 2026. Resolve relative dates accurately. If dates are missing, leave them null.
        """
        raw_json, _ = await execute_resilient_ai(
            system_prompt=system_prompt,
            user_prompt=text,
            db_client=self.db,
            is_json=True
        )
        data = json.loads(raw_json)

        # Robust handling for list vs dict response formats
        if isinstance(data, list):
            return [LoanNLPData(**item) for item in data]
        elif isinstance(data, dict) and "actions" in data:
            return [LoanNLPData(**item) for item in data["actions"]]
        else:
            return [LoanNLPData(**data)]