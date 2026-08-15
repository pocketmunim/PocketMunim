from decimal import Decimal


class BulkTransactionDAO:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id

    def check_transaction_exists(self, amount: str, normalized_item: str, txn_type: str, date_iso: str) -> bool:
        try:
            # Extract YYYY-MM-DD from the provided ISO string
            target_date = date_iso[:10]

            # CRITICAL TIMEZONE FIX:
            # Construct boundaries using the application's native +05:30 (IST) offset.
            # Using +00:00 causes transactions recorded between 12:00 AM and 5:30 AM IST
            # to be completely ignored by the calendar day duplicate filter.
            start_of_day = f"{target_date}T00:00:00+05:30"
            end_of_day = f"{target_date}T23:59:59.999999+05:30"

            res = self.db.table('transactions').select('txn_id') \
                .eq('user_id', self.user_id) \
                .eq('amount', float(amount)) \
                .ilike('normalized_item', normalized_item) \
                .eq('txn_type', txn_type) \
                .gte('date', start_of_day) \
                .lte('date', end_of_day) \
                .eq('soft_deleted', False) \
                .execute()

            return bool(res.data)
        except Exception as e:
            print(f"Duplicate check failed: {e}")
            return False

    def execute_bulk_commit(self, account_id: str, payloads: list, total_deduction: Decimal,
                            total_addition: Decimal) -> Decimal:
        net_change = total_addition - total_deduction
        max_amount = max(total_deduction, total_addition)

        net_change_str = str(net_change)
        max_amount_str = str(max_amount)

        for p in payloads:
            if 'amount' in p:
                p['amount'] = str(p['amount'])

        try:
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