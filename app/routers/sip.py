from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client
from datetime import date, timedelta
import calendar

from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from app.schemas.sip import CreateSIPRequest, PaySIPRequest, SnoozeSIPRequest

router = APIRouter(prefix="/api/v1/sip", tags=["Wealth & SIP Engine"])


@router.post("/list/{user_id}", dependencies=[Depends(verify_zero_trust_signature)])
async def list_sips(user_id: str, db: Client = Depends(get_db)):
    res = db.table("sip_contracts").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return {"status": "SUCCESS", "data": res.data}


@router.post("/create", dependencies=[Depends(verify_zero_trust_signature)])
async def create_sip(payload: CreateSIPRequest, db: Client = Depends(get_db)):
    # Safely evaluate deduction_day using getattr to protect against missing attributes
    deduction_val = getattr(payload, 'deduction_day', None)

    data = {
        "user_id": payload.user_id,
        "asset_name": payload.asset_name.strip(),
        "description": payload.description.strip() if payload.description else None,
        "is_flexible": payload.is_flexible,
        "monthly_amount": payload.monthly_amount,
        "frequency": payload.frequency,
        "start_date": str(payload.start_date),
        "next_due_date": str(payload.start_date),
        "deduction_day": deduction_val if deduction_val is not None else payload.start_date.day,
        "duration_months": payload.duration_months,
        "reminder_preference": payload.reminder_preference,
        "status": "ACTIVE"
    }
    res = db.table("sip_contracts").insert(data).execute()
    return {"status": "SUCCESS", "message": "SIP Contract Initialized.", "data": res.data[0]}


@router.post("/settle-past", dependencies=[Depends(verify_zero_trust_signature)])
async def settle_past_sips(payload: PaySIPRequest, db: Client = Depends(get_db)):
    rpc_payload = {
        "user_id": payload.user_id,
        "sip_id": payload.sip_id,
        "account_id": payload.account_id
    }
    try:
        res = db.rpc("settle_past_sips_atomic", {"payload": rpc_payload}).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/pay", dependencies=[Depends(verify_zero_trust_signature)])
async def pay_sip(payload: PaySIPRequest, db: Client = Depends(get_db)):
    rpc_payload = {
        "user_id": payload.user_id,
        "sip_id": payload.sip_id,
        "account_id": payload.account_id,
        "amount": payload.amount
    }
    try:
        res = db.rpc("pay_sip_installment_atomic", {"payload": rpc_payload}).execute()
        return res.data
    except Exception as e:
        err = str(e)
        if "Insufficient funds" in err or "Solvency Violation" in err:
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
    try:
        res = db.rpc("liquidate_sip_atomic", {"payload": rpc_payload}).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==========================================
# CRON SCHEDULER: Evaluates Due SIPs
# ==========================================
@router.post("/cron/reminders", dependencies=[Depends(verify_zero_trust_signature)])
async def evaluate_sip_reminders(db: Client = Depends(get_db)):
    today = date.today()
    res = db.table("sip_contracts").select("*").eq("status", "ACTIVE").execute()
    sips = res.data or []

    notifications_to_send = []

    for sip in sips:
        snooze = sip.get('snoozed_until')
        if snooze and date.fromisoformat(snooze) > today:
            continue

        last_paid = sip.get('last_paid_date')
        if last_paid:
            last_paid_dt = date.fromisoformat(last_paid)
            if last_paid_dt.year == today.year and last_paid_dt.month == today.month:
                continue

        target_day = sip.get('deduction_day') or 1
        _, max_days = calendar.monthrange(today.year, today.month)
        effective_target_day = min(target_day, max_days)

        days_until_due = effective_target_day - today.day
        pref = sip.get('reminder_preference', '1_DAY_BEFORE')

        trigger = False
        if pref == 'SAME_DAY' and days_until_due <= 0:
            trigger = True
        elif pref == '1_DAY_BEFORE' and days_until_due <= 1:
            trigger = True
        elif pref == '1_WEEK_BEFORE' and days_until_due <= 7:
            trigger = True

        if trigger:
            notifications_to_send.append({
                "user_id": sip['user_id'],
                "sip_id": sip['sip_id'],
                "title": f"🔔 SIP Due: {sip['asset_name']}",
                "body": f"Your SIP of ₹{sip['monthly_amount']} is due for approval."
            })

    return {"status": "SUCCESS", "notifications_dispatched": len(notifications_to_send)}