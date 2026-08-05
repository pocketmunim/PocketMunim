import os
import json
import httpx
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, Request, HTTPException, Depends
from contextlib import asynccontextmanager
from supabase import create_client, Client
from groq import Groq

# Core PocketMunim Imports
from app.security.auth import authenticate_telegram_request
from app.ai.schemas import AITransactionExtraction
from app.ai.category_pull_service import CategoryPullService
from app.cache.category_cache import CategoryCacheManager

# Environment Configurations
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
GROQ_API_KEYS = os.getenv("GROQ_API_KEYS", "").split(",")

# Initialize Supabase Clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
supabase_admin: Client = create_client(SUPABASE_URL,
                                       SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else supabase

# Initialize Groq Client
active_groq_key = GROQ_API_KEYS[0].strip() if GROQ_API_KEYS and GROQ_API_KEYS[0] else os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=active_groq_key) if active_groq_key else None

# Initialize Phase 4 Category Services
category_pull_service = CategoryPullService(groq_client, supabase_admin)


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
                        {"command": "categorypull", "description": "Seed or refresh categories"},
                        {"command": "report", "description": "Get financial dashboard link"}
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
# FOUNDER FROZEN SYSTEM PROMPT (WITH DYNAMIC TIME INJECTION)
# =====================================================================
SYSTEM_PROMPT = """SYSTEM ROLE:
You are the PocketMunim Enterprise NLP Extraction Engine. Your exclusive mandate is to extract financial data, commands, and intents from unstructured multi-lingual text (English, Hindi, Marathi, Hinglish) and output a STRICT, heavily nested JSON object.

CRITICAL RULES (NON-NEGOTIABLE):
1. NO MATHEMATICS: You are strictly forbidden from calculating totals, EMIs, or balances.
2. NO HALLUCINATION: If a field is missing, return `null`. Never guess or assume default values.
3. MULTI-INTENT & SEQUENCING: A single message may contain multiple operations. Extract each as a separate object in the `transactions` array. Assign a chronological `execution_order` (1, 2, 3).
4. BULK DETECTION (BUG #1 & #2 FIXED): If the user lists MORE THAN 5 expense items (i.e., 6 or more), set `metadata.bulk_operation = true` and `operation_type = "bulk"`.
5. UNKNOWN CATEGORIES (BUG #5 FIXED): If you cannot confidently map an item to a standard category, set the transaction's `category` and `subcategory` to `null`, AND strictly set `metadata.category_lookup_required = true`.
6. LOAN PAYMENTS (BUG #3 FIXED): A loan payment MUST generate two intents: an `expense` (to deduct the bank balance) in the `transactions` array, AND a `loan_payment` intent in the `loan` object.
7. EXACT DATES & CURRENCY: TODAY IS {CURRENT_DATE}. You MUST calculate exact relative dates (e.g., "yesterday" = current date minus 1 day). Output calculated date strictly in YYYY-MM-DD format in `date.relative_date`. Preserve spoken words in `date.raw_expression`. Default currency is INR.
8. CLARIFICATION: If a transaction is missing a critical component, set `needs_clarification = true` and list missing keys in `clarification_fields`.
9. JSON ONLY: Output NOTHING but valid JSON. No markdown wrappers, no conversational text.
10. PEER-TO-PEER TRANSFERS (NO CASH HALLUCINATION): If a user receives money (e.g., "got 10k from raj"), set intent to "income", item to "Received from [Name]", and DO NOT assume or hallucinate the word "Cash" unless explicitly stated.

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
        "frequency": "enum: [daily, weekly, monthly, yearly, null]",
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
      "date": {"raw_expression": "yesterday", "relative_date": "2026-08-04", "date_type": "relative"}, "future": {"is_future": false},
      "validation": {"amount_valid": true, "date_valid": true, "item_valid": true, "account_valid": false},
      "duplicate_detection": {"possible_duplicate": false, "duplicate_reference": null},
      "needs_clarification": false, "confidence": {"overall_confidence": 0.98}
    }
  ]
}
"""


# =====================================================================

