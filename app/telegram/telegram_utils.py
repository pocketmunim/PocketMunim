import os
import httpx

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

async def send_telegram_reply(chat_id: int, text: str, reply_markup: dict = None):
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)

async def edit_telegram_message(chat_id: int, message_id: int, text: str = None, reply_markup: dict = None):
    if not TELEGRAM_BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"
    payload = {"chat_id": chat_id, "message_id": message_id}
    if reply_markup: payload["reply_markup"] = reply_markup
    if text:
        url += "editMessageText"
        payload["text"] = text
        payload["parse_mode"] = "Markdown"
    else:
        url += "editMessageReplyMarkup"
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)
