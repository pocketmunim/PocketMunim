import calendar
from datetime import date
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client

from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from app.schemas.loan import (
    RegisterLoanRequest,
    PayEMIRequest,
    SettlePastEMIsRequest,
    FlexibleRepaymentRequest,
    LoanListResponse,
    LoanSummaryItem,
    PartialRepaymentLogItem,
)
from app.services.loan_service import LoanService

router = APIRouter(prefix="/api/v1/loans", tags=["Loans & Amortization"])


@router.post(
    "/list/{user_id}",
    response_model=LoanListResponse,
    dependencies=[Depends(verify_zero_trust_signature)],
)
async def list_user_loans(user_id: str, db: Client = Depends(get_db)):
    uid = str(user_id)
    today = date.today()
    first_of_month = date(today.year, today.month, 1)
    _, last_day = calendar.monthrange(today.year, today.month)
    end_of_month = date(today.year, today.month, last_day)

    # 1. Fetch all active loans
    loans_res = (
        db.table("loans")
        .select("*, accounts(account_name)")
        .eq("user_id", uid)
        .eq("status", "ACTIVE")
        .order("created_at", desc=True)
        .execute()
    )
    loans = loans_res.data or []

    # 2. Fetch all repayments for pending past EMIs and current month status
    repayments_res = (
        db.table("loan_repayments")
        .select("*")
        .eq("user_id", uid)
        .execute()
    )
    repayments = repayments_res.data or []

    # 3. Fetch all partial repayments for flexible loans
    partials_res = (
        db.table("loan_partial_repayments")
        .select("*")
        .eq("user_id", uid)
        .order("payment_date", desc=True)
        .execute()
    )
    partials = partials_res.data or []

    # Aggregates
    total_liabilities = 0.0
    total_receivables = 0.0
    loan_items: List[LoanSummaryItem] = []

    for l in loans:
        lid = str(l["loan_id"])
        pending_p = float(l.get("pending_principal") or 0.0)
        ltype = l.get("loan_type", "BORROWED")
        is_flexible = bool(l.get("is_flexible", False))

        if ltype == "BORROWED":
            total_liabilities += pending_p
        else:
            total_receivables += pending_p

        # Filter partial repayments for this specific loan
        loan_partials = [
            PartialRepaymentLogItem(
                partial_repayment_id=str(p["partial_repayment_id"]),
                amount=float(p["amount"]),
                payment_date=p["payment_date"],
                note=p.get("note") or "Ad-hoc repayment",
                remaining_balance_after=float(p["remaining_balance_after"]),
                created_at=str(p["created_at"]),
            )
            for p in partials
            if str(p.get("loan_id")) == lid
        ]

        # Amortization flags
        is_current_month_paid = False
        has_pending_past_emis = False
        pending_past_emis_count = 0
        pending_past_emis_total = 0.0

        if not is_flexible:
            loan_reps = [r for r in repayments if str(r.get("loan_id")) == lid]

            # Check if current month is paid
            for r in loan_reps:
                due_d = date.fromisoformat(r["due_date"])
                if first_of_month <= due_d <= end_of_month and r["status"] == "PAID":
                    is_current_month_paid = True

            # Check if past EMIs are pending
            past_due_reps = [
                r for r in loan_reps
                if date.fromisoformat(r["due_date"]) <= today and r["status"] == "SCHEDULED"
            ]
            if past_due_reps:
                has_pending_past_emis = True
                pending_past_emis_count = len(past_due_reps)
                pending_past_emis_total = sum(float(r["emi_amount"]) for r in past_due_reps)

        account_info = l.get("accounts")
        account_name = account_info.get("account_name") if account_info else "Default Vault"

        loan_items.append(
            LoanSummaryItem(
                loan_id=lid,
                loan_name=l["loan_name"],
                loan_type=ltype,
                counterparty=l["counterparty"],
                disbursement_date=l["disbursement_date"],
                first_emi_date=l.get("first_emi_date"),
                original_principal=float(l["original_principal"]),
                pending_principal=pending_p,
                annual_interest_rate=float(l.get("annual_interest_rate") or 0.0),
                original_tenure_months=int(l.get("original_tenure_months") or 0),
                pending_tenure_months=int(l.get("pending_tenure_months") or 0),
                monthly_emi=float(l.get("monthly_emi") or 0.0),
                total_interest_payable=float(l.get("total_interest_payable") or 0.0),
                principal_paid=float(l.get("principal_paid") or 0.0),
                interest_paid=float(l.get("interest_paid") or 0.0),
                next_emi_date=l.get("next_emi_date"),
                status=l["status"],
                is_flexible=is_flexible,
                account_id=str(l["account_id"]) if l.get("account_id") else None,
                account_name=account_name,
                is_current_month_paid=is_current_month_paid,
                has_pending_past_emis=has_pending_past_emis,
                pending_past_emis_count=pending_past_emis_count,
                pending_past_emis_total=round(pending_past_emis_total, 2),
                partial_repayments=loan_partials,
            )
        )

    return LoanListResponse(
        status="SUCCESS",
        total_liabilities=round(total_liabilities, 2),
        total_receivables=round(total_receivables, 2),
        net_debt_position=round(total_receivables - total_liabilities, 2),
        active_loans_count=len(loan_items),
        loans=loan_items,
    )


