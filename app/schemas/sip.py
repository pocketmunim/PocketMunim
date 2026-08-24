from pydantic import BaseModel, Field
from typing import Optional

class CreateSIPRequest(BaseModel):
    user_id: str
    asset_name: str = Field(..., min_length=2, max_length=255)
    monthly_amount: float = Field(..., gt=0.0)
    deduction_day: int = Field(..., ge=1, le=31)
    duration_months: Optional[int] = Field(default=None, gt=0)
    reminder_preference: str = Field(default="1_DAY_BEFORE")

class PaySIPRequest(BaseModel):
    user_id: str
    sip_id: str
    account_id: str

class SnoozeSIPRequest(BaseModel):
    user_id: str
    sip_id: str
    snooze_days: int = Field(..., gt=0, le=30)