import os
import logging
import firebase_admin
from firebase_admin import credentials, messaging

logger = logging.getLogger(__name__)


class NotificationService:
    _initialized = False

    @classmethod
    def initialize(cls):
        if not cls._initialized:
            try:
                # Target the JSON file in the root of your backend
                cred_path = "firebase-adminsdk.json"
                if os.path.exists(cred_path):
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred)
                    cls._initialized = True
                    logger.info("Firebase Admin SDK initialized successfully.")
                else:
                    logger.warning(f"CRITICAL: Firebase credentials not found at {cred_path}")
            except ValueError:
                # App already initialized
                cls._initialized = True
            except Exception as e:
                logger.error(f"Firebase initialization failed: {e}")

    @classmethod
    def send_push_notification(cls, token: str, title: str, body: str, route: str = None):
        cls.initialize()
        if not cls._initialized or not token:
            return False

        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                # This matches the frontend logic you set up in main.dart _handleNotificationRoute
                data={"route": route} if route else {},
                token=token,
            )
            response = messaging.send(message)
            logger.info(f"Successfully sent FCM push message: {response}")
            return True
        except Exception as e:
            logger.error(f"Error sending FCM message: {e}")
            return False