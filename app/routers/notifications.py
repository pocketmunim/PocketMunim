from fastapi import APIRouter, Request, status, Depends
from fastapi.responses import JSONResponse
from supabase import Client
from app.core.database import get_db

router = APIRouter(
    prefix="/api/v1/notifications",
    tags=["Notifications"]
)


@router.post("/register-device")
async def register_device(request: Request, db: Client = Depends(get_db)):
    payload = await request.json()
    user_id = payload.get("user_id")
    fcm_token = payload.get("fcm_token")

    if not user_id or not fcm_token:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"message": "Missing user_id or fcm_token"}
        )

    # Save the FCM token to the user's profile using the injected DB client
    db.table("users").update({"fcm_token": fcm_token}).eq("user_id", user_id).execute()

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "SUCCESS", "message": "Device securely registered for push notifications."}
    )