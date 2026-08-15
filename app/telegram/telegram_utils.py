import json
import httpx
import os
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ==========================================
# ORIGINAL CORE API FUNCTIONS (RESTORED)
# ==========================================

async def send_telegram_reply(chat_id: int, text: str, reply_markup: dict = None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or not chat_id:
        return None

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2"} # Upgraded to MarkdownV2 for premium UI

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
        payload["parse_mode"] = "MarkdownV2"
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

# ==========================================
# NEW PREMIUM FORMATTING FUNCTIONS (ADDED)
# ==========================================

def escape_markdown_v2(text: str) -> str:
    """
    Escapes characters strictly required by Telegram's MarkdownV2 parser.
    Ensures no unescaped characters crash the delivery.
    """
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", str(text))


def format_transaction_receipt(amount: float, category: str, date: str, note: Optional[str] = None) -> str:
    """
    Generates an 'attractive' premium receipt format.
    """
    escaped_cat = escape_markdown_v2(category)
    escaped_amt = escape_markdown_v2(f"₹{amount:,.2f}")
    escaped_date = escape_markdown_v2(date)

    receipt = (
        f"✅ *Transaction Recorded*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Amount:* {escaped_amt}\n"
        f"📂 *Category:* {escaped_cat}\n"
        f"📅 *Date:* {escaped_date}\n"
    )

    if note:
        receipt += f"📝 *Note:* _{escape_markdown_v2(note)}_\n"

    receipt += f"━━━━━━━━━━━━━━━━━━\n"
    receipt += f"⚡ _Processed by PocketMunim AI_"

    return receipt


def build_dashboard_keyboard(token: str) -> dict:
    """Creates a premium inline keyboard with a magic link button."""
    return {
        "inline_keyboard": [
            [{"text": "📊 Open Financial Dashboard", "url": f"https://munim.ishita.financial/dashboard?token={token}"}],
            [{"text": "⚙️ Manage Account", "callback_data": "manage_account"}]
        ]
    }