from typing import Any


class CategoryCacheManager:
    def __init__(self, db_client: Any, user_id: str):
        self.db = db_client
        self.user_id = str(user_id)
        # Holds the compiled tree in RAM strictly for the life of the webhook request
        self._lifecycle_cache: dict[str, Any] | None = None

    def _get_or_load_cache(self) -> dict[str, Any]:
        """Fetches from the master 'categories' table ONCE per request and compiles the tree."""
        if self._lifecycle_cache is not None:
            return self._lifecycle_cache

        try:
            # 1 single HTTP call to Supabase for the master data
            res = self.db.table('categories').select('category_name, subcategories').eq('user_id',
                                                                                        self.user_id).execute()

            # Assemble the tree in RAM instantly
            tree = {}
            for row in (res.data or []):
                cat = row['category_name']
                tree[cat] = {}
                for sub in row.get('subcategories', []):
                    tree[cat][sub.get('subcategory_name', 'General')] = sub.get('items', [])

            self._lifecycle_cache = tree
            return tree
        except Exception as e:
            print(f"CategoryCacheManager load error: {e}")
            return {}

    def search_item(self, item_name: str) -> dict[str, str] | None:
        """Instant memory traversal using the assembled lifecycle tree."""
        user_cache = self._get_or_load_cache()
        search_key = item_name.strip().lower()

        for category, subcategories in user_cache.items():
            if isinstance(subcategories, dict):
                for subcategory, items in subcategories.items():
                    if isinstance(items, list) and any(
                            isinstance(i, str) and i.strip().lower() == search_key for i in items):
                        return {"category": category, "subcategory": subcategory, "item": item_name}
        return None

    def rebuild_cache(self) -> None:
        """
        Since we no longer use a DB cache table, this just forces the RAM
        to refresh if we pull new categories during the same request lifecycle.
        """
        self._lifecycle_cache = None
        self._get_or_load_cache()