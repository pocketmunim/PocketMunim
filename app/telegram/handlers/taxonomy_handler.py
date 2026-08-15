from app.interfaces.notification_gateway import TelegramNotificationAdapter
from app.cache.category_cache import CategoryCacheManager


class TaxonomyHandler:
    @staticmethod
    async def handle_category_pull(supabase_admin, chat_id, user_id, text, category_pull_service):
        gateway = TelegramNotificationAdapter()
        query = text.replace("/categorypull", "").strip()

        # If no argument is provided, pull a random assortment of common daily categories
        if not query:
            query = "random common daily expenses and income sources"

        # --- UI UX: NEON PULSING INDICATOR ---
        status_msg_id = await gateway.send_message(
            str(chat_id),
            f"🔄 *Taxonomy Engine Active*\n_Pulling new classifications for: {query}..._\n🟪🟪🟦🟦🟩🟩🟨🟨🟧🔴 `[AI Processing]`"
        )

        # Execute AI categorization
        res = await category_pull_service.manual_category_pull(query, user_id)

        # --- UI UX: CLEANUP ---
        if status_msg_id:
            await gateway.delete_message(str(chat_id), status_msg_id)

        if res.get("error"):
            await gateway.send_message(str(chat_id), f"❌ *Taxonomy Pull Failed*: `{res['error']}`")
        else:
            # Force the memory cache to wipe and reload from the newly updated DB
            cache_manager = CategoryCacheManager(supabase_admin, user_id)
            cache_manager.rebuild_cache()

            await gateway.send_message(str(chat_id),
                                       f"✅ *Taxonomy Updated*\nSuccessfully learned and cached {res['added']} new items for '{query}'.")

    @staticmethod
    async def show_categories(supabase_admin, chat_id, user_id):
        gateway = TelegramNotificationAdapter()
        cache_manager = CategoryCacheManager(supabase_admin, user_id)

        # Pulls directly from the True In-Memory Cache if loaded, otherwise fetches from DB
        tree = cache_manager._get_or_load_cache()

        if not tree:
            await gateway.send_message(str(chat_id), "📭 *Cache Empty*\nNo categories found in memory or database.")
            return

        lines = ["📋 *Active In-Memory Taxonomy Cache:*"]
        for cat, subs in tree.items():
            lines.append(f"\n📁 *{cat}*")
            if isinstance(subs, dict):
                for sub, items in subs.items():
                    item_str = ", ".join(items) if items else "No items"
                    lines.append(f"  └ 📂 {sub}: _{item_str}_")

        # Telegram has a 4096 character limit per message.
        msg = "\n".join(lines)
        if len(msg) > 4000:
            msg = msg[:4000] + "\n... [Truncated due to Telegram limits]"

        await gateway.send_message(str(chat_id), msg)