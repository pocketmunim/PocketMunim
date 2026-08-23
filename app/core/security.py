import hmac
import hashlib
import time
import os
from collections import OrderedDict
from fastapi import Request, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader

API_SECRET = os.getenv("ZERO_TRUST_SECRET", "pocketmunim-super-secure-key-2026")
SIGNATURE_HEADER = APIKeyHeader(name="X-Zero-Trust-Signature", auto_error=False)
TIMESTAMP_HEADER = APIKeyHeader(name="X-Request-Timestamp", auto_error=False)
NONCE_HEADER = APIKeyHeader(name="X-Request-Nonce", auto_error=False)

# In-memory LRU Nonce Cache to prevent Replay Attacks (10,000 capacity)
SEEN_NONCES: OrderedDict[str, float] = OrderedDict()
MAX_NONCE_ENTRIES = 10000
MAX_CLOCK_DRIFT_SECONDS = 300  # 5-minute validity window


def _cleanup_old_nonces(current_time: float):
    """Evicts expired nonces from memory."""
    cutoff = current_time - MAX_CLOCK_DRIFT_SECONDS
    while SEEN_NONCES:
        oldest_nonce, ts = next(iter(SEEN_NONCES.items()))
        if ts < cutoff:
            SEEN_NONCES.pop(oldest_nonce)
        else:
            break


async def verify_zero_trust_signature(
    request: Request,
    signature: str = Security(SIGNATURE_HEADER),
    timestamp: str = Security(TIMESTAMP_HEADER),
    nonce: str = Security(NONCE_HEADER),
):
    """Zero-Trust signature, anti-replay, and tamper verification guard."""
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Zero-Trust cryptographic signature.",
        )

    current_time = time.time()
    _cleanup_old_nonces(current_time)

    # 1. Anti-Replay Timestamp Validation (if provided by client)
    if timestamp:
        try:
            req_ts = float(timestamp)
            if abs(current_time - req_ts) > MAX_CLOCK_DRIFT_SECONDS:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Request expired or system clock out of sync.",
                )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed request timestamp.",
            )

    # 2. Nonce Duplication Check
    if nonce:
        if nonce in SEEN_NONCES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Replay attack detected: Nonce has already been consumed.",
            )
        if len(SEEN_NONCES) >= MAX_NONCE_ENTRIES:
            SEEN_NONCES.popitem(last=False)
        SEEN_NONCES[nonce] = current_time

    # 3. Cryptographic Signature Validation
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