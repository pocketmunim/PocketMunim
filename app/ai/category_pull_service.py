import json
from groq import Groq
from typing import List


class CategoryPullService:
    def __init__(self, ai_client: Groq, admin_db_client=None):
        self.ai = ai_client
        self.admin_db = admin_db_client

    def manual_category_pull(self, query: str, user_id: str) -> int:
        if not self.ai or not self.admin_db:
            return 0

        # FOUNDER's STRICT TAXONOMY PROMPT
        base_rules_and_format = """
RULES:
1. Generate exactly 15-20 items.
2. Items must represent realistic, commonly occurring day-to-day purchases or expenses.
3. Each item must have a meaningful Category and Subcategory.
4. Keep categories broad and reusable.
5. Keep subcategories specific enough to be useful for transaction classification.
6. Do not create overly specific, obscure, rare, luxury, or unusual items.
7. Do not generate duplicate items.
8. Avoid generating multiple items that are effectively the same thing.
9. Do not use brand names unless the brand itself is commonly used as the generic description of the expense.
10. Categories and subcategories must be logically consistent.
11. Each item should be something a user could realistically enter into a personal finance app.
12. Items should be suitable for future AI transaction classification.
13. Use simple, commonly understood English names.
14. Do not include prices, currency, descriptions, explanations, IDs, or additional fields.
15. Return ONLY valid JSON.
16. Do not wrap the response in Markdown code fences.
17. Do not include any text before or after the JSON.

OUTPUT FORMAT:
{
  "categories": [
    {
      "category": "Medicines & Healthcare",
      "subcategory": "Pharmacy",
      "item": "Paracetamol"
    },
    {
      "category": "Household",
      "subcategory": "Cleaning",
      "item": "Dishwash Liquid"
    }
  ]
}

FINAL REQUIREMENT:
Return exactly one JSON object containing a "categories" array with 15-20 objects.
Every object MUST contain exactly these three fields:
- category
- subcategory
- item"""

        # If empty query, pull random day-to-day categories using Founder's exact prompt
        if not query:
            system_prompt = f"""You are the PocketMunim Day-to-Day Taxonomy Expansion Engine.

Your task is to generate 15-20 common, realistic, practical day-to-day financial items that people may commonly purchase or spend money on.

FOCUS AREAS:
- Household
- Medicines & Healthcare
- Groceries
- Food & Dining
- Transportation
- Utilities
- Personal Care
- Education
- Entertainment
- Shopping
- Other common everyday personal expenses
{base_rules_and_format}"""

        # If specific query provided, adapt the Founder's prompt to focus on the query
        else:
            system_prompt = f"""You are the PocketMunim Day-to-Day Taxonomy Expansion Engine.

Your task is to generate 15-20 common, realistic, practical day-to-day financial items STRICTLY RELATED TO THE DOMAIN: "{query}".
{base_rules_and_format}"""

        try:
            completion = self.ai.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Generate the JSON category list now. Output ONLY valid JSON."}
                ],
                response_format={"type": "json_object"},  # CRITICAL: Enforces strict JSON physical output
                temperature=0.4
            )

            raw_content = completion.choices[0].message.content.strip()
            parsed = json.loads(raw_content)
            items_list = parsed.get("categories", [])
            added_count = 0

            for entry in items_list:
                cat = entry.get("category")
                itm = entry.get("item")

                if cat and itm:
                    try:
                        # Insert flat item payload
                        payload = {"user_id": user_id, "name": itm, "level": "ITEM", "category": cat}
                        self.admin_db.table('categories').insert(payload).execute()
                        added_count += 1
                    except Exception as e:
                        print(f"Insert skipped for {itm} (possible duplicate): {str(e)}")

            return added_count

        except Exception as e:
            print(f"[CATEGORY PULL ERROR] AI or Parsing failed: {str(e)}")
            return 0

    def classify_item(self, item_name: str) -> dict:
        if not self.ai:
            return {"category": None, "subcategory": None, "item": item_name}

        system_prompt = """You are the PocketMunim Category Classification Engine.
Your sole responsibility is to classify a given financial transaction item into the most appropriate PocketMunim Category and Subcategory.

CLASSIFICATION RULES:
1. Select the most appropriate day-to-day Category and most specific Subcategory.
2. If the item is ambiguous or unrelated, return null for both.
3. Return ONLY valid JSON.

OUTPUT FORMAT MUST BE STRICT JSON:
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
                response_format={"type": "json_object"},
                temperature=0.0
            )
            raw_content = completion.choices[0].message.content.strip()
            parsed = json.loads(raw_content)
            return {
                "category": parsed.get("category"),
                "subcategory": parsed.get("subcategory"),
                "item": parsed.get("item") or item_name
            }
        except Exception as e:
            print(f"[CLASSIFICATION ERROR] {str(e)}")
            return {"category": None, "subcategory": None, "item": item_name}