import json
import httpx
import os
import logging

logger = logging.getLogger(__name__)


async def send_telegram_reply(chat_id, text, reply_markup=None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }

    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            # This will print Telegram's exact error description to your console/logs
            logger.error(f"Telegram API Error ({response.status_code}): {response.text}")


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
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            logger.error(f"Telegram API Edit Error ({response.status_code}): {response.text}")