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

class FutureSchema(BaseModel):
    is_future: Optional[bool] = False

class TransactionItem(BaseModel):
    intent: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = "INR"
    item: Optional[str] = None
    raw_description: Optional[str] = None
    normalized_item: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    counterparty: Optional[str] = None
    source_account: Optional[str] = None
    destination_account: Optional[str] = None
    payment_method: Optional[str] = None
    transaction_reference: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    date: Optional[DateSchema] = None
    future: Optional[FutureSchema] = None
    needs_clarification: Optional[bool] = False
    clarification_fields: Optional[List[str]] = []

class AITransactionExtraction(BaseModel):
    metadata: Optional[MetadataSchema] = None
    transactions: Optional[List[TransactionItem]] = []
