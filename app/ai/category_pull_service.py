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

        existing_res = self.admin_db.table('categories').select('*').eq('user_id', user_id).execute()
        existing_data = existing_res.data or []

        db_map = {}
        existing_items_set = set()

        for row in existing_data:
            cat_key = row['category_name'].strip().lower()
            db_map[cat_key] = row
            for sub in row.get('subcategories', []):
                for item in sub.get('items', []):
                    existing_items_set.add(item.strip().lower())

        exclusion_text = ""
        if existing_items_set:
            existing_items_str = ", ".join(sorted(existing_items_set))
            exclusion_text = f"\n\nCRITICAL EXCLUSION LIST:\nThe user ALREADY HAS the following items. You MUST NOT generate any of these items. Generate completely NEW, unlisted items:\n[{existing_items_str}]\n"

        base_rules_and_format = f"""
RULES:
1. Generate realistic day-to-day purchases.
2. Group them intelligently into broad Categories.
3. Inside each Category, group items into Subcategories.
4. Output MUST STRICTLY MATCH the nested JSON schema below.
5. Return ONLY valid JSON.
6. Do not generate duplicate items.{exclusion_text}

OUTPUT FORMAT:
{{
  "taxonomy": [
    {{
      "category_name": "Groceries",
      "subcategories": [
        {{
          "subcategory_name": "Dairy and Eggs",
          "items": ["paneer", "butter"]
        }}
      ]
    }}
  ]
}}
"""

        if not query:
            system_prompt = f"You are the PocketMunim Taxonomy Engine. Generate 15-20 common, realistic day-to-day items.\n{base_rules_and_format}"
        else:
            system_prompt = f"You are the PocketMunim Taxonomy Engine. Generate 15-20 items STRICTLY RELATED TO: '{query}'.\n{base_rules_and_format}"

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

            db_errors = []

            for cat_obj in taxonomy_list:
                raw_cat_name = cat_obj.get("category_name", "").strip()
                new_subs = cat_obj.get("subcategories", [])

                if not raw_cat_name or not new_subs:
                    continue

                cat_key = raw_cat_name.lower()

                try:
                    if cat_key in db_map:
                        existing_row = db_map[cat_key]
                        actual_cat_name = existing_row['category_name']
                        existing_subs = existing_row.get('subcategories', [])

                        sub_dict = {}
                        for s in existing_subs:
                            s_key = s.get('subcategory_name', 'General').strip().lower()
                            sub_dict[s_key] = {
                                "original_name": s.get('subcategory_name', 'General'),
                                "items": {i.strip().lower(): i.strip() for i in s.get('items', [])}
                            }

                        for ns in new_subs:
                            raw_s_name = ns.get('subcategory_name', 'General').strip()
                            s_key = raw_s_name.lower()
                            i_list = ns.get('items', [])

                            if s_key not in sub_dict:
                                sub_dict[s_key] = {"original_name": raw_s_name, "items": {}}

                            for i in i_list:
                                i_key = i.strip().lower()
                                if i_key not in sub_dict[s_key]["items"]:
                                    sub_dict[s_key]["items"][i_key] = i.strip()

                        merged_subs = [{"subcategory_name": v["original_name"], "items": list(v["items"].values())} for
                                       v in sub_dict.values()]

                        self.admin_db.table('categories').update({"subcategories": merged_subs}).eq('user_id',
                                                                                                    user_id).eq(
                            'category_name', actual_cat_name).execute()
                        db_map[cat_key]['subcategories'] = merged_subs
                    else:
                        clean_subs = []
                        for ns in new_subs:
                            raw_s_name = ns.get('subcategory_name', 'General').strip()
                            i_list = ns.get('items', [])

                            unique_items = list({i.strip().lower(): i.strip() for i in i_list}.values())
                            clean_subs.append({"subcategory_name": raw_s_name, "items": unique_items})

                        self.admin_db.table('categories').insert({
                            "user_id": user_id,
                            "category_name": raw_cat_name,
                            "subcategories": clean_subs
                        }).execute()

                        db_map[cat_key] = {"category_name": raw_cat_name, "subcategories": clean_subs}

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
        if not self.admin_db or not cat_name or not sub_name or not item_name: return
        try:
            res = self.admin_db.table('categories').select('*').eq('user_id', user_id).ilike('category_name',
                                                                                             cat_name.strip()).execute()

            if res.data:
                existing_row = res.data[0]
                actual_cat_name = existing_row['category_name']
                existing_subs = existing_row.get('subcategories', [])

                found_sub = False
                for sub in existing_subs:
                    if sub.get('subcategory_name', '').strip().lower() == sub_name.strip().lower():
                        existing_items = [i.strip().lower() for i in sub.get('items', [])]
                        if item_name.strip().lower() not in existing_items:
                            sub['items'].append(item_name.strip())
                        found_sub = True
                        break

                if not found_sub:
                    existing_subs.append({"subcategory_name": sub_name.strip(), "items": [item_name.strip()]})

                self.admin_db.table('categories').update({"subcategories": existing_subs}).eq('user_id', user_id).eq(
                    'category_name', actual_cat_name).execute()
            else:
                new_subs = [{"subcategory_name": sub_name.strip(), "items": [item_name.strip()]}]
                self.admin_db.table('categories').insert(
                    {"user_id": user_id, "category_name": cat_name.strip(), "subcategories": new_subs}).execute()
        except Exception as e:
            print(f"Fallback insert error: {e}")

    def classify_item(self, item_name: str) -> dict:
        if not self.ai: return {"category": None, "subcategory": None, "normalized_item": item_name}

        system_prompt = """You are the PocketMunim Category Classification Engine.
Classify the given input into a day-to-day Category and most specific Subcategory.

CRITICAL NORMALIZATION RULE:
If the input is a full sentence or contains specific amounts, personal names, or hardcoded details, you MUST generalize it. Strip out specific details and return a clean, generic, reusable item name.
- Example 1: "received 50k from sushma" or "got 10k from raj" -> category: "Transfers", subcategory: "Incoming Transfer", normalized_item: "Personal Transfer Received". NEVER hallucinate the word "Cash".
- Example 2: "bought pizza for 500" -> category: "Food & Dining", subcategory: "Dining Out", normalized_item: "Pizza"

OUTPUT FORMAT MUST BE STRICT JSON:
{
  "category": "string",
  "subcategory": "string",
  "normalized_item": "clean generic string"
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
                "normalized_item": parsed.get("normalized_item") or item_name
            }
        except Exception:
            return {"category": None, "subcategory": None, "normalized_item": item_name}