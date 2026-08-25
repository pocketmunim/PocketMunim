from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from supabase import create_client
import os

router = APIRouter(
    prefix="/api/v1/notifications",
    tags=["Notifications"]
)

db = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))


@router.post("/register-device")
async def register_device(request: Request):
    payload = await request.json()
    user_id = payload.get("user_id")
    fcm_token = payload.get("fcm_token")

    if not user_id or not fcm_token:
        return JSONResponse(status_code=400, content={"message": "Missing user_id or fcm_token"})

    # Save the FCM token to the user's profile
    res = db.table("users").update({"fcm_token": fcm_token}).eq("user_id", user_id).execute()

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "SUCCESS", "message": "Device securely registered for push notifications."}
    )