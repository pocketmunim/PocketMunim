import os
import re
import httpx
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from supabase import create_client, Client

from app.security.auth import authenticate_telegram_request
from app.ai.category_pull_service import CategoryPullService
from app.telegram.telegram_utils import send_telegram_reply
from app.telegram.handlers.user_handler import UserHandler
from app.telegram.handlers.account_handler import AccountHandler
from app.telegram.handlers.salary_handler import SalaryHandler
from app.telegram.handlers.report_handler import ReportHandler
from app.telegram.handlers.callback_handler import CallbackHandler
from app.telegram.handlers.nlp_handler import NLPHandler
from app.telegram.handlers.loan_handler import LoanHandler

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
    return {"status": "PocketMunim Enterprise API is live (Vercel-Safe Synchronous Mode)", "status_code": 200}


@app.get("/setup-menu")
async def setup_telegram_menu():
    """
    Hit this endpoint once (e.g., https://your-vercel-app.vercel.app/setup-menu)
    to permanently register the bot commands in the Telegram UI Menu.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN is missing"}

    url = f"https://api.telegram.org/bot{token}/setMyCommands"

    commands = [
        {"command": "getloans", "description": "🏦 View active loans & pay EMIs"},
        {"command": "report", "description": "📊 View financial dashboard"},
        {"command": "monthly", "description": "📅 Get monthly summary"},
        {"command": "showaccount", "description": "💳 Show all bank accounts"},
        {"command": "addaccount", "description": "➕ Add a new bank account"},
        {"command": "setsalary", "description": "💸 Set monthly salary"},
        {"command": "start", "description": "🚀 Restart the bot"}
    ]

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={"commands": commands})
        return response.json()


@app.get("/report/view/{token}", response_class=HTMLResponse)
async def view_report(token: str):
    html_content = await ReportHandler.get_html_report(token, supabase_admin)
    return HTMLResponse(content=html_content)


async def execute_telegram_command(chat_id: int, text: str, user_id: str, request_url: str):
    is_safe, user_exists = await UserHandler.security_check(supabase_admin, chat_id, text)
    if not is_safe: return

    if not user_exists and not text.startswith("/register"):
        await UserHandler.prompt_registration(chat_id)
        return

    deduct_all_regex = r"^deduct\s+all\s+(?:amount\s+of\s+|for\s+)?([a-zA-Z]+)$"
    text_lower = text.lower()

    # Precise Loan Detection Rules
    is_loan_intent = (
            any(kw in text_lower for kw in ["loan", " emi", "emi ", "borrowed", "lender"]) or
            ("taken" in text_lower and "from" in text_lower) or
            ("%" in text_lower and any(kw in text_lower for kw in ["year", "yr", "month", "p.a"]))
    )

    # ================= COMMAND ROUTING =================
    if text.startswith("/register"):
        await UserHandler.register(supabase_admin, chat_id, user_id, text, user_exists)
    elif text.startswith("/setsalary"):
        await SalaryHandler.set_salary(supabase_admin, chat_id, user_id, text)
    elif text.startswith("/settle"):
        await SalaryHandler.settle_salary(supabase_admin, chat_id, user_id, text)
    elif deduct_all_match := re.match(deduct_all_regex, text, re.IGNORECASE):
        await SalaryHandler.deduct_all(supabase_admin, chat_id, user_id, deduct_all_match)
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

    # --- HYBRID LOAN & GROCERY INTERCEPTION ---
    elif is_loan_intent:
        leftover_text = await LoanHandler.handle_loan_text(supabase_admin, chat_id, user_id, text)
        if leftover_text and leftover_text.strip():
            await NLPHandler.process_text(supabase_admin, supabase, chat_id, user_id, leftover_text,
                                          category_pull_service)

    elif text.startswith("/start"):
        # Premium Branded Corporate UI/UX Formatting
        welcome_msg = (
            "✨ *Welcome to PocketMunim!* ✨\n"
            "_An Initiative by Ishita Financial Intelligence (I) Pvt. Ltd._ 🏢\n\n"
            "Your premium AI-powered wealth and expense manager is online. Forget rigid formats and complex accounting—just text me exactly how you speak! I'll automate your ledgers, track your loans, and build your reports instantly.\n\n"
            "💡 *Try it out! Just type:*\n"
            "🟢 *Earned:* _\"Got my 50k salary today\"_\n"
            "🔴 *Spent:* _\"Paid 450 for Zomato & 2k for electricity\"_\n"
            "🏦 *Loans:* _\"HDFC loan 5L at 9.5% for 3 years\"_\n"
            "🛒 *Bulk:* _\"Milk 60, Bread 40, Eggs 50\"_\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👇 *Access your financial universe below:*"
        )

        keyboard = {
            "inline_keyboard": [
                [{"text": "📊 PocketMunim Dashboard", "callback_data": "menu_report"}],
                [
                    {"text": "🏦 Active Loans", "callback_data": "menu_loans"},
                    {"text": "💳 My Accounts", "callback_data": "menu_accounts"}
                ],
                [
                    {"text": "📅 Monthly Report", "callback_data": "menu_monthly"},
                    {"text": "❓ How it works", "callback_data": "menu_help"}
                ]
            ]
        }
        await send_telegram_reply(chat_id, welcome_msg, reply_markup=keyboard)

    elif text.startswith("/categorypull"):
        await NLPHandler.pull_categories(supabase_admin, chat_id, user_id, text, category_pull_service)
    elif text.startswith("/history"):
        await send_telegram_reply(chat_id, "  *Historical Data Auto-Template*\n...")
    elif text.startswith("/monthly"):
        await ReportHandler.monthly_summary(supabase_admin, chat_id, user_id, text)
    else:
        # Standard Transactions
        await NLPHandler.process_text(supabase_admin, supabase, chat_id, user_id, text, category_pull_service)


@app.post("/webhook")
async def telegram_webhook(request: Request, authorized: bool = Depends(authenticate_telegram_request)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

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
        print(f"Execution Error: {str(e)}")

    return {"ok": True}