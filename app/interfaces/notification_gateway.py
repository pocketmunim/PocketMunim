from abc import ABC, abstractmethod
from typing import Optional
from app.telegram.telegram_utils import send_telegram_reply, edit_telegram_message, delete_telegram_message


class NotificationGateway(ABC):
    """Abstract base class for all outbound notifications."""

    @abstractmethod
    async def send_message(self, target_id: str, message: str, reply_markup: Optional[dict] = None) -> Optional[int]:
        pass

    @abstractmethod
    async def edit_message(self, target_id: str, message_id: int, message: str,
                           reply_markup: Optional[dict] = None) -> bool:
        pass

    @abstractmethod
    async def delete_message(self, target_id: str, message_id: int) -> bool:
        pass


class TelegramNotificationAdapter(NotificationGateway):
    """Concrete implementation for Telegram notifications."""

    async def send_message(self, target_id: str, message: str, reply_markup: Optional[dict] = None) -> Optional[int]:
        try:
            return await send_telegram_reply(int(target_id), message, reply_markup=reply_markup)
        except Exception as e:
            print(f"Notification Delivery Failed: {e}")
            return None

    async def edit_message(self, target_id: str, message_id: int, message: str,
                           reply_markup: Optional[dict] = None) -> bool:
        try:
            return await edit_telegram_message(int(target_id), message_id, text=message, reply_markup=reply_markup)
        except Exception as e:
            print(f"Notification Edit Failed: {e}")
            return False

    async def delete_message(self, target_id: str, message_id: int) -> bool:
        try:
            return await delete_telegram_message(int(target_id), message_id)
        except Exception as e:
            print(f"Notification Deletion Failed: {e}")
            return False