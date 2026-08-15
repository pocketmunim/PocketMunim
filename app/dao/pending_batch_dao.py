from typing import Any

class PendingBatchDAO:
    def __init__(self, db_client: Any):
        self.db = db_client

    def create_batch(self, batch_id: str, user_id: str, account_id: str, items: list[dict[str, Any]]) -> bool:
        try:
            payload = {
                "batch_id": str(batch_id),
                "user_id": str(user_id),
                "account_id": str(account_id),
                "items": items
            }
            self.db.table("pending_batches").insert(payload).execute()
            return True
        except Exception as e:
            print(f"Failed to create pending batch {batch_id}: {e}")
            return False

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        try:
            res = self.db.table("pending_batches").select("*").eq("batch_id", str(batch_id)).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            print(f"Failed to fetch pending batch {batch_id}: {e}")
            return None

    def update_batch_items(self, batch_id: str, items: list[dict[str, Any]]) -> bool:
        try:
            self.db.table("pending_batches").update({"items": items}).eq("batch_id", str(batch_id)).execute()
            return True
        except Exception as e:
            print(f"Failed to update pending batch {batch_id}: {e}")
            return False

    def delete_batch(self, batch_id: str) -> bool:
        try:
            self.db.table("pending_batches").delete().eq("batch_id", str(batch_id)).execute()
            return True
        except Exception as e:
            print(f"Failed to delete pending batch {batch_id}: {e}")
            return False
