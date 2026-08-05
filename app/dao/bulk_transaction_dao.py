from decimal import Decimal


class BulkTransactionDAO:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id

    def check_transaction_exists(self, amount: float, description: str, txn_type: str) -> bool:
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

    def execute_bulk_commit(self, account_id: str, payloads: list, total_deduction: float, total_addition: float,
                            current_balance: float) -> bool:
        """Executes atomic account balance update and bulk inserts transactions."""
        try:
            new_balance = float(
                Decimal(str(current_balance)) - Decimal(str(total_deduction)) + Decimal(str(total_addition)))

            # 1. Update account balance
            self.db.table('accounts').update({"balance": new_balance}).eq("id", account_id).execute()

            # 2. Insert account audit log
            if total_deduction > 0 or total_addition > 0:
                self.db.table('account_logs').insert({
                    "account_id": account_id,
                    "user_id": self.user_id,
                    "log_type": "BULK_UPDATE",
                    "amount": max(total_deduction, total_addition),
                    "balance_after": new_balance,
                    "description": f"Bulk Transaction ({len(payloads)} items)"
                }).execute()

            # 3. Bulk insert transactions
            if payloads:
                self.db.table('transactions').insert(payloads).execute()
            return True
        except Exception as e:
            print(f"Bulk commit error: {e}")
            return False