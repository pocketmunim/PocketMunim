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
# Helper: Dispatch FCM & In-App Notification
# ---------------------------------------------------------
def _dispatch_sip_notification(db: Client, sip: dict, title: str, body: str):
    """Handles double-logging of notifications (In-App Database + Native Firebase Push)"""
    # 1. Log In-App Notification
    db.table("app_notifications").insert({
        "user_id": sip["user_id"],
        "title": title,
        "body": body,
    }).execute()

    # 2. Dispatch Native FCM Mobile Push Notification
    fcm_token = sip.get("users", {}).get("fcm_token") if sip.get("users") else None
    if fcm_token:
        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body,
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

    is_authenticated = await _verify_qstash_auth(request, token, authorization, x_qstash_token, upstash_signature)
    if not is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CISO Violation: Unauthorized Cron Trigger Source.",
        )

    today_str = str(date.today())
    notifications_dispatched = 0

    try:
        rpc_res = db.rpc(
            "process_due_salaries_atomic",
            {"p_target_date": today_str}
        ).execute()

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

                db.table("app_notifications").insert({
                    "user_id": user_id,
                    "title": "  Salary Credited!",
                    "body": f"Your {month_name} salary of  {amount} has been securely deposited into your vault.",
                }).execute()

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
    """Evaluates active SIP contracts and sends intelligent push reminders for pending payments."""

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
        next_due_str = sip.get("next_due_date")
        if not next_due_str:
            continue

        next_due_date = date.fromisoformat(next_due_str)
        snoozed_until_str = sip.get("snoozed_until")

        # 1. Self-Healing Snooze Logic:
        # If marked paid, next_due_date advances to the future. Stop snoozing automatically.
        if today < next_due_date:
            if snoozed_until_str:
                db.table("sip_contracts").update({"snoozed_until": None}).eq("sip_id", sip["sip_id"]).execute()
            continue

        # 2. Active Snooze Evaluation
        if snoozed_until_str:
            snoozed_date = date.fromisoformat(snoozed_until_str)
            if today < snoozed_date:
                continue  # Still actively snoozed; do nothing today
            else:
                # Snooze expired! Wake up and alert.
                title = f"  Snooze Expired: {sip['asset_name']}"
                body = f"Your snoozed SIP of  {sip['monthly_amount']} is due! Tap to pay. (Cycle: {next_due_str})"
                _dispatch_sip_notification(db, sip, title, body)
                notifications_dispatched += 1

                # Clear the snooze lock so standard deduplication rules apply tomorrow
                db.table("sip_contracts").update({"snoozed_until": None}).eq("sip_id", sip["sip_id"]).execute()
                continue

        # 3. Frequency-Aware Deduplication Rule
        freq = sip.get("frequency", "MONTHLY").upper()
        if freq == "DAILY":
            # Daily requires a prompt every single day, tied to the current calendar date
            cycle_identifier = f"Date: {today}"
        else:
            # Monthly/Yearly triggers once per specific financial cycle due date
            cycle_identifier = f"Cycle: {next_due_str}"

        # Check if we already alerted the user for this exact cycle
        existing_alerts = (
            db.table("app_notifications")
            .select("is_read")
            .eq("user_id", sip["user_id"])
            .ilike("body", f"%{sip['asset_name']}%")
            .ilike("body", f"%{cycle_identifier}%")
            .execute()
        )

        if not existing_alerts.data:
            # 4. Business Value Addition: Gamification & Escalation
            is_weekend = today.weekday() >= 5
            days_overdue = (today - next_due_date).days

            if days_overdue > 2:
                title = f"  OVERDUE SIP: {sip['asset_name']}"
                body = f"Your SIP of  {sip['monthly_amount']} is overdue by {days_overdue} days. Keep your wealth growing! ({cycle_identifier})"
            elif is_weekend:
                title = f"  Weekend SIP: {sip['asset_name']}"
                body = f"Markets are closed. Authorize your  {sip['monthly_amount']} SIP now for Monday execution. ({cycle_identifier})"
            else:
                invested = sip.get("total_invested", 0)
                milestone = f" You've invested  {invested} so far!" if invested > 0 else ""
                title = f"  Pending SIP: {sip['asset_name']}"
                body = f" {sip['monthly_amount']} is due. {milestone} ({cycle_identifier})"

            _dispatch_sip_notification(db, sip, title, body)
            notifications_dispatched += 1

    return {
        "status": "COMPLETED",
        "notifications_dispatched": notifications_dispatched,
        "date": str(today),
    }