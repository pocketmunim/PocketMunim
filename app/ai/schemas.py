from pydantic import BaseModel
from decimal import Decimal


class MetadataSchema(BaseModel):
    raw_user_text: str | None = None
    operation_type: str | None = None
    language: str | None = None
    entry_source: str | None = None
    bulk_operation: bool | None = None
    category_lookup_required: bool | None = None
    unsupported_chat: bool | None = None
    account_required: bool | None = None


class DateSchema(BaseModel):
    raw_expression: str | None = None
    relative_date: str | None = None
    date_type: str | None = None


class FutureSchema(BaseModel):
    is_future: bool | None = None
    budget_check_required: bool | None = None
    should_save: bool | None = None


class ValidationSchema(BaseModel):
    amount_valid: bool | None = None
    date_valid: bool | None = None
    item_valid: bool | None = None
    account_valid: bool | None = None


class DuplicateDetectionSchema(BaseModel):
    possible_duplicate: bool | None = None
    duplicate_reference: str | None = None


class ConfidenceSchema(BaseModel):
    intent_confidence: float | None = None
    amount_confidence: float | None = None
    date_confidence: float | None = None
    account_confidence: float | None = None
    overall_confidence: float | None = None


class RecurrenceSchema(BaseModel):
    enabled: bool | None = None
    frequency: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class TransactionItem(BaseModel):
    client_transaction_id: str | None = None
    transaction_sequence: int | None = None
    execution_order: int | None = None
    intent: str | None = None
    amount: Decimal | None = None
    original_currency: str | None = None
    normalized_currency: str | None = None
    merchant: str | None = None
    payment_method: str | None = None
    item: str | None = None
    quantity: float | None = None
    unit: str | None = None
    category: str | None = None
    subcategory: str | None = None
    matched_from: str | None = None
    source_account: str | None = None
    destination_account: str | None = None
    date: DateSchema | None = None
    recurrence: RecurrenceSchema | None = None
    future: FutureSchema | None = None
    validation: ValidationSchema | None = None
    duplicate_detection: DuplicateDetectionSchema | None = None
    needs_clarification: bool | None = None

    # Python 3.14 Native List Syntax
    clarification_fields: list[str] | None = None
    confidence: ConfidenceSchema | None = None


class QuerySchema(BaseModel):
    is_query: bool | None = None
    query_type: str | None = None
    target: str | None = None


class LoanSchema(BaseModel):
    intent: str | None = None
    lender: str | None = None
    amount: Decimal | None = None


class SalarySchema(BaseModel):
    intent: str | None = None
    month: str | None = None
    amount: Decimal | None = None


class AccountSchema(BaseModel):
    intent: str | None = None
    account_name: str | None = None
    account_type: str | None = None


class DeleteSchema(BaseModel):
    intent: str | None = None
    selection_mode: str | None = None
    target_date: str | None = None


class ReportSchema(BaseModel):
    intent: str | None = None
    format: str | None = None
    period: str | None = None


class AITransactionExtraction(BaseModel):
    metadata: MetadataSchema | None = None

    # Python 3.14 Native List Syntax (No quotes needed because TransactionItem is defined above)
    transactions: list[TransactionItem] | None = None

    query: QuerySchema | None = None
    loan: LoanSchema | None = None
    salary: SalarySchema | None = None
    account: AccountSchema | None = None
    delete: DeleteSchema | None = None
    report: ReportSchema | None = None