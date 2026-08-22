import hmac
import hashlib
import time
from fastapi import Request, HTTPException, status
from app.core.config import settings
from app.core.database import get_db

async def verify_zero_trust_signature(request: Request):
    signature = request.headers.get("X-Signature")
    timestamp_str = request.headers.get("X-Timestamp")
    nonce = request.headers.get("X-Nonce")
    device_uuid = request.headers.get("X-Device-UUID")
    client_sig = request.headers.get("X-Security-Client")

    if not all([signature, timestamp_str, nonce, device_uuid, client_sig]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="CISO Violation: Incomplete cryptographic security headers."
        )

    if client_sig != "IFIS-NATIVE-ANDROID-V2":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CISO Violation: Untrusted client signature."
        )

    # Check timestamp freshness (+/- 30 seconds)
    try:
        req_timestamp = int(timestamp_str)
        current_time_ms = int(time.time() * 1000)
        if abs(current_time_ms - req_timestamp) > 30000:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CISO Violation: Request timestamp drift exceeded 30s."
            )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid timestamp format.")

    # Check and record Nonce (Anti-Replay)
    db = get_db()
    nonce_check = db.table('security_nonces').select('nonce').eq('nonce', nonce).execute()
    if nonce_check.data:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CISO Violation: Replay attack detected. Nonce consumed."
        )

    db.table('security_nonces').insert({
        "nonce": nonce,
        "device_uuid": device_uuid,
        "created_at": "now()"
    }).execute()

    # Canonical Payload Reassembly
    body_bytes = await request.body()
    body_str = body_bytes.decode('utf-8') if body_bytes else ""
    path = request.url.path
    method = request.method.upper()

    canonical = f"{method}:{path}:{timestamp_str}:{nonce}:{device_uuid}:{body_str}"

    # Derive Dynamic Key & Compare
    derived_key = hashlib.sha256(f"{settings.MASTER_PEPPER}:{device_uuid}".encode()).digest()
    expected_sig = hmac.new(derived_key, canonical.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(signature, expected_sig):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CISO Violation: Cryptographic signature mismatch."
        )

    return True
