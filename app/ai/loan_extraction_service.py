import json
from app.ai.ai_provider import execute_resilient_ai
from app.schemas.loan_schema import LoanNLPData

class LoanExtractionService:
    def __init__(self, admin_db_client):
        self.db = admin_db_client

    async def parse_loan_text(self, text: str) -> list[LoanNLPData]:
        raw, _ = await execute_resilient_ai(
            system_prompt="Extract loan actions to JSON format: {'actions': [{'action': 'CREATE'|'PAY_EMI', ...}]}",
            user_prompt=text, db_client=self.db, is_json=True
        )
        data = json.loads(raw)
        items = data.get("actions", [data] if "action" in data else [])
        return [LoanNLPData(**i) for i in items]