@app.get("/")
def health_check():
    return {"status": "PocketMunim Enterprise API is live", "status_code": 200}


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
    # BUSINESS LOGIC: MANDATORY USER REGISTRATION GATEWAY
    # =====================================================================
    user_res = supabase_admin.table('users').select('*').eq('telegram_id', chat_id).execute()
    user_exists = bool(user_res.data)

    # Handle /register command explicitly
    if text.startswith("/register"):
        reg_parts = text.replace("/register", "").strip()
        # Expecting format: Name: John Doe, Currency: INR
        name = "PocketMunim User"
        currency = "INR"

        if reg_parts:
            # Simple parsing or default assignment
            name = reg_parts.split(",")[0].replace("Name:", "").strip() if "Name:" in reg_parts else reg_parts

        if not user_exists:
            try:
                supabase_admin.table('users').insert({
                    "id": user_id,
                    "telegram_id": chat_id,
                    "full_name": name,
                    "currency": currency
                }).execute()
                await send_telegram_reply(chat_id,
                                          f"✅ *Registration Successful!*\n\nWelcome to PocketMunim, *{name}*! Your account is now active and ready for financial tracking.")
            except Exception as e:
                await send_telegram_reply(chat_id, f"❌ Registration failed: {str(e)}")
        else:
            await send_telegram_reply(chat_id, "ℹ️ You are already registered with PocketMunim!")
        return {"ok": True}

    # If user is not registered, block all actions and give copiable registration form
    if not user_exists:
        copyable_form = "```text\n/register Name: [Your Full Name], Currency: INR\n```"
        reg_msg = (
            "🚨 *Registration Mandatory*\n\n"
            "To use PocketMunim, you must register your account first.\n\n"
            "📋 *Copy, fill, and send the registration form below:*\n"
            f"{copyable_form}"
        )
        await send_telegram_reply(chat_id, reg_msg)
        return {"ok": True}
    # =====================================================================

    # 1. Handle System Commands
    if text.startswith("/start"):
        reply_text = "Welcome to PocketMunim.\n\nYour automated financial intelligence system is active. Send your expenses naturally (e.g., *milk 40* or *dinner 450*)."
        await send_telegram_reply(chat_id, reply_text)
        return {"ok": True}

    elif text.startswith("/report"):
        reply_text = "Dashboard link generated: https://pocketmunim.app/dashboard (Valid for 24 hours)"
        await send_telegram_reply(chat_id, reply_text)
        return {"ok": True}

    # =====================================================================
    # 2. COMMAND: ON-DEMAND CATEGORY SEEDING (/categorypull)
    # =====================================================================
    elif text.startswith("/categorypull"):
        query = text.replace("/categorypull", "").strip()

        if not query:
            await send_telegram_reply(chat_id, "⏳ Seeding random day-to-day life categories using AI...")
        else:
            await send_telegram_reply(chat_id, f"⏳ Pulling categories for '{query}' using AI...")

        pull_result = category_pull_service.manual_category_pull(query, user_id)
        added_count = pull_result.get("added", 0)

        if added_count > 0:
            cache_manager = CategoryCacheManager(supabase, user_id)
            cache_manager.rebuild_cache()
            success_msg = f"✅ Successfully pulled and mapped {added_count} new items to the database and refreshed Cache."
            await send_telegram_reply(chat_id, success_msg)
        else:
            error_reason = pull_result.get("error", "Unknown logic failure")
            await send_telegram_reply(chat_id, f"❌ Failed to pull categories.\n\nReason: {error_reason}")

        return {"ok": True}

    # =====================================================================
    # 3. STANDARD TRANSACTION PROCESSING (The Phase 4 Waterfall)
    # =====================================================================
    else:
        try:
            if not groq_client:
                raise Exception("Groq API client is not configured.")

            # Calculate precise IST time dynamically
            tz_ist = timezone(timedelta(hours=5, minutes=30))
            current_dt = datetime.now(tz_ist)
            current_date_str = current_dt.strftime("%Y-%m-%d")
            current_day_str = current_dt.strftime("%A")

            dynamic_system_prompt = SYSTEM_PROMPT.replace(
                "{CURRENT_DATE}",
                f"{current_date_str} ({current_day_str})"
            )

            messages = [
                {"role": "system", "content": dynamic_system_prompt},
                {"role": "user", "content": text}
            ]

            completion = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.0
            )

            raw_json = json.loads(completion.choices[0].message.content)
            validated_data = AITransactionExtraction(**raw_json)

            transactions_list = validated_data.transactions
            response_sections = []
            committed_items = []

            # =====================================================================
            # BUSINESS LOGIC: LOAN EXISTENCE VERIFICATION FOR EMIS
            # =====================================================================
            if validated_data.loan and validated_data.loan.intent == "loan_payment":
                lender_name = validated_data.loan.lender
                if lender_name:
                    loan_check = supabase_admin.table('loans').select('*').eq('user_id', user_id).ilike('lender',
                                                                                                        lender_name).execute()
                    if not loan_check.data:
                        await send_telegram_reply(chat_id,
                                                  f"❌ *Loan Verification Failed*\n\nNo active loan record found for lender **'{lender_name}'**. Please register the loan in the system before logging an EMI payment.")
                        return {"ok": True}
            # =====================================================================

            if supabase and transactions_list:
                cache_manager = CategoryCacheManager(supabase, user_id)

                for tx in transactions_list:
                    amount = tx.amount if tx.amount else Decimal('0.00')
                    description = tx.item or tx.merchant or text

                    if amount > Decimal('0.00'):

                        if tx.future and tx.future.is_future:
                            response_sections.append(
                                f"🗓️ '{description}' identified as a future plan. Budget intelligence will activate in Phase 9.")
                            continue

                        if not tx.intent or tx.needs_clarification:
                            clarification_msg = f"⚠️ Could not process '{description}'. Please clarify: Is this an expense, income, or transfer?"
                            response_sections.append(clarification_msg)
                            continue

                        # =========================================================
                        # BUSINESS LOGIC: SUFFICIENT BALANCE VALIDATION
                        # =========================================================
                        if tx.intent == "expense":
                            source_acc = tx.source_account or "Default"
                            acc_res = supabase_admin.table('accounts').select('balance').eq('user_id', user_id).ilike(
                                'account_name', source_acc).execute()
                            if acc_res.data:
                                current_bal = Decimal(str(acc_res.data[0]['balance']))
                                if current_bal < amount:
                                    response_sections.append(
                                        f"❌ *Insufficient Balance*\nAccount **'{source_acc}'** has ₹{current_bal:,.2f}, but required amount is ₹{amount:,.2f}.")
                                    continue
                        # =========================================================

                        # =========================================================
                        # PHASE 4: DYNAMIC WATERFALL (RAM -> AI -> REBUILD)
                        # =========================================================
                        search_item_name = tx.item or description
                        category = None
                        subcategory = None

                        cached_match = cache_manager.search_item(search_item_name)
                        if cached_match and cached_match.get("category"):
                            category = cached_match["category"]
                            subcategory = cached_match.get("subcategory")

                        if not category:
                            ai_classified = category_pull_service.classify_item(search_item_name)
                            category = ai_classified.get("category")
                            subcategory = ai_classified.get("subcategory") or "General"

                            normalized_taxonomy_item = ai_classified.get("normalized_item") or search_item_name

                            if category:
                                try:
                                    category_pull_service.add_single_item_to_taxonomy(
                                        cat_name=category,
                                        sub_name=subcategory,
                                        item_name=normalized_taxonomy_item,
                                        user_id=user_id
                                    )
                                    cache_manager.rebuild_cache()
                                except Exception as e:
                                    print(f"Failed to persist AI fallback: {str(e)}")

                        # Date calculation logic
                        db_date = current_dt.isoformat()
                        display_date_raw = "Today"

                        if tx.date:
                            if tx.date.raw_expression:
                                display_date_raw = str(tx.date.raw_expression).title()

                            if tx.date.relative_date:
                                try:
                                    date_part = tx.date.relative_date.split("T")[0]
                                    parsed_date = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=tz_ist)
                                    db_date = parsed_date.isoformat()
                                    formatted_display = parsed_date.strftime("%d %b %Y")
                                    if display_date_raw.lower() != "today":
                                        display_date_raw = f"{formatted_display} ({display_date_raw})"
                                    else:
                                        display_date_raw = formatted_display
                                except Exception:
                                    pass

                        db_payload = {
                            "user_id": user_id,
                            "amount": float(amount),
                            "txn_type": tx.intent,
                            "description": description,
                            "intent": tx.intent,
                            "category": category,
                            "date": db_date,
                            "soft_deleted": False
                        }
                        supabase.table("transactions").insert(db_payload).execute()

                        # =========================================================
                        # COLOR-CODED UI BADGES & FORMATTING
                        # =========================================================
                        intent_lower = tx.intent.lower()
                        if "income" in intent_lower or "credit" in intent_lower:
                            color_badge = "🟢 *INCOME*"
                        elif "expense" in intent_lower or "debit" in intent_lower:
                            color_badge = "🔴 *EXPENSE*"
                        elif "transfer" in intent_lower:
                            color_badge = "🔵 *TRANSFER*"
                        else:
                            color_badge = "🟠 *TRANSACTION*"

                        cat_display = f"{category} -> {subcategory}" if subcategory else (category or "Unassigned")

                        commit_msg = (
                            f"✅ *Transaction Saved Successfully*\n"
                            f"{color_badge}\n"
                            f"🔹 *Item:* {description}\n"
                            f"🔹 *Amount:* ₹{float(amount):,.2f}\n"
                            f"🔹 *Date:* {display_date_raw}\n"
                            f"🔹 *Category:* {cat_display}"
                        )
                        committed_items.append(commit_msg)

            if committed_items:
                response_sections.append("\n\n".join(committed_items))

            if validated_data.loan and validated_data.loan.intent:
                response_sections.append(
                    f"🏦 *Loan Alert:* {validated_data.loan.intent} for {validated_data.loan.lender}")

            if not response_sections:
                reply_text = f"Processed command/text: '{text}'. No transactional intents committed to DB."
            else:
                reply_text = "\n\n".join(response_sections)

            await send_telegram_reply(chat_id, reply_text)

        except Exception as e:
            reply_text = f"Error processing intent through NLP engine: {str(e)}"
            await send_telegram_reply(chat_id, reply_text)

    return {"ok": True}