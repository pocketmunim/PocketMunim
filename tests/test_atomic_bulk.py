import pytest
from unittest.mock import MagicMock
from decimal import Decimal
from app.dao.bulk_transaction_dao import BulkTransactionDAO


@pytest.fixture
def mock_supabase():
    return MagicMock()


def test_atomic_bulk_commit_precision(mock_supabase):
    dao = BulkTransactionDAO(mock_supabase, "user_123")
    account_id = "acc_456"

    # 10.33 + 12.01 - 5.11 = 17.23
    total_deduction = Decimal('5.11')
    total_addition = Decimal('22.34')

    payloads = [{"amount": Decimal('12.01')}, {"amount": Decimal('10.33')}]

    # FIX: Use .return_value instead of calling () during mock setup
    mock_supabase.rpc.return_value.execute.return_value = MagicMock(data="1017.23")

    result = dao.execute_bulk_commit(account_id, payloads, total_deduction, total_addition)

    # Assert string conversion happens at the boundary for PostgreSQL NUMERIC safety
    mock_supabase.rpc.assert_called_once_with('atomic_bulk_commit', {
        'p_account_id': account_id,
        'p_user_id': "user_123",
        'p_net_change': '17.23',
        'p_max_amount': '22.34',
        'p_payloads': [{'amount': '12.01'}, {'amount': '10.33'}]
    })
    assert result == Decimal('1017.23')