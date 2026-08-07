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
        # PHASE 1: PRE-FLIGHT AUTO-LEARNING
        # =========================================================
        unknown_item_names = set()
        for tx in transactions_list:
            amount = getattr(tx, 'amount', None) or Decimal('0.00')
            intent = (getattr(tx, 'intent', "") or "").lower()

            if intent == "expense" and amount > Decimal('0.00') and not getattr(tx, 'needs_clarification', False):
                tx_future = getattr(tx, 'future', None)
                if not (tx_future and getattr(tx_future, 'is_future', False)):

                    # SAFE FETCH: Fallback to tx.item if raw_description is missing
                    raw_desc = getattr(tx, 'raw_description', None) or getattr(tx, 'item', "Item")
                    raw_desc = str(raw_desc).title()

                    norm_item = getattr(tx, 'normalized_item', None) or raw_desc
                    norm_item = str(norm_item).title()

                    if not self.cache_manager.search_item(norm_item):
                        unknown_item_names.add(norm_item)

        if unknown_item_names:
            query_string = ", ".join(list(unknown_item_names)[:10])
            try:
                await self.category_pull_service.manual_category_pull(query_string, self.user_id)
                self.cache_manager.rebuild_cache()
            except Exception as e:
                print(f"Auto-learning pre-flight failed: {e}")

        # =========================================================
        # PHASE 2: NORMAL TRANSACTION PROCESSING
        # =========================================================
        for tx in transactions_list:
            raw_desc = getattr(tx, 'raw_description', None) or getattr(tx, 'item', "Item")
            description = str(raw_desc).title()

            norm_val = getattr(tx, 'normalized_item', None) or description
            norm_item = str(norm_val).title()

            amount = getattr(tx, 'amount', None) or Decimal('0.00')

            if amount <= Decimal('0.00'):
                ignored.append(f"  {description} (Zero or missing amount)")
                continue

            tx_future = getattr(tx, 'future', None)
            if tx_future and getattr(tx_future, 'is_future', False):
                ignored.append(f"  {description} (Future item skipped)")
                continue

            if not getattr(tx, 'intent', None) or getattr(tx, 'needs_clarification', False):
                ignored.append(f"  {description} (Needs Clarification)")
                continue

            intent = getattr(tx, 'intent', "").lower()
            category = getattr(tx, 'category', None)
            subcategory = getattr(tx, 'subcategory', None)

            cached = self.cache_manager.search_item(norm_item)

            if intent == "expense":
                if not category or not subcategory:
                    if cached and cached.get("category"):
                        category = category or cached["category"]
                        subcategory = subcategory or cached.get("subcategory")
                    else:
                        category = category or "Groceries"
                        subcategory = subcategory or "General Purchases"
                        new_taxonomy_items.append({"category": category, "subcategory": subcategory, "item": norm_item})
                else:
                    if not cached:
                        new_taxonomy_items.append({"category": category, "subcategory": subcategory, "item": norm_item})
            else:
                if not category:
                    category = "Income" if intent == "income" else "Transfer"
                if not subcategory:
                    subcategory = "General"
                norm_item = None

            source_acc = default_account['account_name'] if intent in ["expense", "transfer_other",
                                                                       "transfer_own"] else None
            dest_acc = default_account['account_name'] if intent in ["income", "transfer_own"] else None

            payload = {
                "user_id": self.user_id,
                "amount": str(amount),
                "txn_type": intent,
                "description": description,
                "normalized_item": norm_item,
                "intent": intent,
                "category": category,
                "subcategory": subcategory,
                "date": datetime.now(TZ_IST).isoformat(),
                "source_account": source_acc,
                "destination_account": dest_acc,
                "soft_deleted": False
            }

            is_salary_or_income = intent == "income" or (category and category.lower() == "income")
            is_duplicate = False if is_salary_or_income else self.dao.check_transaction_exists(str(amount), description,
                                                                                               intent)

            if is_duplicate:
                pending_duplicates.append({
                    "payload": payload, "selected": False, "desc": description, "amount": str(amount),
                    "txn_type": intent
                })
            else:
                unique_payloads.append(payload)
                cat_disp = f"{category} -> {subcategory}" if subcategory else category
                if intent in ["expense", "transfer_other"]:
                    totals["expenses"] += amount
                elif intent == "income":
                    totals["income"] += amount
                elif intent == "transfer_own":
                    totals["transfers"] += amount
                breakdown.append(f"  {description}:  {float(amount):,.2f} ({cat_disp})")

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