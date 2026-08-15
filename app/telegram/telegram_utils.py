"""
Telegram Utility Module: PocketMunim Enterprise
Handles premium UI/UX formatting for Telegram responses.
"""
import re
from typing import Optional


def escape_markdown_v2(text: str) -> str:
    """
    Escapes characters strictly required by Telegram's MarkdownV2 parser.
    Ensures no unescaped characters crash the delivery.
    """
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)


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