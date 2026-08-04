from fastapi import FastAPI, Request, HTTPException
import os

app = FastAPI()


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
        # Log or route the text to your Phase 5 NLP & Ledger Engine
        print(f"Incoming tactical intent from chat {chat_id}: {text}")

        # Example processing for "milk 70"
        # 1. Pass 'text' to Groq/Gemini NLP Parser
        # 2. Extract: category='Groceries', item='Milk', amount=70
        # 3. Commit to Supabase Ledger via RLS
        # 4. Reply back to Telegram user via Bot API

    return {"ok": True}