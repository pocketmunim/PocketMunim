import json
from groq import Groq
from pydantic import BaseModel, Field
from typing import Optional, List

class CategoryPullService:
    def __init__(self, ai_client: Groq, db_client=None, admin_db_client=None):
        self.ai = ai_client
        self.db = db_client
        self.admin_db = admin_db_client or db_client # Falls back to standard client if admin not provided

    def seed_common_categories(self, user_id: str) -> None:
        """
        Proactively fetches common day-to-day categories, subcategories,
        and items from Groq when the system is idle.
        Bypasses user auth/RLS using the admin service role client.
        """
        if not self.ai or not self.admin_db:
            return

        seed_prompt = """You are the PocketMunim Enterprise Taxonomy Generator.
Your sole responsibility is to generate a comprehensive JSON list of common, everyday personal finance categories, their specific subcategories, and typical day-to-day items.

RULES:
1. Output ONLY valid JSON matching the exact schema below.
2. Do not wrap in markdown code fences.
3. Provide at least 15-20 common day-to-day items across various categories (e.g., Food & Dining, Transportation, Utilities, Shopping).

OUTPUT FORMAT:
{
  "categories": [
    {"category": "Food & Dining", "subcategory": "Groceries", "item": "Milk"},
    {"category": "Food & Dining", "subcategory": "Groceries", "item": "Rice"}
  ]
}"""

        try:
            completion = self.ai.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": seed_prompt},
                    {"role": "user", "content": "Generate common day-to-day category seed list."}
                ],
                temperature=0.3
            )
            raw_content = completion.choices[0].message.content.strip()
            if raw_content.startswith("```"):
                raw_content = raw_content.split("```")[1]
                if raw_content.startswith("json"):
                    raw_content = raw_content[4:]
                raw_content = raw_content.strip()

            parsed = json.loads(raw_content)
            items_list = parsed.get("categories", [])

            for entry in items_list:
                cat = entry.get("category")
                sub = entry.get("subcategory")
                itm = entry.get("item")
                if cat and itm:
                    try:
                        payload = {
                            "user_id": user_id,
                            "name": itm,
                            "level": "ITEM",
                            "category": cat
                        }
                        # Bypasses RLS / User Auth check via Admin Client
                        self.admin_db.table('categories').insert(payload).execute()
                    except Exception:
                        pass # Ignore duplicate inserts
        except Exception:
            pass

    def classify_item(self, item_name: str, user_id: str = None) -> dict:
        if not self.ai:
            return {"category": None, "subcategory": None, "item": item_name}

        system_prompt = f"""You are the PocketMunim Category Classification Engine.
Classify the given item into a standard Category and Subcategory.
Output STRICT JSON matching: {{"category": "string or null", "subcategory": "string or null", "item": "original item"}}
If unknown, return null for category and subcategory. Return ONLY valid JSON."""

        try:
            completion = self.ai.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"item: \"{item_name}\""}
                ],
                temperature=0.0
            )
            raw_content = completion.choices[0].message.content.strip()
            if raw_content.startswith("```"):
                raw_content = raw_content.split("```")[1]
                if raw_content.startswith("json"):
                    raw_content = raw_content[4:]
                raw_content = raw_content.strip()

            parsed = json.loads(raw_content)
            return {
                "category": parsed.get("category"),
                "subcategory": parsed.get("subcategory"),
                "item": parsed.get("item") or item_name
            }
        except Exception:
            return {"category": None, "subcategory": None, "item": item_name}