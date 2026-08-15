"""
High-Speed Command Router: PocketMunim Enterprise
Decouples transport layer from business logic for sub-second routing.
"""
from app.dependencies import get_async_db, get_ai_provider, get_notification_gateway
from app.telegram.telegram_utils import format_transaction_receipt
import logging

logger = logging.getLogger("PocketMunim.Router")


class CommandRouter:
    def __init__(self, db, ai, notifier, cache):
        self.db = db
        self.ai = ai
        self.notifier = notifier
        self.cache = cache

    async def process_webhook(self, payload: dict):
        """
        Main entry point for QStash decoupled webhook processing.
        """
        try:
            message = payload.get("message", {})
            text = message.get("text", "")
            chat_id = message.get("chat", {}).get("id")

            if not text or not chat_id:
                return {"status": "ignored", "reason": "empty payload"}

            # Standardized Routing Logic
            if text.startswith("/"):
                await self._route_command(text, chat_id)
            else:
                await self._route_nlp(text, chat_id)

            return {"status": "success"}

        except Exception as e:
            logger.error(f"Routing Error: {str(e)}")
            await self.notifier.send_message(chat_id, "⚠️ System error processing request.")
            raise e

    async def _route_command(self, text: str, chat_id: int):
        """Routes explicit commands (e.g., /start, /dashboard)."""
        command = text.split()[0].lower()
        if command == "/dashboard":
            # Delegate to specialized handler
            await self.notifier.send_message(chat_id, "📊 Generating your secure link...")
        else:
            await self.notifier.send_message(chat_id, "ℹ️ Command recognized but not implemented in fast-router yet.")

    async def _route_nlp(self, text: str, chat_id: int):
        """Routes natural language to Groq AI for extraction."""
        # 1. AI Extraction (Async)
        extraction = await self.ai.extract_transaction(text)

        # 2. Database Commit (Async)
        await self.db.commit_transaction(chat_id, extraction)

        # 3. Premium Formatting & Delivery
        receipt = format_transaction_receipt(
            amount=extraction.amount,
            category=extraction.category,
            date="Today"
        )
        await self.notifier.send_markdown_message(chat_id, receipt)