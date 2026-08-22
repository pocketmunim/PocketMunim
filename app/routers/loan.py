from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.loan import (
    RegisterLoanRequest,
    PayEMIRequest,
    FlexibleRepaymentRequest,
    LoanListResponse,
    LoanSummaryItem,
    PartialRepaymentLogItem
)
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from app.services.loan_service import LoanService
from supabase import Client
from datetime import date
from dateutil.relativedelta import relativedelta
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/loans", tags=["Loan & Amortization Engine"])


class SettlePastEMIsRequest(BaseModel):
    user_id: str
    loan_id: str
    account_id: str = None


@router.post(
    "/list/{user_id}",
    response_model=LoanListResponse,
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def get_user_loans(user_id: str, db: Client = Depends(get_db)):
    uid = str(user_id)
    loans_res = db.table('loans') \
        .select('*') \
        .eq('user_id', uid) \
        .eq('status', 'ACTIVE') \
        .gt('pending_principal', 0) \
        .order('created_at', desc=True) \
        .execute()
    loans_data = loans_res.data or []

    acc_res = db.table('accounts').select('account_id, account_name').eq('user_id', uid).execute()
    acc_map = {a['account_id']: a['account_name'] for a in (acc_res.data or [])}

    today = date.today()
    total_liabilities = 0.0
    total_receivables = 0.0
    loan_items = []

    for l in loans_data:
        lid = l['loan_id']
        p_amt = float(l['pending_principal'])
        l_type = l['loan_type']
        is_flex = l.get('is_flexible', False)

        if l_type == 'BORROWED':
            total_liabilities += p_amt
        else:
            total_receivables += p_amt

        # Fetch partial repayment logs
        partial_res = db.table('loan_partial_repayments') \
            .select('*') \
            .eq('loan_id', lid) \
            .order('payment_date', desc=True) \
            .order('created_at', desc=True) \
            .execute()
        partial_logs = [
            PartialRepaymentLogItem(
                partial_repayment_id=p['partial_repayment_id'],
                amount=float(p['amount']),
                payment_date=date.fromisoformat(p['payment_date']),
                note=p.get('note'),
                remaining_balance_after=float(p['remaining_balance_after']),
                created_at=str(p['created_at'])
            ) for p in (partial_res.data or [])
        ]

        has_pending_past_emis = False
        pending_past_emis_count = 0
        pending_past_emis_total = 0.0
        is_cur_paid = False

        if not is_flex:
            past_sched = db.table('loan_repayments') \
                .select('repayment_id, emi_amount') \
                .eq('loan_id', lid) \
                .lte('due_date', str(today)) \
                .eq('status', 'SCHEDULED') \
                .execute()

            has_pending_past_emis = len(past_sched.data or []) > 0
            pending_past_emis_count = len(past_sched.data or [])
            pending_past_emis_total = sum(float(x['emi_amount']) for x in (past_sched.data or []))

            start_of_month = f"{today.year:04d}-{today.month:02d}-01"
            end_of_month = (date(today.year, today.month, 1) + relativedelta(months=1, days=-1))

            repay_res = db.table('loan_repayments') \
                .select('repayment_id') \
                .eq('loan_id', lid) \
                .gte('due_date', start_of_month) \
                .lte('due_date', str(end_of_month)) \
                .eq('status', 'PAID') \
                .execute()

            is_cur_paid = bool(repay_res.data)

        loan_items.append(LoanSummaryItem(
            loan_id=lid,
            loan_name=l['loan_name'],
            loan_type=l_type,
            counterparty=l['counterparty'],
            disbursement_date=date.fromisoformat(l['disbursement_date']),
            first_emi_date=date.fromisoformat(l['first_emi_date']) if l.get('first_emi_date') else None,
            original_principal=float(l['original_principal']),
            pending_principal=p_amt,
            annual_interest_rate=float(l.get('annual_interest_rate', 0.0)),
            original_tenure_months=int(l.get('original_tenure_months', 0)),
            pending_tenure_months=int(l.get('pending_tenure_months', 0)),
            monthly_emi=float(l.get('monthly_emi', 0.0)),
            total_interest_payable=float(l.get('total_interest_payable', 0.0)),
            principal_paid=float(l.get('principal_paid', 0.0)),
            interest_paid=float(l.get('interest_paid', 0.0)),
            next_emi_date=date.fromisoformat(l['next_emi_date']) if l.get('next_emi_date') else None,
            status=l['status'],
            is_flexible=is_flex,
            account_id=l.get('account_id'),
            account_name=acc_map.get(l.get('account_id'), "Default Vault"),
            is_current_month_paid=is_cur_paid,
            has_pending_past_emis=has_pending_past_emis,
            pending_past_emis_count=pending_past_emis_count,
            pending_past_emis_total=round(pending_past_emis_total, 2),
            partial_repayments=partial_logs
        ))

    return LoanListResponse(
        status="SUCCESS",
        total_liabilities=round(total_liabilities, 2),
        total_receivables=round(total_receivables, 2),
        net_debt_position=round(total_receivables - total_liabilities, 2),
        active_loans_count=len(loan_items),
        loans=loan_items
    )


@router.post(
    "/register",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def register_loan(payload: RegisterLoanRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    sanitized_name = payload.loan_name.strip()
    principal = round(float(payload.original_principal), 2)

    existing = db.table('loans').select('loan_id').eq('user_id', uid).ilike('loan_name', sanitized_name).execute()
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A loan titled '{sanitized_name}' already exists. Please use a unique title."
        )

    if payload.account_id:
        acc_res = db.table('accounts').select('*').eq('account_id', str(payload.account_id)).eq('user_id', uid).eq(
            'is_active', True).execute()
    else:
        acc_res = db.table('accounts').select('*').eq('user_id', uid).eq('is_default', True).eq('is_active',
                                                                                                True).execute()
        if not acc_res.data:
            acc_res = db.table('accounts').select('*').eq('user_id', uid).eq('is_active', True).limit(1).execute()

    if not acc_res.data:
        raise HTTPException(status_code=404, detail="No active account vault found for loan disbursement.")

    acc = acc_res.data[0]
    aid = acc['account_id']
    acc_name = acc['account_name']
    curr_balance = float(acc['balance'])

    if payload.loan_type.value == "LENT" and curr_balance < principal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance in {acc_name} to lend ₹{principal:,.2f}. Available: ₹{curr_balance:,.2f}."
        )

    if payload.is_flexible:
        # Flexible P2P Borrow/Lend: 0% Interest, No Fixed EMI schedule
        loan_insert = db.table('loans').insert({
            "user_id": uid,
            "account_id": aid,
            "loan_name": sanitized_name,
            "loan_type": payload.loan_type.value,
            "counterparty": payload.counterparty.strip(),
            "disbursement_date": str(payload.disbursement_date),
            "first_emi_date": str(payload.disbursement_date),
            "original_principal": principal,
            "pending_principal": principal,
            "annual_interest_rate": 0.0,
            "original_tenure_months": 0,
            "pending_tenure_months": 0,
            "monthly_emi": 0.0,
            "total_interest_payable": 0.0,
            "principal_paid": 0.0,
            "interest_paid": 0.0,
            "next_emi_date": str(payload.disbursement_date),
            "status": "ACTIVE",
            "is_flexible": True
        }).execute()
        monthly_emi = 0.0
    else:
        # Standard Fixed Amortization Loan
        first_emi_d = payload.first_emi_date or LoanService.calculate_default_first_emi_date(payload.disbursement_date)
        monthly_emi = LoanService.calculate_reducing_emi(principal, payload.annual_interest_rate,
                                                         payload.original_tenure_months)
        schedule = LoanService.generate_amortization_schedule(principal, payload.annual_interest_rate,
                                                              payload.original_tenure_months, first_emi_d, monthly_emi)
        total_interest = round(sum(item['emi_amount'] for item in schedule) - principal, 2)

        loan_insert = db.table('loans').insert({
            "user_id": uid,
            "account_id": aid,
            "loan_name": sanitized_name,
            "loan_type": payload.loan_type.value,
            "counterparty": payload.counterparty.strip(),
            "disbursement_date": str(payload.disbursement_date),
            "first_emi_date": str(first_emi_d),
            "original_principal": principal,
            "pending_principal": principal,
            "annual_interest_rate": payload.annual_interest_rate,
            "original_tenure_months": payload.original_tenure_months,
            "pending_tenure_months": payload.original_tenure_months,
            "monthly_emi": monthly_emi,
            "total_interest_payable": total_interest,
            "principal_paid": 0.0,
            "interest_paid": 0.0,
            "next_emi_date": str(first_emi_d),
            "status": "ACTIVE",
            "is_flexible": False
        }).execute()

        new_loan_id = loan_insert.data[0]['loan_id']
        for inst in schedule:
            inst['loan_id'] = new_loan_id
            inst['user_id'] = uid
            inst['account_id'] = aid
        db.table('loan_repayments').insert(schedule).execute()

    new_loan_id = loan_insert.data[0]['loan_id']

    # Update Vault & Double-Entry Ledger
    tx_type = "CREDIT" if payload.loan_type.value == "BORROWED" else "DEBIT"
    status_label = "CREDITED" if tx_type == "CREDIT" else "DEBITED"
    new_bal = round(curr_balance + principal if tx_type == "CREDIT" else curr_balance - principal, 2)

    db.table('accounts').update({"balance": new_bal}).eq('account_id', aid).execute()

    db.table('transactions').insert({
        "user_id": uid,
        "account_id": aid,
        "account_name": acc_name,
        "type": tx_type,
        "category": "Debt & EMI",
        "amount": principal,
        "transaction_date": str(payload.disbursement_date),
        "status": status_label,
        "description": f"Loan Inflow ({payload.loan_type.value}): {sanitized_name} - {payload.counterparty}"
    }).execute()

    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": aid,
        "event_type": f"LOAN_DISBURSEMENT_{tx_type}",
        "amount": principal if tx_type == "CREDIT" else -principal,
        "description": f"Loan registered for '{sanitized_name}' via {acc_name}."
    }).execute()

    return {
        "status": "SUCCESS",
        "message": f"Loan '{sanitized_name}' registered. {'Credited' if tx_type == 'CREDIT' else 'Debited'} ₹{principal:,.2f} on {acc_name}.",
        "loan_id": new_loan_id,
        "monthly_emi": monthly_emi
    }


