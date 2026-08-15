import json
from typing import Optional
from app.ai.ai_provider import execute_resilient_ai
from app.ai.prompt_registry import PromptRegistry


class CategoryPullService:
    def __init__(self, ai_client=None, admin_db_client=None):
        self.admin_db = admin_db_client

    async def manual_category_pull(self, query: str, user_id: str) -> dict:
        result = {"added": 0, "error": None}
        if not self.admin_db:
            result["error"] = "System database missing."
            return result

        existing_res = self.admin_db.table('categories').select('*').eq('user_id', str(user_id)).execute()
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
            exclusion_text = f"\n\nEXCLUSION LIST (DO NOT GENERATE THESE):\n[{existing_items_str}]\n"

        system_prompt = PromptRegistry.CATEGORY_GENERATION.format(query=query, exclusion_text=exclusion_text)

        try:
            raw_content, _ = await execute_resilient_ai(system_prompt, "Generate JSON.", self.admin_db, is_json=True)
            parsed = json.loads(raw_content)
            taxonomy_list = parsed.get("taxonomy", [])

            if not taxonomy_list:
                result["error"] = "AI returned empty taxonomy."
                return result

            for cat_obj in taxonomy_list:
                raw_cat_name = cat_obj.get("category_name")
                new_subs = cat_obj.get("subcategories", [])

                if not raw_cat_name or not new_subs:
                    continue

                raw_cat_name = raw_cat_name.strip()
                cat_key = raw_cat_name.lower()

                if cat_key in db_map:
                    existing_row = db_map[cat_key]
                    actual_cat_name = existing_row['category_name']
                    existing_subs = existing_row.get('subcategories', [])

                    sub_dict = {}
                    for s in existing_subs:
                        s_name = s.get('subcategory_name')
                        if s_name:
                            sub_dict[s_name.strip().lower()] = {
                                "original_name": s_name,
                                "items": {i.strip().lower(): i.strip() for i in s.get('items', [])}
                            }

                    for ns in new_subs:
                        raw_s_name = ns.get('subcategory_name')
                        if not raw_s_name or raw_s_name.lower() == raw_cat_name.lower():
                            raw_s_name = f"{raw_cat_name} Specifics"
                        raw_s_name = raw_s_name.strip()
                        s_key = raw_s_name.lower()

                        if s_key not in sub_dict:
                            sub_dict[s_key] = {"original_name": raw_s_name, "items": {}}
                        for i in ns.get('items', []):
                            sub_dict[s_key]["items"][i.strip().lower()] = i.strip()

                    merged_subs = [{"subcategory_name": v["original_name"], "items": list(v["items"].values())} for v in
                                   sub_dict.values()]
                    self.admin_db.table('categories').update({"subcategories": merged_subs}).eq('user_id',
                                                                                                str(user_id)).eq(
                        'category_name', actual_cat_name).execute()
                else:
                    clean_subs = []
                    for ns in new_subs:
                        raw_s_name = ns.get('subcategory_name')
                        if not raw_s_name or raw_s_name.lower() == raw_cat_name.lower():
                            raw_s_name = f"{raw_cat_name} Specifics"
                        clean_subs.append({
                            "subcategory_name": raw_s_name.strip(),
                            "items": list({i.strip().lower(): i.strip() for i in ns.get('items', [])}.values())
                        })
                    if clean_subs:
                        self.admin_db.table('categories').insert(
                            {"user_id": str(user_id), "category_name": raw_cat_name,
                             "subcategories": clean_subs}).execute()

                result["added"] += sum(len(sub.get("items", [])) for sub in new_subs)

            return result
        except Exception as e:
            result["error"] = str(e)
            return result

    async def bulk_add_items_to_taxonomy(self, items_list: list[dict], user_id: str) -> Optional[str]:
        if not self.admin_db or not items_list:
            return "Missing database connection or empty payload."

        try:
            res = self.admin_db.table('categories').select('*').eq('user_id', str(user_id)).execute()
            db_map = {row['category_name'].strip().lower(): row for row in (res.data or [])}
            taxonomy_map = {}

            for data in items_list:
                cat_name = data.get("category")
                sub_name = data.get("subcategory")
                item_name = data.get("item")

                if not item_name:
                    continue

                if not cat_name:
                    cat_name = "Uncategorized"

                if not sub_name or sub_name.lower() == cat_name.lower():
                    sub_name = f"{cat_name} Specifics"

                cat_name = cat_name.strip()
                sub_name = sub_name.strip()
                item_name = item_name.strip()

                cat_key, sub_key = cat_name.lower(), sub_name.lower()

                if cat_key not in taxonomy_map:
                    taxonomy_map[cat_key] = {"name": cat_name, "subs": {}}
                if sub_key not in taxonomy_map[cat_key]["subs"]:
                    taxonomy_map[cat_key]["subs"][sub_key] = {"name": sub_name, "items": set()}
                taxonomy_map[cat_key]["subs"][sub_key]["items"].add(item_name)

            for cat_key, new_cat_data in taxonomy_map.items():
                if cat_key in db_map:
                    existing_row = db_map[cat_key]
                    actual_cat_name = existing_row['category_name']
                    existing_subs = existing_row.get('subcategories', [])

                    sub_dict = {}
                    for s in existing_subs:
                        s_name = s.get('subcategory_name')
                        if s_name:
                            sub_dict[s_name.strip().lower()] = {
                                "original_name": s_name,
                                "items": {i.strip().lower(): i.strip() for i in s.get('items', [])}
                            }

                    for sub_key, sub_data in new_cat_data["subs"].items():
                        if sub_key not in sub_dict:
                            sub_dict[sub_key] = {"original_name": sub_data["name"], "items": {}}
                        for item in sub_data["items"]:
                            sub_dict[sub_key]["items"][item.lower()] = item

                    merged_subs = [{"subcategory_name": v["original_name"], "items": list(v["items"].values())} for v in
                                   sub_dict.values()]
                    self.admin_db.table('categories').update({"subcategories": merged_subs}).eq('user_id',
                                                                                                str(user_id)).eq(
                        'category_name', actual_cat_name).execute()
                else:
                    clean_subs = [{"subcategory_name": sub_data["name"], "items": list(sub_data["items"])} for sub_data
                                  in new_cat_data["subs"].values()]
                    self.admin_db.table('categories').insert(
                        {"user_id": str(user_id), "category_name": new_cat_data["name"],
                         "subcategories": clean_subs}).execute()

            return None  # Success
        except Exception as e:
            err_msg = str(e)
            print(f"Failed bulk category insert: {err_msg}")
            return err_msg

    async def classify_item(self, item_name: str, intent: Optional[str] = None) -> dict:
        system_prompt = PromptRegistry.CATEGORY_CLASSIFICATION

        try:
            raw_content, _ = await execute_resilient_ai(system_prompt, f"item: \"{item_name}\", intent: \"{intent}\"",
                                                        self.admin_db, is_json=True)
            parsed = json.loads(raw_content)
            return {
                "category": parsed.get("category"),
                "subcategory": parsed.get("subcategory"),
                "normalized_item": parsed.get("normalized_item") or item_name
            }
        except Exception as e:
            print(f"Classification AI Call Failed: {e}")
            return {"category": None, "subcategory": None, "normalized_item": item_name}