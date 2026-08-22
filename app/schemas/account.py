from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from typing import Optional, List
from datetime import datetime

class CreateAccountRequest(BaseModel):
    user_id: UUID
    account_name: str = Field(..., min_length=2, max_length=100)
    balance: float = Field(..., ge=0.0)
    is_default: Optional[bool] = False

    @field_validator('account_name')
    @classmethod
    def sanitize(cls, v: str) -> str:
        return v.strip().upper()

class SetDefaultAccountRequest(BaseModel):
    user_id: UUID
    account_id: UUID

class AccountItem(BaseModel):
    account_id: UUID
    user_id: UUID
    account_name: str
    balance: float
    is_default: bool
    is_active: bool
    created_at: datetime

class AccountListResponse(BaseModel):
    status: str
    accounts: List[AccountItem]