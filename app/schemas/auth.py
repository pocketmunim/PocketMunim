from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from typing import Optional

class RegisterRequest(BaseModel):
    user_id: UUID = Field(..., description="Hardware UUID from device")
    full_name: str = Field(..., min_length=2, max_length=150)
    salary: float = Field(..., ge=0.0)
    salary_date: int = Field(..., ge=1, le=31)
    bank_name: str = Field(..., min_length=2, max_length=80)
    current_balance: float = Field(..., ge=0.0)
    currency: Optional[str] = "INR"

    @field_validator('full_name', 'bank_name')
    @classmethod
    def sanitize(cls, v: str) -> str:
        return v.strip()

class RegisterResponse(BaseModel):
    status: str
    code: int
    user_id: UUID
    message: str
