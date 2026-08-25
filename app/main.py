import logging
import hmac
import hashlib
import os
import ast
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.routers import auth, salary, account, cron, dashboard, transaction, loan, sip, notifications
import json
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ZERO_TRUST_SECRET = os.getenv("ZERO_TRUST_SECRET")
if not ZERO_TRUST_SECRET:
    raise RuntimeError("CRITICAL: ZERO_TRUST_SECRET environment variable missing. System halted.")

app = FastAPI(
    title="PocketMunim Core Engine",
    description="Ishita Financial Intelligence System - Zero-Trust Backend",
    version="2.6.4"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://pocket-munim.vercel.app", "capacitor://localhost", "http://localhost"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def zero_trust_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.url.path in ["/", "/webhook", "/docs", "/openapi.json"] or request.url.path.startswith("/api/v1/cron/"):        return await call_next(request)

    signature = request.headers.get("X-Zero-Trust-Signature")
    if not signature:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED,
                            content={"detail": "Zero-Trust Signature Missing"})

    body = await request.body()
    expected_mac = hmac.new(ZERO_TRUST_SECRET.encode('utf-8'), body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_mac, signature):
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED,
                            content={"detail": "Zero-Trust Signature Invalid"})

    async def receive():
        return {"type": "http.request", "body": body}

    request._receive = receive
    return await call_next(request)


@app.exception_handler(Exception)
async def global_catch_all_exception_handler(request: Request, exc: Exception):
    err_str = str(exc)

    extracted_msg = None
    if hasattr(exc, "message") and exc.message:
        extracted_msg = exc.message
    elif hasattr(exc, "details") and exc.details:
        extracted_msg = exc.details
    else:
        try:
            dict_match = re.search(r"\{.*\}", err_str)
            if dict_match:
                parsed = ast.literal_eval(dict_match.group(0))
                if isinstance(parsed, dict):
                    extracted_msg = parsed.get("message") or parsed.get("details")
        except Exception:
            pass

    final_msg = extracted_msg or err_str

    if "unique constraint" in final_msg.lower() or "23505" in final_msg:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"status": "ERROR", "error_code": 409, "detail": "Duplicate record detected."}
        )

    # ADDED LOAN SPECIFIC ERRORS TO WHITELIST
    known_safe_keywords = [
        "duplicate_current_month", "insufficient balance", "account not found",
        "solvency violation", "no active liquidity vault", "settlement blocked",
        "salary is already settled", "salary record not found", "must be in paid state",
        "transaction declined", "loan contract not found", "already closed",
        "exceeds outstanding balance"
    ]

    for safe_word in known_safe_keywords:
        if safe_word in final_msg.lower():
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"status": "ERROR", "error_code": 400, "detail": final_msg}
            )

    logger.error(f"SYSTEM ERROR [{request.method} {request.url.path}]: {err_str}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"status": "ERROR", "error_code": 500, "detail": "Internal System Error."}
    )


app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(transaction.router)
app.include_router(account.router)
app.include_router(salary.router)
app.include_router(loan.router)
app.include_router(cron.router)
app.include_router(sip.router)
app.include_router(notifications.router)


@app.get("/")
def health():
    return {"status": "ONLINE", "system": "PocketMunim", "protocol": "IFIS-ZERO-TRUST-V2.6.4"}