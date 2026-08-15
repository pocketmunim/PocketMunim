"""
DI Container: PocketMunim Enterprise
Injects fully asynchronous clients and services to guarantee high throughput.
"""
from typing import AsyncGenerator
from fastapi import Request

# Core Clients (Simulated Async Wrappers for Supabase/Groq)
from app.dao.database import AsyncSupabaseClient
from app.ai.ai_provider import AsyncAIProvider
from app.cache.category_cache import AsyncCategoryCache
from app.interfaces.notification_gateway import TelegramNotificationGateway

async def get_async_db() -> AsyncGenerator[AsyncSupabaseClient, None]:
    """Yields a 100% Async Database client connection."""
    client = AsyncSupabaseClient()
    try:
        yield client
    finally:
        await client.close()

async def get_ai_provider() -> AsyncAIProvider:
    """Yields resilient LLM extraction provider."""
    return AsyncAIProvider()

async def get_notification_gateway() -> TelegramNotificationGateway:
    """Yields the outbound messaging gateway."""
    return TelegramNotificationGateway()

async def get_cache_manager() -> AsyncCategoryCache:
    """Yields in-memory taxonomy cache to avoid DB round-trips."""
    return AsyncCategoryCache()