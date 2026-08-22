from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from typing import Optional
from datetime import date
from enum import Enum

class TransactionTypeEnum(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"

class CreateTransactionRequest(BaseModel):
    user_id: UUID
    item_name: str = Field(..., min_length=2, max_length=150)
    amount: float = Field(..., gt=0.0)
    type: TransactionTypeEnum = TransactionTypeEnum.DEBIT
    account_id: Optional[UUID] = None
    category: Optional[str] = "Miscellaneous"
    transaction_date: Optional[date] = None

    @field_validator('item_name')
    @classmethod
    def sanitize_item(cls, v: str) -> str:
        return v.strip()