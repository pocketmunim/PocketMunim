"""
DI Container: PocketMunim Enterprise
Injects fully asynchronous clients and services to guarantee high throughput.
"""
from typing import AsyncGenerator
from fastapi import Request

# Core Clients
from app.dao.database import AsyncSupabaseClient
from app.ai.ai_provider import AsyncAIProvider
from app.interfaces.notification_gateway import TelegramNotificationAdapter
from app.cache.category_cache import AsyncCategoryCache

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

async def get_notification_gateway() -> TelegramNotificationAdapter:
    """Yields the outbound messaging gateway."""
    return TelegramNotificationAdapter()

async def get_cache_manager() -> AsyncCategoryCache:
    """Yields in-memory taxonomy cache to avoid DB round-trips."""
    return AsyncCategoryCache()