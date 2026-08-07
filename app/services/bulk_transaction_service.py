from decimal import Decimal
from datetime import datetime
from app.utils.constants import TZ_IST

class BulkTransactionService:
    def __init__(self, db_client, user_id: str, cache_manager, category_pull_service):
        self.db = db_client
        self.user_id = user_id
        from app.dao.bulk_transaction_dao import BulkTransactionDAO
        self.dao = BulkTransactionDAO(self.db, self.user_id)
        self.cache_manager = cache_manager
        self.category_pull_service = category_pull_service

    async def process_bulk_payload(self, transactions_list: list, default_account: dict) -> dict:
        unique_payloads = []
        pending_duplicates = []
        breakdown = []
        ignored = []
        new_taxonomy_items = []

        totals = {
            "expenses": Decimal('0.00'),
            "income": Decimal('0.00'),
            "transfers": Decimal('0.00')
        }
        counts = {
            "expenses": 0,
            "income": 0,
            "transfers": 0
        }

        # =========================================================
        # PHASE 1: PRE-FLIGHT AUTO-LEARNING (Prevent Timeouts)
        # Scan for all unknown items and learn them in ONE AI call.
        # =========================================================
        unknown_item_names = set()
        for tx in transactions_list:
            amount = tx.amount if tx.amount else Decimal('0.00')
            if amount > Decimal('0.00') and not tx.needs_clarification and not (tx.future and tx.future.is_future):
                description = str(tx.item or "Item").title()
                if not self.cache_manager.search_item(description):
                    unknown_item_names.add(description)

        if unknown_item_names:
            # Combine up to 10 unknown items into a single query to train the DB in one shot
            query_string = ", ".join(list(unknown_item_names)[:10])
            try:
                # Internally trigger the /categorypull functionality
                await self.category_pull_service.manual_category_pull(query_string, self.user_id)
                # Immediately rebuild the cache so Phase 2 can use the newly learned data
                self.cache_manager.rebuild_cache()
            except Exception as e:
                print(f"Auto-learning pre-flight failed: {e}")

        # =========================================================
        # PHASE 2: NORMAL TRANSACTION PROCESSING
        # =========================================================
        for tx in transactions_list:
            description = str(tx.item or "Item").title()
            amount = tx.amount if tx.amount else Decimal('0.00')

            if amount <= Decimal('0.00'):
                ignored.append(f"  {description} (Zero or missing amount)")
                continue

            if tx.future and tx.future.is_future:
                ignored.append(f"  {description} (Future item skipped)")
                continue

            if not tx.intent or tx.needs_clarification:
                ignored.append(f"  {description} (Needs Clarification)")
                continue

            intent = tx.intent.lower()
            category = tx.category
            subcategory = tx.subcategory

            # Search the freshly updated cache
            cached = self.cache_manager.search_item(description)

            # Core Taxonomy Resolution
            if cached and cached.get("category"):
                category = category or cached["category"]
                subcategory = subcategory or cached.get("subcategory")
            else:
                # ULTIMATE FALLBACK: If the LLM failed to include the exact word in the bulk pull
                category = category or "Groceries"
                subcategory = subcategory or "General Purchases"
                new_taxonomy_items.append({"category": category, "subcategory": subcategory, "item": description})

            source_acc = default_account['account_name'] if intent in ["expense", "transfer_other", "transfer_own"] else None
            dest_acc = default_account['account_name'] if intent in ["income", "transfer_own"] else None

            payload = {
                "user_id": self.user_id,
                "amount": str(amount),
                "txn_type": intent,
                "description": description,
                "intent": intent,
                "category": category,
                "subcategory": subcategory,
                "date": datetime.now(TZ_IST).isoformat(),
                "source_account": source_acc,
                "destination_account": dest_acc,
                "soft_deleted": False
            }

            is_salary_or_income = intent == "income" or (category and category.lower() == "income")
            is_duplicate = False if is_salary_or_income else self.dao.check_transaction_exists(str(amount), description, intent)

            if is_duplicate:
                pending_duplicates.append({
                    "payload": payload, "selected": False, "desc": description, "amount": str(amount), "txn_type": intent
                })
            else:
                unique_payloads.append(payload)
                cat_disp = f"{category} -> {subcategory}" if subcategory else category

                if intent in ["expense", "transfer_other"]:
                    totals["expenses"] += amount
                    counts["expenses"] += 1
                elif intent == "income":
                    totals["income"] += amount
                    counts["income"] += 1
                elif intent == "transfer_own":
                    totals["transfers"] += amount
                    counts["transfers"] += 1

                breakdown.append(f"  {description}:  {float(amount):,.2f} ({cat_disp})")

        # COMMIT ANY RESIDUAL UNKNOWN ITEMS DIRECTLY AS A SAFETY NET
        if new_taxonomy_items:
            await self.category_pull_service.bulk_add_items_to_taxonomy(new_taxonomy_items, self.user_id)

        return {
            "unique": unique_payloads,
            "duplicates": pending_duplicates,
            "totals": totals,
            "counts": counts,
            "breakdown": breakdown,
            "ignored": ignored
        }