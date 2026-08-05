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

        totals = {
            "expenses": Decimal('0.00'),
            "income": Decimal('0.00'),
            "transfers": Decimal('0.00')
        }

        for tx in transactions_list:
            amount = tx.amount if tx.amount else Decimal('0.00')
            if amount <= Decimal('0.00'):
                continue

            description = str(tx.item or tx.merchant or "Item").title()
            intent = tx.intent or "expense"

            category = tx.category
            subcategory = tx.subcategory
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
                if intent == "expense" or intent == "transfer_other":
                    totals["expenses"] += amount
                elif intent == "income":
                    totals["income"] += amount
                elif intent == "transfer_own":
                    totals["transfers"] += amount

                cat_disp = f"{category} -> {subcategory}" if subcategory else category
                breakdown.append(f"• {description}: ₹{float(amount):,.2f} ({cat_disp})")

        return {
            "unique": unique_payloads,
            "duplicates": pending_duplicates,
            "totals": totals,
            "breakdown": breakdown
        }