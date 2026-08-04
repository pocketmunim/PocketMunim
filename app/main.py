import os
import json
import httpx
from decimal import Decimal
from fastapi import FastAPI, Request, HTTPException, Depends
from supabase import create_client, Client
from groq import Groq

# Core PocketMunim Imports
from app.security.auth import authenticate_telegram_request
from app.ai.schemas import AITransactionExtraction
from app.ai.category_pull_service import CategoryPullService
from app.cache.category_cache import CategoryCacheManager

app = FastAPI()

# Environment Configurations
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
GROQ_API_KEYS = os.getenv("GROQ_API_KEYS", "").split(",")

# Initialize Supabase Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# Initialize Groq Client
active_groq_key = GROQ_API_KEYS[0].strip() if GROQ_API_KEYS and GROQ_API_KEYS[0] else os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=active_groq_key) if active_groq_key else None

# Initialize Phase 4 Category Services
category_pull_service = CategoryPullService(groq_client)

# =====================================================================
# FOUNDER FROZEN SYSTEM PROMPT (STRICTLY UNMODIFIED)
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
7. EXACT DATES & CURRENCY: Preserve the exact date expression. Default `normalized_currency` to "INR".
8. CLARIFICATION: If a transaction is missing a critical component, set `needs_clarification = true` and list missing keys in `clarification_fields`.
9. JSON ONLY: Output NOTHING but valid JSON. No markdown wrappers, no conversational text.

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

User: "Salary 85000 credited and paid 15000 EMI for Sushma"
Output: 
{
  "metadata": {
    "raw_user_text": "Salary 85000 credited and paid 15000 EMI for Sushma",
    "operation_type": "mixed", "language": "English", "entry_source": "telegram",
    "bulk_operation": false, "category_lookup_required": false, "unsupported_chat": false, "account_required": true
  },
  "transactions": [
    {
      "transaction_sequence": 1, "execution_order": 1, "intent": "income", "amount": 85000, 
      "normalized_currency": "INR", "item": "Salary", "category": "Income", "subcategory": "Salary",
      "date": {"raw_expression": "today", "date_type": "relative"}, "future": {"is_future": false},
      "validation": {"amount_valid": true, "date_valid": true, "item_valid": true, "account_valid": false},
      "duplicate_detection": {"possible_duplicate": false, "duplicate_reference": null},
      "needs_clarification": false, "confidence": {"overall_confidence": 0.99}
    },
    {
      "transaction_sequence": 2, "execution_order": 2, "intent": "expense", "amount": 15000, 
      "normalized_currency": "INR", "item": "EMI for Sushma", "category": "Loans", "subcategory": "EMI Payment",
      "date": {"raw_expression": "today", "date_type": "relative"}, "future": {"is_future": false},
      "validation": {"amount_valid": true, "date_valid": true, "item_valid": true, "account_valid": false},
      "duplicate_detection": {"possible_duplicate": false, "duplicate_reference": null},
      "needs_clarification": false, "confidence": {"overall_confidence": 0.99}
    }
  ],
  "loan": {"intent": "loan_payment", "lender": "Sushma", "amount": 15000}
}

User: "Added 50k to Upstox via UPI"
Output:
{
  "metadata": {
    "raw_user_text": "Added 50k to Upstox via UPI", "operation_type": "single", "language": "English", "entry_source": "telegram",
    "bulk_operation": false, "category_lookup_required": false, "unsupported_chat": false, "account_required": true
  },
  "transactions": [
    {
      "transaction_sequence": 1, "execution_order": 1, "intent": "transfer_other", "amount": 50000, 
      "normalized_currency": "INR", "merchant": "Upstox", "payment_method": "UPI", "destination_account": "Upstox",
      "category": "Investments", "subcategory": "Trading Account",
      "date": {"raw_expression": "today", "date_type": "relative"}, "future": {"is_future": false},
      "validation": {"amount_valid": true, "date_valid": true, "item_valid": true, "account_valid": true},
      "duplicate_detection": {"possible_duplicate": false, "duplicate_reference": null},
      "needs_clarification": false, "confidence": {"overall_confidence": 0.98}
    }
  ]
}

User: "Milk 50, Bread 40, Eggs 60, Paneer 120, Curd 40, Butter 90"
Output:
{
  "metadata": {
    "raw_user_text": "Milk 50, Bread 40, Eggs 60, Paneer 120, Curd 40, Butter 90",
    "operation_type": "bulk", "language": "English", "entry_source": "telegram",
    "bulk_operation": true, "category_lookup_required": false, "unsupported_chat": false, "account_required": true
  },
  "transactions": [
    {"transaction_sequence": 1, "execution_order": 1, "intent": "expense", "amount": 50, "item": "Milk"},
    {"transaction_sequence": 2, "execution_order": 2, "intent": "expense", "amount": 40, "item": "Bread"},
    {"transaction_sequence": 3, "execution_order": 3, "intent": "expense", "amount": 60, "item": "Eggs"},
    {"transaction_sequence": 4, "execution_order": 4, "intent": "expense", "amount": 120, "item": "Paneer"},
    {"transaction_sequence": 5, "execution_order": 5, "intent": "expense", "amount": 40, "item": "Curd"},
    {"transaction_sequence": 6, "execution_order": 6, "intent": "expense", "amount": 90, "item": "Butter"}
  ]
}

