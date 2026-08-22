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

        if l_type == 'BORROWED':
            total_liabilities += p_amt
        else:
            total_receivables += p_amt

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
            is_current_month_paid=is_cur_paid,
            has_pending_past_emis=has_pending_past_emis,
            pending_past_emis_count=pending_past_emis_count,
            pending_past_emis_total=round(pending_past_emis_total, 2)
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

    # 1. Deduplication Guard
    existing = db.table('loans').select('loan_id').eq('user_id', uid).ilike('loan_name', sanitized_name).execute()
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A loan titled '{sanitized_name}' already exists. Please use a unique title."
        )

    # 2. Resolve Vault Account for Disbursement
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

    # 3. Solvency Guard for LENT loans (Money given out must not exceed bank balance)
    if payload.loan_type.value == "LENT" and curr_balance < principal:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance in {acc_name} to lend ₹{principal:,.2f}. Available balance: ₹{curr_balance:,.2f}."
        )

    # 4. Calculate EMI & Amortization Plan
    monthly_emi = LoanService.calculate_reducing_emi(
        principal,
        payload.annual_interest_rate,
        payload.original_tenure_months
    )

    schedule = LoanService.generate_amortization_schedule(
        principal,
        payload.annual_interest_rate,
        payload.original_tenure_months,
        payload.first_emi_date,
        monthly_emi
    )

    total_repayment = sum(item['emi_amount'] for item in schedule)
    total_interest = round(total_repayment - principal, 2)

    # 5. Insert Master Loan Contract
    loan_insert = db.table('loans').insert({
        "user_id": uid,
        "account_id": aid,
        "loan_name": sanitized_name,
        "loan_type": payload.loan_type.value,
        "counterparty": payload.counterparty.strip(),
        "disbursement_date": str(payload.disbursement_date),
        "first_emi_date": str(payload.first_emi_date),
        "original_principal": principal,
        "pending_principal": principal,
        "annual_interest_rate": payload.annual_interest_rate,
        "original_tenure_months": payload.original_tenure_months,
        "pending_tenure_months": payload.original_tenure_months,
        "monthly_emi": monthly_emi,
        "total_interest_payable": total_interest,
        "principal_paid": 0.0,
        "interest_paid": 0.0,
        "next_emi_date": str(payload.first_emi_date),
        "status": "ACTIVE"
    }).execute()

    if not loan_insert.data:
        raise HTTPException(status_code=500, detail="Failed to initialize loan contract.")

    new_loan_id = loan_insert.data[0]['loan_id']

    for inst in schedule:
        inst['loan_id'] = new_loan_id
        inst['user_id'] = uid
        inst['account_id'] = aid

    db.table('loan_repayments').insert(schedule).execute()

    # 6. Apply Disbursement Flow
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
        "description": f"Loan Disbursement ({payload.loan_type.value}): {sanitized_name} - {payload.counterparty}"
    }).execute()

    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": aid,
        "event_type": f"LOAN_DISBURSEMENT_{tx_type}",
        "amount": principal if tx_type == "CREDIT" else -principal,
        "description": f"Loan disbursement processed for '{sanitized_name}' via {acc_name}."
    }).execute()

    return {
        "status": "SUCCESS",
        "message": f"Loan '{sanitized_name}' registered. {'Credited' if tx_type == 'CREDIT' else 'Debited'} ₹{principal:,.2f} on {acc_name}.",
        "loan_id": new_loan_id,
        "monthly_emi": monthly_emi
    }


