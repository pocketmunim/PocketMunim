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

        # FIXED: Exclude the salary's own transaction to prevent double-counting in the matrix
        m_other_income = sum(
            float(t['amount']) for t in m_txs
            if t['type'] in ['INCOME', 'CREDIT'] and t['status'] == 'CREDITED' and t.get('salary_id') != s['salary_id']
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
    # Clean fallback for empty string account IDs to ensure proper UUID casting in Postgres
    target_aid = None
    if payload.target_account_id and str(payload.target_account_id).strip() != "":
        target_aid = str(payload.target_account_id)

    rpc_payload = {
        "user_id": str(payload.user_id),
        "salary_id": str(payload.salary_id),
        "target_account_id": target_aid
    }

    try:
        # SECURED: Defers entirety of multi-table updates to the ACID-compliant RPC
        res = db.rpc("settle_salary_atomic", {"payload": rpc_payload}).execute()

        data = res.data
        if isinstance(data, list) and len(data) > 0:
            data = data[0]

        return {"status": "SUCCESS", "data": data}
    except Exception as e:
        err_str = str(e)
        user_message = "Your salary settlement request could not be completed."

        if "already settled" in err_str.lower():
            user_message = "This salary cycle has already been settled and accounted for."
        elif "not found" in err_str.lower():
            user_message = "Account vault or salary record could not be found."

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=user_message
        )