from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from supabase import Client
from datetime import date, timedelta
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature

router = APIRouter(prefix="/api/v1/sip", tags=["Wealth & SIP Engine"])


class CreateSIPRequest(BaseModel):
    user_id: str
    asset_name: str
    monthly_amount: float
    deduction_day: int
    duration_months: Optional[int] = None
    reminder_preference: str = "1_DAY_BEFORE"


class PaySIPRequest(BaseModel):
    user_id: str
    sip_id: str
    account_id: str


class SnoozeSIPRequest(BaseModel):
    user_id: str
    sip_id: str
    snooze_days: int


@router.post("/create", dependencies=[Depends(verify_zero_trust_signature)])
async def create_sip(payload: CreateSIPRequest, db: Client = Depends(get_db)):
    if not (1 <= payload.deduction_day <= 31):
        raise HTTPException(status_code=400, detail="Deduction day must be between 1 and 31.")

    data = {
        "user_id": payload.user_id,
        "asset_name": payload.asset_name,
        "monthly_amount": payload.monthly_amount,
        "deduction_day": payload.deduction_day,
        "duration_months": payload.duration_months,
        "reminder_preference": payload.reminder_preference,
        "status": "ACTIVE"
    }
    res = db.table("sip_contracts").insert(data).execute()
    return {"status": "SUCCESS", "message": "SIP Contract Initialized.", "data": res.data[0]}


@router.post("/pay", dependencies=[Depends(verify_zero_trust_signature)])
async def pay_sip(payload: PaySIPRequest, db: Client = Depends(get_db)):
    rpc_payload = {
        "user_id": payload.user_id,
        "sip_id": payload.sip_id,
        "account_id": payload.account_id
    }
    try:
        res = db.rpc("pay_sip_installment_atomic", {"payload": rpc_payload}).execute()
        return res.data
    except Exception as e:
        err = str(e)
        if "Insufficient funds" in err:
            raise HTTPException(status_code=400, detail="Solvency Violation: Not enough funds in selected vault.")
        raise HTTPException(status_code=400, detail=err)


@router.post("/snooze", dependencies=[Depends(verify_zero_trust_signature)])
async def snooze_sip(payload: SnoozeSIPRequest, db: Client = Depends(get_db)):
    snooze_date = date.today() + timedelta(days=payload.snooze_days)
    db.table("sip_contracts").update({"snoozed_until": str(snooze_date)}).eq("sip_id", payload.sip_id).eq("user_id",
                                                                                                          payload.user_id).execute()
    return {"status": "SUCCESS", "message": f"Reminder snoozed until {snooze_date}."}


@router.post("/liquidate", dependencies=[Depends(verify_zero_trust_signature)])
async def liquidate_sip(payload: PaySIPRequest, db: Client = Depends(get_db)):
    rpc_payload = {
        "user_id": payload.user_id,
        "sip_id": payload.sip_id,
        "account_id": payload.account_id
    }
    res = db.rpc("liquidate_sip_atomic", {"payload": rpc_payload}).execute()
    return res.data

@router.post("/list/{user_id}", dependencies=[Depends(verify_zero_trust_signature)])
async def list_sips(user_id: str, db: Client = Depends(get_db)):
    # Fetches all SIPs for the user, ordered by newest first
    res = db.table("sip_contracts").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return {"status": "SUCCESS", "data": res.data}