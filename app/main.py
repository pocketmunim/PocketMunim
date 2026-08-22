from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.routers import auth, salary, account, cron, dashboard, transaction, loan

app = FastAPI(
    title="PocketMunim Core Engine",
    description="Ishita Financial Intelligence System - Zero-Trust Backend",
    version="2.5.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. Uniform HTTP Exception Formatter
@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    detail_msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "ERROR",
            "error_code": exc.status_code,
            "detail": detail_msg
        }
    )

# 2. Pydantic Request Validation Error Formatter
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first_error = errors[0] if errors else {}
    field = " -> ".join([str(loc) for loc in first_error.get("loc", []) if loc != "body"])
    msg = first_error.get("msg", "Invalid field format")
    formatted_detail = f"Validation Error in '{field}': {msg}" if field else f"Validation Error: {msg}"

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "status": "ERROR",
            "error_code": 422,
            "detail": formatted_detail
        }
    )

# 3. Global Catch-All Handler (Database crashes & duplicate constraints)
@app.exception_handler(Exception)
async def global_catch_all_exception_handler(request: Request, exc: Exception):
    err_str = str(exc)

    if "duplicate key value violates unique constraint" in err_str.lower() or "23505" in err_str:
        if "idx_unique_user_daily_transaction" in err_str:
            detail = "Duplicate Transaction! An identical item, amount, and date entry is already recorded in your ledger."
        elif "idx_unique_user_account_name" in err_str:
            detail = "Duplicate Account! An account vault with this name already exists."
        elif "unique_user_salary_month" in err_str:
            detail = "Duplicate Salary Cycle! A salary record for this month already exists."
        elif "idx_unique_user_loan_name" in err_str:
            detail = "Duplicate Loan! A loan with this title already exists in your registry."
        elif "unique_loan_installment" in err_str:
            detail = "Duplicate Installment! This EMI installment number is already scheduled."
        else:
            detail = "Duplicate record detected. This entry already exists."

        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"status": "ERROR", "error_code": 409, "detail": detail}
        )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "ERROR",
            "error_code": 500,
            "detail": f"System Engine Error: {err_str}"
        }
    )

# Route Registrations
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(transaction.router)
app.include_router(account.router)
app.include_router(salary.router)
app.include_router(loan.router)
app.include_router(cron.router)

@app.get("/")
def health():
    return {
        "status": "ONLINE",
        "system": "Ishita Financial Intelligence System",
        "protocol": "IFIS-ZERO-TRUST-V2.5"
    }