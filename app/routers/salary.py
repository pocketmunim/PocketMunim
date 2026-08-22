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
    tx_res = db.table('transactions').select('*').eq('user_id', user_id).gte('transaction_date', start_dt).lte('transaction_date', end_dt).execute()
    txs = tx_res.data or []

    month_items = []
    base_total = 0.0
    disbursed_total = 0.0
    scheduled_total = 0.0

    for s in salaries:
        m = s['month']
        base = float(s['base_amount'])
        actual = float(s['actual_amount'])
        base_total += base

        if s['status'] in ['PAID', 'SETTLED']:
            disbursed_total += actual
        else:
            scheduled_total += actual

        m_txs = [t for t in txs if int(t['transaction_date'].split('-')[1]) == m]
        m_income = sum(float(t['amount']) for t in m_txs if t['type'] in ['INCOME', 'SALARY'] and t['status'] == 'CREDITED')
        m_expense = sum(float(t['amount']) for t in m_txs if t['type'] == 'EXPENSE')
        net_margin = m_income - m_expense

        payout_d = date.fromisoformat(s['payout_date'])
        can_settle = (s['status'] == 'SCHEDULED') and (payout_d < date.today()) and (net_margin >= 0)

        month_items.append(SalaryMonthItem(
            salary_id=s['salary_id'],
            year=s['year'],
            month=m,
            base_amount=base,
            actual_amount=actual,
            payout_date=payout_d,
            status=s['status'],
            is_custom_override=s.get('is_custom_override', False),
            total_income=m_income,
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
    sal_res = db.table('salaries').select('*').eq('user_id', uid).eq('year', payload.year).eq('month', payload.month).execute()
    if not sal_res.data:
        raise HTTPException(status_code=404, detail="Salary entry not found for specified cycle.")

    sal = sal_res.data[0]
    old_actual = float(sal['actual_amount'])
    old_status = sal['status']

    # Auto-shift the override date if it hits a weekend or bank holiday
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
                    "description": f"Differential adjustment for {calendar.month_name[payload.month]} {payload.year} salary (Effective Date: {effective_override_date})."
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
    yr = sal['year']
    m = sal['month']

    start_d = f"{yr}-{m:02d}-01"
    end_d = f"{yr}-{m:02d}-{calendar.monthrange(yr, m)[1]:02d}"

    tx_res = db.table('transactions').select('*').eq('user_id', uid).gte('transaction_date', start_d).lte('transaction_date', end_d).execute()
    txs = tx_res.data or []

    m_income = sum(float(t['amount']) for t in txs if t['type'] in ['INCOME', 'SALARY'] and t['status'] == 'CREDITED')
    m_expense = sum(float(t['amount']) for t in txs if t['type'] == 'EXPENSE')

    if m_expense > (m_income + float(sal['actual_amount'])):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Settlement Blocked: Total monthly expenses (₹{m_expense:,.2f}) exceeded earnings (₹{m_income:,.2f})."
        )

    target_acc = str(payload.target_account_id) if payload.target_account_id else sal.get('account_id')
    amount_to_credit = float(sal['actual_amount'])

    acc_res = db.table('accounts').select('balance').eq('account_id', target_acc).execute()
    if acc_res.data:
        curr_bal = float(acc_res.data[0]['balance'])
        db.table('accounts').update({"balance": curr_bal + amount_to_credit}).eq('account_id', target_acc).execute()

    db.table('salaries').update({
        "status": "SETTLED",
        "paid_at": "now()",
        "account_id": target_acc
    }).eq('salary_id', sid).execute()

    db.table('transactions').update({
        "status": "CREDITED",
        "account_id": target_acc
    }).eq('salary_id', sid).execute()

    db.table('account_logs').insert({
        "user_id": uid,
        "account_id": target_acc,
        "event_type": "SALARY_PAST_SETTLEMENT",
        "amount": amount_to_credit,
        "description": f"Past salary manual settlement for {calendar.month_name[m]} {yr}."
    }).execute()

    return {"status": "SETTLED", "message": f"Successfully settled ₹{amount_to_credit:,.2f}."}