@router.post(
    "/register",
    dependencies=[Depends(verify_zero_trust_signature)],
)
async def register_loan(payload: RegisterLoanRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    first_emi_d = payload.first_emi_date or LoanService.calculate_default_first_emi_date(payload.disbursement_date)

    if not payload.is_flexible:
        calculated_emi = LoanService.calculate_reducing_emi(
            principal=payload.original_principal,
            annual_rate=payload.annual_interest_rate,
            tenure_months=payload.original_tenure_months,
        )
        total_payable = calculated_emi * payload.original_tenure_months
        total_interest = max(0.0, total_payable - payload.original_principal)
        amortization_schedule = LoanService.generate_amortization_schedule(
            principal=payload.original_principal,
            annual_rate=payload.annual_interest_rate,
            tenure_months=payload.original_tenure_months,
            first_emi_date=first_emi_d,
            monthly_emi=calculated_emi,
        )
    else:
        calculated_emi = 0.0
        total_interest = 0.0
        amortization_schedule = []

    rpc_payload = {
        "user_id": uid,
        "loan_name": payload.loan_name.strip(),
        "loan_type": payload.loan_type.value,
        "counterparty": payload.counterparty.strip(),
        "disbursement_date": str(payload.disbursement_date),
        "first_emi_date": str(first_emi_d),
        "original_principal": payload.original_principal,
        "annual_interest_rate": payload.annual_interest_rate,
        "original_tenure_months": payload.original_tenure_months,
        "monthly_emi": calculated_emi,
        "total_interest_payable": total_interest,
        "account_id": payload.account_id,
        "is_flexible": payload.is_flexible,
        "schedule": amortization_schedule,
    }

    res = db.rpc("register_loan_atomic", {"payload": rpc_payload}).execute()
    return {"status": "SUCCESS", "data": res.data}


@router.post(
    "/pay-emi",
    dependencies=[Depends(verify_zero_trust_signature)],
)
async def pay_loan_emi(payload: PayEMIRequest, db: Client = Depends(get_db)):
    rpc_payload = {
        "user_id": str(payload.user_id),
        "loan_id": str(payload.loan_id),
        "account_id": str(payload.account_id) if payload.account_id else None,
        "is_advance_confirmed": bool(payload.is_advance_confirmed),
    }

    res = db.rpc("pay_loan_emi_atomic", {"payload": rpc_payload}).execute()
    return {"status": "SUCCESS", "data": res.data}


@router.post(
    "/settle-past-emis",
    dependencies=[Depends(verify_zero_trust_signature)],
)
async def settle_past_emis(payload: SettlePastEMIsRequest, db: Client = Depends(get_db)):
    # Ensure empty string account IDs are explicitly converted to None for PostgreSQL UUID parsing
    target_aid = None
    if payload.account_id and str(payload.account_id).strip() != "":
        target_aid = str(payload.account_id)

    rpc_payload = {
        "user_id": str(payload.user_id),
        "loan_id": str(payload.loan_id),
        "account_id": target_aid,
    }

    try:
        res = db.rpc("settle_past_emis_atomic", {"payload": rpc_payload}).execute()
        data = res.data
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        return {"status": "SUCCESS", "data": data or {"message": "Settlement processed successfully."}}
    except Exception as e:
        # Bank-grade polite error formatting
        err_str = str(e)
        user_message = "Your batch settlement request could not be completed. Please check your vault balance."
        if "Insufficient balance" in err_str:
            user_message = "Transaction Declined: Insufficient funds in your vault to settle historical installments."
        elif "Loan contract not found" in err_str:
            user_message = "Error: The specified financial contract could not be located."

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=user_message
        )


@router.post(
    "/repay-flexible",
    dependencies=[Depends(verify_zero_trust_signature)],
)
async def repay_flexible_loan(payload: FlexibleRepaymentRequest, db: Client = Depends(get_db)):
    payment_d = payload.payment_date or date.today()
    rpc_payload = {
        "user_id": str(payload.user_id),
        "loan_id": str(payload.loan_id),
        "account_id": str(payload.account_id) if payload.account_id else None,
        "amount": payload.amount,
        "payment_date": str(payment_d),
        "note": payload.note or "Ad-hoc repayment",
    }

    res = db.rpc("repay_flexible_loan_atomic", {"payload": rpc_payload}).execute()
    return {"status": "SUCCESS", "data": res.data}