from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.loan import (
    RegisterLoanRequest, PayEMIRequest, SettlePastEMIsRequest,
    FlexibleRepaymentRequest, LoanListResponse, LoanSummaryItem, PartialRepaymentLogItem
)
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from app.services.loan_service import LoanService
from supabase import Client
from datetime import date
from dateutil.relativedelta import relativedelta

router = APIRouter(prefix="/api/v1/loans", tags=["Loan & Amortization Engine"])


@router.post("/list/{user_id}", response_model=LoanListResponse, dependencies=[Depends(verify_zero_trust_signature)])
async def get_user_loans(user_id: str, db: Client = Depends(get_db)):
    uid = str(user_id)
    loans_res = db.table('loans').select('*').eq('user_id', uid).eq('status', 'ACTIVE').gt('pending_principal',
                                                                                           0).order('created_at',
                                                                                                    desc=True).execute()
    loans_data = loans_res.data or []

    acc_res = db.table('accounts').select('account_id, account_name').eq('user_id', uid).execute()
    acc_map = {a['account_id']: a['account_name'] for a in (acc_res.data or [])}

    loan_ids = [l['loan_id'] for l in loans_data]

    # API-01 FIX: Batch query all partial repayments and schedules instead of N+1 loop
    partial_map = {lid: [] for lid in loan_ids}
    if loan_ids:
        p_res = db.table('loan_partial_repayments').select('*').in_('loan_id', loan_ids).order('payment_date',
                                                                                               desc=True).execute()
        for p in (p_res.data or []):
            partial_map[p['loan_id']].append(PartialRepaymentLogItem(**p))

    sched_map = {lid: [] for lid in loan_ids}
    if loan_ids:
        s_res = db.table('loan_repayments').select('*').in_('loan_id', loan_ids).lte('due_date', str(date.today())).eq(
            'status', 'SCHEDULED').execute()
        for s in (s_res.data or []):
            sched_map[s['loan_id']].append(s)

    today = date.today()
    start_of_month = f"{today.year:04d}-{today.month:02d}-01"
    end_of_month = (date(today.year, today.month, 1) + relativedelta(months=1, days=-1))

    cur_paid_set = set()
    if loan_ids:
        cur_res = db.table('loan_repayments').select('loan_id').in_('loan_id', loan_ids).gte('due_date',
                                                                                             start_of_month).lte(
            'due_date', str(end_of_month)).eq('status', 'PAID').execute()
        cur_paid_set = {c['loan_id'] for c in (cur_res.data or [])}

    total_liabilities, total_receivables = 0.0, 0.0
    loan_items = []

    for l in loans_data:
        lid = l['loan_id']
        p_amt = float(l.get('pending_principal') or 0.0)
        l_type = l.get('loan_type', 'BORROWED')

        if l_type == 'BORROWED':
            total_liabilities += p_amt
        else:
            total_receivables += p_amt

        past_emis = sched_map.get(lid, [])
        pending_past_total = sum(float(x['emi_amount']) for x in past_emis)

        loan_items.append(LoanSummaryItem(
            loan_id=lid, loan_name=l['loan_name'], loan_type=l_type, counterparty=l['counterparty'],
            disbursement_date=date.fromisoformat(str(l['disbursement_date'])),
            first_emi_date=date.fromisoformat(str(l['first_emi_date'])) if l.get('first_emi_date') else None,
            original_principal=float(l.get('original_principal') or 0.0), pending_principal=p_amt,
            annual_interest_rate=float(l.get('annual_interest_rate') or 0.0),
            original_tenure_months=int(l.get('original_tenure_months') or 0),
            pending_tenure_months=int(l.get('pending_tenure_months') or 0),
            monthly_emi=float(l.get('monthly_emi') or 0.0),
            total_interest_payable=float(l.get('total_interest_payable') or 0.0),
            principal_paid=float(l.get('principal_paid') or 0.0), interest_paid=float(l.get('interest_paid') or 0.0),
            next_emi_date=date.fromisoformat(str(l['next_emi_date'])) if l.get('next_emi_date') else None,
            status=l.get('status', 'ACTIVE'), is_flexible=bool(l.get('is_flexible', False)),
            account_id=l.get('account_id'), account_name=acc_map.get(l.get('account_id'), "Default Vault"),
            is_current_month_paid=(lid in cur_paid_set), has_pending_past_emis=len(past_emis) > 0,
            pending_past_emis_count=len(past_emis), pending_past_emis_total=round(pending_past_total, 2),
            partial_repayments=partial_map.get(lid, [])
        ))

    return LoanListResponse(
        status="SUCCESS", total_liabilities=round(total_liabilities, 2), total_receivables=round(total_receivables, 2),
        net_debt_position=round(total_receivables - total_liabilities, 2), active_loans_count=len(loan_items),
        loans=loan_items
    )


