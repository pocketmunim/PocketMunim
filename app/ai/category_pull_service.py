import json
from groq import Groq
from pydantic import BaseModel, Field
from typing import Optional


class AICategoryResponse(BaseModel):
    category: Optional[str] = None
    subcategory: Optional[str] = None
    item: Optional[str] = None


class CategoryPullService:
    def __init__(self, ai_client: Groq):
        self.ai = ai_client
        self.system_prompt = (
            "You are the PocketMunim Category Classification Engine. "
            "Classify the given item into a standard financial Category and Subcategory. "
            "Output STRICT JSON matching: {\"category\": \"...\", \"subcategory\": \"...\", \"item\": \"...\"}. "
            "If unknown, return null for category and subcategory."
        )

    def classify_item(self, item_name: str) -> dict:
        """
        Queries AI client with strict schema validation.
        Ensures AI never directly executes database mutations.
        """
        if not self.ai:
            return {"category": "General", "subcategory": "Uncategorized", "item": item_name}

        try:
            completion = self.ai.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": f"Classify item: {item_name}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            raw_content = completion.choices[0].message.content
            parsed = json.loads(raw_content)
            validated = AICategoryResponse(**parsed)

            return {
                "category": validated.category or "General",
                "subcategory": validated.subcategory or "Uncategorized",
                "item": validated.item or item_name
            }
        except Exception:
            return {"category": "General", "subcategory": "Uncategorized", "item": item_name}