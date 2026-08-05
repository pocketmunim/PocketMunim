import os
import re
import json
import uuid
import httpx
import calendar
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from supabase import create_client, Client

# Core PocketMunim Imports
from app.security.auth import authenticate_telegram_request
from app.ai.schemas import AITransactionExtraction
from app.ai.category_pull_service import CategoryPullService
from app.cache.category_cache import CategoryCacheManager
from app.ai.ai_provider import execute_resilient_ai

# Bulk Transaction Imports
from app.services.bulk_transaction_service import BulkTransactionService
from app.dao.bulk_transaction_dao import BulkTransactionDAO

# Environment Configurations
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Initialize Supabase Clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
supabase_admin: Client = create_client(SUPABASE_URL,
                                       SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else supabase

# Initialize Phase 4 Category Services
category_pull_service = CategoryPullService(None, supabase_admin)

# In-memory secure report token store (Token -> {user_id, expires_at})
REPORT_TOKENS = {}

# IN-MEMORY DUPLICATE MANAGER
PENDING_BATCHES = {}

# Timezone Helper
TZ_IST = timezone(timedelta(hours=5, minutes=30))

# =====================================================================
# SECURITY: WEB APPLICATION FIREWALL (WAF) PATTERN
# =====================================================================
MALICIOUS_PATTERN = re.compile(
    r"(DROP\s+TABLE|SELECT\s+\*|OR\s+1=1|<script>|<img|jndi:ldap|rm\s+-rf|;/|{{.*}}|\.\./\.\./|\"\s*OR\s*\"\")",
    re.IGNORECASE
)


# =====================================================================
# STARTUP EVENT: SET TELEGRAM MENU BAR COMMANDS AUTOMATICALLY
# =====================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    if TELEGRAM_BOT_TOKEN:
        try:
            async with httpx.AsyncClient() as client:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands"
                commands = {
                    "commands": [
                        {"command": "start", "description": "Start PocketMunim"},
                        {"command": "register", "description": "Register your account"},
                        {"command": "addaccount", "description": "Add a bank account"},
                        {"command": "categorypull", "description": "Seed or refresh categories"},
                        {"command": "report", "description": "Get 1-hour secure AI HTML dashboard report"},
                        {"command": "monthly", "description": "Get monthly P&L (e.g. /monthly Jan 2025)"},
                        {"command": "history", "description": "Get template for bulk past entries"}
                    ]
                }
                await client.post(url, json=commands)
        except Exception as e:
            print(f"Failed to set Telegram menu: {e}")
    yield


app = FastAPI(lifespan=lifespan)


# =====================================================================
# HELPER: SEND TELEGRAM MESSAGE IMMEDIATELY
# =====================================================================
async def send_telegram_reply(chat_id: int, text: str, reply_markup: dict = None):
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)


# =====================================================================
# INTERACTIVE UI HELPERS (CHECKBOXES)
# =====================================================================
def generate_duplicate_keyboard(batch_id: str, items: list) -> dict:
    keyboard = []
    for i, item in enumerate(items):
        icon = "☑️" if item["selected"] else "⬜️"
        text = f"{icon} {item['desc']} (₹{item['amount']:,.2f})"
        keyboard.append([{"text": text, "callback_data": f"btog_{batch_id}_{i}"}])
    keyboard.append([
        {"text": "✅ Confirm Selected", "callback_data": f"bconf_{batch_id}"},
        {"text": "❌ Cancel All", "callback_data": f"bcanc_{batch_id}"}
    ])
    return {"inline_keyboard": keyboard}


async def edit_telegram_message(chat_id: int, message_id: int, text: str = None, reply_markup: dict = None):
    if not TELEGRAM_BOT_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/"
    payload = {"chat_id": chat_id, "message_id": message_id}
    if reply_markup: payload["reply_markup"] = reply_markup
    if text:
        url += "editMessageText"
        payload["text"] = text
        payload["parse_mode"] = "Markdown"
    else:
        url += "editMessageReplyMarkup"
    async with httpx.AsyncClient() as client:
        await client.post(url, json=payload)


# =====================================================================
# HELPER: RECURRENCE EXPANSION ENGINE
# =====================================================================
def generate_recurrence_dates(start_date_str: str, frequency: str, current_dt: datetime) -> list:
    try:
        start_dt = datetime.strptime(start_date_str.split("T")[0], "%Y-%m-%d").replace(tzinfo=current_dt.tzinfo)
    except Exception:
        return []

    dates = []
    curr_iter = start_dt
    freq = frequency.lower() if frequency else ""

    while curr_iter <= current_dt:
        dates.append(curr_iter)
        if freq == 'daily':
            curr_iter += timedelta(days=1)
        elif freq == 'weekly':
            curr_iter += timedelta(weeks=1)
        elif freq == 'monthly':
            month = curr_iter.month
            year = curr_iter.year
            day = curr_iter.day
            if month == 12:
                month = 1
                year += 1
            else:
                month += 1
            while True:
                try:
                    curr_iter = curr_iter.replace(year=year, month=month, day=day)
                    break
                except ValueError:
                    day -= 1
        elif freq == 'quarterly':
            month = curr_iter.month + 3
            year = curr_iter.year
            day = curr_iter.day
            if month > 12:
                month -= 12
                year += 1
            while True:
                try:
                    curr_iter = curr_iter.replace(year=year, month=month, day=day)
                    break
                except ValueError:
                    day -= 1
        elif freq == 'half_yearly':
            month = curr_iter.month + 6
            year = curr_iter.year
            day = curr_iter.day
            if month > 12:
                month -= 12
                year += 1
            while True:
                try:
                    curr_iter = curr_iter.replace(year=year, month=month, day=day)
                    break
                except ValueError:
                    day -= 1
        elif freq == 'yearly':
            try:
                curr_iter = curr_iter.replace(year=curr_iter.year + 1)
            except ValueError:
                curr_iter = curr_iter.replace(year=curr_iter.year + 1, month=2, day=28)
        else:
            break

    return dates


