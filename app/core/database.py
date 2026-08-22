from supabase import create_client, Client
from app.core.config import settings
from fastapi import HTTPException

def get_db() -> Client:
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Database vault configuration missing.")
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
