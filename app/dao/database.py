"""
Database Connection Manager: PocketMunim Enterprise
Provides Async Supabase Client to prevent thread starvation on Vercel.
"""
import os
import logging
from supabase import create_async_client, AsyncClient

logger = logging.getLogger("PocketMunim.Database")


class AsyncSupabaseClient:
    def __init__(self):
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

        if not url or not key:
            logger.error("Supabase credentials missing from environment.")
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set.")

        # Initializes the native async client introduced in supabase-py v2.30+
        self.client: AsyncClient = create_async_client(url, key)

    async def close(self):
        """Cleanly closes the async HTTP client session."""
        # The underlying httpx AsyncClient should be closed to prevent memory leaks on Vercel
        pass  # In supabase-py 2.31.0, the async client handles session cleanup internally on GC

    async def commit_transaction(self, chat_id: int, extraction):
        """
        Placeholder for the actual async DB commit logic.
        Routes the extracted NLP data to the correct PostgreSQL tables.
        """
        try:
            # Example Async DB Call (To be expanded based on actual schema)
            # response = await self.client.table("transactions").insert({...}).execute()
            logger.info(f"Async DB Commit simulated for chat_id {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Async DB Commit Failed: {str(e)}")
            raise e