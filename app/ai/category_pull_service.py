import json
from groq import Groq
from typing import List


class CategoryPullService:
    def __init__(self, ai_client: Groq, admin_db_client=None):
        self.ai = ai_client
        self.admin_db = admin_db_client

    def manual_category_pull(self, query: str, user_id: str) -> dict:
        result = {"added": 0, "error": None}
        if not self.ai or not self.admin_db:
            result["error"] = "System configuration missing."
            return result

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
    }
  ]
}

FINAL REQUIREMENT:
Return exactly one JSON object containing a "categories" array with 15-20 objects.
Every object MUST contain exactly these three fields: category, subcategory, item."""

        if not query:
            system_prompt = f"""You are the PocketMunim Day-to-Day Taxonomy Expansion Engine.
Your task is to generate 15-20 common, realistic, practical day-to-day financial items that people may commonly purchase or spend money on.
FOCUS AREAS: Household, Medicines & Healthcare, Groceries, Food & Dining, Transportation, Utilities, Personal Care, Education, Entertainment, Shopping.
{base_rules_and_format}"""
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
                response_format={"type": "json_object"},
                temperature=0.4
            )

            raw_content = completion.choices[0].message.content.strip()
            parsed = json.loads(raw_content)
            items_list = parsed.get("categories", [])

            if not items_list:
                result["error"] = "AI returned an empty list."
                return result

            # Fetch existing taxonomy to prevent duplicates and link hierarchical IDs correctly
            existing = self.admin_db.table('categories').select('*').eq('user_id', user_id).execute().data or []
            cats_map = {r['name'].lower(): r['id'] for r in existing if r.get('level') == 'CATEGORY'}
            subcats_map = {f"{r.get('parent_id')}_{r['name'].lower()}": r['id'] for r in existing if
                           r.get('level') == 'SUBCATEGORY'}
            items_map = {f"{r.get('parent_id')}_{r['name'].lower()}": r['id'] for r in existing if
                         r.get('level') == 'ITEM'}

            db_errors = []

            for entry in items_list:
                cat_name = entry.get("category")
                sub_name = entry.get("subcategory")
                itm_name = entry.get("item")

                if not (cat_name and sub_name and itm_name):
                    continue

                try:
                    # Get or Create CATEGORY
                    cat_key = cat_name.lower()
                    if cat_key not in cats_map:
                        res = self.admin_db.table('categories').insert(
                            {"user_id": user_id, "name": cat_name, "level": "CATEGORY"}).execute()
                        cats_map[cat_key] = res.data[0]['id']
                    cat_id = cats_map[cat_key]

                    # Get or Create SUBCATEGORY
                    sub_key = f"{cat_id}_{sub_name.lower()}"
                    if sub_key not in subcats_map:
                        res = self.admin_db.table('categories').insert(
                            {"user_id": user_id, "name": sub_name, "level": "SUBCATEGORY",
                             "parent_id": cat_id}).execute()
                        subcats_map[sub_key] = res.data[0]['id']
                    sub_id = subcats_map[sub_key]

                    # Get or Create ITEM
                    itm_key = f"{sub_id}_{itm_name.lower()}"
                    if itm_key not in items_map:
                        self.admin_db.table('categories').insert(
                            {"user_id": user_id, "name": itm_name, "level": "ITEM", "parent_id": sub_id}).execute()
                        items_map[itm_key] = True
                        result["added"] += 1

                except Exception as e:
                    db_errors.append(str(e))

            if result["added"] == 0 and db_errors:
                result["error"] = f"DB Insert Error (Check Supabase Columns): {db_errors[0]}"

            return result

        except Exception as e:
            result["error"] = f"Execution Exception: {str(e)}"
            return result

    def add_single_item_to_taxonomy(self, cat_name: str, sub_name: str, item_name: str, user_id: str) -> None:
        """Helper for Transaction AI Fallback to safely insert hierarchical records."""
        if not self.admin_db or not cat_name or not sub_name or not item_name: return
        try:
            res_c = self.admin_db.table('categories').select('id').eq('user_id', user_id).eq('level', 'CATEGORY').ilike(
                'name', cat_name).execute()
            cat_id = res_c.data[0]['id'] if res_c.data else self.admin_db.table('categories').insert(
                {"user_id": user_id, "name": cat_name, "level": "CATEGORY"}).execute().data[0]['id']

            res_s = self.admin_db.table('categories').select('id').eq('user_id', user_id).eq('level', 'SUBCATEGORY').eq(
                'parent_id', cat_id).ilike('name', sub_name).execute()
            sub_id = res_s.data[0]['id'] if res_s.data else self.admin_db.table('categories').insert(
                {"user_id": user_id, "name": sub_name, "level": "SUBCATEGORY", "parent_id": cat_id}).execute().data[0][
                'id']

            res_i = self.admin_db.table('categories').select('id').eq('user_id', user_id).eq('level', 'ITEM').eq(
                'parent_id', sub_id).ilike('name', item_name).execute()
            if not res_i.data:
                self.admin_db.table('categories').insert(
                    {"user_id": user_id, "name": item_name, "level": "ITEM", "parent_id": sub_id}).execute()
        except Exception as e:
            print(f"Fallback insert error: {e}")

    def classify_item(self, item_name: str) -> dict:
        if not self.ai: return {"category": None, "subcategory": None, "item": item_name}
        system_prompt = """You are the PocketMunim Category Classification Engine.
Classify the given item into a day-to-day Category and most specific Subcategory. Return ONLY JSON.
OUTPUT FORMAT MUST BE STRICT JSON: {"category": "...", "subcategory": "...", "item": "..."}"""
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
            return {"category": parsed.get("category"), "subcategory": parsed.get("subcategory"),
                    "item": parsed.get("item") or item_name}
        except Exception:
            return {"category": None, "subcategory": None, "item": item_name}