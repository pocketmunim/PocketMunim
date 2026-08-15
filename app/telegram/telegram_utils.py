import json
import httpx
import os
import logging

logger = logging.getLogger(__name__)


async def send_telegram_reply(chat_id: int, text: str, reply_markup: dict = None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or not chat_id:
        return None

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}

    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            logger.error(f"Telegram API Error ({response.status_code}): {response.text}")
            return None

        data = response.json()
        return data.get("result", {}).get("message_id")


async def edit_telegram_message(chat_id: int, message_id: int, text: str = None, reply_markup: dict = None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return False

    url = f"https://api.telegram.org/bot{token}/"
    payload = {"chat_id": chat_id, "message_id": message_id}

    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)

    if text:
        url += "editMessageText"
        payload["text"] = text
        payload["parse_mode"] = "Markdown"
    else:
        url += "editMessageReplyMarkup"

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            logger.error(f"Telegram API Edit Error ({response.status_code}): {response.text}")
            return False
        return True


async def delete_telegram_message(chat_id: int, message_id: int):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return False

    url = f"https://api.telegram.org/bot{token}/deleteMessage"
    payload = {"chat_id": chat_id, "message_id": message_id}

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        return response.status_code == 200