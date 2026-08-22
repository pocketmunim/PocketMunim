import os
import hmac
import hashlib
import time
from fastapi import Request, HTTPException, status, Depends
from app.core.database import get_db
from supabase import Client

# Read secret key from environment variable with fallback
ZERO_TRUST_SECRET = os.getenv("ZERO_TRUST_SECRET", "IFIS_ZERO_TRUST_SECRET_KEY_PROD_2026")
MAX_DRIFT_SECONDS = 300  # 5 minutes replay window

async def verify_zero_trust_signature(request: Request, db: Client = Depends(get_db)):
    # Read raw body bytes
    raw_body = await request.body()
    payload = raw_body.decode("utf-8") if raw_body else ""

    # Case-insensitive header lookup
    headers = {k.lower(): v for k, v in request.headers.items()}

    device_uuid = (
        headers.get("x-device-uuid")
        or headers.get("x-device-id")
        or headers.get("device-uuid")
    )
    timestamp_str = (
        headers.get("x-timestamp")
        or headers.get("x-request-timestamp")
        or headers.get("timestamp")
    )
    nonce = (
        headers.get("x-nonce")
        or headers.get("x-request-nonce")
        or headers.get("nonce")
    )
    client_signature = (
        headers.get("x-signature")
        or headers.get("x-hmac-signature")
        or headers.get("signature")
    )

    if not all([device_uuid, timestamp_str, nonce, client_signature]):
        missing = []
        if not device_uuid: missing.append("X-Device-UUID")
        if not timestamp_str: missing.append("X-Timestamp")
        if not nonce: missing.append("X-Nonce")
        if not client_signature: missing.append("X-Signature")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Incomplete cryptographic security headers. Missing: {', '.join(missing)}"
        )

    # 1. Timestamp Drift Validation (Replay Protection)
    try:
        req_timestamp = int(timestamp_str)
        # If timestamp is in milliseconds (13 digits), convert to seconds
        if req_timestamp > 1e11:
            req_timestamp_sec = req_timestamp / 1000.0
        else:
            req_timestamp_sec = float(req_timestamp)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid timestamp format in security header."
        )

    now_sec = time.time()
    if abs(now_sec - req_timestamp_sec) > MAX_DRIFT_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cryptographic timestamp expired or clock skew too high."
        )

    # 2. Nonce Anti-Replay Check
    try:
        nonce_res = db.table("security_nonces").select("nonce").eq("nonce", nonce).execute()
        if nonce_res.data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Security Nonce Replay Detected! Request rejected."
            )
        # Record nonce
        db.table("security_nonces").insert({
            "nonce": nonce,
            "device_uuid": device_uuid
        }).execute()
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        # If table check fails due to DB, continue or log error

    # 3. Canonical String & HMAC Signature Verification
    # Canonical string: deviceUUID:timestamp:nonce:payload
    canonical_string = f"{device_uuid}:{timestamp_str}:{nonce}:{payload}"
    expected_signature = hmac.new(
        ZERO_TRUST_SECRET.encode("utf-8"),
        canonical_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_signature.lower(), client_signature.lower()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cryptographic Signature Mismatch. Access Denied."
        )

    return True