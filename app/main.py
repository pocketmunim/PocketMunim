import os
import httpx
from fastapi import FastAPI, Request, HTTPException, Depends, Header, Query
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager

from supabase import create_client, Client
from qstash import QStash

# Preserved Legacy Core Web & Cron Routes
from app.services.loan_dashboard_service import LoanDashboardService
from app.telegram.handlers.report_handler import ReportHandler
from app.cron.cron_handler import CronHandler
from app.security.auth import authenticate_telegram_request, verify_qstash_request

# New High-Speed Async Router & DI
from app.telegram.router import CommandRouter
from app.dependencies import get_async_db, get_ai_provider, get_notification_gateway, get_cache_manager

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Admin client required for preserving legacy HTML Dashboards & Cron Tasks
supabase_admin: Client = create_client(SUPABASE_URL,
                                       SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(lifespan=lifespan, title="PocketMunim Enterprise API", version="2.0.0")


@app.get("/")
@app.head("/")
def health_check():
    return {"status": "PocketMunim Enterprise Engine live with QStash Decoupling (Fast-Router)", "status_code": 200}


@app.get("/setup-menu")
async def setup_telegram_menu():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN missing"}

    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    commands = [
        {"command": "getloans", "description": "View active loans & pay EMIs"},
        {"command": "report", "description": "View interactive dashboard"},
        {"command": "monthly", "description": "Get monthly summary"},
        {"command": "showaccount", "description": "List all bank accounts"},
        {"command": "addaccount", "description": "Add new bank account"},
        {"command": "setsalary", "description": "Set monthly salary"},
        {"command": "categorypull", "description": "Learn new item categories"},
        {"command": "showcategories", "description": "View cached taxonomy"},
        {"command": "start", "description": "Show system guide"}
    ]

    async with httpx.AsyncClient() as client:
        res = await client.post(url, json={"commands": commands})
        return res.json()


@app.get("/report/view/{token}", response_class=HTMLResponse)
async def view_report(token: str, request: Request):
    html_content = await ReportHandler.get_html_report(token, supabase_admin, request)
    return HTMLResponse(content=html_content)


@app.get("/loans/view/{token}", response_class=HTMLResponse)
async def view_loan_report(token: str):
    html_content = await LoanDashboardService.render_dashboard(token, supabase_admin)
    return HTMLResponse(content=html_content)


@app.post("/webhook")
async def telegram_webhook(request: Request, authorized: bool = Depends(authenticate_telegram_request)):
    """
    Entry point for Telegram. Fast-acknowledges and pushes to QStash.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    qstash_token = os.getenv("QSTASH_TOKEN")
    if not qstash_token:
        raise HTTPException(status_code=500, detail="QSTASH_TOKEN missing for decoupled routing")

    client = QStash(qstash_token)
    base_url = str(request.url).split('/webhook')[0]
    target_url = f"{base_url}/process-task"
    telegram_id = str(request.state.telegram_id)

    try:
        client.message.publish_json(
            url=target_url,
            body=payload,
            headers={"x-pocketmunim-user": telegram_id}
        )
    except Exception as e:
        print(f"QStash publish failure: {e}")
        raise HTTPException(status_code=500, detail="Message broker failed")

    return {"ok": True, "status": "queued"}


@app.post("/process-task")
async def process_task(
        request: Request,
        verified: bool = Depends(verify_qstash_request),
        db=Depends(get_async_db),
        ai=Depends(get_ai_provider),
        notifier=Depends(get_notification_gateway),
        cache=Depends(get_cache_manager)
):
    """
    Background execution endpoint. Safe from Telegram timeouts. Powered by Dependency Injection.
    """
    try:
        payload = await request.json()

        # Restore the telegram user id from the QStash header
        request.state.telegram_id = request.headers.get("x-pocketmunim-user")

        # Instantiate high-speed router with injected async dependencies
        router = CommandRouter(db=db, ai=ai, notifier=notifier, cache=cache)

        # Execute fully async business logic
        result = await router.process_webhook(payload)
        return result

    except Exception as e:
        print(f"Task Execution Error: {e}")
        return {"ok": False}


@app.post("/cron/payday")
async def run_payday_cron(
        secret: str = Query(None, description="Auth secret passed via URL"),
        authorization: str = Header(None)
):
    expected_secret = os.getenv("CRON_SECRET")
    if expected_secret:
        auth_header_valid = authorization and authorization == f"Bearer {expected_secret}"
        query_param_valid = secret and secret == expected_secret
        if not (auth_header_valid or query_param_valid):
            raise HTTPException(status_code=401, detail="Unauthorized Cron Request")

    result = await CronHandler.process_daily_paydays(supabase_admin)
    return result