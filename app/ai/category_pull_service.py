import json
from groq import Groq
from typing import List

class CategoryPullService:
    def __init__(self, ai_client: Groq, admin_db_client=None):
        self.ai = ai_client
        self.admin_db = admin_db_client

    def manual_category_pull(self, query: str, user_id: str) -> int:
        """
        Handles both specific queries AND empty queries for random day-to-day seeding.
        """
        if not self.ai or not self.admin_db:
            return 0

        # If empty query, pull random day-to-day categories (Founder's Tweak)
        if not query:
            prompt = """You are the PocketMunim Day-to-Day Taxonomy Expansion Engine.
Generate a JSON list of 15-20 random, common day-to-day life items, subcategories, and categories.
Focus strictly on practical everyday areas like Household, Medicines, Groceries, Transport, Utilities, and Personal Care.

OUTPUT FORMAT:
{
  "categories": [
    {"category": "Medicines", "subcategory": "Pharmacy", "item": "Paracetamol"},
    {"category": "Household", "subcategory": "Cleaning", "item": "Dishwash Liquid"}
  ]
}
Do NOT wrap in markdown fences. Output ONLY JSON."""

        # If specific query provided, fetch related categories
        else:
            prompt = f"""You are the PocketMunim Day-to-Day Taxonomy Expansion Engine.
The user requested categories related to: "{query}".
Generate a JSON list of 10-15 common items, subcategories, and categories directly related to this query in day-to-day life.

OUTPUT FORMAT:
{{
  "categories": [
    {{"category": "...", "subcategory": "...", "item": "..."}}
  ]
}}
Do NOT wrap in markdown fences. Output ONLY JSON."""

        try:
            completion = self.ai.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4 # Slightly higher temperature for better randomness when empty
            )
            raw_content = completion.choices[0].message.content.strip()
            if raw_content.startswith("```"):
                raw_content = raw_content.split("```")[1]
                if raw_content.startswith("json"):
                    raw_content = raw_content[4:]
                raw_content = raw_content.strip()

            parsed = json.loads(raw_content)
            items_list = parsed.get("categories", [])
            added_count = 0

            for entry in items_list:
                cat, sub, itm = entry.get("category"), entry.get("subcategory"), entry.get("item")
                if cat and itm:
                    try:
                        payload = {"user_id": user_id, "name": itm, "level": "ITEM", "category": cat}
                        self.admin_db.table('categories').insert(payload).execute()
                        added_count += 1
                    except Exception:
                        pass
            return added_count
        except Exception as e:
            print(f"Manual pull failed: {str(e)}")
            return 0

    def classify_item(self, item_name: str) -> dict:
        """Strict fallback classification using Founder's provided prompt logic."""
        if not self.ai:
            return {"category": None, "subcategory": None, "item": item_name}

        system_prompt = """You are the PocketMunim Category Classification Engine.
Your sole responsibility is to classify a given financial transaction item into the most appropriate PocketMunim Category and Subcategory.

CLASSIFICATION RULES:
1. Select the most appropriate day-to-day Category and most specific Subcategory.
2. If the item is ambiguous or unrelated, return null for both.
3. Return ONLY valid JSON.
4. Never wrap the JSON in Markdown code fences.
5. Never return additional text before or after the JSON.

OUTPUT FORMAT:
{
  "category": "string or null",
  "subcategory": "string or null",
  "item": "original item exactly as provided"
}"""
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