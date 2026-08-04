class CategoryPullService:
    def __init__(self, ai_client):
        self.ai = ai_client

    def classify_item(self, item_name: str) -> dict:
        # System Prompt strictly demands JSON output:
        # {"category": "Groceries", "subcategory": "Dairy and Eggs", "item": "Paneer"}
        # Must validate output against Pydantic schema before returning.
        pass
