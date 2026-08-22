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
    loan_name: str = Field(..., min_length=1, max_length=150)
    loan_type: LoanTypeEnum = LoanTypeEnum.BORROWED
    counterparty: str = Field(..., min_length=1, max_length=150)
    disbursement_date: date
    first_emi_date: Optional[date] = None
    original_principal: float = Field(..., gt=0.0)
    annual_interest_rate: float = Field(default=0.0, ge=0.0, le=100.0)
    original_tenure_months: int = Field(default=0, ge=0, le=480)
    account_id: Optional[str] = None
    is_flexible: bool = False

    @field_validator('loan_name', 'counterparty')
    @classmethod
    def sanitize_strings(cls, v: str) -> str:
        return v.strip()

class PayEMIRequest(BaseModel):
    user_id: str
    loan_id: str
    account_id: Optional[str] = None
    is_advance_confirmed: bool = False

class SettlePastEMIsRequest(BaseModel):
    user_id: str
    loan_id: str
    account_id: Optional[str] = None

class FlexibleRepaymentRequest(BaseModel):
    user_id: str
    loan_id: str
    amount: float = Field(..., gt=0.0)
    account_id: Optional[str] = None
    payment_date: Optional[date] = None
    note: Optional[str] = "Ad-hoc repayment"

class PartialRepaymentLogItem(BaseModel):
    partial_repayment_id: str
    amount: float
    payment_date: date
    note: Optional[str] = "Ad-hoc repayment"
    remaining_balance_after: float
    created_at: str

class LoanSummaryItem(BaseModel):
    loan_id: str
    loan_name: str
    loan_type: str
    counterparty: str
    disbursement_date: date
    first_emi_date: Optional[date] = None
    original_principal: float
    pending_principal: float
    annual_interest_rate: float = 0.0
    original_tenure_months: int = 0
    pending_tenure_months: int = 0
    monthly_emi: float = 0.0
    total_interest_payable: float = 0.0
    principal_paid: float = 0.0
    interest_paid: float = 0.0
    next_emi_date: Optional[date] = None
    status: str
    is_flexible: bool = False
    account_id: Optional[str] = None
    account_name: Optional[str] = "Default Vault"
    is_current_month_paid: bool = False
    has_pending_past_emis: bool = False
    pending_past_emis_count: int = 0
    pending_past_emis_total: float = 0.0
    partial_repayments: List[PartialRepaymentLogItem] = []

class LoanListResponse(BaseModel):
    status: str
    total_liabilities: float
    total_receivables: float
    net_debt_position: float
    active_loans_count: int
    loans: List[LoanSummaryItem]