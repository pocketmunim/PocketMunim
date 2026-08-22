from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.transaction import CreateTransactionRequest
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from supabase import Client
from datetime import date, timedelta

router = APIRouter(prefix="/api/v1/transactions", tags=["Daily Ledger Engine"])


@router.post(
    "/create",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def create_transaction(payload: CreateTransactionRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    tx_amount = round(float(payload.amount), 2)
    tx_type = payload.type.value
    sanitized_item = payload.item_name.strip()

    today_utc = date.today()
    max_allowed_date = today_utc + timedelta(days=1)

    if payload.transaction_date:
        try:
            parsed_date = date.fromisoformat(payload.transaction_date)
        except ValueError:
            parsed_date = today_utc
    else:
        parsed_date = today_utc

    if parsed_date > max_allowed_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Future transactions cannot be logged directly. Selected date ({parsed_date}) is in the future."
        )

    # Deduplication Guard: Check if an identical item name, amount, and date already exists
    dup_check = db.table('transactions') \
        .select('transaction_id') \
        .eq('user_id', uid) \
        .ilike('description', sanitized_item) \
        .eq('amount', tx_amount) \
        .eq('transaction_date', str(parsed_date)) \
        .execute()

    if dup_check.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Duplicate entry detected! A transaction for '{sanitized_item}' with amount ₹{tx_amount:,.2f} is already recorded on {parsed_date}."
        )

    # 1. Resolve Target Account Vault
    if payload.account_id and str(payload.account_id).strip():
        acc_res = db.table('accounts').select('*').eq('account_id', str(payload.account_id).strip()).eq('user_id',
                                                                                                        uid).eq(
            'is_active', True).execute()
    else:
        acc_res = db.table('accounts').select('*').eq('user_id', uid).eq('is_default', True).eq('is_active',
                                                                                                True).execute()
        if not acc_res.data:
            acc_res = db.table('accounts').select('*').eq('user_id', uid).eq('is_active', True).limit(1).execute()

    if not acc_res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active account vault found. Please create an account vault first."
        )

    acc = acc_res.data[0]
    aid = acc['account_id']
    acc_name = acc['account_name']
    current_balance = float(acc['balance'])

    # 2. Solvency Guard
    if tx_type == "DEBIT" and current_balance < tx_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance in {acc_name}. Available: ₹{current_balance:,.2f}, Required: ₹{tx_amount:,.2f}."
        )

    # 3. Calculate Balance Mutation
    new_balance = round(current_balance - tx_amount if tx_type == "DEBIT" else current_balance + tx_amount, 2)
    status_label = "DEBITED" if tx_type == "DEBIT" else "CREDITED"

    # 4. Atomic Execution Block
    db.table('accounts').update({"balance": new_balance}).eq('account_id', aid).execute()

    tx_insert = db.table('transactions').insert({
        "user_id": uid,
        "account_id": aid,
        "account_name": acc_name,
        "type": tx_type,
        "category": payload.category or ("Miscellaneous" if tx_type == "DEBIT" else "Other Income"),
        "amount": tx_amount,
        "transaction_date": str(parsed_date),
        "status": status_label,
        "description": sanitized_item
    }).execute()

    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": aid,
        "event_type": f"MANUAL_{tx_type}",
        "amount": -tx_amount if tx_type == "DEBIT" else tx_amount,
        "description": f"Manual {tx_type.lower()} logged: '{sanitized_item}' on {acc_name} (New Balance: ₹{new_balance:,.2f})."
    }).execute()

    return {
        "status": "SUCCESS",
        "message": f"Successfully logged ₹{tx_amount:,.2f} on {acc_name}.",
        "transaction": tx_insert.data[0] if tx_insert.data else None,
        "updated_account": {
            "account_id": aid,
            "account_name": acc_name,
            "balance": new_balance
        }
    }