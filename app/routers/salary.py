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

    start_dt = f"{year:04d}-01-01"
    _, last_day_of_dec = calendar.monthrange(year, 12)
    end_dt = f"{year:04d}-12-{last_day_of_dec:02d}"

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

        m_txs = [t for t in txs if int(t['transaction_date'].split('-')[1]) == m]

        m_other_income = sum(
            float(t['amount']) for t in m_txs
            if t['type'] in ['INCOME', 'CREDIT'] and t['status'] == 'CREDITED'
        )
        total_month_income = actual + m_other_income
        m_debit = sum(float(t['amount']) for t in m_txs if t['type'] in ['DEBIT', 'EXPENSE'])
        net_margin = total_month_income - m_debit

        payout_d = date.fromisoformat(s['payout_date'])

        # Settle Eligibility: Must be PAID in a past month, and total debits <= total income
        can_settle = (current_status == 'PAID') and (payout_d < today) and (m_debit <= total_month_income)

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
            total_expense=m_debit,
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

    if sal['status'] != 'PAID':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Settlement Invalid: Salary must be in PAID state to settle (Current: {sal['status']})."
        )

    yr = sal['year']
    m = sal['month']
    salary_amount = float(sal['actual_amount'])

    start_d = f"{yr:04d}-{m:02d}-01"
    _, last_day_of_month = calendar.monthrange(yr, m)
    end_d = f"{yr:04d}-{m:02d}-{last_day_of_month:02d}"

    # Fetch month transactions to calculate net margin
    tx_res = db.table('transactions').select('*').eq('user_id', uid).gte('transaction_date', start_d).lte(
        'transaction_date', end_d).execute()
    txs = tx_res.data or []

    m_other_income = sum(
        float(t['amount']) for t in txs
        if t['type'] in ['INCOME', 'CREDIT'] and t['status'] == 'CREDITED'
    )
    total_inflow = salary_amount + m_other_income
    total_debits = sum(float(t['amount']) for t in txs if t['type'] in ['DEBIT', 'EXPENSE'])

    if total_debits > total_inflow:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Settlement Blocked: Total debits (₹{total_debits:,.2f}) exceed total incoming funds (₹{total_inflow:,.2f})."
        )

    # Net settlement amount to deduct/debit
    settlement_debit_amount = total_inflow - total_debits
    target_acc = str(payload.target_account_id) if payload.target_account_id else sal.get('account_id')

    # 1. Deduct amount from accounts balance
    if settlement_debit_amount > 0 and target_acc:
        acc_res = db.table('accounts').select('balance').eq('account_id', target_acc).execute()
        if acc_res.data:
            curr_bal = float(acc_res.data[0]['balance'])
            new_bal = curr_bal - settlement_debit_amount
            db.table('accounts').update({"balance": new_bal}).eq('account_id', target_acc).execute()

        # 2. Make DEBIT entry in transactions table (Type strictly = DEBIT)
        db.table('transactions').insert({
            "user_id": uid,
            "account_id": target_acc,
            "salary_id": sid,
            "type": "DEBIT",
            "category": "Salary Settlement",
            "amount": settlement_debit_amount,
            "transaction_date": str(date.today()),
            "status": "CREDITED",
            "description": f"Bulk Month Settlement Sweep - {calendar.month_name[m]} {yr}"
        }).execute()

        # 3. Make audit entry in account_logs
        db.table('account_logs').insert({
            "user_id": uid,
            "account_id": target_acc,
            "event_type": "SALARY_MONTH_SETTLED_DEBIT",
            "amount": -settlement_debit_amount,
            "description": f"Month closed and balance swept for {calendar.month_name[m]} {yr} (Deducted: ₹{settlement_debit_amount:,.2f})."
        }).execute()

    # 4. Update salary status to SETTLED
    db.table('salaries').update({
        "status": "SETTLED",
        "account_id": target_acc
    }).eq('salary_id', sid).execute()

    return {
        "status": "SETTLED",
        "settled_amount_debited": settlement_debit_amount,
        "message": f"Month {calendar.month_name[m]} {yr} settled. ₹{settlement_debit_amount:,.2f} debited from vault."
    }