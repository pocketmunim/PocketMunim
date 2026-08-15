from typing import Any

class CategoryCacheManager:
    def __init__(self, db_client: Any, user_id: str):
        self.db = db_client
        self.user_id = str(user_id)
        self._lifecycle_cache: dict[str, Any] | None = None

    def _get_or_load_cache(self) -> dict[str, Any]:
        if self._lifecycle_cache is not None:
            return self._lifecycle_cache
        try:
            res = self.db.table('categories').select('category_name, subcategories').eq('user_id', self.user_id).execute()
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
        user_cache = self._get_or_load_cache()
        search_key = item_name.strip().lower()
        for category, subcategories in user_cache.items():
            if isinstance(subcategories, dict):
                for subcategory, items in subcategories.items():
                    if isinstance(items, list) and any(isinstance(i, str) and i.strip().lower() == search_key for i in items):
                        return {"category": category, "subcategory": subcategory, "item": item_name}
        return None

    def rebuild_cache(self) -> None:
        self._lifecycle_cache = None
        self._get_or_load_cache()


class AsyncCategoryCache:
    """
    Asynchronous Enterprise Cache Adapter.
    Ensures Vercel serverless functions do not block the ASGI event loop while building the category tree.
    """
    def __init__(self):
        self._lifecycle_cache = None

    async def _get_or_load_cache(self, db_client, user_id: str) -> dict:
        if self._lifecycle_cache is not None:
            return self._lifecycle_cache
        try:
            # Executes via the new AsyncSupabaseClient injected by the DI container
            res = await db_client.client.table('categories').select('category_name, subcategories').eq('user_id', str(user_id)).execute()
            tree = {}
            for row in (res.data or []):
                cat = row['category_name']
                tree[cat] = {}
                for sub in row.get('subcategories', []):
                    tree[cat][sub.get('subcategory_name', 'General')] = sub.get('items', [])
            self._lifecycle_cache = tree
            return tree
        except Exception as e:
            import logging
            logging.getLogger("PocketMunim.Cache").error(f"AsyncCategoryCache load error: {e}")
            return {}

    async def search_item(self, item_name: str, db_client, user_id: str) -> dict | None:
        user_cache = await self._get_or_load_cache(db_client, user_id)
        search_key = item_name.strip().lower()
        for category, subcategories in user_cache.items():
            if isinstance(subcategories, dict):
                for subcategory, items in subcategories.items():
                    if isinstance(items, list) and any(isinstance(i, str) and i.strip().lower() == search_key for i in items):
                        return {"category": category, "subcategory": subcategory, "item": item_name}
        return None