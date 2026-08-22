from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.loan import (
    RegisterLoanRequest,
    PayEMIRequest,
    LoanListResponse,
    LoanSummaryItem
)
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from app.services.loan_service import LoanService
from supabase import Client
from datetime import date
from dateutil.relativedelta import relativedelta

router = APIRouter(prefix="/api/v1/loans", tags=["Loan & Amortization Engine"])


@router.post(
    "/list/{user_id}",
    response_model=LoanListResponse,
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def get_user_loans(user_id: str, db: Client = Depends(get_db)):
    uid = str(user_id)
    loans_res = db.table('loans').select('*').eq('user_id', uid).order('status').order('created_at',
                                                                                       desc=True).execute()
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

        if l['status'] == 'ACTIVE':
            if l_type == 'BORROWED':
                total_liabilities += p_amt
            else:
                total_receivables += p_amt

        # Check if current month's installment is already settled
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
            first_emi_date=date.fromisoformat(l['first_emi_date']),
            original_principal=float(l['original_principal']),
            pending_principal=p_amt,
            annual_interest_rate=float(l['annual_interest_rate']),
            original_tenure_months=int(l['original_tenure_months']),
            pending_tenure_months=int(l['pending_tenure_months']),
            monthly_emi=float(l['monthly_emi']),
            total_interest_payable=float(l['total_interest_payable']),
            principal_paid=float(l['principal_paid']),
            interest_paid=float(l['interest_paid']),
            next_emi_date=date.fromisoformat(l['next_emi_date']),
            status=l['status'],
            account_id=l.get('account_id'),
            account_name=acc_map.get(l.get('account_id'), "Default Vault"),
            is_current_month_paid=is_cur_paid
        ))

    return LoanListResponse(
        status="SUCCESS",
        total_liabilities=round(total_liabilities, 2),
        total_receivables=round(total_receivables, 2),
        net_debt_position=round(total_receivables - total_liabilities, 2),
        active_loans_count=len([l for l in loan_items if l.status == 'ACTIVE']),
        loans=loan_items
    )


@router.post(
    "/register",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def register_loan(payload: RegisterLoanRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    sanitized_name = payload.loan_name.strip()

    # Deduplication Guard
    existing = db.table('loans').select('loan_id').eq('user_id', uid).ilike('loan_name', sanitized_name).execute()
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A loan titled '{sanitized_name}' already exists. Please use a unique title."
        )

    # Date Validation
    if payload.first_emi_date < payload.disbursement_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="First EMI date cannot precede the disbursement date."
        )

    # 1. Compute EMI
    monthly_emi = LoanService.calculate_reducing_emi(
        payload.original_principal,
        payload.annual_interest_rate,
        payload.original_tenure_months
    )

    # 2. Generate Base Amortization Schedule
    raw_schedule = LoanService.generate_amortization_schedule(
        payload.original_principal,
        payload.annual_interest_rate,
        payload.original_tenure_months,
        payload.first_emi_date,
        monthly_emi
    )

    total_repayment = sum(item['emi_amount'] for item in raw_schedule)
    total_interest = round(total_repayment - payload.original_principal, 2)

    # 3. Process Inception Catch-Up via LoanService
    (
        schedule,
        pending_principal,
        principal_paid,
        interest_paid,
        pending_tenure,
        next_emi_date,
        loan_status
    ) = LoanService.process_inception_settlement(
        raw_schedule,
        payload.settle_past_emis,
        payload.first_emi_date,
        payload.original_principal,
        payload.original_tenure_months
    )

    settled_count = payload.original_tenure_months - pending_tenure

    # 4. Save Master Loan Contract
    loan_insert = db.table('loans').insert({
        "user_id": uid,
        "account_id": payload.account_id,
        "loan_name": sanitized_name,
        "loan_type": payload.loan_type.value,
        "counterparty": payload.counterparty.strip(),
        "disbursement_date": str(payload.disbursement_date),
        "first_emi_date": str(payload.first_emi_date),
        "original_principal": payload.original_principal,
        "pending_principal": pending_principal,
        "annual_interest_rate": payload.annual_interest_rate,
        "original_tenure_months": payload.original_tenure_months,
        "pending_tenure_months": pending_tenure,
        "monthly_emi": monthly_emi,
        "total_interest_payable": total_interest,
        "principal_paid": principal_paid,
        "interest_paid": interest_paid,
        "next_emi_date": str(next_emi_date),
        "status": loan_status
    }).execute()

    if not loan_insert.data:
        raise HTTPException(status_code=500, detail="Failed to initialize loan contract.")

    new_loan_id = loan_insert.data[0]['loan_id']

    # 5. Save Amortization Installments
    for inst in schedule:
        inst['loan_id'] = new_loan_id
        inst['user_id'] = uid
        inst['account_id'] = payload.account_id

    db.table('loan_repayments').insert(schedule).execute()

    return {
        "status": "SUCCESS",
        "message": f"Loan '{sanitized_name}' registered. {settled_count} past installments settled.",
        "loan_id": new_loan_id,
        "monthly_emi": monthly_emi,
        "pending_principal": pending_principal,
        "next_emi_date": str(next_emi_date)
    }


