# FROZEN
from pydantic import BaseModel, Field
from typing import Literal
from decimal import Decimal

class AccountCreate(BaseModel):
    account_name: str = Field(..., max_length=100)
    # UPDATED: Validation rules match database constraints
    account_type: Literal['BANK', 'CASH', 'WALLET', 'CREDIT_CARD', 'INVESTMENT']
    initial_balance: Decimal = Field(default=Decimal('0.00'), max_digits=15, decimal_places=2)
    is_primary: bool = False
