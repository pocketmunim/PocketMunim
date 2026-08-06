import pytest
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from app.dao.pending_batch_dao import PendingBatchDAO
from app.dao.report_token_dao import ReportTokenDAO
from app.cache.category_cache import CategoryCacheManager

@pytest.fixture
def mock_supabase():
    mock_client = MagicMock()
    return mock_client

def test_pending_batch_dao_crud(mock_supabase):
    dao = PendingBatchDAO(mock_supabase)
    batch_id = "test_batch_123"
    user_id = "user_456"
    account_id = "acc_789"
    items = [{"desc": "Milk", "amount": 50.0, "selected": True}]

    # Create Mock
    mock_supabase.table().insert().execute.return_value = MagicMock(data=[{"batch_id": batch_id}])
    assert dao.create_batch(batch_id, user_id, account_id, items) is True

    # Get Mock
    mock_supabase.table().select().eq().execute.return_value = MagicMock(data=[{
        "batch_id": batch_id, "user_id": user_id, "account_id": account_id, "items": items
    }])
    result = dao.get_batch(batch_id)
    assert result["batch_id"] == batch_id
    assert result["items"][0]["desc"] == "Milk"

    # Delete Mock
    assert dao.delete_batch(batch_id) is True

def test_report_token_dao_crud(mock_supabase):
    dao = ReportTokenDAO(mock_supabase)
    token = str(uuid.uuid4())
    user_id = "user_789"
    expires_at = datetime.utcnow() + timedelta(hours=1)

    mock_supabase.table().insert().execute.return_value = MagicMock(data=[{"token": token}])
    assert dao.create_token(token, user_id, expires_at) is True

    mock_supabase.table().select().eq().execute.return_value = MagicMock(data=[{
        "token": token, "user_id": user_id, "expires_at": expires_at.isoformat()
    }])
    result = dao.get_token(token)
    assert result["token"] == token
    assert result["user_id"] == user_id


def test_category_cache_stateless_lookup(mock_supabase):
    user_id = "user_101"
    cache_manager = CategoryCacheManager(mock_supabase, user_id)

    # UPDATED MOCK: Now mimics the master 'categories' table structure instead of the old cache table
    mock_supabase.table().select().eq().execute.return_value = MagicMock(data=[{
        "category_name": "Groceries",
        "subcategories": [
            {
                "subcategory_name": "Dairy",
                "items": ["milk", "paneer"]
            }
        ]
    }])

    match = cache_manager.search_item("milk")

    assert match is not None
    assert match["category"] == "Groceries"
    assert match["subcategory"] == "Dairy"