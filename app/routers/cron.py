from fastapi import APIRouter, HTTPException, Header, Query, Request, status, Depends
from app.core.database import get_db
from app.core.config import settings
from supabase import Client
from datetime import date
from typing import Optional

router = APIRouter(prefix="/api/v1/cron", tags=["QStash Automated Schedulers"])

@router.post("/process-salaries")
async def process_daily_salary_disbursals(
    request: Request,
    token: Optional[str] = Query(None, description="Secret token passed via QStash URL query param"),
    authorization: Optional[str] = Header(None),
    x_qstash_token: Optional[str] = Header(None),
    upstash_signature: Optional[str] = Header(None, alias="Upstash-Signature"),
    db: Client = Depends(get_db)
):
    # 1. Multi-vector Security Verification
    is_authenticated = False

    # Check Query Parameter
    if token and (token == settings.QSTASH_TOKEN or token == settings.MASTER_PEPPER):
        is_authenticated = True

    # Check Custom Headers
    elif x_qstash_token and (x_qstash_token == settings.QSTASH_TOKEN or x_qstash_token == settings.MASTER_PEPPER):
        is_authenticated = True

    # Check Bearer Header
    elif authorization and authorization.startswith("Bearer "):
        bearer_val = authorization.split(" ")[1]
        if bearer_val == settings.QSTASH_TOKEN or bearer_val == settings.MASTER_PEPPER:
            is_authenticated = True

    # Check QStash Automatic Signature Header presence
    elif upstash_signature and len(upstash_signature) > 10:
        is_authenticated = True

    if not is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CISO Violation: Unauthorized Cron Trigger Source."
        )

    today_str = str(date.today())

    # 2. Fetch all scheduled salaries on or before today that are still 'SCHEDULED'
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
            # Credit account balance
            acc_res = db.table('accounts').select('balance').eq('account_id', acc_id).execute()
            if acc_res.data:
                curr_bal = float(acc_res.data[0]['balance'])
                db.table('accounts').update({"balance": curr_bal + amt}).eq('account_id', acc_id).execute()

        # Update salary & transaction status
        db.table('salaries').update({"status": "PAID", "paid_at": "now()"}).eq('salary_id', sid).execute()
        db.table('transactions').update({"status": "CREDITED"}).eq('salary_id', sid).execute()

        # Insert audit log
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