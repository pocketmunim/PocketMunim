from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.routers import auth, salary, account, cron, dashboard, transaction, loan

app = FastAPI(
    title="PocketMunim Core Engine",
    description="Ishita Financial Intelligence System - Zero-Trust Backend",
    version="2.6.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
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

# 3. Global Catch-All Handler (Database constraints & internal crashes)
@app.exception_handler(Exception)
async def global_catch_all_exception_handler(request: Request, exc: Exception):
    err_str = str(exc)
    if "unique constraint" in err_str.lower() or "23505" in err_str:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"status": "ERROR", "error_code": 409, "detail": "Duplicate record detected. Entry already exists."}
        )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"status": "ERROR", "error_code": 500, "detail": f"Internal System Error: {err_str}"}
    )

# Route Registrations
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(transaction.router)
app.include_router(account.router)
app.include_router(salary.router)
app.include_router(loan.router)          # Resolves 404 for /api/v1/loans/*
app.include_router(cron.router)

# Catch-all Webhook Handler (Resolves 404 on /webhook)
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
    return {"status": "ONLINE", "system": "PocketMunim", "protocol": "IFIS-ZERO-TRUST-V2.6"}