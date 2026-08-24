import logging
import hmac
import hashlib
import os
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.routers import auth, salary, account, cron, dashboard, transaction, loan, sip, notifications

# Configure internal secure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ZERO_TRUST_KEY = os.getenv("ZERO_TRUST_KEY")
if not ZERO_TRUST_KEY:
    raise RuntimeError("CRITICAL: ZERO_TRUST_KEY environment variable missing. System halted.")

app = FastAPI(
    title="PocketMunim Core Engine",
    description="Ishita Financial Intelligence System - Zero-Trust Backend",
    version="2.6.3"
)

# 1. SECURE CORS POLICY
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://pocket-munim.vercel.app",
        "capacitor://localhost",
        "http://localhost"
    ],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:[0-9]+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# 2. ZERO-TRUST HMAC SIGNATURE MIDDLEWARE
@app.middleware("http")
async def zero_trust_middleware(request: Request, call_next):
    if request.url.path in ["/", "/webhook", "/docs", "/openapi.json"]:
        return await call_next(request)

    signature = request.headers.get("X-Zero-Trust-Signature")
    if not signature:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED,
                            content={"detail": "Zero-Trust Signature Missing"})

    body = await request.body()
    expected_mac = hmac.new(ZERO_TRUST_KEY.encode('utf-8'), body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_mac, signature):
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED,
                            content={"detail": "Zero-Trust Signature Invalid"})

    # Restore body for downstream routers
    async def receive():
        return {"type": "http.request", "body": body}

    request._receive = receive
    return await call_next(request)


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail_msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "ERROR", "error_code": exc.status_code, "detail": detail_msg}
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first_error = errors[0] if errors else {}
    field = " -> ".join([str(loc) for loc in first_error.get("loc", []) if loc != "body"])
    msg = first_error.get("msg", "Invalid format")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"status": "ERROR", "error_code": 422, "detail": f"Validation Error in '{field}': {msg}"}
    )


@app.exception_handler(Exception)
async def global_catch_all_exception_handler(request: Request, exc: Exception):
    err_str = str(exc).lower()

    if "unique constraint" in err_str or "23505" in err_str:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"status": "ERROR", "error_code": 409,
                     "detail": "Duplicate record detected. Please use a unique title."}
        )

    known_safe_keywords = [
        "duplicate_current_month", "insufficient balance", "account not found",
        "solvency violation", "no active liquidity vault"
    ]

    for safe_word in known_safe_keywords:
        if safe_word in err_str:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"status": "ERROR", "error_code": 400, "detail": str(exc)}
            )

    logger.error(f"CRITICAL SYSTEM ERROR [{request.method} {request.url.path}]: {err_str}", exc_info=True)
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


@app.post("/webhook")
async def webhook_handler(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    return JSONResponse(status_code=status.HTTP_200_OK,
                        content={"status": "SUCCESS", "message": "Webhook acknowledged", "payload": payload})


@app.get("/webhook")
async def health_webhook():
    return {"status": "ONLINE", "endpoint": "/webhook"}


@app.get("/")
def health():
    return {"status": "ONLINE", "system": "PocketMunim", "protocol": "IFIS-ZERO-TRUST-V2.6.3"}