# =====================================================================
# FOUNDER FROZEN SYSTEM PROMPT (UPDATED RULES 7 & 8)
# =====================================================================
SYSTEM_PROMPT = """SYSTEM ROLE:
You are the PocketMunim Enterprise NLP Extraction Engine. Your exclusive mandate is to extract financial data, commands, and intents from unstructured multi-lingual text (English, Hindi, Marathi, Hinglish) and output a STRICT, heavily nested JSON object.

CRITICAL RULES (NON-NEGOTIABLE):
1. NO MATHEMATICS & NO SPLITTING: You are strictly forbidden from calculating totals, EMIs, balances, or splitting amounts. (e.g., 'paid 4000 split between 4' MUST be logged as a 4000/4 transaction).
2. NO HALLUCINATION: If a field is missing, return `null`. Never guess or assume default values.
3. MULTI-INTENT & SEQUENCING: A single message may contain multiple operations. Extract each as a separate object in the `transactions` array. Assign a chronological `execution_order`.
4. BULK DETECTION: If the user lists MORE THAN 1 item (e.g., 2 or more items in a list), set `metadata.bulk_operation = true` and `operation_type = "bulk"`.
5. UNKNOWN CATEGORIES: If you cannot confidently map an item to a standard category, set the transaction's `category` and `subcategory` to `null`, AND strictly set `metadata.category_lookup_required = true`.
6. LOAN PAYMENTS: A loan payment MUST generate two intents: an `expense` (to deduct the bank balance) in the `transactions` array, AND a `loan_payment` intent in the `loan` object.
7. EXACT DATES & CURRENCY: TODAY IS {CURRENT_DATE}. If no date is explicitly mentioned, ALWAYS assume the transaction occurred TODAY. Calculate relative dates strictly in YYYY-MM-DD. For "last month", "last year", or "last week", subtract exactly that interval from today. DO NOT default to the 1st of the month.
8. CLARIFICATION STRICTNESS: You MUST NOT set needs_clarification = true unless the AMOUNT is missing or Rule 12 applies. Never ask for missing accounts, categories, payment methods, or DATES.
9. JSON ONLY: Output NOTHING but valid JSON. No markdown wrappers.
10. PEER-TO-PEER TRANSFERS / INCOME SOURCES: If a user receives money (e.g., "got 10k from raj" or "received extra income of 50"), set intent to "income". If the source name/person is missing (e.g., generic "extra income" without a donor/company), you MUST set `needs_clarification = true` and `clarification_fields = ["source name"]`.
11. ACCOUNT ROUTING: 
    - If user specifies an account paid FROM (e.g., "bought milk from Kotak"), set `source_account` to "Kotak".
    - If user specifies an account received INTO, set `destination_account`.
    - If transfer between OWN accounts ("send 10k from SBI to Axis"), intent is `transfer_own`, `source_account` is "SBI", `destination_account` is "Axis".
12. GENERIC NAMES: If a transaction involves a person but uses a generic term (e.g., "friend", "brother", "mitra", "dost", "vendor") instead of a specific name, you MUST set `needs_clarification = true` and ask for the specific name.
13. PAST RECURRING: For inputs like "every month on 17th from jun 2025", set recurrence.enabled = true, extract frequency (e.g. 'monthly'), and set start_date strictly in YYYY-MM-DD.

JSON OUTPUT SCHEMA:
{
  "metadata": {
    "raw_user_text": "string",
    "operation_type": "enum: [single, bulk, mixed, command, query, unsupported]",
    "language": "string",
    "entry_source": "enum: [telegram, api, manual, ocr, voice, import]",
    "bulk_operation": "boolean",
    "category_lookup_required": "boolean",
    "unsupported_chat": "boolean",
    "account_required": "boolean"
  },

  "transactions": [
    {
      "client_transaction_id": "string (generate random UUID) or null",
      "transaction_sequence": "integer (e.g., 1)",
      "execution_order": "integer (e.g., 1)",
      "intent": "enum: [expense, income, transfer_own, transfer_other]",
      "amount": "float or null",
      "original_currency": "string",
      "normalized_currency": "string (default: INR)",
      "merchant": "string or null",
      "payment_method": "enum: [Cash, UPI, Credit Card, Debit Card, Net Banking, Wallet, null]",
      "item": "string or null",
      "quantity": "float or null",
      "unit": "string or null",
      "category": "string or null",
      "subcategory": "string or null",
      "matched_from": "enum: [AI, null]",
      "source_account": "string or null",
      "destination_account": "string or null",
      "date": {
        "raw_expression": "string",
        "relative_date": "string or null",
        "date_type": "enum: [specific, relative, period_end, period_start]"
      },
      "recurrence": {
        "enabled": "boolean",
        "frequency": "enum: [daily, weekly, monthly, quarterly, half_yearly, yearly, null]",
        "start_date": "string or null",
        "end_date": "string or null"
      },
      "future": {
        "is_future": "boolean",
        "budget_check_required": "boolean",
        "should_save": "boolean"
      },
      "validation": {
        "amount_valid": "boolean",
        "date_valid": "boolean",
        "item_valid": "boolean",
        "account_valid": "boolean"
      },
      "duplicate_detection": {
        "possible_duplicate": "boolean",
        "duplicate_reference": "string or null"
      },
      "needs_clarification": "boolean",
      "clarification_fields": ["array"],
      "confidence": {
        "intent_confidence": "float",
        "amount_confidence": "float",
        "date_confidence": "float",
        "account_confidence": "float",
        "overall_confidence": "float"
      }
    }
  ],

  "query": {
    "is_query": "boolean",
    "query_type": "enum: [Balance, Expense History, Income History, Top Expense, Top Income, Cashflow, Net Worth, Loan Summary, Salary History, Category Summary, Merchant Summary, Budget Status, Investment Summary, null]",
    "target": "string or null"
  },

  "loan": {
    "intent": "enum: [loan_add, loan_update, loan_payment, loan_query, loan_close, null]",
    "lender": "string or null",
    "amount": "float or null"
  },

  "salary": {
    "intent": "enum: [salary_add, salary_update, salary_delete, salary_query, null]",
    "month": "string or null",
    "amount": "float or null"
  },

  "account": {
    "intent": "enum: [account_add, account_update, account_delete, account_query, null]",
    "account_name": "string or null",
    "account_type": "string or null"
  },

  "delete": {
    "intent": "enum: [delete_transaction, delete_all_period, null]",
    "selection_mode": "enum: [single, multiple, last5, date, range, null]",
    "target_date": "string or null"
  },

  "report": {
    "intent": "enum: [report, statistics, summary, chart, budget, export, null]",
    "format": "enum: [PDF, CSV, Excel, JSON, null]",
    "period": "string or null"
  }
}

FEW-SHOT EXAMPLES:

User: "John sent 4k day before yesterday"
Output:
{
  "metadata": {
    "raw_user_text": "John sent 4k day before yesterday",
    "operation_type": "single", "language": "English", "entry_source": "telegram",
    "bulk_operation": false, "category_lookup_required": true, "unsupported_chat": false, "account_required": false
  },
  "transactions": [
    {
      "transaction_sequence": 1, "execution_order": 1, "intent": "income", "amount": 4000, 
      "normalized_currency": "INR", "item": "Received from John", "payment_method": null,
      "category": null, "subcategory": null,
      "source_account": null, "destination_account": null,
      "date": {"raw_expression": "day before yesterday", "relative_date": "2026-08-03", "date_type": "relative"}, "future": {"is_future": false},
      "validation": {"amount_valid": true, "date_valid": true, "item_valid": true, "account_valid": false},
      "duplicate_detection": {"possible_duplicate": false, "duplicate_reference": null},
      "needs_clarification": false, "confidence": {"overall_confidence": 0.99}
    }
  ]
}

User: "received extra income of 50"
Output:
{
  "metadata": {
    "raw_user_text": "received extra income of 50",
    "operation_type": "single", "language": "English", "entry_source": "telegram",
    "bulk_operation": false, "category_lookup_required": false, "unsupported_chat": false, "account_required": false
  },
  "transactions": [
    {
      "transaction_sequence": 1, "execution_order": 1, "intent": "income", "amount": 50, 
      "normalized_currency": "INR", "item": "Extra Income", "payment_method": null,
      "category": "Income", "subcategory": "Other Income",
      "source_account": null, "destination_account": null,
      "date": {"raw_expression": "today", "relative_date": null, "date_type": "relative"}, "future": {"is_future": false},
      "validation": {"amount_valid": true, "date_valid": true, "item_valid": true, "account_valid": false},
      "duplicate_detection": {"possible_duplicate": false, "duplicate_reference": null},
      "needs_clarification": true, "clarification_fields": ["source name"], "confidence": {"overall_confidence": 0.95}
    }
  ]
}

User: "got 10k from raj yesterday"
Output:
{
  "metadata": {
    "raw_user_text": "got 10k from raj yesterday",
    "operation_type": "single", "language": "English", "entry_source": "telegram",
    "bulk_operation": false, "category_lookup_required": true, "unsupported_chat": false, "account_required": false
  },
  "transactions": [
    {
      "transaction_sequence": 1, "execution_order": 1, "intent": "income", "amount": 10000, 
      "normalized_currency": "INR", "item": "Received from Raj", "payment_method": null,
      "category": null, "subcategory": null,
      "source_account": null, "destination_account": null,
      "date": {"raw_expression": "yesterday", "relative_date": "2026-08-04", "date_type": "relative"}, "future": {"is_future": false},
      "validation": {"amount_valid": true, "date_valid": true, "item_valid": true, "account_valid": false},
      "duplicate_detection": {"possible_duplicate": false, "duplicate_reference": null},
      "needs_clarification": false, "confidence": {"overall_confidence": 0.98}
    }
  ]
}

User: "send 10000 from SBI to Axis account"
Output:
{
  "metadata": {
    "raw_user_text": "send 10000 from SBI to Axis account",
    "operation_type": "single", "language": "English", "entry_source": "telegram",
    "bulk_operation": false, "category_lookup_required": false, "unsupported_chat": false, "account_required": true
  },
  "transactions": [
    {
      "transaction_sequence": 1, "execution_order": 1, "intent": "transfer_own", "amount": 10000, 
      "normalized_currency": "INR", "item": "Self Transfer", "payment_method": null,
      "category": "Transfers", "subcategory": "Bank Account Transfer",
      "source_account": "SBI", "destination_account": "Axis",
      "date": {"raw_expression": "today", "relative_date": null, "date_type": "relative"}, "future": {"is_future": false},
      "validation": {"amount_valid": true, "date_valid": true, "item_valid": true, "account_valid": true},
      "duplicate_detection": {"possible_duplicate": false, "duplicate_reference": null},
      "needs_clarification": false, "confidence": {"overall_confidence": 0.99}
    }
  ]
}
"""


