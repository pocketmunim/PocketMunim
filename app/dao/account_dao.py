from decimal import Decimal
from typing import Optional, Dict, Any

class AccountDAO:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id # Authenticated Telegram ID

    def count_user_accounts(self) -> int:
        response = self.db.table('accounts').select('account_id', count='exact').eq('user_id', self.user_id).execute()
        return response.count if response.count else 0

    def get_primary_account(self) -> Optional[Dict[str, Any]]:
        response = self.db.table('accounts').select('*').eq('user_id', self.user_id).eq('is_primary', True).execute()
        return response.data[0] if response.data else None

    def get_account_by_name(self, account_name: str) -> Optional[Dict[str, Any]]:
        response = self.db.table('accounts').select('*').eq('user_id', self.user_id).ilike('account_name', account_name).execute()
        return response.data[0] if response.data else None

    def create_account(self, account_data: dict) -> Dict[str, Any]:
        # Insert Account
        account_data['user_id'] = self.user_id
        response = self.db.table('accounts').insert(account_data).execute()
        new_account = response.data[0]

        # Rule 22: Enforce Audit Trail
        audit_payload = {
            "account_id": new_account['account_id'],
            "user_id": self.user_id,
            "operation": "ACCOUNT_CREATION",
            "old_balance": 0.00,
            "new_balance": float(new_account['current_balance'])
        }
        self.db.table('account_audit_log').insert(audit_payload).execute()
        return new_account