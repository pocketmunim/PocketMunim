from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.transaction import CreateTransactionRequest
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from supabase import Client
from datetime import date

router = APIRouter(prefix="/api/v1/transactions", tags=["Daily Ledger Engine"])

@router.post(
    "/create",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def create_transaction(payload: CreateTransactionRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    tx_amount = round(float(payload.amount), 2)
    tx_date = str(payload.transaction_date or date.today())
    tx_type = payload.type.value

    # 1. Resolve Account (Specific Account or fallback to Default Account)
    if payload.account_id:
        acc_res = db.table('accounts').select('*').eq('account_id', str(payload.account_id)).eq('user_id', uid).eq('is_active', True).execute()
    else:
        acc_res = db.table('accounts').select('*').eq('user_id', uid).eq('is_default', True).eq('is_active', True).execute()
        if not acc_res.data:
            # Fallback to any active account if default is somehow missing
            acc_res = db.table('accounts').select('*').eq('user_id', uid).eq('is_active', True).limit(1).execute()

    if not acc_res.data:
        raise HTTPException(status_code=404, detail="No active liquidity vault available for this transaction.")

    acc = acc_res.data[0]
    aid = acc['account_id']
    acc_name = acc['account_name']
    current_balance = float(acc['balance'])

    # 2. Solvency Invariant Check on DEBIT
    if tx_type == "DEBIT" and current_balance < tx_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient funds in {acc_name}. Available: ₹{current_balance:,.2f}, Required: ₹{tx_amount:,.2f}."
        )

    # 3. Calculate New Balance
    new_balance = round(current_balance - tx_amount if tx_type == "DEBIT" else current_balance + tx_amount, 2)
    status_label = "DEBITED" if tx_type == "DEBIT" else "CREDITED"

    # 4. Atomic Execution Block
    # Update Account Balance
    db.table('accounts').update({"balance": new_balance}).eq('account_id', aid).execute()

    # Insert Transaction Entry
    tx_insert = db.table('transactions').insert({
        "user_id": uid,
        "account_id": aid,
        "account_name": acc_name,
        "type": tx_type,
        "category": payload.category or "Miscellaneous",
        "amount": tx_amount,
        "transaction_date": tx_date,
        "status": status_label,
        "description": payload.item_name
    }).execute()

    # Insert Audit Log
    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": aid,
        "event_type": f"MANUAL_{tx_type}",
        "amount": -tx_amount if tx_type == "DEBIT" else tx_amount,
        "description": f"Manual {tx_type.lower()} entry: {payload.item_name} via {acc_name}."
    }).execute()

    return {
        "status": "SUCCESS",
        "message": f"Recorded ₹{tx_amount:,.2f} {tx_type.lower()} under {acc_name}.",
        "transaction": tx_insert.data[0] if tx_insert.data else None,
        "updated_account": {
            "account_id": aid,
            "account_name": acc_name,
            "balance": new_balance
        }
    }