User: "Bought dragon fruit for 150"
Output:
{
  "metadata": {
    "raw_user_text": "Bought dragon fruit for 150",
    "operation_type": "single", "language": "English", "entry_source": "telegram",
    "bulk_operation": false, "category_lookup_required": true, "unsupported_chat": false, "account_required": true
  },
  "transactions": [
    {
      "transaction_sequence": 1, "execution_order": 1, "intent": "expense", "amount": 150, 
      "normalized_currency": "INR", "item": "dragon fruit", "category": null, "subcategory": null,
      "date": {"raw_expression": "today", "date_type": "relative"}, "future": {"is_future": false},
      "validation": {"amount_valid": true, "date_valid": true, "item_valid": true, "account_valid": false},
      "duplicate_detection": {"possible_duplicate": false, "duplicate_reference": null},
      "needs_clarification": false, "confidence": {"overall_confidence": 0.95}
    }
  ]
}"""


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

    reply_text = "System processing error."

    # 1. Handle System Commands
    if text.startswith("/start"):
        reply_text = "Welcome to PocketMunim.\n\nYour automated financial intelligence system is active. Send your expenses naturally (e.g., *milk 40* or *dinner 450*)."
    elif text.startswith("/report"):
        reply_text = "Dashboard link generated: https://pocketmunim.app/dashboard (Valid for 24 hours)"

    # 2. Handle Financial NLP Extraction & Multi-Intent Routing
    else:
        try:
            if not groq_client:
                raise Exception("Groq API client is not configured.")

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
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
            user_id = request.state.telegram_id
            response_sections = []
            committed_items = []

            if supabase and transactions_list:
                cache_manager = CategoryCacheManager(supabase, user_id)

                for tx in transactions_list:
                    amount = tx.amount if tx.amount else Decimal('0.00')
                    description = tx.item or tx.merchant or text

                    if amount > Decimal('0.00'):

                        # Future Transaction Interceptor
                        if tx.future and tx.future.is_future:
                            response_sections.append(
                                f"🗓️ '{description}' identified as a future plan. Budget intelligence will activate in Phase 9.")
                            continue

                        # Clarification Rule
                        if not tx.intent or tx.needs_clarification:
                            clarification_msg = f"⚠️ Could not process '{description}'. Please clarify: Is this an expense, income, or transfer?"
                            response_sections.append(clarification_msg)
                            continue

                        # =========================================================
                        # PHASE 4: CATEGORY SOURCING & SOURCE AUDIT LOGGING
                        # =========================================================
                        category = tx.category
                        search_item_name = tx.item or description
                        source_origin = "AI Prompt Extracted"

                        if not category:
                            # Tier 1: Check In-Memory JSONB Cache
                            cached_match = cache_manager.search_item(search_item_name)
                            if cached_match and cached_match.get("category"):
                                category = cached_match["category"]
                                source_origin = "In-Memory JSONB Cache"
                            else:
                                # Tier 2: Check Relational Database (`categories` table)
                                try:
                                    db_res = supabase.table('categories').select('*').eq('user_id', user_id).ilike(
                                        'name', search_item_name).execute()
                                    if db_res.data:
                                        category = db_res.data[0].get('category') or "General"
                                        source_origin = "Relational Database Table"
                                    else:
                                        # Tier 3: AI Fallback (CategoryPullService)
                                        ai_classified = category_pull_service.classify_item(search_item_name)
                                        category = ai_classified.get("category") or "General"
                                        source_origin = "AI Fallback (CategoryPullService)"

                                        # Auto-persist newly discovered category to DB and rebuild cache
                                        try:
                                            new_cat_payload = {
                                                "user_id": user_id,
                                                "name": search_item_name,
                                                "level": "ITEM",
                                                "category": category
                                            }
                                            supabase.table('categories').insert(new_cat_payload).execute()
                                            cache_manager.rebuild_cache()
                                        except Exception:
                                            pass  # Prevent insertion failure if already exists
                                except Exception:
                                    category = "General"
                                    source_origin = "Default Fallback"

                        # Log source to Vercel runtime console
                        print(
                            f"[CATEGORY SOURCE] Item: '{search_item_name}' | Resolved Category: '{category}' | Loaded From: {source_origin}")

                        category = category or "General"

                        db_payload = {
                            "user_id": user_id,
                            "amount": float(amount),
                            "txn_type": tx.intent,
                            "description": description,
                            "intent": tx.intent,
                            "category": category,
                            "soft_deleted": False
                        }
                        supabase.table("transactions").insert(db_payload).execute()
                        committed_items.append(f"{description}: ₹{amount} [{category}]")

            if committed_items:
                response_sections.append("Committed to Ledger:\n" + "\n".join(committed_items))

            if validated_data.loan and validated_data.loan.intent:
                response_sections.append(
                    f"Loan intent detected: {validated_data.loan.intent} for {validated_data.loan.lender}")

            if not response_sections:
                reply_text = f"Processed command/text: '{text}'. No transactional intents committed to DB."
            else:
                reply_text = "\n\n".join(response_sections)

        except Exception as e:
            reply_text = f"Error processing intent through NLP engine: {str(e)}"

    # Send Outbound Reply via Telegram Bot API
    if TELEGRAM_BOT_TOKEN:
        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        async with httpx.AsyncClient() as client:
            await client.post(
                telegram_url,
                json={
                    "chat_id": chat_id,
                    "text": reply_text
                }
            )

    return {"ok": True}