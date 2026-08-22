from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas.salary import SalaryMatrixResponse, SalaryOverrideRequest, SettleSalaryRequest, SalaryMonthItem
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from app.services.holiday_service import HolidayService
from supabase import Client
from datetime import date
import calendar

router = APIRouter(prefix="/api/v1/salary", tags=["Salary & Dispersal Engine"])


@router.post(
    "/matrix/{user_id}/{year}",
    response_model=SalaryMatrixResponse,
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def get_salary_matrix(user_id: str, year: int, db: Client = Depends(get_db)):
    sal_res = db.table('salaries').select('*').eq('user_id', user_id).eq('year', year).order('month').execute()
    salaries = sal_res.data or []

    start_dt = f"{year}-01-01"
    end_dt = f"{year}-12-31"
    tx_res = db.table('transactions').select('*').eq('user_id', user_id).gte('transaction_date', start_dt).lte(
        'transaction_date', end_dt).execute()
    txs = tx_res.data or []

    month_items = []
    base_total = 0.0
    disbursed_total = 0.0
    scheduled_total = 0.0

    today = date.today()

    for s in salaries:
        m = s['month']
        base = float(s['base_amount'])
        actual = float(s['actual_amount'])
        current_status = s['status']
        base_total += base

        if current_status in ['PAID', 'SETTLED']:
            disbursed_total += actual
        else:
            scheduled_total += actual

        # Filter transactions for this specific month
        m_txs = [t for t in txs if int(t['transaction_date'].split('-')[1]) == m]

        # Other income excludes the core automated salary line
        m_other_income = sum(
            float(t['amount']) for t in m_txs
            if t['type'] in ['INCOME'] and t['status'] == 'CREDITED'
        )
        total_month_income = actual + m_other_income
        m_expense = sum(float(t['amount']) for t in m_txs if t['type'] == 'EXPENSE')
        net_margin = total_month_income - m_expense

        payout_d = date.fromisoformat(s['payout_date'])

        # ELIGIBILITY RULE:
        # 1. Must be ALREADY PAID (status == 'PAID')
        # 2. Payout date is in the past
        # 3. Logged expenses do not exceed total incoming funds (Salary + Other Income)
        can_settle = (current_status == 'PAID') and (payout_d < today) and (m_expense <= total_month_income)

        month_items.append(SalaryMonthItem(
            salary_id=s['salary_id'],
            year=s['year'],
            month=m,
            base_amount=base,
            actual_amount=actual,
            payout_date=payout_d,
            status=current_status,
            is_custom_override=s.get('is_custom_override', False),
            total_income=total_month_income,
            total_expense=m_expense,
            net_margin=net_margin,
            can_settle=can_settle
        ))

    return SalaryMatrixResponse(
        status="SUCCESS",
        year=year,
        annual_base_total=base_total,
        total_disbursed=disbursed_total,
        total_scheduled=scheduled_total,
        months=month_items
    )


@router.post(
    "/override",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def override_salary(payload: SalaryOverrideRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    sal_res = db.table('salaries').select('*').eq('user_id', uid).eq('year', payload.year).eq('month',
                                                                                              payload.month).execute()
    if not sal_res.data:
        raise HTTPException(status_code=404, detail="Salary entry not found for specified cycle.")

    sal = sal_res.data[0]
    old_actual = float(sal['actual_amount'])
    old_status = sal['status']

    effective_override_date = await HolidayService.get_effective_payout_date(payload.new_payout_date)

    db.table('salaries').update({
        "actual_amount": payload.new_amount,
        "payout_date": str(effective_override_date),
        "is_custom_override": True
    }).eq('salary_id', sal['salary_id']).execute()

    if old_status in ['PAID', 'SETTLED'] and sal.get('account_id'):
        diff = payload.new_amount - old_actual
        if diff != 0:
            acc_res = db.table('accounts').select('balance').eq('account_id', sal['account_id']).execute()
            if acc_res.data:
                curr_bal = float(acc_res.data[0]['balance'])
                db.table('accounts').update({"balance": curr_bal + diff}).eq('account_id', sal['account_id']).execute()

                db.table('account_logs').insert({
                    "user_id": uid,
                    "account_id": sal['account_id'],
                    "event_type": "SALARY_OVERRIDE_ADJUSTMENT",
                    "amount": diff,
                    "description": f"Differential adjustment for {calendar.month_name[payload.month]} {payload.year} salary."
                }).execute()

        db.table('transactions').update({
            "amount": payload.new_amount,
            "transaction_date": str(effective_override_date)
        }).eq('salary_id', sal['salary_id']).execute()

    return {
        "status": "SUCCESS",
        "message": f"Salary for {calendar.month_name[payload.month]} updated.",
        "effective_payout_date": str(effective_override_date)
    }


@router.post(
    "/settle",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def settle_salary(payload: SettleSalaryRequest, db: Client = Depends(get_db)):
    uid = str(payload.user_id)
    sid = str(payload.salary_id)

    sal_res = db.table('salaries').select('*').eq('salary_id', sid).eq('user_id', uid).execute()
    if not sal_res.data:
        raise HTTPException(status_code=404, detail="Salary record not found.")

    sal = sal_res.data[0]

    # 1. Verification: Must be currently in 'PAID' state to settle
    if sal['status'] != 'PAID':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Settlement Invalid: Salary must be in PAID state to settle (Current: {sal['status']})."
        )

    yr = sal['year']
    m = sal['month']
    salary_amount = float(sal['actual_amount'])

    start_d = f"{yr}-{m:02d}-01"
    end_d = f"{yr}-{m:02d}-{calendar.monthrange(yr, m)[1]:02d}"

    # 2. Fetch transactions for the month
    tx_res = db.table('transactions').select('*').eq('user_id', uid).gte('transaction_date', start_d).lte(
        'transaction_date', end_d).execute()
    txs = tx_res.data or []

    m_other_income = sum(
        float(t['amount']) for t in txs
        if t['type'] in ['INCOME'] and t['status'] == 'CREDITED'
    )
    total_inflow = salary_amount + m_other_income
    total_expense = sum(float(t['amount']) for t in txs if t['type'] == 'EXPENSE')

    # 3. Verification: Expense <= Overall Inflow (Salary + Other Income)
    if total_expense > total_inflow:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Settlement Blocked: Total expenses (₹{total_expense:,.2f}) exceed total incoming funds (₹{total_inflow:,.2f})."
        )

    target_acc = str(payload.target_account_id) if payload.target_account_id else sal.get('account_id')

    # 4. Mark Salary status as SETTLED
    db.table('salaries').update({
        "status": "SETTLED",
        "account_id": target_acc
    }).eq('salary_id', sid).execute()

    # 5. Record Month Closing Audit Log
    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": target_acc,
        "event_type": "MONTH_SETTLEMENT_CLOSED",
        "amount": salary_amount,
        "description": f"Month closed and settled for {calendar.month_name[m]} {yr} (Total Inflow: ₹{total_inflow:,.2f}, Logged Outflow: ₹{total_expense:,.2f})."
    }).execute()

    return {
        "status": "SETTLED",
        "message": f"Month {calendar.month_name[m]} {yr} successfully settled and balanced."
    }