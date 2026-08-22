from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.auth import RegisterRequest, RegisterResponse
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from app.services.salary_service import SalaryService
from supabase import Client
from datetime import date
from pydantic import BaseModel
from uuid import UUID

router = APIRouter(prefix="/api/v1/auth", tags=["Identity & Provisioning"])


class NodeStatusRequest(BaseModel):
    user_id: UUID


class NodeStatusResponse(BaseModel):
    status: str
    is_registered: bool
    full_name: str = ""
    currency: str = "INR"


@router.post(
    "/status",
    response_model=NodeStatusResponse,
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def check_node_clearance(payload: NodeStatusRequest, db: Client = Depends(get_db)):
    uid_str = str(payload.user_id)
    try:
        user_res = db.table('users').select('user_id, full_name, currency, is_active').eq('user_id', uid_str).execute()

        if user_res.data and len(user_res.data) > 0:
            user = user_res.data[0]
            return NodeStatusResponse(
                status="PROVISIONED",
                is_registered=True,
                full_name=user.get("full_name", ""),
                currency=user.get("currency", "INR")
            )

        return NodeStatusResponse(
            status="UNREGISTERED",
            is_registered=False,
            full_name="",
            currency="INR"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Vault Identity Verification Fault: {str(e)}"
        )


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def register_node(payload: RegisterRequest, db: Client = Depends(get_db)):
    uid_str = str(payload.user_id)
    try:
        existing = db.table('users').select('user_id').or_(
            f"user_id.eq.{uid_str},telegram_id.eq.{uid_str}"
        ).execute()

        if existing.data and len(existing.data) > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Security Clearance: Node identity already provisioned in vault."
            )

        # 1. Insert user
        user_insert = {
            "user_id": uid_str,
            "telegram_id": uid_str,
            "full_name": payload.full_name,
            "currency": payload.currency or "INR",
            "security_strikes": 0,
            "role": "user",
            "is_active": True
        }
        db.table('users').insert(user_insert).execute()

        # 2. Insert primary bank account
        acc_insert = {
            "user_id": uid_str,
            "account_name": payload.bank_name.upper(),
            "balance": float(payload.current_balance),
            "is_active": True
        }
        acc_res = db.table('accounts').insert(acc_insert).execute()
        account_id = acc_res.data[0]['account_id']

        # 3. Genesis audit log
        db.table('account_logs').insert({
            "user_id": uid_str,
            "account_id": account_id,
            "event_type": "GENESIS_INITIALIZATION",
            "amount": float(payload.current_balance),
            "description": f"Initial liquidity provisioned for {payload.bank_name.upper()}."
        }).execute()

        # 4. Dynamically seed 12 months with holiday & weekend shifting
        current_year = date.today().year
        await SalaryService.seed_annual_salaries(
            db=db,
            user_id=uid_str,
            account_id=account_id,
            salary_amount=float(payload.salary),
            salary_date=int(payload.salary_date),
            year=current_year
        )

        return RegisterResponse(
            status="PROVISIONED",
            code=201,
            user_id=payload.user_id,
            message="Node successfully provisioned. Historical salaries and ledger accounts initialized."
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Neural Engine Fault: {str(e)}"
        )