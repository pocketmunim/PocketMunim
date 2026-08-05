import os
import re
import json
import httpx
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, HTTPException, Depends
from contextlib import asynccontextmanager
from supabase import create_client, Client

# Core PocketMunim Imports
from app.security.auth import authenticate_telegram_request
from app.ai.schemas import AITransactionExtraction
from app.ai.category_pull_service import CategoryPullService
from app.cache.category_cache import CategoryCacheManager
from app.ai.ai_provider import execute_resilient_ai

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
                        {"command": "report", "description": "Get financial dashboard"},
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
async def send_telegram_reply(chat_id: int, text: str):
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})


# =====================================================================
# HELPER: RECURRENCE EXPANSION ENGINE
# =====================================================================
def generate_recurrence_dates(start_date_str: str, frequency: str, current_dt: datetime) -> list:
    """Calculates all past occurrences of a recurring transaction up to today."""
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
# FOUNDER FROZEN SYSTEM PROMPT
# =====================================================================
SYSTEM_PROMPT = """SYSTEM ROLE:
You are the PocketMunim Enterprise NLP Extraction Engine. Your exclusive mandate is to extract financial data, commands, and intents from unstructured multi-lingual text (English, Hindi, Marathi, Hinglish) and output a STRICT, heavily nested JSON object.

CRITICAL RULES (NON-NEGOTIABLE):
1. NO MATHEMATICS & NO SPLITTING: You are strictly forbidden from calculating totals, EMIs, balances, or splitting amounts. (e.g., 'paid 4000 split between 4' MUST be logged as a 4000/4 transaction).
2. NO HALLUCINATION: If a field is missing, return `null`. Never guess or assume default values.
3. MULTI-INTENT & SEQUENCING: A single message may contain multiple operations. Extract each as a separate object in the `transactions` array. Assign a chronological `execution_order`.
4. BULK DETECTION: If the user lists MORE THAN 5 expense items (i.e., 6 or more), set `metadata.bulk_operation = true` and `operation_type = "bulk"`.
5. UNKNOWN CATEGORIES: If you cannot confidently map an item to a standard category, set the transaction's `category` and `subcategory` to `null`, AND strictly set `metadata.category_lookup_required = true`.
6. LOANS: For paying a loan EMI, generate 'expense' in transactions AND 'loan_payment' in loan. For RECEIVING/ADDING a loan, generate 'income' in transactions AND 'loan_add' in loan.
7. EXACT DATES & CURRENCY: TODAY IS {CURRENT_DATE}. Calculate relative dates strictly in YYYY-MM-DD. For "last month", "last year", or "last week", subtract exactly that interval from today (e.g., Aug 5 minus 1 month is Jul 5). DO NOT default to the 1st of the month.
8. CLARIFICATION STRICTNESS: You MUST NOT set needs_clarification = true unless the AMOUNT is missing or Rule 12 applies. Never ask for missing accounts, categories, or payment methods.
9. JSON ONLY: Output NOTHING but valid JSON. No markdown wrappers.
10. PEER-TO-PEER TRANSFERS: If a user receives money (e.g., "got 10k from raj"), set intent to "income", item to "Received from [Name]".
11. ACCOUNT ROUTING: 
    - If user specifies an account paid FROM (e.g., "bought milk from Kotak"), set `source_account` to "Kotak".
    - If user specifies an account received INTO, set `destination_account`.
    - If transfer between OWN accounts ("send 10k from SBI to Axis"), intent is `transfer_own`, `source_account` is "SBI", `destination_account` is "Axis".
12. GENERIC NAMES: If a transaction involves a person but uses a generic term (e.g., "friend", "brother", "mitra", "dost", "vendor") instead of a specific name, you MUST set `needs_clarification = true` and ask for the specific name.
13. PAST RECURRING: For inputs like "every month on 17th from jun 2025", set recurrence.enabled = true, extract frequency (e.g. 'monthly'), and set start_date strictly in YYYY-MM-DD (e.g. '2025-06-17'). Do NOT mark future.is_future = true if the start date is in the past.

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


@app.post("/webhook")
async def telegram_webhook(request: Request, authorized: bool = Depends(authenticate_telegram_request)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

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
    # MANDATORY USER REGISTRATION GATEWAY
    # =====================================================================
    if text.startswith("/register"):
        reg_parts = text.replace("/register", "").strip()
        name = "PocketMunim User"
        currency = "INR"
        if reg_parts:
            name = reg_parts.split(",")[0].replace("Name:", "").strip() if "Name:" in reg_parts else reg_parts
            if "Currency:" in reg_parts:
                try:
                    currency = reg_parts.split("Currency:")[1].strip()
                except Exception:
                    pass

        name = name.title()

        if not user_exists:
            try:
                supabase_admin.table('users').insert(
                    {"id": user_id, "telegram_id": chat_id, "full_name": name, "currency": currency,
                     "security_strikes": 0}).execute()
                await send_telegram_reply(chat_id,
                                          f"✅ *Registration Successful!*\n\nWelcome to PocketMunim, *{name}*! Your account is active.")
            except Exception as e:
                await send_telegram_reply(chat_id, f"❌ Registration failed: {str(e)}")
        else:
            await send_telegram_reply(chat_id, "ℹ️ You are already registered with PocketMunim!")
        return {"ok": True}

    if not user_exists:
        copyable_form = "```text\n/register Name: [Your Name], Currency: INR\n```"
        await send_telegram_reply(chat_id,
                                  f"🚨 *Registration Mandatory*\n\nTo use PocketMunim, you must register your account first.\n\n📋 *Copy, fill, and send the registration form below:*\n{copyable_form}")
        return {"ok": True}

    # =====================================================================
    # COMMAND: ADD ACCOUNT & SET DEFAULT
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

    if text.startswith("/setdefault"):
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

    if text.startswith("/start"):
        await send_telegram_reply(chat_id,
                                  "Welcome to PocketMunim.\n\nYour automated financial intelligence system is active.")
        return {"ok": True}

    elif text.startswith("/report"):
        await send_telegram_reply(chat_id,
                                  "Dashboard link generated: https://pocketmunim.app/dashboard (Valid for 24 hours)")
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

    # =====================================================================
    # NEW COMMAND: HISTORICAL DATA TEMPLATE (UX Solution)
    # =====================================================================
    elif text.startswith("/history"):
        template = """📋 *Historical Data Auto-Template*
