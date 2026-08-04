import os
import json
import httpx
from fastapi import FastAPI, Request, HTTPException
from supabase import create_client, Client
from groq import Groq

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

# Finalized Enterprise NLP Extraction System Prompt
SYSTEM_PROMPT = """
SYSTEM ROLE:
You are the PocketMunim Enterprise NLP Extraction Engine. Your exclusive mandate is to extract financial data, commands, and intents from unstructured multi-lingual text (English, Hindi, Marathi, Hinglish) and output a STRICT, heavily nested JSON object.

CRITICAL RULES (NON-NEGOTIABLE):
1. NO MATHEMATICS: You are strictly forbidden from calculating totals, EMIs, or balances.
2. NO HALLUCINATION: If a field is missing, return `null`. Never guess or assume default values.
3. MULTI-INTENT & SEQUENCING: A single message may contain multiple operations. Extract each as a separate object in the `transactions` array. Assign a chronological `execution_order` (1, 2, 3).
4. BULK DETECTION: If the user lists MORE THAN 5 expense items (i.e., 6 or more), set `metadata.bulk_operation = true` and `operation_type = "bulk"`.
5. UNKNOWN CATEGORIES: If you cannot confidently map an item to a standard category, set the transaction's `category` and `subcategory` to `null`, AND strictly set `metadata.category_lookup_required = true`.
6. LOAN PAYMENTS: A loan payment MUST generate two intents: an `expense` (to deduct the bank balance) in the `transactions` array, AND a `loan_payment` intent in the `loan` object.
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
      "client_transaction_id": "string or null",
      "transaction_sequence": "integer",
      "execution_order": "integer",
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
"""


@app.get("/")
def health_check():
    return {"status": "PocketMunim Enterprise API is live", "status_code": 200}


@app.post("/webhook")
async def telegram_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    message = payload.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()

    if not text or not chat_id:
        return {"ok": True}

    reply_text = "⚠️ System processing error."

    # 1. Handle System Commands
    if text.startswith("/start"):
        reply_text = "👋 Welcome to PocketMunim.\n\nYour automated financial intelligence system is active. Send your expenses naturally (e.g., *milk 40* or *dinner 450*)."
    elif text.startswith("/report"):
        reply_text = "📊 Dashboard link generated: https://pocketmunim.app/dashboard (Valid for 24 hours)"

    # 2. Handle Financial NLP Extraction & Ledger Commit
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
                response_format={"type": "json_object"}
            )

            tx_data = json.loads(completion.choices[0].message.content)
            transactions_list = tx_data.get("transactions", [])
            user_id = str(chat_id)

            committed_items = []
            if supabase and transactions_list:
                for tx in transactions_list:
                    amount = float(tx.get("amount") or 0.0)
                    if amount > 0:
                        intent = str(tx.get("intent") or "expense")
                        category = str(tx.get("category") or "General")
                        description = str(tx.get("item") or tx.get("merchant") or text)

                        db_payload = {
                            "user_id": user_id,
                            "amount": amount,
                            "txn_type": intent,
                            "description": description,
                            "intent": intent,
                            "category": category,
                            "soft_deleted": False
                        }

                        supabase.table("transactions").insert(db_payload).execute()
                        committed_items.append(f"• {description}: ₹{amount} [{category}]")

            if committed_items:
                reply_text = "✅ Committed to Ledger:\n\n" + "\n".join(committed_items)
            else:
                reply_text = f"⚠️ Processed text, but no valid transaction amounts detected for ledger commit."

        except Exception as e:
            reply_text = f"❌ Error processing intent through NLP engine: {str(e)}"

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