@router.post(
    "/settle-past-emis",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def settle_past_emis(payload: SettlePastEMIsRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    lid = str(payload.loan_id)
    today = date.today()

    loan_res = db.table('loans').select('*').eq('loan_id', lid).eq('user_id', uid).execute()
    if not loan_res.data:
        raise HTTPException(status_code=404, detail="Loan not found.")
    loan = loan_res.data[0]

    past_emis_res = db.table('loan_repayments') \
        .select('*') \
        .eq('loan_id', lid) \
        .lte('due_date', str(today)) \
        .eq('status', 'SCHEDULED') \
        .order('installment_number') \
        .execute()

    past_emis = past_emis_res.data or []
    if not past_emis:
        return {"status": "SUCCESS", "message": "No pending past EMIs found for this loan."}

    total_settle_amount = sum(float(x['emi_amount']) for x in past_emis)
    total_principal_component = sum(float(x['principal_component']) for x in past_emis)
    total_interest_component = sum(float(x['interest_component']) for x in past_emis)
    last_past_emi = past_emis[-1]

    target_aid = payload.account_id or loan.get('account_id')
    acc_res = db.table('accounts').select('*').eq('account_id', target_aid).eq('user_id', uid).execute()
    if not acc_res.data:
        raise HTTPException(status_code=404, detail="Disbursement account not found.")
    acc = acc_res.data[0]
    aid = acc['account_id']
    acc_name = acc['account_name']
    curr_bal = float(acc['balance'])
    loan_type = loan['loan_type']

    if loan_type == 'BORROWED' and curr_bal < total_settle_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance in {acc_name} to settle {len(past_emis)} past EMIs. Required: ₹{total_settle_amount:,.2f}, Available: ₹{curr_bal:,.2f}."
        )

    new_bal = round(curr_bal - total_settle_amount if loan_type == 'BORROWED' else curr_bal + total_settle_amount, 2)
    tx_type = "DEBIT" if loan_type == 'BORROWED' else "CREDIT"
    db.table('accounts').update({"balance": new_bal}).eq('account_id', aid).execute()

    for item in past_emis:
        db.table('loan_repayments').update({
            "status": "PAID",
            "paid_at": str(today),
            "account_id": aid
        }).eq('repayment_id', item['repayment_id']).execute()

    db.table('transactions').insert({
        "user_id": uid,
        "account_id": aid,
        "account_name": acc_name,
        "type": tx_type,
        "category": "Debt & EMI",
        "amount": round(total_settle_amount, 2),
        "transaction_date": str(today),
        "status": "DEBITED" if tx_type == "DEBIT" else "CREDITED",
        "description": f"Batch Settlement ({len(past_emis)} Past EMIs) - {loan['loan_name']}"
    }).execute()

    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": aid,
        "event_type": "PAST_EMIS_BATCH_SETTLEMENT",
        "amount": -total_settle_amount if tx_type == "DEBIT" else total_settle_amount,
        "description": f"Settled {len(past_emis)} historical EMIs for '{loan['loan_name']}'."
    }).execute()

    new_pending_p = round(float(last_past_emi['remaining_principal_after']), 2)
    new_pending_t = max(0, int(loan['pending_tenure_months']) - len(past_emis))
    new_p_paid = round(float(loan['principal_paid']) + total_principal_component, 2)
    new_i_paid = round(float(loan['interest_paid']) + total_interest_component, 2)
    new_status = "CLOSED" if new_pending_p <= 0 or new_pending_t == 0 else "ACTIVE"

    next_sched = db.table('loan_repayments') \
        .select('due_date') \
        .eq('loan_id', lid) \
        .eq('status', 'SCHEDULED') \
        .order('installment_number') \
        .limit(1) \
        .execute()
    next_date = next_sched.data[0]['due_date'] if next_sched.data else str(today)

    db.table('loans').update({
        "pending_principal": new_pending_p,
        "pending_tenure_months": new_pending_t,
        "principal_paid": new_p_paid,
        "interest_paid": new_i_paid,
        "next_emi_date": next_date,
        "status": new_status
    }).eq('loan_id', lid).execute()

    return {
        "status": "SUCCESS",
        "message": f"Successfully settled {len(past_emis)} past EMIs (₹{total_settle_amount:,.2f}) for {loan['loan_name']}.",
        "settled_count": len(past_emis),
        "total_amount_debited": total_settle_amount,
        "new_pending_principal": new_pending_p
    }


@router.post(
    "/pay-emi",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def pay_loan_emi(payload: PayEMIRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    lid = str(payload.loan_id)

    loan_res = db.table('loans').select('*').eq('loan_id', lid).eq('user_id', uid).execute()
    if not loan_res.data:
        raise HTTPException(status_code=404, detail="Loan contract not found.")
    loan = loan_res.data[0]

    if loan['status'] != 'ACTIVE':
        raise HTTPException(status_code=400, detail="This loan is already CLOSED.")

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

    target_aid = payload.account_id or loan.get('account_id')
    acc_res = db.table('accounts').select('*').eq('account_id', target_aid).eq('user_id', uid).execute()
    if not acc_res.data:
        raise HTTPException(status_code=404, detail="No active liquidity vault available for EMI deduction.")

    acc = acc_res.data[0]
    aid = acc['account_id']
    acc_name = acc['account_name']
    curr_balance = float(acc['balance'])
    loan_type = loan['loan_type']

    if loan_type == 'BORROWED' and curr_balance < emi_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient balance in {acc_name}. Available: ₹{curr_balance:,.2f}, Required EMI: ₹{emi_amount:,.2f}."
        )

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
        "message": f"Installment #{inst_num} of ₹{emi_amount:,.2f} settled from {acc_name}.",
        "new_pending_principal": new_pending_principal,
        "new_pending_tenure": new_pending_tenure,
        "loan_status": loan_status,
        "next_due_date": new_next_date
    }