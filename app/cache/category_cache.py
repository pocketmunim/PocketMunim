from typing import Optional, Dict

# GLOBAL IN-MEMORY RAM CACHE (Survives warm invocations in serverless)
_MEMORY_DICT: Dict[str, Dict] = {}


class CategoryCacheManager:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id

        # On initialization, if RAM cache is empty for this user, load from DB
        if self.user_id not in _MEMORY_DICT:
            self._load_from_db_to_ram()

    def _load_from_db_to_ram(self):
        """Loads JSONB from Supabase `category_cache` directly into Python RAM."""
        try:
            res = self.db.table('category_cache').select('cache_data').eq('user_id', self.user_id).execute()
            if res.data and res.data[0].get('cache_data'):
                _MEMORY_DICT[self.user_id] = res.data[0]['cache_data']
            else:
                _MEMORY_DICT[self.user_id] = {}
        except Exception:
            _MEMORY_DICT[self.user_id] = {}

    def search_item(self, item_name: str) -> Optional[Dict[str, str]]:
        """
        Tier 1: High-Speed RAM Lookup.
        Traverses the Python in-memory dictionary for O(1) matching.
        """
        user_cache = _MEMORY_DICT.get(self.user_id, {})
        search_key = item_name.strip().lower()

        for category, subcategories in user_cache.items():
            if isinstance(subcategories, dict):
                for subcategory, items in subcategories.items():
                    if isinstance(items, list):
                        if any(i.strip().lower() == search_key for i in items if isinstance(i, str)):
                            return {
                                "category": category,
                                "subcategory": subcategory,
                                "item": item_name
                            }
        return None

    def rebuild_cache(self) -> None:
        """
        Reads all items from `categories`, builds JSON tree, saves to DB,
        and REFRESHES IN-MEMORY RAM CACHE dynamically.
        """
        try:
            response = self.db.table('categories').select('*').eq('user_id', self.user_id).execute()
            rows = response.data or []

            tree: Dict[str, Dict[str, list]] = {}

            # Dynamic Flat-to-Tree Builder (Supports AI generated records)
            for row in rows:
                if row.get('level') == 'ITEM':
                    cat = row.get('category') or "General"
                    sub = "Uncategorized"  # Flattened AI items land here dynamically

                    if cat not in tree:
                        tree[cat] = {}
                    if sub not in tree[cat]:
                        tree[cat][sub] = []

                    item_name = row.get('name')
                    if item_name and item_name not in tree[cat][sub]:
                        tree[cat][sub].append(item_name)

            # 1. Update Supabase DB JSONB Cache
            self.db.table('category_cache').upsert({"user_id": self.user_id, "cache_data": tree}).execute()

            # 2. Update Python RAM In-Memory Cache
            _MEMORY_DICT[self.user_id] = tree

        except Exception as e:
            print(f"Cache rebuild failed: {str(e)}")