from pydantic import BaseModel
from typing import Optional, List
from decimal import Decimal

class LoanNLPData(BaseModel):
    action: str  # "CREATE" or "PAY_EMI"
    lender_name: Optional[str] = None
    principal: Optional[Decimal] = None
    annual_interest_rate: Optional[Decimal] = None
    tenure_years: Optional[int] = None
    disbursement_date: Optional[str] = None
    first_emi_date: Optional[str] = None
    emi_amount: Optional[Decimal] = None
    payment_amount: Optional[Decimal] = None
    target_period: Optional[str] = None

class LoanBatchExtractionSchema(BaseModel):
    actions: List[LoanNLPData] = []