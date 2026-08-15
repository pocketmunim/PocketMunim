import pytest
from unittest.mock import MagicMock, AsyncMock


@pytest.fixture
def mock_db_client():
    """Provides a mocked Supabase client for isolated testing."""
    client = MagicMock()
    # Mock chain: client.table().select().eq().execute().data
    client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    return client


@pytest.fixture
def mock_cache_manager():
    """Provides a mocked category cache manager."""
    cache = MagicMock()
    cache.search_item.return_value = None
    return cache


@pytest.fixture
def mock_category_pull_service():
    """Provides a mocked AI category pull service with full async support."""
    service = MagicMock()

    # All asynchronous methods on CategoryPullService must use AsyncMock
    service.manual_category_pull = AsyncMock(return_value={"added": 1, "error": None})
    service.bulk_add_items_to_taxonomy = AsyncMock()
    service.classify_item = AsyncMock(return_value={
        "category": "Food & Dining",
        "subcategory": "Food Delivery",
        "normalized_item": "Swiggy Order"
    })

    return service