from decimal import Decimal
from typing import Optional
from app.schemas.account_schema import AccountCreate
from app.dao.account_dao import AccountDAO


class AccountService:
    def __init__(self, db_session, user_id: str):
        self.db = db_session
        self.user_id = user_id
        self.dao = AccountDAO(self.db, self.user_id)

    def register_account(self, data: AccountCreate) -> dict:
        # Rule 19: If count == 0, force data.is_primary = True
        existing_count = self.dao.count_user_accounts()
        if existing_count == 0:
            data.is_primary = True
        elif data.is_primary:
            # Future enhancement: DB transaction to demote existing primary
            pass

            # Validate unique name
        if self.dao.get_account_by_name(data.account_name):
            raise ValueError(f"Account '{data.account_name}' already exists.")

        payload = {
            "account_name": data.account_name,
            "account_type": data.account_type,
            "current_balance": float(data.initial_balance),
            "is_primary": data.is_primary
        }
        return self.dao.create_account(payload)

    def resolve_transaction_account(self, specified_account_name: Optional[str]) -> dict:
        # Rule 20: Deterministic Resolution
        if not specified_account_name:
            primary_account = self.dao.get_primary_account()
            if not primary_account:
                raise ValueError("No default account found. Please create an account first.")
            return primary_account

        account = self.dao.get_account_by_name(specified_account_name)
        if not account:
            # Rule 20: Do not silently create it. Clearly warn the user.
            raise ValueError(
                f"Account '{specified_account_name}' does not exist. Please check the spelling or add it first.")

        return account