from typing import Optional, Dict


class CategoryCacheManager:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = str(user_id)

    def search_item(self, item_name: str) -> Optional[Dict[str, str]]:
        """Stateless category lookup querying category_cache / categories table."""
        try:
            res = self.db.table('category_cache').select('cache_data').eq('user_id', self.user_id).execute()
            user_cache = res.data[0]['cache_data'] if res.data and 'cache_data' in res.data[0] else {}
            if not user_cache:
                tree = self.rebuild_cache()
                user_cache = tree
            search_key = item_name.strip().lower()
            for category, subcategories in user_cache.items():
                if isinstance(subcategories, dict):
                    for subcategory, items in subcategories.items():
                        if isinstance(items, list) and any(
                                isinstance(i, str) and i.strip().lower() == search_key for i in items):
                            return {"category": category, "subcategory": subcategory, "item": item_name}
            return None
        except Exception as e:
            print(f"CategoryCacheManager search_item error: {e}")
            return None

    def rebuild_cache(self) -> Dict:
        """Pulls categories from DB, constructs taxonomy tree, and updates category_cache table."""
        try:
            res = self.db.table('categories').select('category_name, subcategories').eq('user_id',
                                                                                        self.user_id).execute()
            tree = {}
            for row in (res.data or []):
                cat = row['category_name']
                tree[cat] = {}
                for sub in row.get('subcategories', []):
                    tree[cat][sub.get('subcategory_name', 'General')] = sub.get('items', [])

            self.db.table('category_cache').upsert({
                "user_id": self.user_id,
                "cache_data": tree
            }).execute()
            return tree
        except Exception as e:
            print(f"Cache database rebuild failed: {str(e)}")
            return {}