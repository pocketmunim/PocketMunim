from datetime import datetime
from typing import Optional, Dict, Any

class ReportTokenDAO:
    def __init__(self, db_client):
        self.db = db_client

    def create_token(self, token: str, user_id: str, expires_at: datetime) -> bool:
        try:
            payload = {
                "token": str(token),
                "user_id": str(user_id),
                "expires_at": expires_at.isoformat()
            }
            self.db.table("report_tokens").insert(payload).execute()
            return True
        except Exception as e:
            print(f"Failed to insert report token {token}: {e}")
            return False

    def get_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            res = self.db.table("report_tokens").select("*").eq("token", str(token)).execute()
            if res.data:
                return res.data[0]
            return None
        except Exception as e:
            print(f"Failed to fetch report token {token}: {e}")
            return None

    def delete_token(self, token: str) -> bool:
        try:
            self.db.table("report_tokens").delete().eq("token", str(token)).execute()
            return True
        except Exception as e:
            print(f"Failed to delete report token {token}: {e}")
            return False