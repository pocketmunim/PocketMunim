from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.auth import RegisterRequest, RegisterResponse
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from supabase import Client
from app.services.salary_service import SalaryService

router = APIRouter(prefix="/api/v1/auth", tags=["Identity & Provisioning"])

@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def register_node(payload: RegisterRequest, db: Client = Depends(get_db)):
    uid_str = str(payload.user_id)
    try:
        # Prevent re-registration
        existing = db.table('users').select('user_id').or_(
            f"user_id.eq.{uid_str},telegram_id.eq.{uid_str}"
        ).execute()

        if existing.data:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Security Clearance: Node identity already provisioned in vault."
            )

        # 1. Insert user
        db.table('users').insert({
            "user_id": uid_str,
            "telegram_id": uid_str,
            "full_name": payload.full_name,
            "currency": payload.currency,
            "salary_amount": payload.salary,
            "salary_date": payload.salary_date,
            "security_strikes": 0,
            "role": "user",
            "is_active": True
        }).execute()

        # 2. Insert primary bank account
        db.table('accounts').insert({
            "user_id": uid_str,
            "account_name": payload.bank_name.upper(),
            "balance": payload.current_balance,
            "is_active": True
        }).execute()

        SalaryService.seed_annual_salaries(
            db=db,
            user_id=uid_str,
            account_id=account_id,
            salary_amount=float(payload.salary),
            salary_date=int(payload.salary_date),
            year=date.today().year
        )

        return RegisterResponse(
            status="PROVISIONED",
            code=201,
            user_id=payload.user_id,
            message="Node successfully linked to Ishita Financial Intelligence System."
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Neural Engine Fault: {str(e)}"
        )
