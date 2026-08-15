import os
from fastapi import HTTPException, Header, Request
from typing import Optional
from app.telegram.telegram_utils import send_telegram_reply
from qstash import Receiver

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

    message_obj = payload.get("message") or payload.get("edited_message")
    callback_query = payload.get("callback_query")
    telegram_id = None
    chat_id = None

    if message_obj:
        telegram_id = message_obj.get("from", {}).get("id")
        chat_id = message_obj.get("chat", {}).get("id")
    elif callback_query:
        telegram_id = callback_query.get("from", {}).get("id")
        chat_id = callback_query.get("message", {}).get("chat", {}).get("id")

    if not telegram_id:
        raise HTTPException(status_code=200, detail="Missing Telegram ID in payload, dropped cleanly.")

    if not verify_user_authorization(str(telegram_id)):
        if chat_id:
            try:
                await send_telegram_reply(
                    chat_id,
                    "⛔ *ACCESS DENIED*\n\nYou are not an authorized PocketMunim member."
                )
            except Exception as e:
                print(f"Failed to send denial message: {e}")
        raise HTTPException(status_code=200, detail="You are not an authorized PocketMunim member.")

    request.state.telegram_id = str(telegram_id)
    return True

async def verify_qstash_request(request: Request) -> bool:
    current_signing_key = os.getenv("QSTASH_CURRENT_SIGNING_KEY")
    next_signing_key = os.getenv("QSTASH_NEXT_SIGNING_KEY")

    if not current_signing_key or not next_signing_key:
        print("WARNING: QStash keys missing. Running direct pass-through.")
        return True

    receiver = Receiver(
        current_signing_key=current_signing_key,
        next_signing_key=next_signing_key,
    )

    body = await request.body()
    signature = request.headers.get("Upstash-Signature")

    if not signature:
        raise HTTPException(status_code=401, detail="Missing Upstash Signature Header")

    try:
        receiver.verify(
            body=body.decode("utf-8"),
            signature=signature,
            url=str(request.url)
        )
        return True
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"Invalid QStash Signature: {str(e)}")