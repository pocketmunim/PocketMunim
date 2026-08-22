from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional, List
from datetime import date

class SalaryMonthItem(BaseModel):
    salary_id: UUID
    year: int
    month: int
    base_amount: float
    actual_amount: float
    payout_date: date
    status: str
    is_custom_override: bool
    total_income: float = 0.0
    total_expense: float = 0.0
    net_margin: float = 0.0
    can_settle: bool = False

class SalaryMatrixResponse(BaseModel):
    status: str
    year: int
    annual_base_total: float
    total_disbursed: float
    total_scheduled: float
    months: List[SalaryMonthItem]

class SalaryOverrideRequest(BaseModel):
    user_id: UUID
    year: int
    month: int
    new_amount: float = Field(..., ge=0.0)
    new_payout_date: date

class SettleSalaryRequest(BaseModel):
    user_id: UUID
    salary_id: UUID
    target_account_id: Optional[UUID] = None