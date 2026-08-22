from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import date
from enum import Enum

class LoanTypeEnum(str, Enum):
    BORROWED = "BORROWED"
    LENT = "LENT"

class LoanStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"

class RegisterLoanRequest(BaseModel):
    user_id: str
    loan_name: str = Field(..., min_length=2, max_length=150)
    loan_type: LoanTypeEnum = LoanTypeEnum.BORROWED
    counterparty: str = Field(..., min_length=2, max_length=150)
    disbursement_date: date
    first_emi_date: date
    original_principal: float = Field(..., gt=0.0)
    annual_interest_rate: float = Field(default=0.0, ge=0.0, le=100.0)
    original_tenure_months: int = Field(..., gt=0, le=480)
    account_id: Optional[str] = None

    @field_validator('loan_name', 'counterparty')
    @classmethod
    def sanitize_strings(cls, v: str) -> str:
        return v.strip()

class PayEMIRequest(BaseModel):
    user_id: str
    loan_id: str
    account_id: Optional[str] = None
    is_advance_confirmed: bool = False

class LoanSummaryItem(BaseModel):
    loan_id: str
    loan_name: str
    loan_type: str
    counterparty: str
    disbursement_date: date
    first_emi_date: date
    original_principal: float
    pending_principal: float
    annual_interest_rate: float
    original_tenure_months: int
    pending_tenure_months: int
    monthly_emi: float
    total_interest_payable: float
    principal_paid: float
    interest_paid: float
    next_emi_date: date
    status: str
    account_id: Optional[str] = None
    account_name: Optional[str] = "Default Vault"
    is_current_month_paid: bool = False
    has_pending_past_emis: bool = False
    pending_past_emis_count: int = 0
    pending_past_emis_total: float = 0.0

class LoanListResponse(BaseModel):
    status: str
    total_liabilities: float
    total_receivables: float
    net_debt_position: float
    active_loans_count: int
    loans: List[LoanSummaryItem]