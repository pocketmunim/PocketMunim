from fastapi import APIRouter, Depends, HTTPException
from app.core.database import get_db
from app.core.security import verify_zero_trust_signature
from supabase import Client
from datetime import date
import calendar

router = APIRouter(prefix="/api/v1/dashboard", tags=["Command Dashboard Engine"])


@router.post(
    "/summary/{user_id}",
    dependencies=[Depends(verify_zero_trust_signature)]
)
async def get_dashboard_summary(user_id: str, db: Client = Depends(get_db)):
    uid = str(user_id)
    today = date.today()
    current_year = today.year
    current_month = today.month

    # 1. Fetch user profile
    u_res = db.table('users').select('full_name, currency').eq('user_id', uid).execute()
    if not u_res.data:
        raise HTTPException(status_code=404, detail="User identity not provisioned in vault.")
    user = u_res.data[0]

    # 2. Fetch all registered liquidity accounts
    acc_res = db.table('accounts').select('*').eq('user_id', uid).eq('is_active', True).order('is_default',
                                                                                              desc=True).execute()
    accounts = acc_res.data or []
    total_liquidity = sum(float(a['balance']) for a in accounts)
    default_acc = next((a for a in accounts if a['is_default']), accounts[0] if accounts else None)

    # 3. Fetch current month salary status
    sal_res = db.table('salaries').select('*').eq('user_id', uid).eq('year', current_year).eq('month',
                                                                                              current_month).execute()
    current_salary = sal_res.data[0] if sal_res.data else None

    # 4. Fetch transactions for month metrics & recent 5 ledger events
    start_d = f"{current_year:04d}-{current_month:02d}-01"
    _, last_day = calendar.monthrange(current_year, current_month)
    end_d = f"{current_year:04d}-{current_month:02d}-{last_day:02d}"

    # Recent activity feed strictly capped at the last 5 transactions
    tx_res = db.table('transactions') \
        .select('*') \
        .eq('user_id', uid) \
        .order('created_at', desc=True) \
        .limit(5) \
        .execute()
    recent_txs = tx_res.data or []

    # Monthly calculation metrics for income & spend
    all_tx_month = db.table('transactions') \
                       .select('amount, type, status, category') \
                       .eq('user_id', uid) \
                       .gte('transaction_date', start_d) \
                       .lte('transaction_date', end_d) \
                       .execute().data or []

    month_spent = sum(
        float(t['amount']) for t in all_tx_month
        if t['type'] in ['DEBIT', 'EXPENSE'] and t['category'] != 'Vault Transfer'
    )
    month_income = sum(
        float(t['amount']) for t in all_tx_month
        if t['type'] in ['CREDIT', 'SALARY', 'INCOME'] and t['category'] != 'Vault Transfer'
    )

    return {
        "status": "SUCCESS",
        "user_name": user.get('full_name', 'Commander'),
        "currency": user.get('currency', 'INR'),
        "total_liquidity": total_liquidity,
        "active_vaults_count": len(accounts),
        "default_vault": default_acc['account_name'] if default_acc else "None",
        "current_month_name": calendar.month_name[current_month],
        "current_salary": {
            "amount": float(current_salary['actual_amount']) if current_salary else 0.0,
            "status": current_salary['status'] if current_salary else "UNSCHEDULED",
            "payout_date": current_salary['payout_date'] if current_salary else str(today)
        },
        "month_metrics": {
            "total_income": month_income,
            "total_spent": month_spent,
            "net_surplus": month_income - month_spent
        },
        "recent_activity": recent_txs
    }