@router.post("/register", dependencies=[Depends(verify_zero_trust_signature)])
async def register_loan(payload: RegisterLoanRequest, db: Client = Depends(get_db)):
    """Delegates complex multi-table loan generation to a Postgres RPC for ACID isolation."""
    principal = round(float(payload.original_principal), 2)
    schedule = []
    first_emi_d = payload.first_emi_date or payload.disbursement_date
    monthly_emi, total_interest = 0.0, 0.0

    if not payload.is_flexible:
        first_emi_d = payload.first_emi_date or LoanService.calculate_default_first_emi_date(payload.disbursement_date)
        monthly_emi = LoanService.calculate_reducing_emi(principal, payload.annual_interest_rate,
                                                         payload.original_tenure_months)
        schedule = LoanService.generate_amortization_schedule(principal, payload.annual_interest_rate,
                                                              payload.original_tenure_months, first_emi_d, monthly_emi)
        total_interest = round(sum(item['emi_amount'] for item in schedule) - principal, 2)

    rpc_payload = {
        "user_id": str(payload.user_id),
        "account_id": str(payload.account_id) if payload.account_id else None,
        "loan_name": payload.loan_name.strip(),
        "loan_type": payload.loan_type.value,
        "counterparty": payload.counterparty.strip(),
        "disbursement_date": str(payload.disbursement_date),
        "first_emi_date": str(first_emi_d),
        "original_principal": principal,
        "annual_interest_rate": payload.annual_interest_rate,
        "original_tenure_months": payload.original_tenure_months,
        "monthly_emi": monthly_emi,
        "total_interest_payable": total_interest,
        "is_flexible": payload.is_flexible,
        "schedule": schedule
    }

    try:
        rpc_res = db.rpc("register_loan_atomic", {"payload": rpc_payload}).execute()
        return rpc_res.data
    except Exception as e:
        err = str(e)
        if "Insufficient balance" in err or "already exists" in err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"RPC Execution Failed: {err}")


@router.post("/pay-emi", dependencies=[Depends(verify_zero_trust_signature)])
async def pay_loan_emi(payload: PayEMIRequest, db: Client = Depends(get_db)):
    try:
        rpc_res = db.rpc("pay_loan_emi_atomic", {"payload": payload.model_dump()}).execute()
        return rpc_res.data
    except Exception as e:
        err = str(e)
        if "DUPLICATE_CURRENT_MONTH" in err:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Installment for this month has ALREADY been paid. Advance confirmation required.")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)


@router.post("/settle-past-emis", dependencies=[Depends(verify_zero_trust_signature)])
async def settle_past_emis(payload: SettlePastEMIsRequest, db: Client = Depends(get_db)):
    try:
        rpc_res = db.rpc("settle_past_emis_atomic", {"payload": payload.model_dump()}).execute()
        return rpc_res.data
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/repay-flexible", dependencies=[Depends(verify_zero_trust_signature)])
async def repay_flexible_loan(payload: FlexibleRepaymentRequest, db: Client = Depends(get_db)):
    rpc_payload = payload.model_dump()
    if rpc_payload.get('payment_date'):
        rpc_payload['payment_date'] = str(rpc_payload['payment_date'])

    try:
        rpc_res = db.rpc("repay_flexible_loan_atomic", {"payload": rpc_payload}).execute()
        return rpc_res.data
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))