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

    # 1. Fetch User Identity & Avatar
    user_res = db.table('users').select('full_name, avatar_url').eq('user_id', uid).execute()
    user_name = user_res.data[0]['full_name'] if user_res.data else "Commander"
    avatar_url = user_res.data[0].get('avatar_url') if user_res.data else None

    # 2. Aggregate Active Accounts (Vaults)
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

    # 3. Aggregate Liabilities
    loans_res = db.table('loans').select('pending_principal').eq('user_id', uid).eq('status', 'ACTIVE').eq('loan_type', 'BORROWED').execute()
    total_liabilities = sum(float(l.get('pending_principal', 0)) for l in (loans_res.data or []))

    # 4. Calculate Current Month Inflows
    start_d = f"{today.year:04d}-{today.month:02d}-01"
    _, last_day = calendar.monthrange(today.year, today.month)
    end_d = f"{today.year:04d}-{today.month:02d}-{last_day:02d}"

    tx_res = db.table('transactions').select('amount').eq('user_id', uid).eq('type', 'CREDIT').gte('transaction_date', start_d).lte('transaction_date', end_d).execute()
    total_income = sum(float(tx['amount']) for tx in (tx_res.data or []))

    # 5. Fetch EXACTLY the last 5 realized transactions by created_at DESC (As requested)
    recent_tx_res = (
        db.table('transactions')
        .select('*')
        .eq('user_id', uid)
        .in_('status', ['CREDITED', 'DEBITED'])
        .order('created_at', desc=True)
        .limit(5)
        .execute()
    )
    recent_activity = recent_tx_res.data or []

    return {
        "success": True,
        "data": {
            "user_name": user_name,
            "avatar_url": avatar_url,
            "total_liquidity": total_liquidity,
            "total_liabilities": total_liabilities,
            "default_vault": default_vault,
            "active_vaults_count": len(accounts),
            "current_month_name": calendar.month_name[today.month],
            "month_metrics": {
                "total_income": total_income
            },
            "recent_activity": recent_activity
        }
    }