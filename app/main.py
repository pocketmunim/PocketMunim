import os
import re
import httpx
from fastapi import FastAPI, Request, HTTPException, Depends, Header, Query
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from app.services.loan_dashboard_service import LoanDashboardService
from supabase import create_client, Client
from qstash import QStash

from app.security.auth import authenticate_telegram_request, verify_qstash_request
from app.ai.category_pull_service import CategoryPullService
from app.telegram.telegram_utils import send_telegram_reply
from app.telegram.handlers.user_handler import UserHandler
from app.telegram.handlers.account_handler import AccountHandler
from app.telegram.handlers.salary_handler import SalaryHandler
from app.telegram.handlers.report_handler import ReportHandler
from app.telegram.handlers.callback_handler import CallbackHandler
from app.telegram.handlers.nlp_handler import NLPHandler
from app.telegram.handlers.loan_handler import LoanHandler
from app.telegram.handlers.taxonomy_handler import TaxonomyHandler
from app.cron.cron_handler import CronHandler

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
supabase_admin: Client = create_client(SUPABASE_URL,
                                       SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else supabase

category_pull_service = CategoryPullService(None, supabase_admin)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
@app.head("/")
def health_check():
    return {"status": "PocketMunim Enterprise Engine live with QStash Decoupling", "status_code": 200}


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


async def execute_telegram_command(chat_id: int, text: str, user_id: str, request_url: str):
    is_safe, user_exists = await UserHandler.security_check(supabase_admin, chat_id, text)
    if not is_safe:
        return

    if not user_exists and not text.startswith("/register"):
        await UserHandler.prompt_registration(chat_id)
        return

    text_lower = text.lower()
    is_loan_intent = (
            any(kw in text_lower for kw in ["loan", " emi", "emi ", "borrowed", "lender"]) or
            ("taken" in text_lower and "from" in text_lower) or
            ("%" in text_lower and any(kw in text_lower for kw in ["year", "yr", "month", "p.a"]))
    )

    if text.startswith("/register"):
        await UserHandler.register(supabase_admin, chat_id, user_id, text, user_exists)
    elif text.startswith("/setsalary"):
        await SalaryHandler.set_salary(supabase_admin, chat_id, user_id, text)
    elif text.startswith("/settle"):
        await SalaryHandler.settle_salary(supabase_admin, chat_id, user_id, text)
    elif text.startswith("/report"):
        await ReportHandler.generate_report_link(request_url, chat_id, user_id, supabase_admin)
    elif text.startswith("/addaccount"):
        await AccountHandler.add_account(supabase_admin, chat_id, user_id, text)
    elif text.startswith("/setdefault"):
        await AccountHandler.set_default(supabase_admin, chat_id, user_id, text)
    elif text.startswith("/showaccount"):
        await AccountHandler.show_accounts(supabase_admin, chat_id, user_id)
    elif text.startswith("/getloans"):
        await LoanHandler.get_loans(supabase_admin, chat_id, user_id, text)
    elif text.startswith("/loanreport"):
        await LoanHandler.generate_loan_report_link(request_url, chat_id, user_id)
    elif text.startswith("/categorypull"):
        await TaxonomyHandler.handle_category_pull(supabase_admin, chat_id, user_id, text, category_pull_service)
    elif text.startswith("/showcategories"):
        await TaxonomyHandler.show_categories(supabase_admin, chat_id, user_id)
    elif is_loan_intent:
        leftover_text = await LoanHandler.handle_loan_text(supabase_admin, chat_id, user_id, text)
        if leftover_text and leftover_text.strip():
            await NLPHandler.process_text(supabase_admin, supabase, chat_id, user_id, leftover_text,
                                          category_pull_service, request_url)
    elif text.startswith("/start"):
        welcome_msg = (
            "🚀 *Welcome to PocketMunim Enterprise*\n\n"
            "Your AI-powered personal finance engine is live. Speak naturally to record transactions, monitor loans, and track net worth.\n\n"
            "💡 *Quick Examples:*\n"
            "  _\"Got 85k salary in HDFC today\"_\n"
            "  _\"Paid 450 for Zomato & 1200 for Uber\"_\n"
            "  _\"HDFC loan 5L at 9.5% for 3 years\"_\n\n"
            "Tap below to navigate:"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "📊 Open Dashboard", "callback_data": "menu_report"}],
                [{"text": "🏦 Active Loans", "callback_data": "menu_loans"},
                 {"text": "💳 Accounts", "callback_data": "menu_accounts"}],
                [{"text": "📅 Monthly Summary", "callback_data": "menu_monthly"}]
            ]
        }
        await send_telegram_reply(chat_id, welcome_msg, reply_markup=keyboard)
    elif text.startswith("/monthly"):
        await ReportHandler.monthly_summary(supabase_admin, chat_id, user_id, text)
    else:
        await NLPHandler.process_text(supabase_admin, supabase, chat_id, user_id, text, category_pull_service,
                                      request_url)

@app.get("/loans/view/{token}", response_class=HTMLResponse)
async def view_loan_report(token: str):
    html_content = await LoanDashboardService.render_dashboard(token, supabase_admin)
    return HTMLResponse(content=html_content)

@app.post("/webhook")
async def telegram_webhook(request: Request, authorized: bool = Depends(authenticate_telegram_request)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    qstash_token = os.getenv("QSTASH_TOKEN")
    if not qstash_token:
        return await process_telegram_payload(request, payload)

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
        print(f"QStash publish failure, falling back to sync: {e}")
        return await process_telegram_payload(request, payload)

    return {"ok": True}


@app.post("/process-task")
async def process_task(request: Request, verified: bool = Depends(verify_qstash_request)):
    try:
        payload = await request.json()
        request.state.telegram_id = request.headers.get("x-pocketmunim-user")
        return await process_telegram_payload(request, payload)
    except Exception as e:
        print(f"Task Execution Error: {e}")
        return {"ok": False}


async def process_telegram_payload(request: Request, payload: dict):
    if payload.get("internal_task") == "duplicate_timeout":
        await NLPHandler.handle_duplicate_timeout(
            supabase_admin,
            payload.get("batch_id"),
            payload.get("chat_id"),
            payload.get("message_id")
        )
        return {"ok": True}

    if "callback_query" in payload:
        return await CallbackHandler.handle(payload, supabase_admin)

    message = payload.get("message", payload.get("edited_message", {}))
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()

    if not text or not chat_id:
        return {"ok": True}

    user_id = str(request.state.telegram_id)

    try:
        await execute_telegram_command(chat_id, text, user_id, str(request.url))
    except Exception as e:
        print(f"Execution Failure: {str(e)}")

    return {"ok": True}


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