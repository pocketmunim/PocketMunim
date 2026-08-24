from pydantic import BaseModel
import logging

class RegisterDeviceRequest(BaseModel):
    user_id: str
    fcm_token: str

@router.post("/register-device", dependencies=[Depends(verify_zero_trust_signature)])
async def register_device(payload: RegisterDeviceRequest, db: Client = Depends(get_db)):
    try:
        db.table("users").update({"fcm_token": payload.fcm_token}).eq("user_id", payload.user_id).execute()
        return {"status": "SUCCESS", "message": "Device registered for push notifications."}
    except Exception as e:
        logging.error(f"FCM Registration Error: {e}")
        raise HTTPException(status_code=400, detail="Failed to register device token.")