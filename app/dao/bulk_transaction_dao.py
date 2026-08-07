from decimal import Decimal


class BulkTransactionDAO:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id

    def check_transaction_exists(self, amount: str, description: str, txn_type: str) -> bool:
        """Checks if a non-salary transaction already exists in the transactions table."""
        try:
            res = self.db.table('transactions').select('*') \
                .eq('user_id', self.user_id) \
                .eq('amount', amount) \
                .ilike('description', description) \
                .eq('txn_type', txn_type) \
                .eq('soft_deleted', False) \
                .execute()
            return bool(res.data)
        except Exception:
            return False

    def execute_bulk_commit(self, account_id: str, payloads: list, total_deduction: Decimal,
                            total_addition: Decimal) -> Decimal:
        """Executes atomic account balance update and bulk inserts transactions via PostgreSQL RPC."""

        net_change = total_addition - total_deduction
        max_amount = max(total_deduction, total_addition)

        # Convert Decimal to string for network boundary to avoid float precision loss
        net_change_str = str(net_change)
        max_amount_str = str(max_amount)

        # Ensure all transaction amounts are strictly strings for exact numeric representation
        for p in payloads:
            if 'amount' in p:
                p['amount'] = str(p['amount'])

        try:
            # Atomic execution delegating balance math and insufficiency checks to PostgreSQL
            res = self.db.rpc('atomic_bulk_commit', {
                'p_account_id': account_id,
                'p_user_id': self.user_id,
                'p_net_change': net_change_str,
                'p_max_amount': max_amount_str,
                'p_payloads': payloads
            }).execute()

            return Decimal(str(res.data))
        except Exception as e:
            raise e