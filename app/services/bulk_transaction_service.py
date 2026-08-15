import json
from decimal import Decimal
from datetime import datetime
from app.utils.constants import TZ_IST


def _safely_serialize_complex(val):
    if not val:
        return None
    if hasattr(val, 'model_dump_json'):
        return json.loads(val.model_dump_json(exclude_none=True))
    elif hasattr(val, 'json'):
        return json.loads(val.json(exclude_none=True))
    return None


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
        taxonomy_err = None
        totals = {
            "expenses": Decimal('0.00'),
            "income": Decimal('0.00'),
            "transfers": Decimal('0.00')
        }
        unknown_item_names = set()

        for tx in transactions_list:
            amount = getattr(tx, 'amount', None) or Decimal('0.00')
            intent = (getattr(tx, 'intent', "") or "").lower()

            if intent == "expense" and amount > Decimal('0.00') and not getattr(tx, 'needs_clarification', False):
                tx_future = getattr(tx, 'future', None)
                if not (tx_future and getattr(tx_future, 'is_future', False)):
                    raw_desc = getattr(tx, 'raw_description', None) or getattr(tx, 'item', "Item")
                    norm_item = getattr(tx, 'normalized_item', None) or str(raw_desc).title()
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

        # Baseline timestamp for processing relative dates
        current_dt = datetime.now(TZ_IST)

        for tx in transactions_list:
            raw_desc = getattr(tx, 'raw_description', None) or getattr(tx, 'item', "Item")
            description = str(raw_desc).title()
            norm_val = getattr(tx, 'normalized_item', None) or description
            norm_item = str(norm_val).title()
            amount = getattr(tx, 'amount', None) or Decimal('0.00')

            if amount <= Decimal('0.00'):
                ignored.append(f"• {description} (Zero or missing amount)")
                continue

            tx_future = getattr(tx, 'future', None)
            if tx_future and getattr(tx_future, 'is_future', False):
                ignored.append(f"• {description} (Future item skipped)")
                continue

            if not getattr(tx, 'intent', None) or getattr(tx, 'needs_clarification', False):
                ignored.append(f"• {description} (Needs Clarification)")
                continue

            # --- DATE RESOLUTION LOGIC ---
            tx_date_obj = getattr(tx, 'date', None)
            final_date_iso = current_dt.isoformat()
            if tx_date_obj and getattr(tx_date_obj, 'date', None):
                try:
                    parsed_date = datetime.strptime(tx_date_obj.date, "%Y-%m-%d").date()
                    final_date_iso = current_dt.replace(year=parsed_date.year, month=parsed_date.month,
                                                        day=parsed_date.day).isoformat()
                except ValueError:
                    pass

            intent = getattr(tx, 'intent', "").lower()

            cached = self.cache_manager.search_item(norm_item)
            category = None
            subcategory = None
            is_credit = intent in ["income", "borrow"]

            # EXACT TAXONOMY LOOP FOR ARRAYS
            if cached:
                category = cached.get("category")
                subcategory = cached.get("subcategory")
            else:
                primary_cat = getattr(tx, 'category', None)
                primary_sub = getattr(tx, 'subcategory', None)

                if primary_cat and primary_sub and primary_cat.lower() != primary_sub.lower() and primary_cat.lower() not in [
                    "general", "miscellaneous", "unclassified", "uncategorized"]:
                    category = primary_cat
                    subcategory = primary_sub
                else:
                    ai_class = await self.category_pull_service.classify_item(norm_item, intent)
                    category = ai_class.get("category")
                    subcategory = ai_class.get("subcategory")

                if not category or category.lower() in ["general", "miscellaneous", "unclassified", "uncategorized"]:
                    category = "Income" if is_credit else "Expense"

                if not subcategory or subcategory.lower() in ["general", "miscellaneous", "unclassified",
                                                              "uncategorized"] or subcategory.lower() == category.lower():
                    subcategory = f"{category} Specifics"

                new_taxonomy_items.append({"category": category, "subcategory": subcategory, "item": norm_item})

            is_debit = intent in ["expense", "transfer_other", "transfer_own", "loan_payment", "lend"]

            if intent == "loan_repayment":
                loan_rep = getattr(tx, 'loan_repayment', None)
                direction = getattr(loan_rep, 'direction', None) if loan_rep else None
                if direction == "paid":
                    is_debit = True
                else:
                    is_credit = True

            source_acc = default_account['account_name'] if is_debit else None
            dest_acc = default_account['account_name'] if is_credit else None

            extended_data = {}
            for complex_key in ['loan', 'loan_repayment', 'split', 'investment', 'tax', 'subscription', 'future',
                                'recurrence']:
                val = getattr(tx, complex_key, None)
                serialized = _safely_serialize_complex(val)
                if serialized:
                    extended_data[complex_key] = serialized

            quantity_val = getattr(tx, 'quantity', None)

            payload = {
                "user_id": self.user_id,
                "amount": str(amount),
                "txn_type": intent,
                "description": description,
                "normalized_item": norm_item,
                "intent": intent,
                "category": category,
                "subcategory": subcategory,
                "date": final_date_iso,
                "source_account": source_acc,
                "destination_account": dest_acc,
                "soft_deleted": False,
                "currency": getattr(tx, 'currency', 'INR') or 'INR',
                "quantity": str(quantity_val) if quantity_val is not None else None,
                "unit": getattr(tx, 'unit', None),
                "counterparty": getattr(tx, 'counterparty', None),
                "payment_method": getattr(tx, 'payment_method', None),
                "transaction_reference": getattr(tx, 'transaction_reference', None),
                "extended_data": extended_data
            }

            is_salary_or_income = intent == "income" or (category and category.lower() == "income")

            # Use Date-Bound Composite Checking Logic
            is_duplicate = False if is_salary_or_income else self.dao.check_transaction_exists(str(amount), norm_item,
                                                                                               intent, final_date_iso)

            if is_duplicate:
                pending_duplicates.append({
                    "payload": payload, "selected": False, "desc": description, "amount": str(amount),
                    "txn_type": intent
                })
            else:
                unique_payloads.append(payload)
                cat_disp = f"{category.title()} -> {subcategory.title()}" if category and subcategory and category.lower() != subcategory.lower() else (
                    category.title() if category else "Uncategorized")

                if is_debit and not is_credit:
                    totals["expenses"] += amount
                elif is_credit and not is_debit:
                    totals["income"] += amount
                elif is_debit and is_credit:
                    totals["transfers"] += amount

                breakdown.append(f"• {description}: ₹{float(amount):,.2f} ({cat_disp})")

        if new_taxonomy_items:
            taxonomy_err = await self.category_pull_service.bulk_add_items_to_taxonomy(new_taxonomy_items, self.user_id)

        return {
            "unique": unique_payloads,
            "duplicates": pending_duplicates,
            "totals": totals,
            "breakdown": breakdown,
            "ignored": ignored,
            "taxonomy_error": taxonomy_err
        }