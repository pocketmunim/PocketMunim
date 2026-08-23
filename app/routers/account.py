from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.account import (
    CreateAccountRequest,
    SetDefaultAccountRequest,
    TransferFundsRequest,
    AccountListResponse,
    AccountItem,
)
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from supabase import Client

router = APIRouter(prefix="/api/v1/accounts", tags=["Liquidity Vaults & Accounts"])


@router.post(
    "/list/{user_id}",
    response_model=AccountListResponse,
    dependencies=[Depends(verify_zero_trust_signature)],
)
async def list_user_accounts(user_id: str, db: Client = Depends(get_db)):
    acc_res = (
        db.table("accounts")
        .select("*")
        .eq("user_id", str(user_id))
        .eq("is_active", True)
        .order("is_default", desc=True)
        .order("created_at")
        .execute()
    )
    accounts = acc_res.data or []
    return AccountListResponse(
        status="SUCCESS",
        accounts=[AccountItem(**acc) for acc in accounts],
    )


@router.post(
    "/create",
    dependencies=[Depends(verify_zero_trust_signature)],
)
async def create_account(payload: CreateAccountRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    sanitized_name = payload.account_name.strip().upper()

    existing_acc = (
        db.table("accounts")
        .select("account_id")
        .eq("user_id", uid)
        .ilike("account_name", sanitized_name)
        .execute()
    )
    if existing_acc.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An account vault named '{sanitized_name}' already exists. Please use a unique name.",
        )

    if payload.is_default:
        db.table("accounts").update({"is_default": False}).eq("user_id", uid).execute()
    else:
        existing = (
            db.table("accounts")
            .select("account_id")
            .eq("user_id", uid)
            .eq("is_active", True)
            .execute()
        )
        if not existing.data:
            payload.is_default = True

    acc_res = (
        db.table("accounts")
        .insert({
            "user_id": uid,
            "account_name": sanitized_name,
            "balance": payload.balance,
            "is_default": payload.is_default,
            "is_active": True,
        })
        .execute()
    )

    if not acc_res.data:
        raise HTTPException(status_code=500, detail="Failed to initialize liquidity vault.")

    new_acc = acc_res.data[0]
    db.table("account_logs").insert({
        "user_id": uid,
        "account_id": new_acc["account_id"],
        "event_type": "ACCOUNT_PROVISIONED",
        "amount": payload.balance,
        "description": f"New liquidity vault provisioned: {sanitized_name} with opening balance ₹{payload.balance:,.2f}.",
    }).execute()

    return {
        "status": "SUCCESS",
        "message": f"Account '{sanitized_name}' created successfully.",
        "account": new_acc,
    }


@router.post(
    "/set-default",
    dependencies=[Depends(verify_zero_trust_signature)],
)
async def set_default_account(payload: SetDefaultAccountRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    target_aid = str(payload.account_id)

    verify_acc = (
        db.table("accounts")
        .select("*")
        .eq("account_id", target_aid)
        .eq("user_id", uid)
        .execute()
    )
    if not verify_acc.data:
        raise HTTPException(status_code=404, detail="Account not found.")

    db.table("accounts").update({"is_default": False}).eq("user_id", uid).execute()
    db.table("accounts").update({"is_default": True}).eq("account_id", target_aid).execute()
    db.table("salaries").update({"account_id": target_aid}).eq("user_id", uid).eq("status", "SCHEDULED").execute()

    return {
        "status": "SUCCESS",
        "message": f"'{verify_acc.data[0]['account_name']}' is now set as the primary default account.",
    }


@router.post(
    "/transfer",
    dependencies=[Depends(verify_zero_trust_signature)],
)
async def transfer_funds(payload: TransferFundsRequest, db: Client = Depends(get_db)):
    """Executes atomic fund transfer via PostgreSQL RPC to prevent race conditions."""
    try:
        rpc_res = db.rpc("transfer_vault_funds", {
            "p_user_id": str(payload.user_id),
            "p_src_account_id": str(payload.source_account_id),
            "p_dest_account_id": str(payload.destination_account_id),
            "p_amount": float(payload.amount),
        }).execute()
        return rpc_res.data
    except Exception as e:
        err_msg = str(e)
        if "Insufficient funds" in err_msg:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Transfer failed: {err_msg}")