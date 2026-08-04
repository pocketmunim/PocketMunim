import os
import httpx
from fastapi import FastAPI, Request, HTTPException
from supabase import create_client, Client
from groq import Groq

app = FastAPI()

# Environment Configurations
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEYS = os.getenv("GROQ_API_KEYS", "").split(",")

# Initialize Clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
groq_client = Groq(api_key=GROQ_API_KEYS[0].strip()) if GROQ_API_KEYS and GROQ_API_KEYS[0] else None


@app.get("/")
def health_check():
    return {"status": "PocketMunim Enterprise API is live", "phase": "8 Active - Production Engine"}


@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    message = payload.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()

    if not text or not chat_id:
        return {"ok": True}

    reply_text = "⚠️ System processing error."

    # 1. Handle System Commands
    if text.startswith("/start"):
        reply_text = "👋 Welcome to **PocketMunim**.\n\nYour automated financial intelligence system is active. Send your expenses naturally (e.g., *Milk 60* or *Dinner 450*)."
    elif text.startswith("/report"):
        reply_text = "📊 Dashboard link generated: https://pocketmunim.app/dashboard (Valid for 24 hours)"

    # 2. Handle Financial NLP Extraction & Ledger Commit
    else:
        try:
            # Phase 5 NLP Extraction via Groq Llama-3
            prompt = f"""
            Extract financial transaction details from this text: "{text}"
            Return ONLY a valid JSON object with keys: "intent" (expense/income), "amount" (float), "category" (string), "description" (string).
            """

            completion = groq_client.chat.completions.create(
                model="llama3-70b-8192",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )

            import json
            tx_data = json.loads(completion.choices[0].message.content)

            intent = tx_data.get("intent", "expense")
            amount = tx_data.get("amount", 0.0)
            category = tx_data.get("category", "General")
            description = tx_data.get("description", text)

            # Commit to Supabase Ledger
            if supabase and amount > 0:
                db_payload = {
                    "user_id": str(chat_id),  # Mapped to Telegram chat ID for single-tenant setup
                    "intent": intent,
                    "amount": amount,
                    "category": category,
                    "description": description
                }
                res = supabase.table("transactions").insert(db_payload).execute()

                reply_text = f"✅ **Committed to Ledger**\n\n- **Item:** {description}\n- **Amount:** ₹{amount}\n- **Category:** {category}"
            else:
                reply_text = f"✅ **Extracted (DB Offline):** {description} - ₹{amount} [{category}]"

        except Exception as e:
            reply_text = f"❌ Error processing intent through NLP engine: {str(e)}"

    # Send Outbound Reply via Telegram Bot API
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