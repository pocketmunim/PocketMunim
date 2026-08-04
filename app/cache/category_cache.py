from typing import Optional, Dict, Any


class CategoryCacheManager:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id

    def search_item(self, item_name: str) -> Optional[Dict[str, str]]:
        """
        Rule 25 Lookup Order: Memory cache (JSONB traversal)
        Traverses the user's cached JSON document locally in Python for O(1) lookup.
        """
        try:
            response = self.db.table('category_cache').select('cache_data').eq('user_id', self.user_id).execute()
            if not response.data or not response.data[0].get('cache_data'):
                return None

            cache_data = response.data[0]['cache_data']
            search_key = item_name.strip().lower()

            # Traverse JSONB structure: { "Category": { "Subcategory": ["item1", "item2"] } }
            for category, subcategories in cache_data.items():
                if isinstance(subcategories, dict):
                    for subcategory, items in subcategories.items():
                        if isinstance(items, list):
                            if any(i.strip().lower() == search_key for i in items if isinstance(i, str)):
                                return {
                                    "category": category,
                                    "subcategory": subcategory,
                                    "item": item_name
                                }
        except Exception:
            pass
        return None

    def rebuild_cache(self) -> None:
        """
        Queries the normalized `categories` table and constructs
        the nested JSONB representation, writing it back to `category_cache`.
        """
        try:
            # Fetch all categories for user
            response = self.db.table('categories').select('*').eq('user_id', self.user_id).execute()
            rows = response.data or []

            # Build relational tree
            tree: Dict[str, Dict[str, list]] = {}
            category_map = {row['category_id']: row for row in rows}

            # First pass: Top-level categories
            for row in rows:
                if row['level'] == 'CATEGORY' and not row['parent_id']:
                    tree[row['name']] = {}

            # Second pass: Subcategories
            for row in rows:
                if row['level'] == 'SUBCATEGORY' and row['parent_id'] in category_map:
                    parent_name = category_map[row['parent_id']]['name']
                    if parent_name not in tree:
                        tree[parent_name] = {}
                    tree[parent_name][row['name']] = []

            # Third pass: Items
            for row in rows:
                if row['level'] == 'ITEM' and row['parent_id'] in category_map:
                    sub_row = category_map[row['parent_id']]
                    sub_name = sub_row['name']
                    parent_id = sub_row['parent_id']
                    if parent_id in category_map:
                        cat_name = category_map[parent_id]['name']
                        if cat_name in tree and sub_name in tree[cat_name]:
                            tree[cat_name][sub_name].append(row['name'])

            # Upsert into category_cache
            payload = {
                "user_id": self.user_id,
                "cache_data": tree
            }
            self.db.table('category_cache').upsert(payload).execute()
        except Exception as e:
            raise RuntimeError(f"Failed to rebuild category cache: {str(e)}")