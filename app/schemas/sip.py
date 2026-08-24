from pydantic import BaseModel, Field
from typing import Optional
from datetime import date

class CreateSIPRequest(BaseModel):
    user_id: str
    asset_name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    is_flexible: bool = False
    monthly_amount: float = Field(..., gt=0.0)
    frequency: str = Field(default="MONTHLY")
    start_date: date
    duration_months: Optional[int] = Field(default=None, gt=0)
    reminder_preference: str = Field(default="1_DAY_BEFORE")

class PaySIPRequest(BaseModel):
    user_id: str
    sip_id: str
    account_id: str
    amount: Optional[float] = None

class SnoozeSIPRequest(BaseModel):
    user_id: str
    sip_id: str
    snooze_days: int