@router.post(
    "/pay-emi",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def pay_loan_emi(payload: PayEMIRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    lid = str(payload.loan_id)

    # 1. Fetch Loan Details
    loan_res = db.table('loans').select('*').eq('loan_id', lid).eq('user_id', uid).execute()
    if not loan_res.data:
        raise HTTPException(status_code=404, detail="Loan contract not found.")
    loan = loan_res.data[0]

    if loan['status'] != 'ACTIVE':
        raise HTTPException(status_code=400, detail="This loan is already fully settled and CLOSED.")

    # 2. Find earliest SCHEDULED installment
    sched_res = db.table('loan_repayments') \
        .select('*') \
        .eq('loan_id', lid) \
        .eq('status', 'SCHEDULED') \
        .order('installment_number') \
        .limit(1) \
        .execute()

    if not sched_res.data:
        db.table('loans').update({"status": "CLOSED", "pending_principal": 0.0}).eq('loan_id', lid).execute()
        return {"status": "SUCCESS", "message": "All EMIs for this loan have been completed."}

    next_installment = sched_res.data[0]
    inst_num = next_installment['installment_number']
    emi_amount = float(next_installment['emi_amount'])
    due_date = date.fromisoformat(next_installment['due_date'])
    today = date.today()

    # 3. Duplicate Month / Advance Confirmation Guard
    start_of_month = f"{today.year:04d}-{today.month:02d}-01"
    end_of_month = (date(today.year, today.month, 1) + relativedelta(months=1, days=-1))

    cur_month_paid = db.table('loan_repayments') \
        .select('repayment_id') \
        .eq('loan_id', lid) \
        .gte('due_date', start_of_month) \
        .lte('due_date', str(end_of_month)) \
        .eq('status', 'PAID') \
        .execute()

    if cur_month_paid.data and not payload.is_advance_confirmed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"DUPLICATE_CURRENT_MONTH: Installment for {today.strftime('%B %Y')} has ALREADY been paid. Are you sure you want to pay in advance for Installment #{inst_num} (Due: {due_date})?"
        )

    # 4. Resolve Target Vault Account
    target_aid = payload.account_id or loan.get('account_id')
    if target_aid:
        acc_res = db.table('accounts').select('*').eq('account_id', target_aid).eq('user_id', uid).eq('is_active',
                                                                                                      True).execute()
    else:
        acc_res = db.table('accounts').select('*').eq('user_id', uid).eq('is_default', True).eq('is_active',
                                                                                                True).execute()
        if not acc_res.data:
            acc_res = db.table('accounts').select('*').eq('user_id', uid).eq('is_active', True).limit(1).execute()

    if not acc_res.data:
        raise HTTPException(status_code=404, detail="No active liquidity vault available for EMI deduction.")

    acc = acc_res.data[0]
    aid = acc['account_id']
    acc_name = acc['account_name']
    curr_balance = float(acc['balance'])
    loan_type = loan['loan_type']

    # 5. Solvency Guard
    if loan_type == 'BORROWED' and curr_balance < emi_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance in {acc_name}. Available: ₹{curr_balance:,.2f}, Required EMI: ₹{emi_amount:,.2f}."
        )

    # 6. Execute Mutations
    new_balance = round(curr_balance - emi_amount if loan_type == 'BORROWED' else curr_balance + emi_amount, 2)
    tx_type = "DEBIT" if loan_type == 'BORROWED' else "CREDIT"
    status_label = "DEBITED" if loan_type == 'BORROWED' else "CREDITED"

    db.table('accounts').update({"balance": new_balance}).eq('account_id', aid).execute()

    db.table('transactions').insert({
        "user_id": uid,
        "account_id": aid,
        "account_name": acc_name,
        "type": tx_type,
        "category": "Debt & EMI",
        "amount": emi_amount,
        "transaction_date": str(today),
        "status": status_label,
        "description": f"Loan EMI #{inst_num} ({loan['loan_name']}) - {loan['counterparty']}"
    }).execute()

    db.table('loan_repayments').update({
        "status": "PAID",
        "paid_at": str(today),
        "account_id": aid
    }).eq('repayment_id', next_installment['repayment_id']).execute()

    new_pending_principal = round(float(next_installment['remaining_principal_after']), 2)
    new_pending_tenure = max(0, int(loan['pending_tenure_months']) - 1)
    new_principal_paid = round(float(loan['principal_paid']) + float(next_installment['principal_component']), 2)
    new_interest_paid = round(float(loan['interest_paid']) + float(next_installment['interest_component']), 2)
    loan_status = "CLOSED" if new_pending_principal <= 0 or new_pending_tenure == 0 else "ACTIVE"

    future_sched = db.table('loan_repayments') \
        .select('due_date') \
        .eq('loan_id', lid) \
        .eq('status', 'SCHEDULED') \
        .order('installment_number') \
        .limit(1) \
        .execute()
    new_next_date = future_sched.data[0]['due_date'] if future_sched.data else str(today)

    db.table('loans').update({
        "pending_principal": new_pending_principal,
        "pending_tenure_months": new_pending_tenure,
        "principal_paid": new_principal_paid,
        "interest_paid": new_interest_paid,
        "next_emi_date": new_next_date,
        "status": loan_status
    }).eq('loan_id', lid).execute()

    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": aid,
        "event_type": f"LOAN_EMI_{tx_type}",
        "amount": -emi_amount if tx_type == 'DEBIT' else emi_amount,
        "description": f"EMI #{inst_num} cleared for {loan['loan_name']} (Pending Principal: ₹{new_pending_principal:,.2f})."
    }).execute()

    return {
        "status": "SUCCESS",
        "message": f"Installment #{inst_num} of ₹{emi_amount:,.2f} successfully settled from {acc_name}.",
        "new_pending_principal": new_pending_principal,
        "new_pending_tenure": new_pending_tenure,
        "loan_status": loan_status,
        "next_due_date": new_next_date
    }