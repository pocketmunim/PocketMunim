from pydantic import BaseModel
from typing import Optional, List, Any
from decimal import Decimal


class MetadataSchema(BaseModel):
    operation_type: Optional[str] = None
    bulk_operation: Optional[bool] = None


class DateSchema(BaseModel):
    date: Optional[str] = None
    original_expression: Optional[str] = None
    is_relative: Optional[bool] = None
    relative_date: Optional[str] = None  # Retained for legacy fallback


class RecurrenceSchema(BaseModel):
    enabled: Optional[bool] = False
    frequency: Optional[str] = None
    interval: Optional[int] = None
    day_of_month: Optional[int] = None
    day_of_week: Optional[int] = None
    start_date: Optional[str] = None


class FutureSchema(BaseModel):
    is_future: Optional[bool] = False


class LoanSchema(BaseModel):
    lender: Optional[str] = None
    principal: Optional[Decimal] = None
    interest_rate: Optional[Decimal] = None
    tenure_value: Optional[int] = None
    tenure_unit: Optional[str] = None
    emi: Optional[Decimal] = None


class SplitSchema(BaseModel):
    enabled: Optional[bool] = False
    participants: Optional[int] = None
    equal: Optional[bool] = None
    percentage: Optional[List[Decimal]] = None
    shares: Optional[List[Decimal]] = None


class InvestmentSchema(BaseModel):
    type: Optional[str] = None
    action: Optional[str] = None
    instrument: Optional[str] = None


class TaxSchema(BaseModel):
    type: Optional[str] = None
    action: Optional[str] = None
    amount: Optional[Decimal] = None


class SubscriptionSchema(BaseModel):
    service: Optional[str] = None
    action: Optional[str] = None


class EditTargetSchema(BaseModel):
    field: Optional[str] = None
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None


class TransactionTargetSchema(BaseModel):
    item: Optional[str] = None
    date: Optional[str] = None
    position: Optional[str] = None
    reference: Optional[str] = None


class TransactionItem(BaseModel):
    intent: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = "INR"

    # Dual-Extraction
    item: Optional[str] = None  # Legacy
    raw_description: Optional[str] = None
    normalized_item: Optional[str] = None

    # Financial Attributes
    category: Optional[str] = None
    subcategory: Optional[str] = None
    counterparty: Optional[str] = None
    source_account: Optional[str] = None
    destination_account: Optional[str] = None
    payment_method: Optional[str] = None
    transaction_reference: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None

    # Complex Nested Objects
    date: Optional[DateSchema] = None
    recurrence: Optional[RecurrenceSchema] = None
    loan: Optional[LoanSchema] = None
    split: Optional[SplitSchema] = None
    investment: Optional[InvestmentSchema] = None
    tax: Optional[TaxSchema] = None
    subscription: Optional[SubscriptionSchema] = None
    edit_target: Optional[EditTargetSchema] = None
    transaction_target: Optional[TransactionTargetSchema] = None
    future: Optional[FutureSchema] = None

    # Edge Cases
    query_type: Optional[str] = None
    needs_clarification: Optional[bool] = False
    clarification_fields: Optional[List[str]] = []


class AITransactionExtraction(BaseModel):
    metadata: Optional[MetadataSchema] = None
    transactions: Optional[List[TransactionItem]] = []