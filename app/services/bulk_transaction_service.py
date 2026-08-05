from decimal import Decimal
from datetime import datetime


class BulkTransactionService:
    def __init__(self, db_client, user_id: str, cache_manager, category_pull_service):
        self.db = db_client
        self.user_id = user_id
        from app.dao.bulk_transaction_dao import BulkTransactionDAO
        self.dao = BulkTransactionDAO(self.db, self.user_id)
        self.cache_manager = cache_manager
        self.category_pull_service = category_pull_service

    def process_bulk_payload(self, transactions_list: list, default_account: dict) -> dict:
        unique_payloads = []
        pending_duplicates = []
        breakdown = []
        ignored = []

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

        for tx in transactions_list:
            description = str(tx.item or tx.merchant or "Item").title()
            amount = tx.amount if tx.amount else Decimal('0.00')

            # Capture Ignored Items precisely
            if amount <= Decimal('0.00'):
                ignored.append(f"• {description} (Zero or missing amount)")
                continue

            if tx.future and tx.future.is_future:
                ignored.append(f"• {description} (Future/Planned item skipped)")
                continue

            if not tx.intent or tx.needs_clarification:
                missing = ", ".join(tx.clarification_fields) if tx.clarification_fields else "Intent"
                ignored.append(f"• {description} (Needs Clarification: {missing})")
                continue

            intent = tx.intent.lower()
            category = tx.category
            subcategory = tx.subcategory

            # Category Resolution
            if not category:
                cached = self.cache_manager.search_item(description)
                if cached and cached.get("category"):
                    category, subcategory = cached["category"], cached.get("subcategory")
                else:
                    ai_cls = self.category_pull_service.classify_item(description, intent=intent)
                    category, subcategory = ai_cls.get("category", "Expenses"), ai_cls.get("subcategory", "General")
                    try:
                        self.category_pull_service.add_single_item_to_taxonomy(category, subcategory, description,
                                                                               self.user_id)
                        self.cache_manager.rebuild_cache()
                    except Exception:
                        pass

            source_acc = default_account['account_name'] if intent in ["expense", "transfer_other",
                                                                       "transfer_own"] else None
            dest_acc = default_account['account_name'] if intent in ["income", "transfer_own"] else None

            payload = {
                "user_id": self.user_id, "amount": float(amount), "txn_type": intent,
                "description": description, "intent": intent, "category": category,
                "subcategory": subcategory, "date": datetime.now().isoformat(),
                "source_account": source_acc, "destination_account": dest_acc, "soft_deleted": False
            }

            # Selective Duplication Filter: Ignore Salaries/Income
            is_salary_or_income = intent == "income" or (category and category.lower() == "income")
            is_duplicate = False if is_salary_or_income else self.dao.check_transaction_exists(float(amount),
                                                                                               description, intent)

            if is_duplicate:
                pending_duplicates.append({
                    "payload": payload, "selected": False, "desc": description, "amount": float(amount),
                    "txn_type": intent
                })
            else:
                unique_payloads.append(payload)
                cat_disp = f"{category} -> {subcategory}" if subcategory else category

                # Tabulate Totals & Counts
                if intent == "expense" or intent == "transfer_other":
                    totals["expenses"] += amount
                    counts["expenses"] += 1
                    breakdown.append(f"🔴 {description}: ₹{float(amount):,.2f} ({cat_disp})")
                elif intent == "income":
                    totals["income"] += amount
                    counts["income"] += 1
                    breakdown.append(f"🟢 {description}: ₹{float(amount):,.2f} ({cat_disp})")
                elif intent == "transfer_own":
                    totals["transfers"] += amount
                    counts["transfers"] += 1
                    breakdown.append(f"🔵 {description}: ₹{float(amount):,.2f} ({cat_disp})")

        return {
            "unique": unique_payloads,
            "duplicates": pending_duplicates,
            "totals": totals,
            "counts": counts,
            "breakdown": breakdown,
            "ignored": ignored
        }