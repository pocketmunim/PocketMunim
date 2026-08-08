import json
from typing import List, Tuple
from app.ai.ai_provider import execute_resilient_ai
from app.schemas.loan_schema import LoanNLPData


class LoanExtractionService:
    def __init__(self, admin_db_client):
        self.db = admin_db_client

    async def parse_loan_text(self, text: str) -> Tuple[List[LoanNLPData], str]:
        system_prompt = """You are the PocketMunim Loan NLP Engine.
        Analyze the user text and separate loan-related actions from standard expenses/incomes.

        1. Extract all loan creations and EMI payments into the 'actions' array.
        2. Any text describing standard expenses, incomes, or groceries (e.g., "Salt - 1 kg", "paid rent") MUST be compiled exactly as written into 'other_transactions_text'.

        CRITICAL NUMBER PARSING RULES (INDIAN SYSTEM):
        - "l", "L", "lakh", "lakhs" MUST be multiplied by 100,000 (e.g., "5l" = 500000, "1.5L" = 150000).
        - "k", "K" MUST be multiplied by 1,000 (e.g., "50k" = 50000).
        - "cr", "crore" MUST be multiplied by 10,000,000.

        VALIDATION GUIDELINES:
        - For loan creations, extract explicit lender names (e.g., "HDFC", "SBI", "ICICI", "Bajaj Finserv", "Sushma"). If the lender is generic or missing (e.g., "friend", "someone", "car loan" without a bank), set `lender_name` to null.
        - For EMI payments, extract the specific lender name. If the counterparty is generic (e.g., "friend", "someone"), set `lender_name` to null so it can be flagged and eliminated with a warning.

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
              "target_period": "string or null"
            }
          ],
          "other_transactions_text": "string combining all non-loan items. Empty string if none."
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

        # Extract the leftover text for standard processing
        other_text = data.get("other_transactions_text", "")

        # Fallback handling for lists vs dicts
        items = data.get("actions", [])
        if isinstance(data, list):
            items = data
        elif "action" in data and "actions" not in data:
            items = [data]

        parsed_actions = [LoanNLPData(**item) for item in items if isinstance(item, dict) and "action" in item]

        return parsed_actions, other_text