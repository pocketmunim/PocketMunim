import json
import httpx
from groq import Groq
from typing import Optional, List

class CategoryPullService:
    def __init__(self, ai_client: Groq, db_client=None, admin_db_client=None):
        self.ai = ai_client
        self.db = db_client
        self.admin_db = admin_db_client or db_client

    async def seed_common_categories(self, user_id: str, chat_id: int = None, bot_token: str = None) -> None:
        """
        Proactively fetches common day-to-day life categories from Groq when idle.
        Sends live status alerts to the Telegram bot so you can track execution.
        """
        if not self.ai or not self.admin_db:
            return

        # Send starting alert to Telegram
        if chat_id and bot_token:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"https://api.telegram.org/bot{bot_token}/sendMessage",
                        json={"chat_id": chat_id, "text": "⏳ [System Idle] Fetching day-to-day life categories (Groceries, Medicines, etc.) via AI..."}
                    )
            except Exception:
                pass

        seed_prompt = """You are the PocketMunim Day-to-Day Life Category Generator.
Your sole responsibility is to generate a comprehensive JSON list of common, everyday life categories, their subcategories, and typical day-to-day items (e.g., Groceries, Medicines, Household Supplies, Dining, Transport, Utilities).

RULES:
1. Output ONLY valid JSON matching the exact schema below.
2. Do not wrap in markdown code fences.
3. Provide at least 15-20 common day-to-day items across practical daily categories.

OUTPUT FORMAT:
{
  "categories": [
    {"category": "Groceries", "subcategory": "Vegetables", "item": "Tomato"},
    {"category": "Medicines", "subcategory": "Pharmacy", "item": "Paracetamol"}
  ]
}"""

        try:
            completion = self.ai.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": seed_prompt},
                    {"role": "user", "content": "Generate day-to-day life category seed list."}
                ],
                temperature=0.3
            )
            raw_content = completion.choices[0].message.content.strip()
            if raw_content.startswith("```"):
                raw_content = raw_content.split("```")[1]
                if raw_content.startswith("json"):
                    raw_content = raw_content[4:]
                raw_content = raw_content.strip()

            parsed = json.loads(raw_content)
            items_list = parsed.get("categories", [])
            added_count = 0

            for entry in items_list:
                cat = entry.get("category")
                sub = entry.get("subcategory")
                itm = entry.get("item")
                if cat and itm:
                    try:
                        payload = {
                            "user_id": user_id,
                            "name": itm,
                            "level": "ITEM",
                            "category": cat
                        }
                        self.admin_db.table('categories').insert(payload).execute()
                        added_count += 1
                    except Exception:
                        pass

            # Send completion alert to Telegram
            if chat_id and bot_token:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"https://api.telegram.org/bot{bot_token}/sendMessage",
                            json={"chat_id": chat_id, "text": f"✅ [System Idle] Successfully fetched and saved {added_count} day-to-day categories to database!"}
                        )
                except Exception:
                    pass

        except Exception as e:
            if chat_id and bot_token:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"https://api.telegram.org/bot{bot_token}/sendMessage",
                            json={"chat_id": chat_id, "text": f"❌ [System Idle] Category seeding failed: {str(e)}"}
                        )
                except Exception:
                    pass

    def classify_item(self, item_name: str, user_id: str = None) -> dict:
        if not self.ai:
            return {"category": None, "subcategory": None, "item": item_name}

        system_prompt = """You are the PocketMunim Day-to-Day Category Classification Engine.
Your sole responsibility is to classify a given transaction item into practical, everyday life categories (e.g., Groceries, Medicines, Household Supplies, Dining, Transport, Utilities).

RULES:
1. Select the most appropriate everyday Category and Subcategory.
2. If unknown or ambiguous, return null for category and subcategory.
3. Return ONLY valid JSON matching the exact output format without markdown wrappers.

OUTPUT FORMAT:
{
  "category": "string or null",
  "subcategory": "string or null",
  "item": "original item exactly as provided"
}"""

        try:
            completion = self.ai.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"item: \"{item_name}\""}
                ],
                temperature=0.0
            )
            raw_content = completion.choices[0].message.content.strip()
            if raw_content.startswith("```"):
                raw_content = raw_content.split("```")[1]
                if raw_content.startswith("json"):
                    raw_content = raw_content[4:]
                raw_content = raw_content.strip()

            parsed = json.loads(raw_content)
            return {
                "category": parsed.get("category"),
                "subcategory": parsed.get("subcategory"),
                "item": parsed.get("item") or item_name
            }
        except Exception:
            return {"category": None, "subcategory": None, "item": item_name}