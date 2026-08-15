import pytest
import datetime
from decimal import Decimal
from unittest.mock import MagicMock
from app.services.bulk_transaction_service import BulkTransactionService


class MockTransactionItem:
    def __init__(self, amount, intent, raw_desc, needs_clarification=False, is_future=False):
        self.amount = Decimal(str(amount))
        self.intent = intent
        self.raw_description = raw_desc
        self.item = raw_desc
        self.normalized_item = raw_desc.title()
        self.needs_clarification = needs_clarification
        self.future = lambda: None
        self.future.is_future = is_future
        self.category = None
        self.subcategory = None


@pytest.mark.asyncio
async def test_process_bulk_payload_ignores_invalid(mock_db_client, mock_cache_manager, mock_category_pull_service):
    """Test that zero amounts and future plans are ignored."""
    service = BulkTransactionService(mock_db_client, "test_user", mock_cache_manager, mock_category_pull_service)

    transactions = [
        MockTransactionItem(0.00, "expense", "Zero Dollar Item"),
        MockTransactionItem(100.00, "expense", "Future Item", is_future=True),
        MockTransactionItem(50.00, "expense", "Needs Clarity", needs_clarification=True)
    ]

    default_account = {"account_name": "HDFC", "id": "acc_123"}

    result = await service.process_bulk_payload(transactions, default_account)

    # All three should be categorized as ignored
    assert len(result["unique"]) == 0
    assert len(result["duplicates"]) == 0
    assert len(result["ignored"]) == 3


@pytest.mark.asyncio
async def test_process_bulk_payload_success(mock_db_client, mock_cache_manager, mock_category_pull_service):
    """Test standard bulk processing categorization and totals."""
    service = BulkTransactionService(mock_db_client, "test_user", mock_cache_manager, mock_category_pull_service)

    # Mocks required for isolation
    service.dao.check_transaction_exists = MagicMock(return_value=False)
    service.dao.execute_bulk_commit = MagicMock()

    transactions = [
        MockTransactionItem(500.00, "expense", "Swiggy Order"),
        MockTransactionItem(15000.00, "income", "Freelance Work")
    ]

    default_account = {"account_name": "HDFC", "id": "acc_123"}

    result = await service.process_bulk_payload(transactions, default_account)

    assert len(result["unique"]) == 2
    assert result["totals"]["expenses"] == Decimal('500.00')
    assert result["totals"]["income"] == Decimal('15000.00')