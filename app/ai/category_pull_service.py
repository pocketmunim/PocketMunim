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
1. Generate realistic day-to-day purchases.
2. Group them intelligently into broad Categories.
3. Inside each Category, group items into Subcategories.
4. Output MUST STRICTLY MATCH the nested JSON schema below.
5. Return ONLY valid JSON.

OUTPUT FORMAT:
{
  "taxonomy": [
    {
      "category_name": "Groceries",
      "subcategories": [
        {
          "subcategory_name": "Dairy and Eggs",
          "items": ["milk", "paneer", "butter", "eggs"]
        },
        {
          "subcategory_name": "Fruits",
          "items": ["apple", "banana"]
        }
      ]
    },
    {
      "category_name": "Household",
      "subcategories": [
        {
          "subcategory_name": "Cleaning",
          "items": ["dishwash liquid", "detergent"]
        }
      ]
    }
  ]
}
"""

        if not query:
            system_prompt = f"You are the PocketMunim Taxonomy Engine. Generate common day-to-day items.\n{base_rules_and_format}"
        else:
            system_prompt = f"You are the PocketMunim Taxonomy Engine. Generate items STRICTLY RELATED TO: '{query}'.\n{base_rules_and_format}"

        try:
            completion = self.ai.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Generate the taxonomy JSON now. Output ONLY valid JSON."}
                ],
                response_format={"type": "json_object"},
                temperature=0.4
            )

            raw_content = completion.choices[0].message.content.strip()
            parsed = json.loads(raw_content)
            taxonomy_list = parsed.get("taxonomy", [])

            if not taxonomy_list:
                result["error"] = "AI returned an empty taxonomy."
                return result

            # Fetch existing DB to merge smartly
            existing_res = self.admin_db.table('categories').select('*').eq('user_id', user_id).execute()
            db_map = {row['category_name']: row['subcategories'] for row in (existing_res.data or [])}

            db_errors = []

            for cat_obj in taxonomy_list:
                cat_name = cat_obj.get("category_name")
                new_subs = cat_obj.get("subcategories", [])

                if not cat_name or not new_subs:
                    continue

                try:
                    if cat_name in db_map:
                        # SMART MERGE: Combine existing subcategories and items with AI output
                        existing_subs = db_map[cat_name]
                        sub_dict = {s['subcategory_name']: set(s.get('items', [])) for s in existing_subs}

                        for ns in new_subs:
                            s_name = ns.get('subcategory_name')
                            i_list = ns.get('items', [])
                            if s_name in sub_dict:
                                sub_dict[s_name].update(i_list)
                            else:
                                sub_dict[s_name] = set(i_list)

                        merged_subs = [{"subcategory_name": k, "items": list(v)} for k, v in sub_dict.items()]

                        self.admin_db.table('categories').update({"subcategories": merged_subs}).eq('user_id',
                                                                                                    user_id).eq(
                            'category_name', cat_name).execute()
                        db_map[cat_name] = merged_subs
                    else:
                        # INSERT NEW CATEGORY ROW
                        self.admin_db.table('categories').insert({
                            "user_id": user_id,
                            "category_name": cat_name,
                            "subcategories": new_subs
                        }).execute()
                        db_map[cat_name] = new_subs

                    result["added"] += sum(len(sub.get("items", [])) for sub in new_subs)

                except Exception as e:
                    db_errors.append(str(e))

            if result["added"] == 0 and db_errors:
                result["error"] = f"DB Upsert Error: {db_errors[0]}"

            return result

        except Exception as e:
            result["error"] = f"Execution Exception: {str(e)}"
            return result

    def add_single_item_to_taxonomy(self, cat_name: str, sub_name: str, item_name: str, user_id: str) -> None:
        """Helper for Transaction AI Fallback to safely merge a single item into the JSONB array."""
        if not self.admin_db or not cat_name or not sub_name or not item_name: return
        try:
            res = self.admin_db.table('categories').select('subcategories').eq('user_id', user_id).eq('category_name',
                                                                                                      cat_name).execute()

            if res.data:
                # Merge into existing category
                existing_subs = res.data[0]['subcategories']
                found_sub = False
                for sub in existing_subs:
                    if sub.get('subcategory_name') == sub_name:
                        if item_name not in sub.get('items', []):
                            sub['items'].append(item_name)
                        found_sub = True
                        break
                if not found_sub:
                    existing_subs.append({"subcategory_name": sub_name, "items": [item_name]})

                self.admin_db.table('categories').update({"subcategories": existing_subs}).eq('user_id', user_id).eq(
                    'category_name', cat_name).execute()
            else:
                # Insert completely new category
                new_subs = [{"subcategory_name": sub_name, "items": [item_name]}]
                self.admin_db.table('categories').insert(
                    {"user_id": user_id, "category_name": cat_name, "subcategories": new_subs}).execute()
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