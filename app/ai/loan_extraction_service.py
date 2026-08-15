import json
from typing import List, Tuple
from datetime import datetime
from app.utils.constants import TZ_IST
from app.ai.ai_provider import execute_resilient_ai
from app.ai.prompt_registry import PromptRegistry
from app.schemas.loan_schema import LoanNLPData


class LoanExtractionService:
    def __init__(self, admin_db_client):
        self.db = admin_db_client

    async def parse_loan_text(self, text: str) -> Tuple[List[LoanNLPData], str]:
        current_dt = datetime.now(TZ_IST)
        system_prompt = PromptRegistry.LOAN_EXTRACTION.replace(
            "{CURRENT_DATE}",
            f"{current_dt.strftime('%Y-%m-%d')} ({current_dt.strftime('%A')})"
        )

        raw_json, _ = await execute_resilient_ai(
            system_prompt=system_prompt,
            user_prompt=text,
            db_client=self.db,
            is_json=True
        )

        data = json.loads(raw_json)

        # Safe Text Subtraction to preserve massive OCR lists
        exact_sentences = data.get("exact_loan_sentences", [])
        leftover_text = text

        if exact_sentences:
            for sentence in exact_sentences:
                if sentence and isinstance(sentence, str):
                    leftover_text = leftover_text.replace(sentence, "")
        else:
            # Fallback for earlier cache or failed JSON schemas
            leftover_text = data.get("other_transactions_text", text)

        items = data.get("actions", [])
        if isinstance(data, list):
            items = data
        elif "action" in data and "actions" not in data:
            items = [data]

        parsed_actions = [LoanNLPData(**item) for item in items if isinstance(item, dict) and "action" in item]
        return parsed_actions, leftover_text.strip()