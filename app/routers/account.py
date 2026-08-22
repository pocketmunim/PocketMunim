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
    transfer_amount = float(payload.amount)

    # 1. Validation Checks
    if src_id == dest_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and destination accounts must be distinct vaults."
        )

    # Fetch Source Account
    src_res = db.table('accounts').select('*').eq('account_id', src_id).eq('user_id', uid).eq('is_active',
                                                                                              True).execute()
    if not src_res.data:
        raise HTTPException(status_code=404, detail="Source vault not found or inactive.")
    src_acc = src_res.data[0]
    src_bal = float(src_acc['balance'])

    # Fetch Destination Account
    dest_res = db.table('accounts').select('*').eq('account_id', dest_id).eq('user_id', uid).eq('is_active',
                                                                                                True).execute()
    if not dest_res.data:
        raise HTTPException(status_code=404, detail="Destination vault not found or inactive.")
    dest_acc = dest_res.data[0]
    dest_bal = float(dest_acc['balance'])

    # 2. Solvency / Liquidity Invariant Check
    if src_bal < transfer_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient funds in {src_acc['account_name']}. Available: ₹{src_bal:,.2f}, Requested: ₹{transfer_amount:,.2f}."
        )

    # 3. Double-Entry Balance Execution
    new_src_bal = src_bal - transfer_amount
    new_dest_bal = dest_bal + transfer_amount

    db.table('accounts').update({"balance": new_src_bal}).eq('account_id', src_id).execute()
    db.table('accounts').update({"balance": new_dest_bal}).eq('account_id', dest_id).execute()

    today_str = str(date.today())

    # 4. Paired Transaction Ledger Entries
    # Source Outflow Entry
    db.table('transactions').insert({
        "user_id": uid,
        "account_id": src_id,
        "type": "DEBIT",
        "category": "Vault Transfer",
        "amount": transfer_amount,
        "transaction_date": today_str,
        "status": "DEBITED",
        "description": f"Transfer Out to {dest_acc['account_name']}"
    }).execute()

    # Destination Inflow Entry
    db.table('transactions').insert({
        "user_id": uid,
        "account_id": dest_id,
        "type": "CREDIT",
        "category": "Vault Transfer",
        "amount": transfer_amount,
        "transaction_date": today_str,
        "status": "CREDITED",
        "description": f"Transfer In from {src_acc['account_name']}"
    }).execute()

    # 5. Dual Audit Logs
    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": src_id,
        "event_type": "VAULT_TRANSFER_OUT",
        "amount": -transfer_amount,
        "description": f"Transferred ₹{transfer_amount:,.2f} to {dest_acc['account_name']}."
    }).execute()

    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": dest_id,
        "event_type": "VAULT_TRANSFER_IN",
        "amount": transfer_amount,
        "description": f"Received ₹{transfer_amount:,.2f} from {src_acc['account_name']}."
    }).execute()

    return {
        "status": "SUCCESS",
        "message": f"Successfully transferred ₹{transfer_amount:,.2f} from {src_acc['account_name']} to {dest_acc['account_name']}.",
        "source_balance": new_src_bal,
        "destination_balance": new_dest_bal
    }