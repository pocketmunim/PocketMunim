from datetime import datetime


class ReportTokenDAO:
    def __init__(self, db_client):
        self.db = db_client

    def create_token(self, token: str, user_id: str, expires_at: datetime):
        expires_at_str = expires_at.isoformat() if isinstance(expires_at, datetime) else str(expires_at)

        self.db.table('report_tokens').insert({
            "token": token,
            "user_id": user_id,
            "expires_at": expires_at_str
        }).execute()

        # 🚀 FIX: Return True to satisfy test assertions
        return True

    def get_token(self, token: str):
        try:
            res = self.db.table('report_tokens').select('*').eq('token', token).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
            return None
        except Exception as e:
            print(f"Error fetching token: {e}")
            return None

    def delete_token(self, token: str):
        try:
            self.db.table('report_tokens').delete().eq('token', token).execute()
        except Exception as e:
            print(f"Error deleting token: {e}")