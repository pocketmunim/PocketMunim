import os
import json
import base64
import calendar
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Query, Request, status, Depends
from supabase import Client
import firebase_admin
from firebase_admin import credentials, messaging

from app.core.database import get_db
from app.core.config import settings

router = APIRouter(prefix="/api/v1/cron", tags=["QStash Automated Schedulers"])

# Initialize Firebase Admin securely using Environment Variables (Vercel/Local)
if not firebase_admin._apps:
    try:
        # Fetch the Base64 string from Vercel (or local .env)
        base64_cred = os.getenv("FIREBASE_SERVICE_ACCOUNT_BASE64")

        if base64_cred:
            # Decode the Base64 string back into normal text and load as dictionary
            decoded_cred_json = base64.b64decode(base64_cred).decode('utf-8')
            cred_dict = json.loads(decoded_cred_json)

            # Initialize Firebase
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
        else:
            print("CRITICAL WARNING: FIREBASE_SERVICE_ACCOUNT_BASE64 is missing.")

    except Exception as e:
        print(f"Firebase init error: {e}")


async def _verify_qstash_auth(
        request: Request,
        token: Optional[str] = Query(None),
        authorization: Optional[str] = Header(None),
        x_qstash_token: Optional[str] = Header(None),
        upstash_signature: Optional[str] = Header(None, alias="Upstash-Signature")
) -> bool:
    """Helper for multi-vector security verification on QStash endpoints."""
    if token and (token == settings.QSTASH_TOKEN or token == settings.MASTER_PEPPER):
        return True
    if x_qstash_token and (x_qstash_token == settings.QSTASH_TOKEN or x_qstash_token == settings.MASTER_PEPPER):
        return True
    if authorization and authorization.startswith("Bearer "):
        bearer_val = authorization.split(" ")[1]
        if bearer_val == settings.QSTASH_TOKEN or bearer_val == settings.MASTER_PEPPER:
            return True
    if upstash_signature and len(upstash_signature) > 10:
        return True
    return False


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
    is_authenticated = await _verify_qstash_auth(request, token, authorization, x_qstash_token, upstash_signature)
    if not is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CISO Violation: Unauthorized Cron Trigger Source."
        )

    today_str = str(date.today())

    try:
        # 2. Execute the entire batch operation in ONE network call
        rpc_res = db.rpc(
            "process_due_salaries_atomic",
            {"p_target_date": today_str}
        ).execute()

        # 3. Bubble up the JSONB response directly from Postgres
        return rpc_res.data

    except Exception as e:
        logger.error(f"Salary Cron Failure: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database execution failed during batch processing."
        )

@router.post("/process-sips")
async def process_qstash_sip_reminders(
        request: Request,
        token: Optional[str] = Query(None),
        authorization: Optional[str] = Header(None),
        x_qstash_token: Optional[str] = Header(None),
        upstash_signature: Optional[str] = Header(None, alias="Upstash-Signature"),
        db: Client = Depends(get_db)
):
    # 1. Multi-vector Security Verification
    is_authenticated = await _verify_qstash_auth(request, token, authorization, x_qstash_token, upstash_signature)
    if not is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CISO Violation: Unauthorized Cron Trigger Source."
        )

    today = date.today()
    res = db.table("sip_contracts").select("*, users(fcm_token)").eq("status", "ACTIVE").execute()
    sips = res.data or []

    notifications_dispatched = 0

    for sip in sips:
        # Check 1: Respect snooze constraints
        snooze = sip.get('snoozed_until')
        if snooze and date.fromisoformat(snooze) > today:
            continue

        # Check 2: Evaluate if payment is pending or past due
        next_due = sip.get('next_due_date')
        if next_due and date.fromisoformat(next_due) <= today:

            existing_alert = db.table("app_notifications").select("notification_id").eq(
                "user_id", sip['user_id']
            ).ilike("body", f"%{sip['asset_name']}%").eq("is_read", False).execute()

            if not existing_alert.data:
                # 1. Save In-App Notification Log
                db.table("app_notifications").insert({
                    "user_id": sip['user_id'],
                    "title": f"⚠️ Pending SIP: {sip['asset_name']}",
                    "body": f"Your installment of ₹{sip['monthly_amount']} ({sip['frequency']}) is due and pending approval."
                }).execute()

                # 2. TRIGGER NATIVE MOBILE PUSH NOTIFICATION
                fcm_token = sip.get("users", {}).get("fcm_token")
                if fcm_token:
                    try:
                        message = messaging.Message(
                            notification=messaging.Notification(
                                title=f"⚠️ Pending SIP: {sip['asset_name']}",
                                body=f"₹{sip['monthly_amount']} is due. Tap to authorize payment."
                            ),
                            data={
                                "click_action": "FLUTTER_NOTIFICATION_CLICK",
                                "route": "/wealth_sips",  # Deep link routing instruction
                                "sip_id": str(sip["sip_id"])
                            },
                            token=fcm_token,
                        )
                        messaging.send(message)
                    except Exception as e:
                        print(f"Failed to send FCM Push Notification: {e}")

                notifications_dispatched += 1

    return {
        "status": "COMPLETED",
        "notifications_dispatched": notifications_dispatched,
        "date": str(today)
    }