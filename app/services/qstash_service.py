import os
from qstash import QStash


class QStashService:
    @staticmethod
    def get_client() -> QStash:
        token = os.getenv("QSTASH_TOKEN")
        if not token:
            raise ValueError("QSTASH_TOKEN environment variable is missing.")
        return QStash(token=token)

    @classmethod
    def schedule_reminder(cls, destination_url: str, payload: dict, delay_seconds: int = None, cron_expr: str = None):
        """
        Schedules a task via QStash.
        - Use delay_seconds for one-off delayed tasks (e.g., 'remind me in 2 days').
        - Use cron_expr for periodic jobs (e.g., daily midnight checks).
        """
        client = cls.get_client()

        kwargs = {
            "url": destination_url,
            "body": payload,
        }

        if cron_expr:
            # e.g., cron_expr = "0 0 * * *" (Every day at midnight)
            kwargs["cron"] = cron_expr
        elif delay_seconds:
            kwargs["delay"] = delay_seconds

        response = client.message.publish(**kwargs)
        return response