@router.post(
    "/repay-flexible",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def repay_flexible_loan(payload: FlexibleRepaymentRequest, db: Client = Depends(get_db)):
    """
    Handles ad-hoc irregular repayments (e.g. ₹1,000 or ₹5,000) for P2P flexible borrow/lent loans.
    """
    uid = str(payload.user_id)
    lid = str(payload.loan_id)
    pay_amount = round(float(payload.amount), 2)
    pay_date = payload.payment_date or date.today()

    loan_res = db.table('loans').select('*').eq('loan_id', lid).eq('user_id', uid).execute()
    if not loan_res.data:
        raise HTTPException(status_code=404, detail="Loan not found.")
    loan = loan_res.data[0]

    if loan['status'] != 'ACTIVE':
        raise HTTPException(status_code=400, detail="This loan is already fully settled and CLOSED.")

    pending_p = float(loan['pending_principal'])

    if pay_amount > pending_p:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Repayment amount (₹{pay_amount:,.2f}) exceeds outstanding pending balance (₹{pending_p:,.2f})."
        )

    target_aid = payload.account_id or loan.get('account_id')
    acc_res = db.table('accounts').select('*').eq('account_id', target_aid).eq('user_id', uid).execute()
    if not acc_res.data:
        raise HTTPException(status_code=404, detail="Repayment vault account not found.")

    acc = acc_res.data[0]
    aid = acc['account_id']
    acc_name = acc['account_name']
    curr_balance = float(acc['balance'])
    loan_type = loan['loan_type']

    # For BORROWED loans: user is returning money -> Outflow (DEBIT)
    # For LENT loans: friend is returning money -> Inflow (CREDIT)
    if loan_type == 'BORROWED' and curr_balance < pay_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance in {acc_name}. Available: ₹{curr_balance:,.2f}, Required: ₹{pay_amount:,.2f}."
        )

    new_balance = round(curr_balance - pay_amount if loan_type == 'BORROWED' else curr_balance + pay_amount, 2)
    tx_type = "DEBIT" if loan_type == 'BORROWED' else "CREDIT"
    status_label = "DEBITED" if loan_type == 'BORROWED' else "CREDITED"
    new_pending = round(pending_p - pay_amount, 2)
    new_paid = round(float(loan['principal_paid']) + pay_amount, 2)
    loan_status = "CLOSED" if new_pending <= 0 else "ACTIVE"

    # 1. Update Vault Balance
    db.table('accounts').update({"balance": new_balance}).eq('account_id', aid).execute()

    # 2. Insert Partial Repayment Record
    db.table('loan_partial_repayments').insert({
        "loan_id": lid,
        "user_id": uid,
        "account_id": aid,
        "amount": pay_amount,
        "payment_date": str(pay_date),
        "note": payload.note or "Ad-hoc repayment",
        "remaining_balance_after": new_pending
    }).execute()

    # 3. Insert Transaction Ledger
    db.table('transactions').insert({
        "user_id": uid,
        "account_id": aid,
        "account_name": acc_name,
        "type": tx_type,
        "category": "Debt & EMI",
        "amount": pay_amount,
        "transaction_date": str(pay_date),
        "status": status_label,
        "description": f"P2P Repayment: {loan['loan_name']} ({loan['counterparty']}) - {payload.note or 'Ad-hoc'}"
    }).execute()

    # 4. Insert Account Log
    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": aid,
        "event_type": f"LOAN_PARTIAL_{tx_type}",
        "amount": -pay_amount if tx_type == 'DEBIT' else pay_amount,
        "description": f"Partial repayment of ₹{pay_amount:,.2f} logged for '{loan['loan_name']}' (Pending: ₹{new_pending:,.2f})."
    }).execute()

    # 5. Update Master Loan
    db.table('loans').update({
        "pending_principal": new_pending,
        "principal_paid": new_paid,
        "status": loan_status
    }).eq('loan_id', lid).execute()

    return {
        "status": "SUCCESS",
        "message": f"Logged ₹{pay_amount:,.2f} repayment for {loan['loan_name']}. Remaining pending: ₹{new_pending:,.2f}.",
        "new_pending_principal": new_pending,
        "loan_status": loan_status
    }