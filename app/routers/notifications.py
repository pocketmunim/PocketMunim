from pydantic import BaseModel
import logging
from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.core.database import get_db
from app.core.security import verify_zero_trust_signature


class RegisterDeviceRequest(BaseModel):
    user_id: str
    fcm_token: str
router = APIRouter(
    prefix="/api/v1/notifications",
    tags=["Notifications"]
)
@router.post("/register-device", dependencies=[Depends(verify_zero_trust_signature)])
async def register_device(payload: RegisterDeviceRequest, db: Client = Depends(get_db)):
    try:
        db.table("users").update({"fcm_token": payload.fcm_token}).eq("user_id", payload.user_id).execute()
        return {"status": "SUCCESS", "message": "Device registered for push notifications."}
    except Exception as e:
        logging.error(f"FCM Registration Error: {e}")
        raise HTTPException(status_code=400, detail="Failed to register device token.")