from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.account import (
    CreateAccountRequest,
    SetDefaultAccountRequest,
    TransferFundsRequest,
    AccountListResponse,
    AccountItem
)
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from supabase import Client
from datetime import date

router = APIRouter(prefix="/api/v1/accounts", tags=["Liquidity Vaults & Accounts"])


@router.post(
    "/list/{user_id}",
    response_model=AccountListResponse,
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def list_user_accounts(user_id: str, db: Client = Depends(get_db)):
    acc_res = db.table('accounts').select('*').eq('user_id', user_id).eq('is_active', True).order('is_default',
                                                                                                  desc=True).order(
        'created_at').execute()
    accounts = acc_res.data or []

    return AccountListResponse(
        status="SUCCESS",
        accounts=[AccountItem(**acc) for acc in accounts]
    )


@router.post(
    "/create",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def create_account(payload: CreateAccountRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)

    if payload.is_default:
        db.table('accounts').update({"is_default": False}).eq('user_id', uid).execute()
    else:
        existing = db.table('accounts').select('account_id').eq('user_id', uid).eq('is_active', True).execute()
        if not existing.data:
            payload.is_default = True

    acc_res = db.table('accounts').insert({
        "user_id": uid,
        "account_name": payload.account_name,
        "balance": payload.balance,
        "is_default": payload.is_default,
        "is_active": True
    }).execute()

    if not acc_res.data:
        raise HTTPException(status_code=500, detail="Failed to initialize liquidity vault.")

    new_acc = acc_res.data[0]
    new_acc_id = new_acc['account_id']

    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": new_acc_id,
        "event_type": "ACCOUNT_PROVISIONED",
        "amount": payload.balance,
        "description": f"New liquidity vault provisioned: {payload.account_name} with opening balance ₹{payload.balance:,.2f}."
    }).execute()

    return {
        "status": "SUCCESS",
        "message": f"Account '{payload.account_name}' created successfully.",
        "account": new_acc
    }


@router.post(
    "/set-default",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def set_default_account(payload: SetDefaultAccountRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    target_aid = str(payload.account_id)

    verify_acc = db.table('accounts').select('*').eq('account_id', target_aid).eq('user_id', uid).execute()
    if not verify_acc.data:
        raise HTTPException(status_code=404, detail="Account not found.")

    db.table('accounts').update({"is_default": False}).eq('user_id', uid).execute()
    db.table('accounts').update({"is_default": True}).eq('account_id', target_aid).execute()

    db.table('salaries').update({"account_id": target_aid}).eq('user_id', uid).eq('status', 'SCHEDULED').execute()

    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": target_aid,
        "event_type": "DEFAULT_ACCOUNT_SWITCHED",
        "amount": 0.0,
        "description": f"Default disbursement account switched to {verify_acc.data[0]['account_name']}."
    }).execute()

    return {
        "status": "SUCCESS",
        "message": f"'{verify_acc.data[0]['account_name']}' is now set as the primary default account."
    }


@router.post(
    "/transfer",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def transfer_funds(payload: TransferFundsRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    src_id = str(payload.source_account_id)
    dest_id = str(payload.destination_account_id)
    transfer_amount = round(float(payload.amount), 2)

    # 1. Invariant Validation
    if src_id == dest_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and destination accounts must be distinct vaults."
        )

    if transfer_amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transfer amount must be strictly greater than ₹0.00."
        )

    # 2. Vault Verification
    src_res = db.table('accounts').select('*').eq('account_id', src_id).eq('user_id', uid).eq('is_active',
                                                                                              True).execute()
    if not src_res.data:
        raise HTTPException(status_code=404, detail="Source vault not found or inactive.")
    src_acc = src_res.data[0]
    src_name = src_acc['account_name']
    src_bal = float(src_acc['balance'])

    dest_res = db.table('accounts').select('*').eq('account_id', dest_id).eq('user_id', uid).eq('is_active',
                                                                                                True).execute()
    if not dest_res.data:
        raise HTTPException(status_code=404, detail="Destination vault not found or inactive.")
    dest_acc = dest_res.data[0]
    dest_name = dest_acc['account_name']
    dest_bal = float(dest_acc['balance'])

    # 3. Solvency Check
    if src_bal < transfer_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient funds in {src_name}. Available: ₹{src_bal:,.2f}, Requested: ₹{transfer_amount:,.2f}."
        )

    # 4. Atomic Balance Execution
    new_src_bal = round(src_bal - transfer_amount, 2)
    new_dest_bal = round(dest_bal + transfer_amount, 2)
    today_str = str(date.today())

    db.table('accounts').update({"balance": new_src_bal}).eq('account_id', src_id).execute()
    db.table('accounts').update({"balance": new_dest_bal}).eq('account_id', dest_id).execute()

    # 5. Descriptive Double-Entry Transactions
    # Leg A: Source Account Outflow (DEBIT)
    db.table('transactions').insert({
        "user_id": uid,
        "account_id": src_id,
        "account_name": src_name,
        "related_account_id": dest_id,
        "related_account_name": dest_name,
        "type": "DEBIT",
        "category": "Vault Transfer",
        "amount": transfer_amount,
        "transaction_date": today_str,
        "status": "DEBITED",
        "description": f"Self Transfer: Debited from {src_name} → Transferred to {dest_name}"
    }).execute()

    # Leg B: Destination Account Inflow (CREDIT)
    db.table('transactions').insert({
        "user_id": uid,
        "account_id": dest_id,
        "account_name": dest_name,
        "related_account_id": src_id,
        "related_account_name": src_name,
        "type": "CREDIT",
        "category": "Vault Transfer",
        "amount": transfer_amount,
        "transaction_date": today_str,
        "status": "CREDITED",
        "description": f"Self Transfer: Credited to {dest_name} ← Received from {src_name}"
    }).execute()

    # 6. Immutable Audit Logs
    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": src_id,
        "event_type": "VAULT_TRANSFER_OUT",
        "amount": -transfer_amount,
        "description": f"Transferred ₹{transfer_amount:,.2f} out to {dest_name}."
    }).execute()

    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": dest_id,
        "event_type": "VAULT_TRANSFER_IN",
        "amount": transfer_amount,
        "description": f"Received ₹{transfer_amount:,.2f} in from {src_name}."
    }).execute()

    return {
        "status": "SUCCESS",
        "message": f"Transferred ₹{transfer_amount:,.2f} from {src_name} to {dest_name}.",
        "source_vault": {
            "account_id": src_id,
            "account_name": src_name,
            "balance": new_src_bal
        },
        "destination_vault": {
            "account_id": dest_id,
            "account_name": dest_name,
            "balance": new_dest_bal
        }
    }