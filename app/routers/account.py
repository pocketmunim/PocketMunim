from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.account import (
    CreateAccountRequest,
    SetDefaultAccountRequest,
    AccountListResponse,
    AccountItem
)
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from supabase import Client

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

    # If this is marked default, unset existing default accounts for this user
    if payload.is_default:
        db.table('accounts').update({"is_default": False}).eq('user_id', uid).execute()
    else:
        # If user has no existing accounts, force this first one to be default
        existing = db.table('accounts').select('account_id').eq('user_id', uid).eq('is_active', True).execute()
        if not existing.data:
            payload.is_default = True

    # 1. Insert new account
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

    # 2. Add audit log
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

    # 1. Verify account belongs to user
    verify_acc = db.table('accounts').select('*').eq('account_id', target_aid).eq('user_id', uid).execute()
    if not verify_acc.data:
        raise HTTPException(status_code=404, detail="Account not found.")

    # 2. Reset all user accounts to is_default = False
    db.table('accounts').update({"is_default": False}).eq('user_id', uid).execute()

    # 3. Set the target account as default
    db.table('accounts').update({"is_default": True}).eq('account_id', target_aid).execute()

    # 4. Point upcoming scheduled salaries to this new default account
    db.table('salaries').update({"account_id": target_aid}).eq('user_id', uid).eq('status', 'SCHEDULED').execute()

    # 5. Audit log
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