import os
import httpx
from fastapi import FastAPI, Request, HTTPException

app = FastAPI()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


@app.get("/")
def health_check():
    return {"status": "PocketMunim Enterprise API is live", "phase": "8 Active"}


@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Extract incoming Telegram message fields
    message = payload.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if text and chat_id:
        print(f"Incoming tactical intent from chat {chat_id}: {text}")

        # Formulate response (Simulating Phase 5 NLP Ledger confirmation)
        reply_text = f"✅ PocketMunim Logged: \"{text}\" [Status: Committed to Ledger]"

        # Send outbound message back to user via Telegram Bot API
        if TELEGRAM_BOT_TOKEN:
            telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            async with httpx.AsyncClient() as client:
                await client.post(
                    telegram_url,
                    json={
                        "chat_id": chat_id,
                        "text": reply_text,
                        "parse_mode": "Markdown"
                    }
                )

    return {"ok": True}