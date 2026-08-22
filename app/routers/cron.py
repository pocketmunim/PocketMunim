from fastapi import APIRouter, HTTPException, Header, status, Depends
from app.core.database import get_db
from app.core.config import settings
from supabase import Client
from datetime import date

router = APIRouter(prefix="/api/v1/cron", tags=["QStash Automated Schedulers"])

@router.post("/process-salaries")
async def process_daily_salary_disbursals(
    x_qstash_token: str = Header(None),
    db: Client = Depends(get_db)
):
    if x_qstash_token != settings.QSTASH_TOKEN and x_qstash_token != settings.MASTER_PEPPER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized Cron Source")

    today_str = str(date.today())

    # Fetch scheduled disbursals due on or before today
    pending_res = db.table('salaries').select('*').eq('status', 'SCHEDULED').lte('payout_date', today_str).execute()
    pending = pending_res.data or []

    disbursed_count = 0
    total_amount = 0.0

    for s in pending:
        sid = s['salary_id']
        uid = s['user_id']
        acc_id = s.get('account_id')
        amt = float(s['actual_amount'])

        if acc_id:
            acc_res = db.table('accounts').select('balance').eq('account_id', acc_id).execute()
            if acc_res.data:
                curr_bal = float(acc_res.data[0]['balance'])
                db.table('accounts').update({"balance": curr_bal + amt}).eq('account_id', acc_id).execute()

        db.table('salaries').update({"status": "PAID", "paid_at": "now()"}).eq('salary_id', sid).execute()
        db.table('transactions').update({"status": "CREDITED"}).eq('salary_id', sid).execute()

        if acc_id:
            db.table('account_logs').insert({
                "user_id": uid,
                "account_id": acc_id,
                "event_type": "QSTASH_AUTO_SALARY_CREDIT",
                "amount": amt,
                "description": f"Automated cron dispersal on payout date {s['payout_date']}."
            }).execute()

        disbursed_count += 1
        total_amount += amt

    return {
        "status": "COMPLETED",
        "processed_count": disbursed_count,
        "total_disbursed": total_amount,
        "date": today_str
    }