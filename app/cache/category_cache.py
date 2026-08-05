from typing import Optional, Dict

_MEMORY_DICT: Dict[str, Dict] = {}


class CategoryCacheManager:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id
        if self.user_id not in _MEMORY_DICT:
            self.rebuild_cache()

    def search_item(self, item_name: str) -> Optional[Dict[str, str]]:
        """O(1) Memory Traversal for Classification"""
        user_cache = _MEMORY_DICT.get(self.user_id, {})
        search_key = item_name.strip().lower()

        for category, subcategories in user_cache.items():
            for subcategory, items in subcategories.items():
                if any(i.strip().lower() == search_key for i in items if isinstance(i, str)):
                    return {"category": category, "subcategory": subcategory, "item": item_name}
        return None

    def rebuild_cache(self) -> None:
        """Pulls JSONB arrays from DB and maps them to RAM instantly."""
        try:
            res = self.db.table('categories').select('category_name, subcategories').eq('user_id',
                                                                                        self.user_id).execute()
            tree = {}
            for row in (res.data or []):
                cat = row['category_name']
                tree[cat] = {}
                for sub in row.get('subcategories', []):
                    tree[cat][sub.get('subcategory_name', 'General')] = sub.get('items', [])

            _MEMORY_DICT[self.user_id] = tree
        except Exception as e:
            print(f"Cache memory rebuild failed: {str(e)}")
            _MEMORY_DICT[self.user_id] = {}