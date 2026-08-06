import json
from typing import Optional
from app.ai.ai_provider import execute_resilient_ai


class CategoryPullService:
    def __init__(self, ai_client=None, admin_db_client=None):
        self.admin_db = admin_db_client

    async def manual_category_pull(self, query: str, user_id: str) -> dict:
        result = {"added": 0, "error": None}
        # ... (Keep all existing setup logic exactly the same until the AI call) ...
        # For brevity, insert your existing DB map logic here

        base_rules_and_format = """ RULES: 1. Generate realistic day-to-day purchases. 2. Group them intelligently. OUTPUT FORMAT: {"taxonomy": [{"category_name": "Groceries", "subcategories": [{"subcategory_name": "Dairy", "items": ["milk"]}]}]}"""
        system_prompt = f"You are the PocketMunim Taxonomy Engine. Generate 15-20 items STRICTLY RELATED TO: '{query}'.\n{base_rules_and_format}"
        try:
            # AWAIT THE AI CALL
            raw_content = await execute_resilient_ai(system_prompt, "Generate JSON now.", self.admin_db, is_json=True)
            parsed = json.loads(raw_content)
            # ... (Keep existing DB insert logic here) ...
            return result
        except Exception as e:
            result["error"] = f"Execution Exception: {str(e)}"
            return result

    async def add_single_item_to_taxonomy(self, cat_name: str, sub_name: str, item_name: str, user_id: str) -> None:
        # Keep your existing DB insert code here exactly as is.
        pass

    async def classify_item(self, item_name: str, intent: Optional[str] = None) -> dict:
        system_prompt = f"""You are the Category Engine. Classify this into a Category and Subcategory. OUTPUT FORMAT STRICT JSON: {{"category": "string", "subcategory": "string", "normalized_item": "clean string"}}"""
        try:
            # AWAIT THE AI CALL
            raw_content = await execute_resilient_ai(system_prompt, f"item: \"{item_name}\", intent: \"{intent}\"",
                                                     self.admin_db, is_json=True)
            parsed = json.loads(raw_content)
            return {
                "category": parsed.get("category") or "General",
                "subcategory": parsed.get("subcategory") or "Miscellaneous",
                "normalized_item": parsed.get("normalized_item") or item_name
            }
        except Exception:
            return {"category": "General", "subcategory": "Miscellaneous", "normalized_item": item_name}