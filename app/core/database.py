from supabase import create_client, Client
from app.core.config import settings
from fastapi import HTTPException

_supabase_client: Client = None


def get_db() -> Client:
    """Returns the persistent Supabase database client singleton."""
    global _supabase_client
    if _supabase_client is None:
        if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
            raise HTTPException(
                status_code=500,
                detail="Database vault configuration is missing from environment variables.",
            )
        _supabase_client = create_client(
            settings.SUPABASE_URL,
            settings.SUPABASE_KEY,
        )
    return _supabase_client