import logging
import ast
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.routers import auth, salary, account, cron, dashboard, transaction, loan, sip, notifications

# Configure internal secure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PocketMunim Core Engine",
    description="Ishita Financial Intelligence System - Zero-Trust Backend",
    version="2.6.2"
)

# 1. SECURE CORS POLICY (Fortune 100 Standard)
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


# 1. Custom HTTP Exception Formatter
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail_msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "ERROR", "error_code": exc.status_code, "detail": detail_msg}
    )


# 2. Pydantic Request Validation Error Formatter
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


# 3. Global Catch-All Handler (DATA LEAKAGE PREVENTED, BUSINESS LOGIC PRESERVED)
@app.exception_handler(Exception)
async def global_catch_all_exception_handler(request: Request, exc: Exception):
    err_str = str(exc)

    # 1. Handle Unique Constraints / Duplicates
    if "unique constraint" in err_str.lower() or "23505" in err_str or "already exists" in err_str.lower():
        clean_msg = "Duplicate record detected. Please use a unique title or entry."
        try:
            parsed_dict = ast.literal_eval(err_str)
            if isinstance(parsed_dict, dict) and "message" in parsed_dict:
                clean_msg = parsed_dict["message"]
        except Exception:
            pass
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"status": "ERROR", "error_code": 409, "detail": clean_msg}
        )

    # 2. Whitelist Known Business Logic Exceptions from Postgres RPCs (Including P0001 custom raises)
    known_safe_keywords = [
        "already exists",
        "DUPLICATE_CURRENT_MONTH",
        "Insufficient balance",
        "Account not found",
        "No active account vault",
        "Account vault not found",
        "Loan contract not found",
        "already CLOSED",
        "No active liquidity vault",
        "exceeds outstanding balance",
        "distinct vaults",
        "strictly greater than 0",
        "Receipt amount must be",
        "Solvency Violation"
    ]

    for safe_word in known_safe_keywords:
        if safe_word.lower() in err_str.lower():
            clean_msg = err_str
            try:
                if hasattr(exc, 'message'):
                    clean_msg = exc.message
                else:
                    parsed_dict = ast.literal_eval(err_str)
                    if isinstance(parsed_dict, dict) and "message" in parsed_dict:
                        clean_msg = parsed_dict["message"]
            except Exception:
                pass

            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"status": "ERROR", "error_code": 400, "detail": clean_msg}
            )

    # 3. CRITICAL: Log actual unhandled errors internally, DO NOT return raw SQL syntax to client
    logger.error(f"CRITICAL SYSTEM ERROR [{request.method} {request.url.path}]: {err_str}", exc_info=True)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"status": "ERROR", "error_code": 500,
                 "detail": "Internal System Error: An unexpected issue occurred. Secure logs have been updated."}
    )


# Route Registrations
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(transaction.router)
app.include_router(account.router)
app.include_router(salary.router)
app.include_router(loan.router)
app.include_router(cron.router)
app.include_router(sip.router)
app.include_router(notifications.router)

# Catch-all Webhook Handler
@app.post("/webhook")
async def webhook_handler(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "SUCCESS", "message": "Webhook acknowledged", "payload": payload}
    )


@app.get("/webhook")
async def health_webhook():
    return {"status": "ONLINE", "endpoint": "/webhook"}


@app.get("/")
def health():
    return {"status": "ONLINE", "system": "PocketMunim", "protocol": "IFIS-ZERO-TRUST-V2.6.2"}