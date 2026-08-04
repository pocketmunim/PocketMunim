import os
from fastapi import HTTPException, Header, Request
from typing import Optional


def get_authorized_users() -> list[str]:
    users_env = os.getenv("AUTHORIZED_TELEGRAM_IDS", "")
    return [uid.strip() for uid in users_env.split(",") if uid.strip()]


def verify_user_authorization(telegram_id: str) -> bool:
    authorized_users = get_authorized_users()
    if not authorized_users:
        return False
    return str(telegram_id) in authorized_users


async def authenticate_telegram_request(
        request: Request,
        x_telegram_bot_api_secret_token: Optional[str] = Header(None)
) -> bool:
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not expected_secret or x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(status_code=403, detail="PocketMunim: Unauthorized Webhook Origin")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    telegram_id = payload.get("message", {}).get("from", {}).get("id")
    if not telegram_id:
        telegram_id = payload.get("edited_message", {}).get("from", {}).get("id")

    if telegram_id and not verify_user_authorization(str(telegram_id)):
        raise HTTPException(status_code=403, detail="You are not an authorized PocketMunim member.")

    # Store validated ID in request state for strict RLS database injection
    request.state.telegram_id = str(telegram_id)
    return True