from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature

router = APIRouter(prefix="/api/v1/notifications", tags=["In-App Notifications"])

@router.post("/list/{user_id}", dependencies=[Depends(verify_zero_trust_signature)])
async def list_notifications(user_id: str, db: Client = Depends(get_db)):
    res = db.table("app_notifications").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(20).execute()
    return {"status": "SUCCESS", "data": res.data or []}

@router.post("/mark-read/{notification_id}", dependencies=[Depends(verify_zero_trust_signature)])
async def mark_notification_read(notification_id: str, db: Client = Depends(get_db)):
    db.table("app_notifications").update({"is_read": True}).eq("notification_id", notification_id).execute()
    return {"status": "SUCCESS", "message": "Notification marked as read."}