Copy this block, fill in your past numbers, and send it back. The system will automatically log them accurately while safely bypassing your live current balance:

```text
Salary for Jan 2025 was 50000 received in SBI
Rent for Jan 2025 was 15000 paid from SBI
Electricity for Jan 2025 was 2000 paid from SBI

Salary for Feb 2025 was 50000 received in SBI
Rent for Feb 2025 was 15000 paid from SBI
Electricity for Feb 2025 was 2200 paid from SBI
```"""
        await send_telegram_reply(chat_id, template)
        return {"ok": True}

    # =====================================================================
    # NEW COMMAND: DYNAMIC MONTHLY REPORTING (P&L Carry Forward Solution)
    # =====================================================================
    elif text.startswith("/monthly"):
        parts = text.replace("/monthly", "").strip().split()
        if len(parts) < 2:
            await send_telegram_reply(chat_id, "⚠️ Use format: `/monthly [Month] [Year]`\nExample: `/monthly Jan 2025`")
            return {"ok": True}

        # Use first 3 letters for standard parsing (Jan, Feb, etc.)
        month_str, year_str = parts[0][:3], parts[1]
        try:
            target_dt = datetime.strptime(f"1 {month_str} {year_str}", "%d %b %Y")
            start_date = target_dt.strftime("%Y-%m-%d")

            if target_dt.month == 12:
                end_dt = target_dt.replace(year=target_dt.year + 1, month=1)
            else:
                end_dt = target_dt.replace(month=target_dt.month + 1)
            end_date = end_dt.strftime("%Y-%m-%d")

            # Dynamically query Supabase for the specific month
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

    else:
        try:
            tz_ist = timezone(timedelta(hours=5, minutes=30))
            current_dt = datetime.now(tz_ist)

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

                for tx in transactions_list:
                    amount = tx.amount if tx.amount else Decimal('0.00')
                    description = str(tx.item or tx.merchant or text).title()

                    if amount <= Decimal('0.00'):
                        response_sections.append(
                            f"⚠️ Could not process '{description}'. Please specify a valid amount.")
                        continue

                    # =========================================================
                    # HISTORICAL BYPASS & RECURRENCE EXPANSION ENGINE
                    # =========================================================
                    tx_dates = []
                    is_recurring_past = False

                    if tx.recurrence and tx.recurrence.enabled and tx.recurrence.start_date:
                        freq = tx.recurrence.frequency or "monthly"
                        tx_dates = generate_recurrence_dates(tx.recurrence.start_date, freq, current_dt)

                        if tx.recurrence.end_date:
                            try:
                                end_dt = datetime.strptime(tx.recurrence.end_date.split("T")[0], "%Y-%m-%d").replace(
                                    tzinfo=tz_ist)
                                tx_dates = [d for d in tx_dates if d <= end_dt]
                            except Exception:
                                pass

                        if tx_dates:
                            is_recurring_past = True

                    if not is_recurring_past:
                        # Ensure future logic still applies if it's not a historical recurring transaction
                        if tx.future and tx.future.is_future:
                            response_sections.append(f"🗓️ '{description}' identified as a future plan.")
                            continue

                        db_date_obj = current_dt
                        if tx.date and tx.date.relative_date:
                            try:
                                db_date_obj = datetime.strptime(tx.date.relative_date.split("T")[0],
                                                                "%Y-%m-%d").replace(tzinfo=tz_ist)
                            except Exception:
                                pass
                        tx_dates = [db_date_obj]

                    num_occurrences = Decimal(len(tx_dates))

                    # ----------------- LIVE VS HISTORICAL SEGREGATION -----------------
                    live_occurrences = 0
                    historical_occurrences = 0

                    for d_obj in tx_dates:
                        if d_obj.date() < current_dt.date():
                            historical_occurrences += 1
                        else:
                            live_occurrences += 1

                    live_total = amount * Decimal(live_occurrences)
                    # =========================================================

                    if not tx.intent:
                        response_sections.append(f"⚠️ Could not process '{description}'. Please clarify intent.")
                        continue

                    if tx.needs_clarification:
                        fields = " ".join(tx.clarification_fields).lower() if tx.clarification_fields else ""
                        if "name" in fields or "person" in fields or "lender" in fields:
                            missing = ", ".join(tx.clarification_fields) if tx.clarification_fields else "Name/Person"
                            response_sections.append(f"⚠️ Could not process '{description}'. Please clarify: {missing}")
                            continue

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
                    # ONLY DEDUCT LIVE (TODAY/FUTURE) TRANSACTIONS FROM LIVE BALANCE
                    if live_total > Decimal('0.00'):
                        if source_acc_obj:
                            current_bal = Decimal(str(source_acc_obj['balance']))
                            if current_bal < live_total:
                                response_sections.append(
                                    f"❌ *Insufficient Balance*\nAccount **'{source_acc_obj['account_name']}'** has ₹{current_bal:,.2f}, but today's transaction(s) require ₹{live_total:,.2f}.")
                                continue
                            updates_to_make.append(
                                (source_acc_obj['id'], float(current_bal - live_total), "DEBIT", float(live_total)))

                        if dest_acc_obj:
                            current_bal = Decimal(str(dest_acc_obj['balance']))
                            updates_to_make.append(
                                (dest_acc_obj['id'], float(current_bal + live_total), "CREDIT", float(live_total)))

                    for acc_id, new_bal, log_type, txn_amount in updates_to_make:
                        supabase_admin.table('accounts').update({"balance": new_bal}).eq("id", acc_id).execute()
                        try:
                            log_desc = f"{description} (Live Deduction)" if (
                                        is_recurring_past or historical_occurrences > 0) else description
                            if is_recurring_past and live_occurrences > 1:
                                log_desc = f"{description} ({live_occurrences} Live Occurrences)"

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
                        normalized_taxonomy_item = str(ai_classified.get("normalized_item") or search_item_name).title()

                        if category:
                            try:
                                category_pull_service.add_single_item_to_taxonomy(
                                    cat_name=category, sub_name=subcategory, item_name=normalized_taxonomy_item,
                                    user_id=user_id
                                )
                                cache_manager.rebuild_cache()
                            except Exception:
                                pass

                    # Prepare Batch Insertion Payloads (Both Live and Historical get saved to DB)
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

                    # Display Formatting
                    if is_recurring_past and num_occurrences > 1:
                        display_date_raw = f"{int(num_occurrences)} Occurrences ({tx_dates[0].strftime('%d %b %Y')} to {tx_dates[-1].strftime('%d %b %Y')})"
                        amt_display = f"₹{float(amount * num_occurrences):,.2f} (₹{float(amount):,.2f} x {int(num_occurrences)})"
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

                    # Explicit UI Warning for the Historical Bypass
                    bypass_msg = f"\nℹ️ *Historical Bypass Applied:* {historical_occurrences} past transaction(s) logged to charts without deducting from live balance." if historical_occurrences > 0 else ""

                    committed_items.append(
                        f"✅ *Transaction Saved Successfully*\n{color_badge}\n🔹 *Item:* {description}\n🔹 *Amount:* {amt_display}\n{acc_text}\n🔹 *Date:* {display_date_raw}\n🔹 *Category:* {cat_display}{bypass_msg}"
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