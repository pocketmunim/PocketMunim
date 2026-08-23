import hmac
import hashlib
import time
import os
from fastapi import Request, HTTPException, Security, status, Depends
from fastapi.security.api_key import APIKeyHeader
from app.core.database import get_db
from supabase import Client

API_SECRET = os.getenv("ZERO_TRUST_SECRET", "pocketmunim-super-secure-key-2026")
SIGNATURE_HEADER = APIKeyHeader(name="X-Zero-Trust-Signature", auto_error=False)
TIMESTAMP_HEADER = APIKeyHeader(name="X-Request-Timestamp", auto_error=False)
NONCE_HEADER = APIKeyHeader(name="X-Request-Nonce", auto_error=False)
DEVICE_HEADER = APIKeyHeader(name="X-Device-UUID", auto_error=False)

MAX_CLOCK_DRIFT_SECONDS = 300  # 5-minute validity window


async def verify_zero_trust_signature(
    request: Request,
    signature: str = Security(SIGNATURE_HEADER),
    timestamp: str = Security(TIMESTAMP_HEADER),
    nonce: str = Security(NONCE_HEADER),
    device_uuid: str = Security(DEVICE_HEADER),
    db: Client = Depends(get_db),
):
    """Zero-Trust cryptographic signature and distributed anti-replay validation guard."""
    if not signature or not timestamp or not nonce:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing required Zero-Trust authentication headers (Signature, Timestamp, Nonce).",
        )

    current_time = time.time()

    # 1. Anti-Replay Timestamp Validation
    try:
        req_ts = float(timestamp)
        if abs(current_time - req_ts) > MAX_CLOCK_DRIFT_SECONDS:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Request expired or client clock out of sync.",
            )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed request timestamp.",
        )

    # 2. Distributed Database Nonce Anti-Replay Check
    try:
        db.table("security_nonces").insert({
            "nonce": nonce,
            "device_uuid": device_uuid or "UNKNOWN_DEVICE",
        }).execute()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Replay attack detected: Nonce has already been consumed.",
        )

    # 3. Cryptographic Signature Verification
    raw_body = await request.body()
    expected_sig = hmac.new(
        API_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid request signature or payload has been tampered with.",
        )