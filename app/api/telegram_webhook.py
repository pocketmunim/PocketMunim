from fastapi import APIRouter, Header, HTTPException, Depends
from app.security.auth import authenticate_telegram_request

router = APIRouter()

@router.post("/webhook/telegram")
async def handle_telegram_payload(
    authorized: bool = Depends(authenticate_telegram_request)
):
    return {"status": "received", "authorized": True}