# =====================================================================

@app.get("/")
def health_check():
    return {"status": "PocketMunim Enterprise API is live", "status_code": 200}


def get_account_from_list(accounts_list, target_name=None):
    if not accounts_list: return None
    if target_name:
        target_clean = target_name.strip().lower()
        for acc in accounts_list:
            if acc['account_name'].lower() == target_clean:
                return acc
        return None
    for acc in accounts_list:
        if acc.get('is_default'): return acc
    return accounts_list[0]


# =====================================================================
# DYNAMIC NEXT-LEVEL AI HTML REPORT ENDPOINT (1-Hour Expiry)
# =====================================================================
@app.get("/report/view/{token}", response_class=HTMLResponse)
async def view_report(token: str):
    token_data = REPORT_TOKENS.get(token)
    if not token_data:
        raise HTTPException(status_code=404, detail="Report link expired or invalid.")

    if datetime.now(TZ_IST) > token_data["expires_at"]:
        del REPORT_TOKENS[token]
        raise HTTPException(status_code=410, detail="Report link has expired (1-hour validity exceeded).")

    user_id = token_data["user_id"]

    # Fetch user details
    user_res = supabase_admin.table('users').select('*').eq('id', user_id).execute()
    user_name = user_res.data[0]['full_name'] if user_res.data else "Valued User"

    # Fetch accounts
    acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
    accounts = acc_res.data or []
    total_balance = sum(float(a['balance']) for a in accounts)

    # Fetch transactions
    txn_res = supabase_admin.table('transactions').select('*').eq('user_id', user_id).eq('soft_deleted', False).order(
        'date', desc=True).execute()
    txns = txn_res.data or []

    total_income = sum(float(t['amount']) for t in txns if t['txn_type'] == 'income')
    total_expense = sum(float(t['amount']) for t in txns if t['txn_type'] == 'expense')
    net_savings = total_income - total_expense

    # Build HTML with Next-Level AI Styling, Phases, and Vibrant Colors
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>PocketMunim AI Financial Intelligence Report</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>body {{ font-family: 'Plus Jakarta Sans', sans-serif; }}</style>
    </head>
    <body class="bg-slate-950 text-slate-100 min-h-screen py-10 px-4 sm:px-6 lg:px-8">
        <div class="max-w-5xl mx-auto space-y-8">
            <!-- Header Phase -->
            <div class="bg-gradient-to-r from-indigo-900 via-purple-900 to-slate-900 border border-indigo-500/30 rounded-3xl p-8 shadow-2xl flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
                <div>
                    <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/20 text-indigo-300 text-xs font-semibold mb-3">
                        <span class="w-2 h-2 rounded-full bg-indigo-400 animate-pulse"></span>
                        AI Intelligence Report &bull; Ishita Financial Intelligence (I) Pvt Ltd
                    </div>
                    <h1 class="text-3xl font-bold tracking-tight text-white">Financial Dashboard: {user_name}</h1>
                    <p class="text-slate-400 text-sm mt-1">Generated live on {datetime.now(TZ_IST).strftime('%d %B %Y, %I:%M %p')} IST (Expires in 1 Hour)</p>
                </div>
                <div class="bg-slate-900/80 border border-slate-700/60 rounded-2xl p-4 text-right">
                    <p class="text-xs text-slate-400 font-medium">Net Worth / Balance</p>
                    <p class="text-2xl font-extrabold text-emerald-400">₹{total_balance:,.2f}</p>
                </div>
            </div>

            <!-- Metrics Phase -->
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-6">
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-lg border-l-4 border-l-emerald-500">
                    <p class="text-sm font-medium text-slate-400">Total Income</p>
                    <p class="text-2xl font-bold text-emerald-400 mt-2">₹{total_income:,.2f}</p>
                </div>
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-lg border-l-4 border-l-rose-500">
                    <p class="text-sm font-medium text-slate-400">Total Expenses</p>
                    <p class="text-2xl font-bold text-rose-400 mt-2">₹{total_expense:,.2f}</p>
                </div>
                <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-lg border-l-4 border-l-cyan-500">
                    <p class="text-sm font-medium text-slate-400">Net Savings</p>
                    <p class="text-2xl font-bold text-cyan-400 mt-2">₹{net_savings:,.2f}</p>
                </div>
            </div>

            <!-- Accounts Phase -->
            <div class="bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-xl">
                <h2 class="text-xl font-bold text-white mb-4">Linked Bank Accounts</h2>
                <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {"".join([f'''<div class="bg-slate-950 border border-slate-800 p-4 rounded-xl flex justify-between items-center">
                        <span class="font-semibold text-slate-200">{acc["account_name"]}</span>
                        <span class="font-mono text-emerald-400">₹{float(acc["balance"]):,.2f}</span>
                    </div>''' for acc in accounts])}
                </div>
            </div>

            <!-- Transactions Ledger Phase -->
            <div class="bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-xl">
                <h2 class="text-xl font-bold text-white mb-4">Transaction History</h2>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-sm text-slate-300">
                        <thead class="bg-slate-950 text-slate-400 uppercase text-xs tracking-wider border-b border-slate-800">
                            <tr>
                                <th class="py-3 px-4">Date</th>
                                <th class="py-3 px-4">Description</th>
                                <th class="py-3 px-4">Category</th>
                                <th class="py-3 px-4">Type</th>
                                <th class="py-3 px-4 text-right">Amount</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-800">
                            {"".join([f'''<tr class="hover:bg-slate-800/50">
                                <td class="py-3 px-4 text-slate-400">{datetime.fromisoformat(t["date"].replace('Z', '+00:00')).astimezone(TZ_IST).strftime('%d %b %Y')}</td>
                                <td class="py-3 px-4 font-medium text-white">{t["description"]}</td>
                                <td class="py-3 px-4 text-slate-400">{t["category"] or "Unassigned"}</td>
                                <td class="py-3 px-4"><span class="px-2 py-1 rounded-full text-xs font-semibold {'bg-emerald-500/20 text-emerald-300' if t['txn_type'] == 'income' else 'bg-rose-500/20 text-rose-300'}">{t["txn_type"].upper()}</span></td>
                                <td class="py-3 px-4 text-right font-mono {'text-emerald-400' if t['txn_type'] == 'income' else 'text-rose-400'}">{'+' if t['txn_type'] == 'income' else '-'}₹{float(t["amount"]):,.2f}</td>
                            </tr>''' for t in txns[:50]])}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Footer Phase -->
            <div class="text-center text-xs text-slate-500 pt-4">
                &copy; 2026 Ishita Financial Intelligence (I) Private Limited. All rights reserved. Powered by PocketMunim AI.
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# =====================================================================
# WEBHOOK HANDLER
# =====================================================================
@app.post("/webhook")
async def telegram_webhook(request: Request, authorized: bool = Depends(authenticate_telegram_request)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # =====================================================================
    # CALLBACK QUERY HANDLER (INTERACTIVE DUPLICATE CHECKBOXES)
    # =====================================================================
    if "callback_query" in payload:
        cb = payload["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        message_id = cb["message"]["message_id"]
        user_id = str(cb["from"]["id"])
        data = cb["data"]

        # Acknowledge tap to remove loading icon
        async with httpx.AsyncClient() as client:
            await client.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery",
                              json={"callback_query_id": cb["id"]})

        if data.startswith("btog_"):
            parts = data.split("_")
            batch_id, item_id = parts[1], int(parts[2])
            if batch_id in PENDING_BATCHES:
                current_state = PENDING_BATCHES[batch_id]["items"][item_id]["selected"]
                PENDING_BATCHES[batch_id]["items"][item_id]["selected"] = not current_state
                kb = generate_duplicate_keyboard(batch_id, PENDING_BATCHES[batch_id]["items"])
                await edit_telegram_message(chat_id, message_id, reply_markup=kb)

        elif data.startswith("bconf_"):
            batch_id = data.split("_")[1]
            if batch_id in PENDING_BATCHES:
                batch = PENDING_BATCHES[batch_id]
                selected_items = [item for item in batch["items"] if item["selected"]]

                if not selected_items:
                    await edit_telegram_message(chat_id, message_id, text="❌ No duplicates selected. Batch discarded.")
                else:
                    dao = BulkTransactionDAO(supabase_admin, user_id)
                    selected_payloads = [i["payload"] for i in selected_items]

                    acc_res = supabase_admin.table('accounts').select('*').eq('id', batch["account_id"]).execute()
                    if acc_res.data:
                        default_acc_name = acc_res.data[0]['account_name']
                        current_bal = float(acc_res.data[0]['balance'])

                        total_deduction = sum(
                            p["amount"] for p in selected_payloads if p["source_account"] == default_acc_name)
                        total_addition = sum(
                            p["amount"] for p in selected_payloads if p["destination_account"] == default_acc_name)

                        if (current_bal - total_deduction + total_addition) < 0:
                            await edit_telegram_message(chat_id, message_id,
                                                        text="❌ Insufficient balance to save selected duplicates.")
                        else:
                            dao.execute_bulk_commit(batch["account_id"], selected_payloads, total_deduction,
                                                    total_addition, current_bal)
                            await edit_telegram_message(chat_id, message_id,
                                                        text=f"✅ {len(selected_payloads)} duplicate transactions confirmed and saved.")
                del PENDING_BATCHES[batch_id]

        elif data.startswith("bcanc_"):
            batch_id = data.split("_")[1]
            if batch_id in PENDING_BATCHES:
                del PENDING_BATCHES[batch_id]
            await edit_telegram_message(chat_id, message_id, text="❌ All duplicate transactions discarded.")
        return {"ok": True}

    message = payload.get("message", {})
    if not message:
        message = payload.get("edited_message", {})

    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()

    if not text or not chat_id:
        return {"ok": True}

    user_id = str(request.state.telegram_id)

    # =====================================================================
    # WAF: INJECTION PROTECTION & STRIKE TRACKER
    # =====================================================================
    if MALICIOUS_PATTERN.search(text):
        user_res = supabase_admin.table('users').select('security_strikes').eq('telegram_id', chat_id).execute()
        current_strikes = 0
        if user_res.data:
            current_strikes = user_res.data[0].get('security_strikes') or 0

        new_strikes = current_strikes + 1
        supabase_admin.table('users').update({'security_strikes': new_strikes}).eq('telegram_id', chat_id).execute()

        if new_strikes >= 3:
            await send_telegram_reply(chat_id,
                                      "🚨 *ACCOUNT BLOCKED*\n\nMultiple malicious inputs detected. Your account has been suspended for security reasons.")
        else:
            await send_telegram_reply(chat_id,
                                      f"⚠️ *SECURITY WARNING ({new_strikes}/3)*\n\nMalicious input detected. Please refrain from sending injection scripts. Your account will be blocked after 3 strikes.")
        return {"ok": True}

    user_res = supabase_admin.table('users').select('*').eq('telegram_id', chat_id).execute()
    user_exists = bool(user_res.data)

    if user_exists and user_res.data[0].get('security_strikes', 0) >= 3:
        await send_telegram_reply(chat_id,
                                  "🚨 *ACCOUNT BLOCKED*\n\nYour account is suspended due to security violations.")
        return {"ok": True}

    # =====================================================================
    # MANDATORY REGISTRATION GATEWAY & SALARY STRUCTURING
    # =====================================================================
    if not user_exists and not text.startswith("/register"):
        copyable_form = "```text\n/register\nName: [Your Name]\nCurrency: INR\nMonthly Salary: [Amount]\nBank Account: [Bank Name]\nCurrent Balance: [Amount]\n```"
        await send_telegram_reply(chat_id,
                                  f"🚨 *Registration Mandatory*\n\nTo use PocketMunim, you must register your account first.\n\n📋 *Copy, fill, and send the exact form below:*\n{copyable_form}")
        return {"ok": True}

    if text.startswith("/register"):
        if "[" in text or "]" in text or "Your Name" in text or len(text.replace("/register", "").strip()) < 10:
            copyable_form = "```text\n/register\nName: [Your Name]\nCurrency: INR\nMonthly Salary: [Amount]\nBank Account: [Bank Name]\nCurrent Balance: [Amount]\n```"
            await send_telegram_reply(chat_id,
                                      f"⚠️ *Invalid or Incomplete Registration Form*\n\nPlease fill in all required fields properly without placeholder brackets.\n\n📋 *Copy and fill this form:*\n{copyable_form}")
            return {"ok": True}

        lines = text.split("\n")
        name = ""
        currency = "INR"
        monthly_salary = None
        bank_name = ""
        current_balance = None

        for line in lines:
            if "Name:" in line: name = line.split("Name:")[1].strip().title()
            if "Currency:" in line: currency = line.split("Currency:")[1].strip().upper()
            if "Monthly Salary:" in line:
                try:
                    monthly_salary = float(line.split("Monthly Salary:")[1].strip().replace(",", ""))
                except:
                    pass
            if "Bank Account:" in line: bank_name = line.split("Bank Account:")[1].strip().title()
            if "Current Balance:" in line:
                try:
                    current_balance = float(line.split("Current Balance:")[1].strip().replace(",", ""))
                except:
                    pass

        if not name or monthly_salary is None or not bank_name or current_balance is None:
            await send_telegram_reply(chat_id,
                                      "❌ *Registration Failed*\n\nMissing required fields. Please ensure Name, Monthly Salary, Bank Account, and Current Balance are provided.")
            return {"ok": True}

        if not user_exists:
            try:
                supabase_admin.table('users').insert(
                    {"id": user_id, "telegram_id": chat_id, "full_name": name, "currency": currency,
                     "security_strikes": 0}).execute()

                acc_res = supabase_admin.table('accounts').insert({
                    "user_id": user_id, "account_name": bank_name, "balance": current_balance, "is_default": True
                }).execute()
                acc_id = acc_res.data[0]['id']

                current_dt = datetime.now(TZ_IST)
                current_year = current_dt.year
                current_month = current_dt.month

                total_salary_added = 0.0

                if monthly_salary > 0:
                    for m in range(1, current_month):
                        last_day = calendar.monthrange(current_year, m)[1]
                        salary_date = current_dt.replace(year=current_year, month=m, day=last_day, hour=23, minute=59,
                                                         second=59)
                        month_name = salary_date.strftime('%b %Y')

                        # Populate salaries table
                        supabase_admin.table('salaries').insert({
                            "user_id": user_id,
                            "year": current_year,
                            "month_number": m,
                            "month_name": month_name,
                            "amount": monthly_salary,
                            "is_deducted": False
                        }).execute()

                        # Populate transactions table with explicit category/subcategory (Observation 2 & 3)
                        supabase_admin.table('transactions').insert({
                            "user_id": user_id,
                            "amount": monthly_salary,
                            "txn_type": "income",
                            "description": f"Salary for {month_name}",
                            "intent": "income",
                            "category": "Income",
                            "subcategory": "Salary",
                            "date": salary_date.isoformat(),
                            "source_account": None,
                            "destination_account": bank_name,
                            "soft_deleted": False
                        }).execute()
                        total_salary_added += monthly_salary

                final_balance = current_balance + total_salary_added
                supabase_admin.table('accounts').update({"balance": final_balance}).eq("id", acc_id).execute()

                if total_salary_added > 0:
                    supabase_admin.table('account_logs').insert({
                        "account_id": acc_id,
                        "user_id": user_id,
                        "log_type": "CREDIT",
                        "amount": total_salary_added,
                        "balance_after": final_balance,
                        "description": "Retroactive Salary Structuring"
                    }).execute()

                welcome_msg = (
                    f"✅ *Registration Successful!*\n\n"
                    f"Welcome to PocketMunim, *{name}*!\n\n"
                    f"Your account is active. We have automatically structured your salary for {current_year}.\n"
                    f"Your **{bank_name}** account balance has been updated to **₹{final_balance:,.2f}** "
                    f"(inclusive of ₹{total_salary_added:,.2f} past salary credits).\n\n"
                    f"Warm Regards,\n"
                    f"*PocketMunim Team*\n"
                    f"Ishita Financial Intelligence (I) Private Limited."
                )
                await send_telegram_reply(chat_id, welcome_msg)

            except Exception as e:
                await send_telegram_reply(chat_id, f"❌ Registration failed: {str(e)}")
        else:
            await send_telegram_reply(chat_id, "ℹ️ You are already registered with PocketMunim!")
        return {"ok": True}

    # =====================================================================
    # COMMAND: /SETSALARY
    # =====================================================================
    if text.startswith("/setsalary"):
        parts = text.replace("/setsalary", "").strip().split()
        if len(parts) < 2:
            await send_telegram_reply(chat_id,
                                      "⚠️ Use format: `/setsalary [Month/Year] [Amount]`\nExample: `/setsalary March 60000` or `/setsalary 2024 50000`")
            return {"ok": True}

        timeframe = parts[0].strip().lower()
        try:
            new_amount = float(parts[1].replace(",", ""))
        except:
            await send_telegram_reply(chat_id, "⚠️ Invalid amount.")
            return {"ok": True}

        current_dt = datetime.now(TZ_IST)
        target_months = []
        target_year = current_dt.year

        month_map = {"1": "1", "jan": "1", "january": "1", "2": "2", "feb": "2", "february": "2", "3": "3", "mar": "3",
                     "march": "3", "4": "4", "apr": "4", "april": "4", "5": "5", "may": "5", "6": "6", "jun": "6",
                     "june": "6", "7": "7", "jul": "7", "july": "7", "8": "8", "aug": "8", "august": "8", "9": "9",
                     "sep": "9", "september": "9", "10": "10", "oct": "10", "october": "10", "11": "11", "nov": "11",
                     "november": "11", "12": "12", "dec": "12", "december": "12"}

        if timeframe.isdigit() and len(timeframe) == 4:
            target_year = int(timeframe)
            target_months = list(range(1, 13))
        elif timeframe in month_map:
            target_months = [int(month_map[timeframe])]
        else:
            await send_telegram_reply(chat_id, f"⚠️ Unknown month or year: '{timeframe}'")
            return {"ok": True}

        acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).eq('is_default', True).execute()
        if not acc_res.data:
            await send_telegram_reply(chat_id, "❌ No default account found.")
            return {"ok": True}
        default_acc = acc_res.data[0]

        balance_adjustment = 0.0

        for m in target_months:
            last_day = calendar.monthrange(target_year, m)[1]
            salary_date = current_dt.replace(year=target_year, month=m, day=last_day, hour=23, minute=59, second=59)
            month_name = salary_date.strftime('%b %Y')

            # Check salaries table
            sal_check = supabase_admin.table('salaries').select('*') \
                .eq('user_id', user_id) \
                .eq('year', target_year) \
                .eq('month_number', m) \
                .execute()

            if sal_check.data:
                sal_id = sal_check.data[0]['id']
                old_amount = float(sal_check.data[0]['amount'])
                if sal_check.data[0]['is_deducted']:
                    await send_telegram_reply(chat_id,
                                              f"⚠️ Salary for {month_name} has already been deducted and cannot be modified directly.")
                    continue
                diff = new_amount - old_amount
                balance_adjustment += diff
                supabase_admin.table('salaries').update({"amount": new_amount}).eq("id", sal_id).execute()

                # Update corresponding transaction
                supabase_admin.table('transactions').update({"amount": new_amount}) \
                    .eq('user_id', user_id) \
                    .eq('subcategory', 'Salary') \
                    .eq('date', salary_date.isoformat()) \
                    .execute()
            else:
                balance_adjustment += new_amount
                supabase_admin.table('salaries').insert({
                    "user_id": user_id,
                    "year": target_year,
                    "month_number": m,
                    "month_name": month_name,
                    "amount": new_amount,
                    "is_deducted": False
                }).execute()

                supabase_admin.table('transactions').insert({
                    "user_id": user_id,
                    "amount": new_amount,
                    "txn_type": "income",
                    "description": f"Salary for {month_name}",
                    "intent": "income",
                    "category": "Income",
                    "subcategory": "Salary",
                    "date": salary_date.isoformat(),
                    "source_account": None,
                    "destination_account": default_acc['account_name'],
                    "soft_deleted": False
                }).execute()

        new_bal = float(default_acc['balance']) + balance_adjustment
        supabase_admin.table('accounts').update({"balance": new_bal}).eq("id", default_acc['id']).execute()

        log_type = "CREDIT" if balance_adjustment >= 0 else "DEBIT"
        if balance_adjustment != 0:
            supabase_admin.table('account_logs').insert({
                "account_id": default_acc['id'],
                "user_id": user_id,
                "log_type": log_type,
                "amount": abs(balance_adjustment),
                "balance_after": new_bal,
                "description": f"Salary Update ({timeframe})"
            }).execute()

        await send_telegram_reply(chat_id,
                                  f"✅ Salary updated successfully for {timeframe.title()}.\nAccount balance adjusted by ₹{balance_adjustment:,.2f}.\nNew Balance: ₹{new_bal:,.2f}")
        return {"ok": True}

    # =====================================================================
    # NLP OVERRIDE: DEDUCT ALL AMOUNT OF [MONTH] (With Hard Block for Double Deduction)
    # =====================================================================
    deduct_all_match = re.match(r"^deduct all amount of ([a-zA-Z]+)$", text, re.IGNORECASE)
    if deduct_all_match:
        month_str = deduct_all_match.group(1).lower()
        month_map = {"jan": "1", "january": "1", "feb": "2", "february": "2", "mar": "3", "march": "3", "apr": "4",
                     "april": "4", "may": "5", "jun": "6", "june": "6", "jul": "7", "july": "7", "aug": "8",
                     "august": "8", "sep": "9", "september": "9", "oct": "10", "october": "10", "nov": "11",
                     "november": "11", "dec": "12", "december": "12"}
        if month_str not in month_map:
            await send_telegram_reply(chat_id, "⚠️ Invalid month provided.")
            return {"ok": True}

        target_m = int(month_map[month_str])
        current_dt = datetime.now(TZ_IST)
        target_year = current_dt.year

        # Check salaries table
        sal_res = supabase_admin.table('salaries').select('*') \
            .eq('user_id', user_id) \
            .eq('year', target_year) \
            .eq('month_number', target_m) \
            .execute()

        if not sal_res.data:
            await send_telegram_reply(chat_id, f"❌ No salary record found for {month_str.title()} {target_year}.")
            return {"ok": True}

        sal_record = sal_res.data[0]

        # HARD BLOCK FOR DOUBLE DEDUCTION (Observation 4)
        if sal_record['is_deducted']:
            await send_telegram_reply(chat_id,
                                      f"❌ *Hard Block Activated*\n\nSalary for **{month_str.title()} {target_year}** (₹{float(sal_record['amount']):,.2f}) has **already been fully deducted**. Duplicate deductions are strictly blocked.")
            return {"ok": True}

        salary_amount = float(sal_record['amount'])

        acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).eq('is_default', True).execute()
        if not acc_res.data:
            return {"ok": True}
        default_acc = acc_res.data[0]
        current_bal = float(default_acc['balance'])

        if current_bal < salary_amount:
            await send_telegram_reply(chat_id, f"❌ Insufficient balance to deduct ₹{salary_amount:,.2f}.")
            return {"ok": True}

        last_day = calendar.monthrange(target_year, target_m)[1]
        expense_date = current_dt.replace(year=target_year, month=target_m, day=last_day, hour=23, minute=59, second=59)

        # Insert expense transaction
        supabase_admin.table('transactions').insert({
            "user_id": user_id,
            "amount": salary_amount,
            "txn_type": "expense",
            "description": f"Deducted all amount of {month_str.title()}",
            "intent": "expense",
            "category": "Miscellaneous",
            "subcategory": "Monthly Clear",
            "date": expense_date.isoformat(),
            "source_account": default_acc['account_name'],
            "destination_account": None,
            "soft_deleted": False
        }).execute()

        # Mark salary as deducted in salaries table
        supabase_admin.table('salaries').update({"is_deducted": True}).eq("id", sal_record['id']).execute()

        new_bal = current_bal - salary_amount
        supabase_admin.table('accounts').update({"balance": new_bal}).eq("id", default_acc['id']).execute()

        supabase_admin.table('account_logs').insert({
            "account_id": default_acc['id'],
            "user_id": user_id,
            "log_type": "DEBIT",
            "amount": salary_amount,
            "balance_after": new_bal,
            "description": f"Deducted all amount of {month_str.title()}"
        }).execute()

        await send_telegram_reply(chat_id,
                                  f"✅ Deducted ₹{salary_amount:,.2f} for {month_str.title()} successfully.\nNew Balance: ₹{new_bal:,.2f}")
        return {"ok": True}

    # =====================================================================
    # COMMAND: /REPORT (Generates 1-Hour Secure Dynamic HTML Link)
    # =====================================================================
    elif text.startswith("/report"):
        token = str(uuid.uuid4())
        expires_at = datetime.now(TZ_IST) + timedelta(hours=1)
        REPORT_TOKENS[token] = {"user_id": user_id, "expires_at": expires_at}

        report_url = f"https://{request.url.hostname}/report/view/{token}" if request.url.hostname else f"http://localhost:8000/report/view/{token}"

        response_msg = (
            f"📊 *Next-Level AI Financial Report Generated*\n\n"
            f"Your interactive HTML report is ready with phase-by-phase analytics and color-coded metrics.\n\n"
            f"🔗 [View Downloadable Report]({report_url})\n\n"
            f"⏰ *Note:* This secure link will automatically expire in **1 hour**."
        )
        await send_telegram_reply(chat_id, response_msg)
        return {"ok": True}

    # =====================================================================
    # STANDARD COMMANDS
    # =====================================================================
    if text.startswith("/addaccount"):
        parts = text.replace("/addaccount", "").strip().split()
        if len(parts) < 2:
            await send_telegram_reply(chat_id,
                                      "⚠️ Invalid format. Use: `/addaccount [BankName] [InitialBalance]`\nExample: `/addaccount HDFC 5000`")
            return {"ok": True}

        acc_name = " ".join(parts[:-1]).title()

        try:
            acc_bal = float(parts[-1])
        except ValueError:
            await send_telegram_reply(chat_id, "⚠️ Invalid balance amount. Please provide a valid number.")
            return {"ok": True}

        existing_accs = supabase_admin.table('accounts').select('id').eq('user_id', user_id).execute()
        is_first = len(existing_accs.data) == 0
        try:
            supabase_admin.table('accounts').insert({
                "user_id": user_id, "account_name": acc_name, "balance": acc_bal, "is_default": is_first
            }).execute()
            def_msg = " (Set as Default)" if is_first else ""
            await send_telegram_reply(chat_id,
                                      f"🏦 *Account Added*\nName: {acc_name}\nBalance: ₹{acc_bal:,.2f}{def_msg}")
        except Exception as e:
            await send_telegram_reply(chat_id, f"❌ Failed to add account: {str(e)}")
        return {"ok": True}

    elif text.startswith("/setdefault"):
        acc_name = text.replace("/setdefault", "").strip().title()

        if not acc_name:
            await send_telegram_reply(chat_id, "⚠️ Please provide an account name. Example: `/setdefault HDFC`")
            return {"ok": True}
        acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).ilike('account_name',
                                                                                            acc_name).execute()
        if not acc_res.data:
            await send_telegram_reply(chat_id, f"❌ Account '{acc_name}' not found.")
            return {"ok": True}
        try:
            supabase_admin.table('accounts').update({"is_default": False}).eq('user_id', user_id).execute()
            supabase_admin.table('accounts').update({"is_default": True}).eq('id', acc_res.data[0]['id']).execute()
            await send_telegram_reply(chat_id, f"✅ '{acc_res.data[0]['account_name']}' is now your default account.")
        except Exception as e:
            await send_telegram_reply(chat_id, f"❌ Failed to set default: {str(e)}")
        return {"ok": True}

    elif text.startswith("/start"):
        await send_telegram_reply(chat_id,
                                  "Welcome to PocketMunim.\n\nYour automated financial intelligence system is active.")
        return {"ok": True}

    elif text.startswith("/categorypull"):
        query = text.replace("/categorypull", "").strip()
        await send_telegram_reply(chat_id, f"⏳ Pulling categories...")
        pull_result = category_pull_service.manual_category_pull(query, user_id)
        if pull_result.get("added", 0) > 0:
            CategoryCacheManager(supabase, user_id).rebuild_cache()
            await send_telegram_reply(chat_id, f"✅ Successfully pulled {pull_result['added']} items.")
        else:
            await send_telegram_reply(chat_id, f"❌ Failed to pull categories: {pull_result.get('error')}")
        return {"ok": True}

    elif text.startswith("/history"):
        template = """📋 *Historical Data Auto-Template*
Copy this block, fill in your past numbers, and send it back. The system will strictly sync everything to your ledger:

```text
Salary for Jan 2025 was 50000 received in SBI
Rent for Jan 2025 was 15000 paid from SBI
Electricity for Jan 2025 was 2000 paid from SBI
```"""
        await send_telegram_reply(chat_id, template)
        return {"ok": True}

    elif text.startswith("/monthly"):
        parts = text.replace("/monthly", "").strip().split()
        if len(parts) < 2:
            await send_telegram_reply(chat_id, "⚠️ Use format: `/monthly [Month] [Year]`\nExample: `/monthly Jan 2025`")
            return {"ok": True}

        month_str, year_str = parts[0][:3], parts[1]
        try:
            target_dt = datetime.strptime(f"1 {month_str} {year_str}", "%d %b %Y")
            start_date = target_dt.strftime("%Y-%m-%d")

            if target_dt.month == 12:
                end_dt = target_dt.replace(year=target_dt.year + 1, month=1)
            else:
                end_dt = target_dt.replace(month=target_dt.month + 1)
            end_date = end_dt.strftime("%Y-%m-%d")

            txns = supabase_admin.table('transactions') \
                .select('amount, txn_type') \
                .eq('user_id', user_id) \
                .gte('date', start_date) \
                .lt('date', end_date) \
                .eq('soft_deleted', False) \
                .execute()

            total_income = sum(t['amount'] for t in txns.data if t['txn_type'] == 'income')
            total_expense = sum(t['amount'] for t in txns.data if t['txn_type'] == 'expense')
            net_saved = total_income - total_expense

            reply = f"📊 *Monthly Report: {target_dt.strftime('%B %Y')}*\n\n"
            reply += f"🟢 *Total Income:* ₹{total_income:,.2f}\n"
            reply += f"🔴 *Total Expense:* ₹{total_expense:,.2f}\n"
            reply += "------------------------\n"
            reply += f"💰 *Net Saved (Carry Forward):* ₹{net_saved:,.2f}"

            await send_telegram_reply(chat_id, reply)

        except ValueError:
            await send_telegram_reply(chat_id, "⚠️ Invalid date format. Use: `/monthly Jan 2025`")
        return {"ok": True}

    # =====================================================================
    # NLP ENGINE PROCESSING
    # =====================================================================
    else:
        try:
            current_dt = datetime.now(TZ_IST)

            dynamic_system_prompt = SYSTEM_PROMPT.replace(
                "{CURRENT_DATE}",
                f"{current_dt.strftime('%Y-%m-%d')} ({current_dt.strftime('%A')})"
            )

            raw_response_text = execute_resilient_ai(system_prompt=dynamic_system_prompt, user_prompt=text,
                                                     db_client=supabase_admin, is_json=True)
            raw_json = json.loads(raw_response_text)

            validated_data = AITransactionExtraction(**raw_json)
            transactions_list = validated_data.transactions
            response_sections = []
            committed_items = []

            acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
            user_accounts = acc_res.data or []

            if not user_accounts and transactions_list:
                await send_telegram_reply(chat_id,
                                          "❌ *No Bank Accounts Configured*\n\nYou must add an account before logging transactions.\n\nUse this command:\n`/addaccount [BankName] [Balance]`\nExample: `/addaccount HDFC 50000`")
                return {"ok": True}

            if validated_data.loan and validated_data.loan.intent == "loan_payment":
                lender_name = validated_data.loan.lender
                if lender_name:
                    loan_check = supabase_admin.table('loans').select('*').eq('user_id', user_id).ilike('lender',
                                                                                                        lender_name).execute()
                    if not loan_check.data:
                        await send_telegram_reply(chat_id,
                                                  f"❌ *Loan Verification Failed*\n\nNo active loan record found for lender **'{lender_name}'**.")
                        return {"ok": True}

            if supabase and transactions_list:
                cache_manager = CategoryCacheManager(supabase, user_id)

                # =====================================================================
                # BULK TRANSACTION PIPELINE (If more than 1 item)
                # =====================================================================
                if len(transactions_list) > 1:
                    default_acc = get_account_from_list(user_accounts)
                    bulk_service = BulkTransactionService(supabase_admin, user_id, cache_manager, category_pull_service)

                    result = bulk_service.process_bulk_payload(transactions_list, default_acc)

                    if result["unique"]:
                        current_bal = float(default_acc['balance'])
                        total_deduction = sum(
                            p["amount"] for p in result["unique"] if p["source_account"] == default_acc['account_name'])
                        total_addition = sum(p["amount"] for p in result["unique"] if
                                             p["destination_account"] == default_acc['account_name'])

                        if (current_bal - total_deduction + total_addition) < 0:
                            await send_telegram_reply(chat_id,
                                                      f"❌ *Insufficient Balance*\nAccount **'{default_acc['account_name']}'** has ₹{current_bal:,.2f}, but unique items require more funds.")
                            return {"ok": True}

                        bulk_service.dao.execute_bulk_commit(default_acc['id'], result["unique"], total_deduction,
                                                             total_addition, current_bal)

                        bd_text = "\n".join(result["breakdown"]) if result["breakdown"] else "No unique items."
                        receipt = (
                            f"🧾 *BULK TRANSACTION SAVED*\n"
                            f"🔴 *EXPENSE* | 🟢 *INCOME* | 🔵 *TRANSFER*\n\n"
                            f"🔹 *Total Expenses:* ₹{result['totals']['expenses']:,.2f}\n"
                            f"🔹 *Total Income:* ₹{result['totals']['income']:,.2f}\n"
                            f"🔹 *Total Transfers:* ₹{result['totals']['transfers']:,.2f}\n\n"
                            f"🔹 *Items Processed:* {len(result['unique'])}\n"
                            f"🔹 *Primary Account:* {default_acc['account_name']}\n"
                            f"🔹 *Date:* Today\n\n"
                            f"🛒 *Receipt Breakdown:*\n{bd_text}\n\n"
                            f"✅ *All unique items categorized and synced to ledger.*"
                        )
                        await send_telegram_reply(chat_id, receipt)

                    if result["duplicates"]:
                        batch_id = uuid.uuid4().hex[:8]
                        PENDING_BATCHES[batch_id] = {
                            "user_id": user_id,
                            "account_id": default_acc['id'],
                            "items": result["duplicates"]
                        }
                        dup_msg = (
                            f"⚠️ *Duplicate Entries Found ({len(result['duplicates'])} items)*\n"
                            f"The items below already exist in your ledger. Tap the boxes to select the ones you want to save, then confirm."
                        )
                        keyboard = generate_duplicate_keyboard(batch_id, result["duplicates"])
                        await send_telegram_reply(chat_id, dup_msg, reply_markup=keyboard)

                    return {"ok": True}

                # =====================================================================
                # SINGLE TRANSACTION PIPELINE
                # =====================================================================
                for tx in transactions_list:
                    amount = tx.amount if tx.amount else Decimal('0.00')
                    description = str(tx.item or tx.merchant or text).title()

                    if amount > Decimal('0.00'):
                        if tx.future and tx.future.is_future:
                            response_sections.append(f"🗓️ '{description}' identified as a future plan.")
                            continue

                        # Check if clarification is needed (e.g. missing income source - Observation 5)
                        if not tx.intent or tx.needs_clarification:
                            missing = ", ".join(
                                tx.clarification_fields) if tx.clarification_fields else "Intent/Details"
                            response_sections.append(
                                f"⚠️ Could not process '{description}'. Please clarify: {missing}.")
                            continue

                        # =========================================================
                        # RECURRENCE EXPANSION ENGINE
                        # =========================================================
                        tx_dates = []
                        is_recurring_past = False

                        if tx.recurrence and tx.recurrence.enabled and tx.recurrence.start_date:
                            freq = tx.recurrence.frequency or "monthly"
                            tx_dates = generate_recurrence_dates(tx.recurrence.start_date, freq, current_dt)

                            if tx.recurrence.end_date:
                                try:
                                    end_dt = datetime.strptime(tx.recurrence.end_date.split("T")[0],
                                                               "%Y-%m-%d").replace(tzinfo=TZ_IST)
                                    tx_dates = [d for d in tx_dates if d <= end_dt]
                                except Exception:
                                    pass

                            if tx_dates:
                                is_recurring_past = True

                        if not is_recurring_past:
                            db_date_obj = current_dt
                            if tx.date and tx.date.relative_date:
                                try:
                                    db_date_obj = datetime.strptime(tx.date.relative_date.split("T")[0],
                                                                    "%Y-%m-%d").replace(tzinfo=TZ_IST)
                                except Exception:
                                    pass
                            tx_dates = [db_date_obj]

                        num_occurrences = Decimal(len(tx_dates))
                        total_amount = amount * num_occurrences
                        # =========================================================

                        source_acc_obj = None
                        dest_acc_obj = None

                        if tx.intent in ["expense", "transfer_other"]:
                            source_acc_obj = get_account_from_list(user_accounts, tx.source_account)
                            if not source_acc_obj:
                                requested_acc = tx.source_account or "Default"
                                response_sections.append(
                                    f"❌ *Account Not Found*\nCannot pay from '{requested_acc}', as it does not exist in your system.")
                                continue

                        elif tx.intent == "income":
                            dest_acc_obj = get_account_from_list(user_accounts, tx.destination_account)
                            if not dest_acc_obj:
                                requested_acc = tx.destination_account or "Default"
                                response_sections.append(
                                    f"❌ *Account Not Found*\nCannot receive into '{requested_acc}', as it does not exist.")
                                continue

                        elif tx.intent == "transfer_own":
                            source_acc_obj = get_account_from_list(user_accounts, tx.source_account)
                            dest_acc_obj = get_account_from_list(user_accounts, tx.destination_account)
                            if not source_acc_obj:
                                response_sections.append(
                                    f"❌ *Source Account Not Found*\nCannot transfer from '{tx.source_account or 'Default'}'.")
                                continue
                            if not dest_acc_obj:
                                response_sections.append(
                                    f"❌ *Destination Account Not Found*\nCannot transfer to '{tx.destination_account or 'Default'}'.")
                                continue

                        updates_to_make = []
                        if total_amount > Decimal('0.00'):
                            if source_acc_obj:
                                current_bal = Decimal(str(source_acc_obj['balance']))
                                if current_bal < total_amount:
                                    response_sections.append(
                                        f"❌ *Insufficient Balance*\nAccount **'{source_acc_obj['account_name']}'** has ₹{current_bal:,.2f}, but transaction requires ₹{total_amount:,.2f}.")
                                    continue
                                updates_to_make.append(
                                    (source_acc_obj['id'], float(current_bal - total_amount), "DEBIT",
                                     float(total_amount)))

                            if dest_acc_obj:
                                current_bal = Decimal(str(dest_acc_obj['balance']))
                                updates_to_make.append((dest_acc_obj['id'], float(current_bal + total_amount), "CREDIT",
                                                        float(total_amount)))

                        for acc_id, new_bal, log_type, txn_amount in updates_to_make:
                            supabase_admin.table('accounts').update({"balance": new_bal}).eq("id", acc_id).execute()
                            try:
                                log_desc = f"{description} ({int(num_occurrences)} Occurrences)" if (
                                        is_recurring_past and num_occurrences > 1) else description
                                supabase_admin.table('account_logs').insert({
                                    "account_id": acc_id,
                                    "user_id": user_id,
                                    "log_type": log_type,
                                    "amount": txn_amount,
                                    "balance_after": new_bal,
                                    "description": log_desc
                                }).execute()
                            except Exception:
                                pass

                            for a in user_accounts:
                                if a['id'] == acc_id: a['balance'] = new_bal

                        search_item_name = description
                        category = None
                        subcategory = None

                        cached_match = cache_manager.search_item(search_item_name)
                        if cached_match and cached_match.get("category"):
                            category = cached_match["category"]
                            subcategory = cached_match.get("subcategory")

                        if not category:
                            ai_classified = category_pull_service.classify_item(search_item_name, intent=tx.intent)
                            category = ai_classified.get("category")
                            subcategory = ai_classified.get("subcategory") or "General"
                            normalized_taxonomy_item = str(
                                ai_classified.get("normalized_item") or search_item_name).title()

                            if category:
                                try:
                                    category_pull_service.add_single_item_to_taxonomy(
                                        cat_name=category, sub_name=subcategory, item_name=normalized_taxonomy_item,
                                        user_id=user_id
                                    )
                                    cache_manager.rebuild_cache()
                                except Exception:
                                    pass

                        db_payloads = []
                        for d_obj in tx_dates:
                            db_payloads.append({
                                "user_id": user_id,
                                "amount": float(amount),
                                "txn_type": tx.intent,
                                "description": description,
                                "intent": tx.intent,
                                "category": category,
                                "subcategory": subcategory,
                                "date": d_obj.isoformat(),
                                "source_account": source_acc_obj['account_name'] if source_acc_obj else None,
                                "destination_account": dest_acc_obj['account_name'] if dest_acc_obj else None,
                                "soft_deleted": False
                            })

                        try:
                            if len(db_payloads) == 1:
                                supabase.table("transactions").insert(db_payloads[0]).execute()
                            elif len(db_payloads) > 1:
                                supabase.table("transactions").insert(db_payloads).execute()
                        except Exception as e:
                            response_sections.append(f"❌ Failed to save '{description}': Database insertion error.")
                            continue

                        intent_lower = tx.intent.lower()
                        if "income" in intent_lower or "credit" in intent_lower:
                            color_badge = "🟢 *INCOME*"
                            acc_text = f"🔹 *To Account:* {dest_acc_obj['account_name']}"
                        elif "expense" in intent_lower or "debit" in intent_lower:
                            color_badge = "🔴 *EXPENSE*"
                            acc_text = f"🔹 *From Account:* {source_acc_obj['account_name']}"
                        elif "transfer_own" in intent_lower:
                            color_badge = "🔵 *TRANSFER (SELF)*"
                            acc_text = f"🔹 *From:* {source_acc_obj['account_name']} ➡️ *To:* {dest_acc_obj['account_name']}"
                        else:
                            color_badge = "🔵 *TRANSFER*"
                            acc_text = f"🔹 *From Account:* {source_acc_obj['account_name']}" if source_acc_obj else ""

                        cat_display = f"{category} -> {subcategory}" if subcategory else (category or "Unassigned")

                        if is_recurring_past and num_occurrences > 1:
                            display_date_raw = f"{int(num_occurrences)} Occurrences ({tx_dates[0].strftime('%d %b %Y')} to {tx_dates[-1].strftime('%d %b %Y')})"
                            amt_display = f"₹{float(total_amount):,.2f} (₹{float(amount):,.2f} x {int(num_occurrences)})"
                        else:
                            display_date_raw = "Today"
                            if tx.date:
                                if tx.date.raw_expression:
                                    display_date_raw = str(tx.date.raw_expression).title()
                                elif tx.date.relative_date:
                                    try:
                                        parsed_date = datetime.strptime(tx.date.relative_date.split("T")[0], "%Y-%m-%d")
                                        display_date_raw = parsed_date.strftime("%d %b %Y")
                                    except Exception:
                                        pass
                            amt_display = f"₹{float(amount):,.2f}"

                        committed_items.append(
                            f"✅ *Transaction Saved Successfully*\n{color_badge}\n🔹 *Item:* {description}\n🔹 *Amount:* {amt_display}\n{acc_text}\n🔹 *Date:* {display_date_raw}\n🔹 *Category:* {cat_display}"
                        )

            if committed_items:
                response_sections.append("\n\n".join(committed_items))

            if validated_data.loan and validated_data.loan.intent:
                safe_intent_str = validated_data.loan.intent.replace("_", " ").title()
                safe_lender_str = validated_data.loan.lender.replace("_",
                                                                     " ") if validated_data.loan.lender else "Unknown Lender"
                response_sections.append(f"🏦 *Loan Alert:* {safe_intent_str} for {safe_lender_str}")

            reply_text = "\n\n".join(
                response_sections) if response_sections else f"Processed text: '{text}'. No commitments made."
            await send_telegram_reply(chat_id, reply_text)

        except Exception as e:
            error_msg = f"Error processing intent through NLP engine: {str(e)}"
            await send_telegram_reply(chat_id, error_msg)

    return {"ok": True}