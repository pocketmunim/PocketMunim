from fastapi import APIRouter, Depends
from supabase import Client
from datetime import date
import calendar

from app.core.database import get_db
from app.core.security import verify_zero_trust_signature

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


@router.post("/summary/{user_id}", dependencies=[Depends(verify_zero_trust_signature)])
async def get_dashboard_summary(user_id: str, db: Client = Depends(get_db)):
    uid = str(user_id)
    today = date.today()

    # 1. Fetch User Identity
    user_res = db.table('users').select('full_name').eq('user_id', uid).execute()
    user_name = user_res.data[0]['full_name'] if user_res.data else "Commander"

    # 2. Aggregate Active Liquidity Vaults
    acc_res = db.table('accounts').select('*').eq('user_id', uid).eq('is_active', True).execute()
    accounts = acc_res.data or []
    total_liquidity = sum(float(a.get('balance', 0)) for a in accounts)

    default_vault = "N/A"
    for a in accounts:
        if a.get('is_default'):
            default_vault = a['account_name']
            break
    if default_vault == "N/A" and accounts:
        default_vault = accounts[0]['account_name']

    # 3. Aggregate Active Debt Liabilities (FIXES THE DEBT STRESS GAUGE)
    loans_res = db.table('loans').select('pending_principal').eq('user_id', uid).eq('status', 'ACTIVE').eq('loan_type',
                                                                                                           'BORROWED').execute()
    total_liabilities = sum(float(l.get('pending_principal', 0)) for l in (loans_res.data or []))

    # 4. Calculate Current Month Inflows
    start_d = f"{today.year:04d}-{today.month:02d}-01"
    _, last_day = calendar.monthrange(today.year, today.month)
    end_d = f"{today.year:04d}-{today.month:02d}-{last_day:02d}"

    tx_res = db.table('transactions').select('*').eq('user_id', uid).gte('transaction_date', start_d).lte(
        'transaction_date', end_d).execute()
    txs = tx_res.data or []
    month_income = sum(float(t.get('amount', 0)) for t in txs if
                       t.get('type') in ['CREDIT', 'INCOME'] and t.get('status') == 'CREDITED')

    # 5. Fetch Current Salary Pulse
    sal_res = db.table('salaries').select('*').eq('user_id', uid).eq('year', today.year).eq('month',
                                                                                            today.month).execute()
    current_salary = sal_res.data[0] if sal_res.data else {}

    # 6. Fetch Recent Ledger Feed
    recent_res = db.table('transactions').select('*').eq('user_id', uid).order('transaction_date', desc=True).limit(
        5).execute()
    recent_activity = recent_res.data or []

    return {
        "status": "SUCCESS",
        "data": {
            "user_name": user_name,
            "total_liquidity": total_liquidity,
            "total_liabilities": total_liabilities,
            "default_vault": default_vault,
            "active_vaults_count": len(accounts),
            "current_month_name": calendar.month_name[today.month],
            "month_metrics": {"total_income": month_income},
            "current_salary": current_salary,
            "recent_activity": recent_activity
        }
    }