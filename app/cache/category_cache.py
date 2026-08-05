from typing import Optional, Dict

_MEMORY_DICT: Dict[str, Dict] = {}


class CategoryCacheManager:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id
        if self.user_id not in _MEMORY_DICT:
            self._load_from_db_to_ram()

    def _load_from_db_to_ram(self):
        try:
            res = self.db.table('category_cache').select('cache_data').eq('user_id', self.user_id).execute()
            if res.data and res.data[0].get('cache_data'):
                _MEMORY_DICT[self.user_id] = res.data[0]['cache_data']
            else:
                _MEMORY_DICT[self.user_id] = {}
        except Exception:
            _MEMORY_DICT[self.user_id] = {}

    def search_item(self, item_name: str) -> Optional[Dict[str, str]]:
        user_cache = _MEMORY_DICT.get(self.user_id, {})
        search_key = item_name.strip().lower()

        for category, subcategories in user_cache.items():
            if isinstance(subcategories, dict):
                for subcategory, items in subcategories.items():
                    if isinstance(items, list):
                        if any(i.strip().lower() == search_key for i in items if isinstance(i, str)):
                            return {"category": category, "subcategory": subcategory, "item": item_name}
        return None

    def rebuild_cache(self) -> None:
        """Reads hierarchical nodes via parent_id and builds JSON tree."""
        try:
            response = self.db.table('categories').select('*').eq('user_id', self.user_id).execute()
            rows = response.data or []

            tree: Dict[str, Dict[str, list]] = {}
            category_map = {row['id']: row for row in rows}

            for row in rows:
                if row['level'] == 'CATEGORY' and not row.get('parent_id'):
                    tree[row['name']] = {}
            for row in rows:
                if row['level'] == 'SUBCATEGORY' and row.get('parent_id') in category_map:
                    parent_name = category_map[row['parent_id']]['name']
                    if parent_name not in tree: tree[parent_name] = {}
                    tree[parent_name][row['name']] = []
            for row in rows:
                if row['level'] == 'ITEM' and row.get('parent_id') in category_map:
                    sub_row = category_map[row['parent_id']]
                    sub_name = sub_row['name']
                    parent_id = sub_row['parent_id']
                    if parent_id in category_map:
                        cat_name = category_map[parent_id]['name']
                        if cat_name in tree and sub_name in tree[cat_name]:
                            tree[cat_name][sub_name].append(row['name'])

            self.db.table('category_cache').upsert({"user_id": self.user_id, "cache_data": tree}).execute()
            _MEMORY_DICT[self.user_id] = tree

        except Exception as e:
            print(f"Cache rebuild failed: {str(e)}")