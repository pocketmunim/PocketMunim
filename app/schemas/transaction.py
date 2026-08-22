from pydantic import BaseModel, Field, field_validator
from typing import Optional
from enum import Enum

class TransactionTypeEnum(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"

class CreateTransactionRequest(BaseModel):
    user_id: str
    item_name: str = Field(..., min_length=1, max_length=150)
    amount: float = Field(..., gt=0.0)
    type: TransactionTypeEnum = TransactionTypeEnum.DEBIT
    account_id: Optional[str] = None
    category: Optional[str] = "Miscellaneous"
    transaction_date: Optional[str] = None

    @field_validator('item_name')
    @classmethod
    def sanitize_item(cls, v: str) -> str:
        return v.strip()