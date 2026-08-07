from pydantic import BaseModel
from decimal import Decimal


class MetadataSchema(BaseModel):
    operation_type: str | None = None
    bulk_operation: bool | None = None


class DateSchema(BaseModel):
    relative_date: str | None = None


class RecurrenceSchema(BaseModel):
    enabled: bool | None = None
    frequency: str | None = None
    start_date: str | None = None


class FutureSchema(BaseModel):
    is_future: bool | None = None


class TransactionItem(BaseModel):
    intent: str | None = None
    amount: Decimal | None = None

    # BACKWARD COMPATIBILITY: Restored so old code/cached memory doesn't crash
    item: str | None = None

    # NEW: Dual-Extraction fields
    raw_description: str | None = None
    normalized_item: str | None = None

    category: str | None = None
    subcategory: str | None = None
    source_account: str | None = None
    destination_account: str | None = None
    date: DateSchema | None = None
    recurrence: RecurrenceSchema | None = None
    future: FutureSchema | None = None
    needs_clarification: bool | None = None
    clarification_fields: list[str] | None = None


class AITransactionExtraction(BaseModel):
    metadata: MetadataSchema | None = None
    transactions: list[TransactionItem] | None = None