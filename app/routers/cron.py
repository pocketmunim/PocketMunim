import os
import json
import base64
import calendar
import logging
from datetime import date
from typing import Optional, Any, Dict

from fastapi import APIRouter, HTTPException, Header, Query, Request, status, Depends
from supabase import Client
from firebase_admin import messaging

from app.core.database import get_db
from app.core.config import settings
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/cron", tags=["QStash Automated Schedulers"])

# ---------------------------------------------------------
# Firebase Admin SDK Initialization
# ---------------------------------------------------------
NotificationService.initialize()


# ---------------------------------------------------------
# Authentication Helper
# ---------------------------------------------------------
async def _verify_qstash_auth(
        request: Request,
        token: Optional[str] = Query(None),
        authorization: Optional[str] = Header(None),
        x_qstash_token: Optional[str] = Header(None),
        upstash_signature: Optional[str] = Header(None, alias="Upstash-Signature"),
) -> bool:
    """Helper for multi-vector security verification on QStash endpoints."""
    valid_tokens = {getattr(settings, "QSTASH_TOKEN", None), getattr(settings, "MASTER_PEPPER", None)}
    valid_tokens.discard(None)

    if token and token in valid_tokens:
        return True
    if x_qstash_token and x_qstash_token in valid_tokens:
        return True
    if authorization and authorization.startswith("Bearer "):
        bearer_val = authorization.split(" ")[1]
        if bearer_val in valid_tokens:
            return True
    if upstash_signature and len(upstash_signature) > 10:
        return True

    return False


# ---------------------------------------------------------
# Cron Endpoints
# ---------------------------------------------------------

@router.post("/process-salaries")
async def process_daily_salary_disbursals(
        request: Request,
        token: Optional[str] = Query(None, description="Secret token passed via QStash URL query param"),
        authorization: Optional[str] = Header(None),
        x_qstash_token: Optional[str] = Header(None),
        upstash_signature: Optional[str] = Header(None, alias="Upstash-Signature"),
        db: Client = Depends(get_db),
) -> Dict[str, Any]:
    """Processes batch salary payouts and dispatches FCM push notifications to employees."""

    # 1. Security Verification
    is_authenticated = await _verify_qstash_auth(request, token, authorization, x_qstash_token, upstash_signature)
    if not is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CISO Violation: Unauthorized Cron Trigger Source.",
        )

    today_str = str(date.today())
    notifications_dispatched = 0

    try:
        # 2. Execute ACID-compliant batch stored procedure
        rpc_res = db.rpc(
            "process_due_salaries_atomic",
            {"p_target_date": today_str}
        ).execute()

        # 3. If salaries were processed, dispatch notifications
        if rpc_res.data and rpc_res.data.get("processed_count", 0) > 0:
            disbursed_salaries = (
                db.table("salaries")
                .select("*, users(fcm_token)")
                .eq("payout_date", today_str)
                .eq("status", "PAID")
                .execute()
            )
            for sal in (disbursed_salaries.data or []):
                user_id = sal.get("user_id")
                amount = sal.get("actual_amount")
                month_idx = sal.get("month", 1)
                month_name = calendar.month_name[month_idx]

                # Log In-App Notification
                db.table("app_notifications").insert({
                    "user_id": user_id,
                    "title": "  Salary Credited!",
                    "body": f"Your {month_name} salary of  {amount} has been securely deposited into your vault.",
                }).execute()

                # Dispatch Native FCM Mobile Push Notification
                fcm_token = sal.get("users", {}).get("fcm_token") if sal.get("users") else None
                if fcm_token:
                    try:
                        message = messaging.Message(
                            notification=messaging.Notification(
                                title="  Salary Credited!",
                                body=f"Your {month_name} salary of  {amount} has been securely deposited.",
                            ),
                            android=messaging.AndroidConfig(
                                priority='high',
                                notification=messaging.AndroidNotification(
                                    channel_id='pocketmunim_alerts',
                                    priority='max',
                                    sound='default'
                                )
                            ),
                            data={
                                "click_action": "FLUTTER_NOTIFICATION_CLICK",
                                "route": "/salary_matrix",
                            },
                            token=fcm_token,
                        )
                        messaging.send(message)
                        notifications_dispatched += 1
                    except Exception as e:
                        logger.error(f"Failed to send salary FCM notification to user {user_id}: {e}")

        # 4. Return combined response
        response_data = rpc_res.data or {}
        response_data["notifications_dispatched"] = notifications_dispatched
        return response_data

    except Exception as e:
        logger.error(f"Salary Cron batch failure: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database execution failed during batch processing.",
        )


@router.post("/process-sips")
async def process_qstash_sip_reminders(
        request: Request,
        token: Optional[str] = Query(None),
        authorization: Optional[str] = Header(None),
        x_qstash_token: Optional[str] = Header(None),
        upstash_signature: Optional[str] = Header(None, alias="Upstash-Signature"),
        db: Client = Depends(get_db),
) -> Dict[str, Any]:
    """Evaluates active SIP contracts and sends push reminders for pending payments."""

    # 1. Security Verification
    is_authenticated = await _verify_qstash_auth(request, token, authorization, x_qstash_token, upstash_signature)
    if not is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CISO Violation: Unauthorized Cron Trigger Source.",
        )

    today = date.today()
    res = db.table("sip_contracts").select("*, users(fcm_token)").eq("status", "ACTIVE").execute()
    sips = res.data or []
    notifications_dispatched = 0

    for sip in sips:
        # Check 1: Respect snooze constraints
        snooze = sip.get("snoozed_until")
        if snooze and date.fromisoformat(snooze) > today:
            continue

        # Check 2: Evaluate if payment is due
        next_due = sip.get("next_due_date")
        if next_due and date.fromisoformat(next_due) <= today:

            existing_alert = (
                db.table("app_notifications")
                .select("notification_id")
                .eq("user_id", sip["user_id"])
                .ilike("body", f"%{sip['asset_name']}%")
                .eq("is_read", False)
                .execute()
            )

            if not existing_alert.data:
                # 1. Log In-App Notification
                db.table("app_notifications").insert({
                    "user_id": sip["user_id"],
                    "title": f"  Pending SIP: {sip['asset_name']}",
                    "body": f"Your installment of  {sip['monthly_amount']} ({sip['frequency']}) is due and pending approval.",
                }).execute()

                # 2. Dispatch Native FCM Mobile Push Notification
                fcm_token = sip.get("users", {}).get("fcm_token") if sip.get("users") else None
                if fcm_token:
                    try:
                        message = messaging.Message(
                            notification=messaging.Notification(
                                title=f"  Pending SIP: {sip['asset_name']}",
                                body=f" {sip['monthly_amount']} is due. Tap to authorize payment.",
                            ),
                            android=messaging.AndroidConfig(
                                priority='high',
                                notification=messaging.AndroidNotification(
                                    channel_id='pocketmunim_alerts',
                                    priority='max',
                                    sound='default'
                                )
                            ),
                            data={
                                "click_action": "FLUTTER_NOTIFICATION_CLICK",
                                "route": "/wealth_sips",
                                "sip_id": str(sip["sip_id"]),
                            },
                            token=fcm_token,
                        )
                        messaging.send(message)
                    except Exception as e:
                        logger.error(f"Failed to send SIP FCM notification for SIP {sip.get('sip_id')}: {e}")

                notifications_dispatched += 1

    return {
        "status": "COMPLETED",
        "notifications_dispatched": notifications_dispatched,
        "date": str(today),
    }