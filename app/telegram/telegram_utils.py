import json
import httpx
import os


async def send_telegram_reply(chat_id, text, reply_markup=None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Clean text to prevent Markdown parsing errors
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }

    if reply_markup:
        # CRITICAL: Must be a JSON string
        payload["reply_markup"] = json.dumps(reply_markup)

    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)


async def edit_telegram_message(chat_id, message_id, text, reply_markup=None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)