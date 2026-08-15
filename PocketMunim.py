import os

def create_workspace():
    print("Initializing PocketMunim Enterprise Build Process...\n")

    files = {
        # ==========================================
        # 1. ENVIRONMENT & CONFIGURATION
        # ==========================================
        "requirements.txt": """\
fastapi
uvicorn
pydantic
supabase
groq
google-generativeai
python-dateutil
pandas
upstash-qstash
httpx
""",
        "vercel.json": """\
{
  "builds": [
    {
      "src": "app/main.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/(.*)",
      "dest": "app/main.py"
    }
  ]
}
""",
        ".env.template": """\
# Application Configuration
ENVIRONMENT=production
TIMEZONE=Asia/Kolkata
CURRENCY=INR

# Telegram Auth & Webhook Secrets
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_WEBHOOK_SECRET=your_random_secure_secret_token
AUTHORIZED_TELEGRAM_IDS=user_telegram_id_1,user_telegram_id_2

# Upstash QStash Decoupling Credentials
QSTASH_TOKEN=your_upstash_qstash_token
QSTASH_CURRENT_SIGNING_KEY=your_qstash_current_signing_key
QSTASH_NEXT_SIGNING_KEY=your_qstash_next_signing_key

# AI Multi-Key Infrastructure
GROQ_API_KEYS=key1,key2,key3
GROQ_API_KEY=key1

# Supabase Database
SUPABASE_URL=https://your-supabase-project.supabase.co
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
""",

        # ==========================================
        # 2. SQL MIGRATIONS
        # ==========================================
        "app/dao/migrations/001_foundation_schema.sql": """\
-- PocketMunim Enterprise Schema - Phase 1 Foundation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255),
    currency VARCHAR(10) DEFAULT 'INR',
    security_strikes INTEGER DEFAULT 0,
    role VARCHAR(50) DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    txn_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    amount NUMERIC(15, 2) NOT NULL,
    txn_type VARCHAR(50) NOT NULL,
    description TEXT,
    normalized_item VARCHAR(150),
    intent VARCHAR(50),
    category VARCHAR(100),
    subcategory VARCHAR(100),
    date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    source_account VARCHAR(100),
    destination_account VARCHAR(100),
    currency VARCHAR(10) DEFAULT 'INR',
    quantity NUMERIC(10, 3),
    unit VARCHAR(20),
    counterparty VARCHAR(100),
    payment_method VARCHAR(50),
    transaction_reference VARCHAR(100),
    extended_data JSONB DEFAULT '{}'::jsonb,
    soft_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
""",
        "app/dao/migrations/002_account_manager_schema.sql": """\
-- PocketMunim Enterprise Schema - Phase 2 Account Manager
CREATE TABLE IF NOT EXISTS accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    account_name VARCHAR(100) NOT NULL,
    account_type VARCHAR(50) NOT NULL DEFAULT 'BANK',
    balance NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    is_default BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, account_name)
);

CREATE TABLE IF NOT EXISTS account_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    user_id VARCHAR(255) NOT NULL,
    log_type VARCHAR(50) NOT NULL,
    amount NUMERIC(15, 2) NOT NULL,
    balance_after NUMERIC(15, 2) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE account_logs ENABLE ROW LEVEL SECURITY;
""",
        "app/dao/migrations/003_category_master_schema.sql": """\
-- PocketMunim Enterprise Schema - Phase 3 Category Master
CREATE TABLE IF NOT EXISTS categories (
    category_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    category_name VARCHAR(100) NOT NULL,
    subcategories JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, category_name)
);

ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
""",
        "app/dao/migrations/005_salary_manager_schema.sql": """\
-- PocketMunim Enterprise Schema - Phase 5 Salary & Business Calendar
CREATE TABLE IF NOT EXISTS bank_holidays (
    holiday_date DATE PRIMARY KEY,
    description VARCHAR(100) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS salaries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    year INTEGER NOT NULL,
    month_number INTEGER NOT NULL,
    month_name VARCHAR(20) NOT NULL,
    amount NUMERIC(15, 2) NOT NULL,
    is_deducted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, year, month_number)
);

ALTER TABLE salaries ENABLE ROW LEVEL SECURITY;
""",
        "app/dao/migrations/006_loan_manager_schema.sql": """\
-- PocketMunim Enterprise Schema - Phase 6 Loan Manager
CREATE TABLE IF NOT EXISTS loans (
    loan_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    lender VARCHAR(100) NOT NULL,
    principal_amount NUMERIC(15, 2) NOT NULL,
    annual_interest_rate NUMERIC(5, 2) NOT NULL,
    tenure_months INTEGER NOT NULL,
    start_date DATE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS emi_schedules (
    schedule_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    loan_id UUID NOT NULL REFERENCES loans(loan_id) ON DELETE CASCADE,
    installment_number INTEGER NOT NULL,
    due_date DATE NOT NULL,
    emi_amount NUMERIC(15, 2) NOT NULL,
    principal_component NUMERIC(15, 2) NOT NULL,
    interest_component NUMERIC(15, 2) NOT NULL,
    remaining_balance NUMERIC(15, 2) NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PAID', 'OVERDUE')),
    UNIQUE (loan_id, installment_number)
);

ALTER TABLE loans ENABLE ROW LEVEL SECURITY;
ALTER TABLE emi_schedules ENABLE ROW LEVEL SECURITY;
""",
        "app/dao/migrations/008_ephemeral_state_persistence.sql": """\
-- PocketMunim Enterprise Schema - Phase 8 Ephemeral State Persistence
CREATE TABLE IF NOT EXISTS pending_batches (
    batch_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    account_id VARCHAR(255) NOT NULL,
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP + INTERVAL '24 hours')
);

CREATE TABLE IF NOT EXISTS report_tokens (
    token VARCHAR(255) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE pending_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_tokens ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service Role Full Access pending_batches" ON pending_batches FOR ALL USING (true);
CREATE POLICY "Service Role Full Access report_tokens" ON report_tokens FOR ALL USING (true);
""",
        "app/dao/migrations/013_atomic_transactions_uuid_fix.sql": """\
-- PocketMunim Enterprise Schema - Phase 13 Atomic Transactions Fix
CREATE OR REPLACE FUNCTION atomic_balance_update(
    p_account_id UUID,
    p_amount NUMERIC
) RETURNS NUMERIC
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_current_balance NUMERIC;
    v_new_balance NUMERIC;
BEGIN
    SELECT balance INTO v_current_balance
    FROM accounts
    WHERE id = p_account_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Account not found';
    END IF;

    v_new_balance := v_current_balance + p_amount;

    IF v_new_balance < 0 THEN
        RAISE EXCEPTION 'Insufficient balance';
    END IF;

    UPDATE accounts
    SET balance = v_new_balance,
        updated_at = CURRENT_TIMESTAMP
    WHERE id = p_account_id;

    RETURN v_new_balance;
END;
$$;

CREATE OR REPLACE FUNCTION atomic_bulk_commit(
    p_account_id UUID,
    p_user_id VARCHAR,
    p_net_change NUMERIC,
    p_max_amount NUMERIC,
    p_payloads JSONB
) RETURNS NUMERIC
LANGUAGE plpgsql
SECURITY DEFINER
AS $$ DECLARE     v_current_balance NUMERIC;     v_new_balance NUMERIC; BEGIN     SELECT balance INTO v_current_balance     FROM accounts     WHERE id = p_account_id     FOR UPDATE;      IF NOT FOUND THEN         RAISE EXCEPTION 'Account not found';     END IF;      v_new_balance := v_current_balance + p_net_change;      IF v_new_balance < 0 THEN         RAISE EXCEPTION 'Insufficient balance';     END IF;      UPDATE accounts     SET balance = v_new_balance,         updated_at = CURRENT_TIMESTAMP     WHERE id = p_account_id;      IF p_max_amount > 0 THEN         INSERT INTO account_logs (             account_id, user_id, log_type, amount, balance_after, description         ) VALUES (             p_account_id, p_user_id, 'BULK_UPDATE', p_max_amount, v_new_balance, 'Bulk Transaction'
        );
    END IF;

    IF jsonb_array_length(p_payloads) > 0 THEN
        INSERT INTO transactions (
            user_id, amount, txn_type, description, normalized_item, intent, category, subcategory, date, source_account, destination_account, soft_deleted
        )
        SELECT
            p_user_id,
            (x->>'amount')::NUMERIC,
            x->>'txn_type',
            x->>'description',
            x->>'normalized_item',
            x->>'intent',
            x->>'category',
            x->>'subcategory',
            (x->>'date')::TIMESTAMPTZ,
            x->>'source_account',
            x->>'destination_account',
            (x->>'soft_deleted')::BOOLEAN
        FROM jsonb_array_elements(p_payloads) AS x;
    END IF;

    RETURN v_new_balance;
END;
$$;
""",

        # ==========================================
        # 3. UTILS & SCHEMAS
        # ==========================================
        "app/utils/constants.py": """\
from datetime import timezone, timedelta

# Timezone Helper - Standardized on Indian Standard Time (IST)
TZ_IST = timezone(timedelta(hours=5, minutes=30))
""",
        "app/schemas/loan_schema.py": """\
from pydantic import BaseModel
from typing import Optional
from decimal import Decimal

class LoanNLPData(BaseModel):
    action: str 
    lender_name: Optional[str] = None
    principal: Optional[Decimal] = None
    annual_interest_rate: Optional[Decimal] = None
    tenure_years: Optional[int] = None
    disbursement_date: Optional[str] = None
    first_emi_date: Optional[str] = None
    emi_amount: Optional[Decimal] = None
    payment_amount: Optional[Decimal] = None
    target_period: Optional[str] = None
""",
        "app/ai/schemas.py": """\
from pydantic import BaseModel
from typing import Optional, List, Any
from decimal import Decimal

class MetadataSchema(BaseModel):
    operation_type: Optional[str] = None
    bulk_operation: Optional[bool] = None

class DateSchema(BaseModel):
    date: Optional[str] = None
    original_expression: Optional[str] = None
    is_relative: Optional[bool] = None

class FutureSchema(BaseModel):
    is_future: Optional[bool] = False

class TransactionItem(BaseModel):
    intent: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = "INR"
    item: Optional[str] = None
    raw_description: Optional[str] = None
    normalized_item: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    counterparty: Optional[str] = None
    source_account: Optional[str] = None
    destination_account: Optional[str] = None
    payment_method: Optional[str] = None
    transaction_reference: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    date: Optional[DateSchema] = None
    future: Optional[FutureSchema] = None
    needs_clarification: Optional[bool] = False
    clarification_fields: Optional[List[str]] = []

class AITransactionExtraction(BaseModel):
    metadata: Optional[MetadataSchema] = None
    transactions: Optional[List[TransactionItem]] = []
""",

        # ==========================================
        # 4. SECURITY & AUTH
        # ==========================================
        "app/security/auth.py": """\
import os
from fastapi import HTTPException, Header, Request
from typing import Optional
from app.telegram.telegram_utils import send_telegram_reply
from upstash_qstash import Receiver

def get_authorized_users() -> list[str]:
    users_env = os.getenv("AUTHORIZED_TELEGRAM_IDS", "")
    return [uid.strip() for uid in users_env.split(",") if uid.strip()]

def verify_user_authorization(telegram_id: str) -> bool:
    authorized_users = get_authorized_users()
    if not authorized_users:
        return False
    return str(telegram_id) in authorized_users

async def authenticate_telegram_request(
    request: Request,
    x_telegram_bot_api_secret_token: Optional[str] = Header(None)
) -> bool:
    expected_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not expected_secret or x_telegram_bot_api_secret_token != expected_secret:
        raise HTTPException(status_code=403, detail="PocketMunim: Unauthorized Webhook Origin")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    message_obj = payload.get("message") or payload.get("edited_message")
    callback_query = payload.get("callback_query")
    telegram_id = None
    chat_id = None

    if message_obj:
        telegram_id = message_obj.get("from", {}).get("id")
        chat_id = message_obj.get("chat", {}).get("id")
    elif callback_query:
        telegram_id = callback_query.get("from", {}).get("id")
        chat_id = callback_query.get("message", {}).get("chat", {}).get("id")

    if not telegram_id:
        raise HTTPException(status_code=200, detail="Missing Telegram ID in payload, dropped cleanly.")

    if not verify_user_authorization(str(telegram_id)):
        if chat_id:
            try:
                await send_telegram_reply(
                    chat_id,
                    "⛔ *ACCESS DENIED*\n\nYou are not an authorized PocketMunim member."
                )
            except Exception as e:
                print(f"Failed to send denial message: {e}")
        raise HTTPException(status_code=200, detail="You are not an authorized PocketMunim member.")

    request.state.telegram_id = str(telegram_id)
    return True

async def verify_qstash_request(request: Request) -> bool:
    current_signing_key = os.getenv("QSTASH_CURRENT_SIGNING_KEY")
    next_signing_key = os.getenv("QSTASH_NEXT_SIGNING_KEY")

    if not current_signing_key or not next_signing_key:
        print("WARNING: QStash keys missing. Running direct pass-through.")
        return True

    receiver = Receiver(
        current_signing_key=current_signing_key,
        next_signing_key=next_signing_key,
    )

    body = await request.body()
    signature = request.headers.get("Upstash-Signature")

    if not signature:
        raise HTTPException(status_code=401, detail="Missing Upstash Signature Header")

    try:
        receiver.verify(
            body=body.decode("utf-8"),
            signature=signature,
            url=str(request.url)
        )
        return True
    except Exception as e:
        raise HTTPException(status_code=403, detail=f"Invalid QStash Signature: {str(e)}")
""",

        # ==========================================
        # 5. DATA ACCESS OBJECTS (DAO)
        # ==========================================
        "app/dao/account_dao.py": """\
from typing import Optional, Dict, Any

class AccountDAO:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id

    def count_user_accounts(self) -> int:
        response = self.db.table('accounts').select('id', count='exact').eq('user_id', self.user_id).execute()
        return response.count if response.count else 0

    def get_primary_account(self) -> Optional[Dict[str, Any]]:
        response = self.db.table('accounts').select('*').eq('user_id', self.user_id).eq('is_default', True).execute()
        return response.data[0] if response.data else None

    def get_account_by_name(self, account_name: str) -> Optional[Dict[str, Any]]:
        response = self.db.table('accounts').select('*').eq('user_id', self.user_id).ilike('account_name', account_name).execute()
        return response.data[0] if response.data else None

    def create_account(self, account_data: dict) -> Dict[str, Any]:
        account_data['user_id'] = self.user_id
        response = self.db.table('accounts').insert(account_data).execute()
        new_account = response.data[0]

        audit_payload = {
            "account_id": new_account['id'],
            "user_id": self.user_id,
            "log_type": "ACCOUNT_CREATION",
            "amount": float(new_account['balance']),
            "balance_after": float(new_account['balance']),
            "description": "Initial account creation"
        }
        self.db.table('account_logs').insert(audit_payload).execute()
        return new_account
""",
        "app/dao/bulk_transaction_dao.py": """\
from decimal import Decimal

class BulkTransactionDAO:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id

    def check_transaction_exists(self, amount: str, description: str, txn_type: str) -> bool:
        try:
            res = self.db.table('transactions').select('*') \\
                .eq('user_id', self.user_id) \\
                .eq('amount', amount) \\
                .ilike('description', description) \\
                .eq('txn_type', txn_type) \\
                .eq('soft_deleted', False) \\
                .execute()
            return bool(res.data)
        except Exception:
            return False

    def execute_bulk_commit(self, account_id: str, payloads: list, total_deduction: Decimal, total_addition: Decimal) -> Decimal:
        net_change = total_addition - total_deduction
        max_amount = max(total_deduction, total_addition)

        net_change_str = str(net_change)
        max_amount_str = str(max_amount)

        for p in payloads:
            if 'amount' in p:
                p['amount'] = str(p['amount'])

        try:
            res = self.db.rpc('atomic_bulk_commit', {
                'p_account_id': account_id,
                'p_user_id': self.user_id,
                'p_net_change': net_change_str,
                'p_max_amount': max_amount_str,
                'p_payloads': payloads
            }).execute()
            return Decimal(str(res.data))
        except Exception as e:
            raise e
""",
        "app/dao/pending_batch_dao.py": """\
from typing import Any

class PendingBatchDAO:
    def __init__(self, db_client: Any):
        self.db = db_client

    def create_batch(self, batch_id: str, user_id: str, account_id: str, items: list[dict[str, Any]]) -> bool:
        try:
            payload = {
                "batch_id": str(batch_id),
                "user_id": str(user_id),
                "account_id": str(account_id),
                "items": items
            }
            self.db.table("pending_batches").insert(payload).execute()
            return True
        except Exception as e:
            print(f"Failed to create pending batch {batch_id}: {e}")
            return False

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        try:
            res = self.db.table("pending_batches").select("*").eq("batch_id", str(batch_id)).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            print(f"Failed to fetch pending batch {batch_id}: {e}")
            return None

    def update_batch_items(self, batch_id: str, items: list[dict[str, Any]]) -> bool:
        try:
            self.db.table("pending_batches").update({"items": items}).eq("batch_id", str(batch_id)).execute()
            return True
        except Exception as e:
            print(f"Failed to update pending batch {batch_id}: {e}")
            return False

    def delete_batch(self, batch_id: str) -> bool:
        try:
            self.db.table("pending_batches").delete().eq("batch_id", str(batch_id)).execute()
            return True
        except Exception as e:
            print(f"Failed to delete pending batch {batch_id}: {e}")
            return False
""",
        "app/dao/report_token_dao.py": """\
from datetime import datetime

class ReportTokenDAO:
    def __init__(self, db_client):
        self.db = db_client

    def create_token(self, token: str, user_id: str, expires_at: datetime) -> bool:
        expires_at_str = expires_at.isoformat() if isinstance(expires_at, datetime) else str(expires_at)
        self.db.table('report_tokens').insert({
            "token": token,
            "user_id": user_id,
            "expires_at": expires_at_str
        }).execute()
        return True

    def get_token(self, token: str):
        try:
            res = self.db.table('report_tokens').select('*').eq('token', token).execute()
            return res.data[0] if res.data and len(res.data) > 0 else None
        except Exception as e:
            print(f"Error fetching token: {e}")
            return None

    def delete_token(self, token: str):
        try:
            self.db.table('report_tokens').delete().eq('token', token).execute()
        except Exception as e:
            print(f"Error deleting token: {e}")
""",
        "app/cache/category_cache.py": """\
from typing import Any

class CategoryCacheManager:
    def __init__(self, db_client: Any, user_id: str):
        self.db = db_client
        self.user_id = str(user_id)
        self._lifecycle_cache: dict[str, Any] | None = None

    def _get_or_load_cache(self) -> dict[str, Any]:
        if self._lifecycle_cache is not None:
            return self._lifecycle_cache
        try:
            res = self.db.table('categories').select('category_name, subcategories').eq('user_id', self.user_id).execute()
            tree = {}
            for row in (res.data or []):
                cat = row['category_name']
                tree[cat] = {}
                for sub in row.get('subcategories', []):
                    tree[cat][sub.get('subcategory_name', 'General')] = sub.get('items', [])
            self._lifecycle_cache = tree
            return tree
        except Exception as e:
            print(f"CategoryCacheManager load error: {e}")
            return {}

    def search_item(self, item_name: str) -> dict[str, str] | None:
        user_cache = self._get_or_load_cache()
        search_key = item_name.strip().lower()
        for category, subcategories in user_cache.items():
            if isinstance(subcategories, dict):
                for subcategory, items in subcategories.items():
                    if isinstance(items, list) and any(isinstance(i, str) and i.strip().lower() == search_key for i in items):
                        return {"category": category, "subcategory": subcategory, "item": item_name}
        return None

    def rebuild_cache(self) -> None:
        self._lifecycle_cache = None
        self._get_or_load_cache()
""",

        # ==========================================
        # 6. BUSINESS LOGIC SERVICES
        # ==========================================
        "app/services/business_calendar_service.py": """\
import datetime
from dateutil.relativedelta import relativedelta

class BusinessCalendarService:
    def __init__(self, db_client):
        self.db = db_client

    def is_holiday(self, target_date: datetime.date) -> bool:
        if not self.db:
            return False
        try:
            res = self.db.table('bank_holidays').select('*').eq('holiday_date', target_date.isoformat()).eq('is_active', True).execute()
            return bool(res.data)
        except Exception:
            return False

    def get_actual_salary_date(self, year: int, month: int, expected_day: int = 31) -> datetime.date:
        try:
            target_date = datetime.date(year, month, expected_day)
        except ValueError:
            target_date = datetime.date(year, month, 1) + relativedelta(months=1, days=-1)

        while True:
            is_weekend = target_date.weekday() >= 5 
            if is_weekend or self.is_holiday(target_date):
                target_date -= datetime.timedelta(days=1)
            else:
                break
        return target_date
""",
        "app/services/amortization_engine.py": """\
import datetime
import math
from decimal import Decimal, ROUND_HALF_UP
from dateutil.relativedelta import relativedelta

class AmortizationEngine:
    @staticmethod
    def calculate_emi(principal: Decimal, annual_rate: Decimal, tenure_months: int) -> Decimal:
        if tenure_months <= 0:
            return Decimal('0.00')
        if annual_rate <= Decimal('0.00'):
            return (principal / Decimal(tenure_months)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        monthly_rate = annual_rate / Decimal('1200')
        factor = (Decimal('1') + monthly_rate) ** tenure_months
        emi = principal * monthly_rate * factor / (factor - Decimal('1'))
        return emi.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @staticmethod
    def generate_schedule(principal: float, annual_rate: float, tenure_months: int, start_date: datetime.date) -> list:
        p = Decimal(str(principal))
        r_annual = Decimal(str(annual_rate))
        monthly_rate = r_annual / Decimal('1200') if r_annual > 0 else Decimal('0.00')

        emi = AmortizationEngine.calculate_emi(p, r_annual, tenure_months)
        schedule = []
        balance = p
        current_date = start_date

        for i in range(1, tenure_months + 1):
            interest_comp = (balance * monthly_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if monthly_rate > 0 else Decimal('0.00')
            principal_comp = (emi - interest_comp).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            if principal_comp > balance or i == tenure_months:
                principal_comp = balance
                emi = principal_comp + interest_comp

            balance -= principal_comp
            schedule.append({
                "installment_number": i,
                "due_date": current_date.isoformat(),
                "emi_amount": float(emi),
                "principal_component": float(principal_comp),
                "interest_component": float(interest_comp),
                "remaining_balance": float(max(balance, Decimal('0.00'))),
                "status": "PENDING"
            })
            current_date += relativedelta(months=1)

        return schedule
""",
        "app/services/salary_service.py": """\
import calendar
from datetime import datetime
from decimal import Decimal
from app.utils.constants import TZ_IST
from app.services.business_calendar_service import BusinessCalendarService

class SalaryService:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id
        self.calendar_service = BusinessCalendarService(db_client)

    def set_monthly_salary_config(self, year: int, default_amount: float, expected_day: int = 31):
        payload = {
            "user_id": self.user_id,
            "year": year,
            "amount": default_amount,
            "updated_at": datetime.now(TZ_IST).isoformat()
        }
        res = self.db.table('salaries').upsert(payload).execute()
        return res.data
""",
        "app/services/loan_service.py": """\
from decimal import Decimal
from datetime import datetime
from app.utils.constants import TZ_IST
from app.services.amortization_engine import AmortizationEngine

class LoanService:
    def __init__(self, db_client, user_id: str):
        self.db = db_client
        self.user_id = user_id

    async def create_loan(self, loan_data) -> tuple[str, bool]:
        if not loan_data.principal or not loan_data.lender_name:
            item_desc = loan_data.lender_name or "Unknown Loan"
            return f"⚠️ *Skipped Loan Creation*: Missing principal or lender for '{item_desc}'.", False

        principal = Decimal(str(loan_data.principal))
        rate = Decimal(str(loan_data.annual_interest_rate or 0.0))
        tenure_years = loan_data.tenure_years or 1
        tenure_months = tenure_years * 12

        existing_loan = self.db.table("loans").select("*").eq("user_id", self.user_id).ilike("lender", loan_data.lender_name.strip()).eq("principal_amount", float(principal)).eq("is_active", True).execute()
        if existing_loan.data:
            return f"⚠️ *Duplicate Loan Detected*\\nAn active loan from *{loan_data.lender_name.title()}* for ₹{float(principal):,.2f} already exists.", False

        emi = loan_data.emi_amount
        if not emi or emi <= 0:
            emi = AmortizationEngine.calculate_emi(principal, rate, tenure_months)

        disbursement_str = loan_data.disbursement_date or datetime.now(TZ_IST).date().isoformat()
        loan_payload = {
            "user_id": self.user_id,
            "lender": loan_data.lender_name.title(),
            "principal_amount": float(principal),
            "annual_interest_rate": float(rate),
            "tenure_months": tenure_months,
            "start_date": str(disbursement_str),
            "is_active": True
        }
        res = self.db.table("loans").insert(loan_payload).execute()
        if not res.data:
            return f"❌ *Failed* to save loan for {loan_data.lender_name}.", False

        loan_id = res.data[0]['loan_id']
        start_date_str = loan_data.first_emi_date or disbursement_str
        start_date = datetime.strptime(str(start_date_str), "%Y-%m-%d").date()

        schedules_raw = AmortizationEngine.generate_schedule(float(principal), float(rate), tenure_months, start_date)
        schedules_payload = [{**s, "loan_id": loan_id} for s in schedules_raw]
        self.db.table("emi_schedules").insert(schedules_payload).execute()

        acc_res = self.db.table("accounts").select("*").eq("user_id", self.user_id).eq("is_default", True).execute()
        default_acc_name = "Account"
        if acc_res.data:
            default_acc = acc_res.data[0]
            default_acc_name = default_acc['account_name']
            current_balance = Decimal(str(default_acc['balance']))
            new_balance = current_balance + principal
            self.db.table("accounts").update({"balance": float(new_balance)}).eq("id", default_acc['id']).execute()
            self.db.table("account_logs").insert({
                "account_id": default_acc['id'],
                "user_id": self.user_id,
                "log_type": "CREDIT",
                "amount": float(principal),
                "balance_after": float(new_balance),
                "description": f"Loan Disbursement - {loan_data.lender_name.title()}"
            }).execute()
            self.db.table("transactions").insert({
                "user_id": self.user_id,
                "amount": float(principal),
                "txn_type": "borrow",
                "intent": "borrow",
                "category": "Loans",
                "subcategory": "Loan Disbursement",
                "description": f"Loan from {loan_data.lender_name.title()}",
                "date": datetime.now(TZ_IST).isoformat(),
                "destination_account": default_acc_name,
                "soft_deleted": False
            }).execute()

        return (
            f"✅ *Loan Registered Successfully*\\n"
            f"Lender: *{loan_data.lender_name.title()}*\\n"
            f"Principal: ₹{float(principal):,.2f} (Credited to {default_acc_name})\\n"
            f"Calculated EMI: ₹{float(emi):,.2f}\\n"
            f"Tenure: {tenure_years} Years ({tenure_months} months)"
        ), True

    async def process_emi_payment_by_id(self, loan_id: str, payment_amount: Decimal = None, target_period: str = None, force_schedule_id: str = None) -> tuple[str, any]:
        loan_res = self.db.table("loans").select("*").eq("loan_id", loan_id).eq("is_active", True).execute()
        if not loan_res.data:
            return "❌ *Loan Not Found*: This loan account is invalid or closed.", False
        loan = loan_res.data[0]

        sched_res = self.db.table("emi_schedules").select("*").eq("loan_id", loan_id).order("installment_number").execute()
        all_schedules = sched_res.data or []
        pending_schedules = [s for s in all_schedules if s['status'] == 'PENDING']

        target_sched = None
        if force_schedule_id:
            for sched in all_schedules:
                if sched['schedule_id'] == force_schedule_id:
                    target_sched = sched
                    break
        else:
            if pending_schedules:
                target_sched = pending_schedules[0]

        if not target_sched:
            return f"🎉 All EMIs for *{loan['lender']}* are already fully paid!", False

        amt_to_pay = payment_amount if (payment_amount and payment_amount > 0) else Decimal(str(target_sched['emi_amount']))

        acc_res = self.db.table("accounts").select("*").eq("user_id", self.user_id).eq("is_default", True).execute()
        if not acc_res.data:
            return "❌ *Transaction Failed*: No default bank account configured.", False
        default_acc = acc_res.data[0]

        current_balance = Decimal(str(default_acc['balance']))
        if current_balance < amt_to_pay:
            return f"⚠️ *Transaction Failed*\\nInsufficient balance in *{default_acc['account_name']}* to complete payment of ₹{amt_to_pay:,.2f}.", False

        new_balance = current_balance - amt_to_pay
        self.db.table("accounts").update({"balance": float(new_balance)}).eq("id", default_acc['id']).execute()
        self.db.table("account_logs").insert({
            "account_id": default_acc['id'],
            "user_id": self.user_id,
            "log_type": "DEBIT",
            "amount": float(amt_to_pay),
            "balance_after": float(new_balance),
            "description": f"Loan EMI Payment to {loan['lender']} (Installment #{target_sched['installment_number']})"
        }).execute()
        self.db.table("transactions").insert({
            "user_id": self.user_id,
            "amount": float(amt_to_pay),
            "txn_type": "loan_payment",
            "intent": "loan_payment",
            "category": "Loans",
            "subcategory": "EMI Payment",
            "description": f"EMI Payment - {loan['lender']}",
            "date": datetime.now(TZ_IST).isoformat(),
            "source_account": default_acc['account_name'],
            "soft_deleted": False
        }).execute()

        self.db.table("emi_schedules").update({"status": "PAID"}).eq("schedule_id", target_sched['schedule_id']).execute()

        remaining_check = self.db.table("emi_schedules").select("schedule_id", count="exact").eq("loan_id", loan_id).eq("status", "PENDING").execute()
        if not remaining_check.count or remaining_check.count == 0:
            self.db.table("loans").update({"is_active": False}).eq("loan_id", loan_id).execute()
            return f"🎉 *Loan Fully Paid Off!*\\nPaid ₹{amt_to_pay:,.2f} to *{loan['lender']}*. Loan closed!", True

        return f"✅ *EMI Payment Successful*\\nPaid ₹{amt_to_pay:,.2f} to *{loan['lender']}* (Installment #{target_sched['installment_number']}).\\nNew Balance in {default_acc['account_name']}: ₹{new_balance:,.2f}", True
""",
        "app/services/bulk_transaction_service.py": """\
import json
from decimal import Decimal
from datetime import datetime
from app.utils.constants import TZ_IST

def _safely_serialize_complex(val):
    if not val:
        return None
    if hasattr(val, 'model_dump_json'):
        return json.loads(val.model_dump_json(exclude_none=True))
    elif hasattr(val, 'json'):
        return json.loads(val.json(exclude_none=True))
    return None

class BulkTransactionService:
    def __init__(self, db_client, user_id: str, cache_manager, category_pull_service):
        self.db = db_client
        self.user_id = user_id
        from app.dao.bulk_transaction_dao import BulkTransactionDAO
        self.dao = BulkTransactionDAO(self.db, self.user_id)
        self.cache_manager = cache_manager
        self.category_pull_service = category_pull_service

    async def process_bulk_payload(self, transactions_list: list, default_account: dict) -> dict:
        unique_payloads = []
        pending_duplicates = []
        breakdown = []
        ignored = []
        new_taxonomy_items = []
        totals = {
            "expenses": Decimal('0.00'),
            "income": Decimal('0.00'),
            "transfers": Decimal('0.00')
        }

        unknown_item_names = set()
        for tx in transactions_list:
            amount = getattr(tx, 'amount', None) or Decimal('0.00')
            intent = (getattr(tx, 'intent', "") or "").lower()
            if intent == "expense" and amount > Decimal('0.00') and not getattr(tx, 'needs_clarification', False):
                tx_future = getattr(tx, 'future', None)
                if not (tx_future and getattr(tx_future, 'is_future', False)):
                    raw_desc = getattr(tx, 'raw_description', None) or getattr(tx, 'item', "Item")
                    norm_item = getattr(tx, 'normalized_item', None) or str(raw_desc).title()
                    norm_item = str(norm_item).title()
                    if not self.cache_manager.search_item(norm_item):
                        unknown_item_names.add(norm_item)

        if unknown_item_names:
            query_string = ", ".join(list(unknown_item_names)[:10])
            try:
                await self.category_pull_service.manual_category_pull(query_string, self.user_id)
                self.cache_manager.rebuild_cache()
            except Exception as e:
                print(f"Auto-learning pre-flight failed: {e}")

        for tx in transactions_list:
            raw_desc = getattr(tx, 'raw_description', None) or getattr(tx, 'item', "Item")
            description = str(raw_desc).title()
            norm_val = getattr(tx, 'normalized_item', None) or description
            norm_item = str(norm_val).title()
            amount = getattr(tx, 'amount', None) or Decimal('0.00')

            if amount <= Decimal('0.00'):
                ignored.append(f"• {description} (Zero or missing amount)")
                continue

            tx_future = getattr(tx, 'future', None)
            if tx_future and getattr(tx_future, 'is_future', False):
                ignored.append(f"• {description} (Future item skipped)")
                continue

            if not getattr(tx, 'intent', None) or getattr(tx, 'needs_clarification', False):
                ignored.append(f"• {description} (Needs Clarification)")
                continue

            intent = getattr(tx, 'intent', "").lower()
            category = getattr(tx, 'category', None)
            subcategory = getattr(tx, 'subcategory', None)
            cached = self.cache_manager.search_item(norm_item)

            if intent == "expense":
                if not category or not subcategory:
                    if cached and cached.get("category"):
                        category = category or cached["category"]
                        subcategory = subcategory or cached.get("subcategory")
                    else:
                        category = category or "Groceries"
                        subcategory = subcategory or "General Purchases"
                        new_taxonomy_items.append({"category": category, "subcategory": subcategory, "item": norm_item})
                else:
                    if not cached:
                        new_taxonomy_items.append({"category": category, "subcategory": subcategory, "item": norm_item})
            else:
                if not category:
                    category = "Income" if intent == "income" else "Transfer"
                if not subcategory:
                    subcategory = "General"
                norm_item = subcategory if subcategory != "General" else category

            is_debit = intent in ["expense", "transfer_other", "transfer_own", "loan_payment", "lend"]
            is_credit = intent in ["income", "transfer_own", "borrow"]
            if intent == "loan_repayment":
                loan_rep = getattr(tx, 'loan_repayment', None)
                direction = getattr(loan_rep, 'direction', None) if loan_rep else None
                if direction == "paid":
                    is_debit = True
                else:
                    is_credit = True

            source_acc = default_account['account_name'] if is_debit else None
            dest_acc = default_account['account_name'] if is_credit else None

            extended_data = {}
            for complex_key in ['loan', 'loan_repayment', 'split', 'investment', 'tax', 'subscription', 'future', 'recurrence']:
                val = getattr(tx, complex_key, None)
                serialized = _safely_serialize_complex(val)
                if serialized:
                    extended_data[complex_key] = serialized

            quantity_val = getattr(tx, 'quantity', None)
            payload = {
                "user_id": self.user_id,
                "amount": str(amount),
                "txn_type": intent,
                "description": description,
                "normalized_item": norm_item,
                "intent": intent,
                "category": category,
                "subcategory": subcategory,
                "date": datetime.now(TZ_IST).isoformat(),
                "source_account": source_acc,
                "destination_account": dest_acc,
                "soft_deleted": False,
                "currency": getattr(tx, 'currency', 'INR') or 'INR',
                "quantity": str(quantity_val) if quantity_val is not None else None,
                "unit": getattr(tx, 'unit', None),
                "counterparty": getattr(tx, 'counterparty', None),
                "payment_method": getattr(tx, 'payment_method', None),
                "transaction_reference": getattr(tx, 'transaction_reference', None),
                "extended_data": extended_data
            }

            is_salary_or_income = intent == "income" or (category and category.lower() == "income")
            is_duplicate = False if is_salary_or_income else self.dao.check_transaction_exists(str(amount), description, intent)

            if is_duplicate:
                pending_duplicates.append({
                    "payload": payload, "selected": False, "desc": description, "amount": str(amount),
                    "txn_type": intent
                })
            else:
                unique_payloads.append(payload)
                cat_disp = f"{category} -> {subcategory}" if subcategory else category
                if is_debit and not is_credit:
                    totals["expenses"] += amount
                elif is_credit and not is_debit:
                    totals["income"] += amount
                elif is_debit and is_credit:
                    totals["transfers"] += amount
                breakdown.append(f"• {description}: ₹{float(amount):,.2f} ({cat_disp})")

        if new_taxonomy_items:
            await self.category_pull_service.bulk_add_items_to_taxonomy(new_taxonomy_items, self.user_id)

        return {
            "unique": unique_payloads,
            "duplicates": pending_duplicates,
            "totals": totals,
            "breakdown": breakdown,
            "ignored": ignored
        }
""",

        # ==========================================
        # 7. AI INFERENCE & CLASSIFICATION
        # ==========================================
        "app/ai/ai_provider.py": """\
import os
import json
import asyncio
from groq import AsyncGroq

async def execute_resilient_ai(system_prompt: str, user_prompt: str, db_client=None, is_json: bool = True) -> tuple[str, str]:
    groq_keys = [k.strip() for k in os.getenv("GROQ_API_KEYS", "").split(",") if k.strip()]
    single_key = os.getenv("GROQ_API_KEY")
    if single_key and single_key.strip() not in groq_keys:
        groq_keys.append(single_key.strip())

    if not groq_keys:
        raise Exception("No Groq API keys configured in environment variables.")

    all_errors = []
    for idx, key in enumerate(groq_keys):
        try:
            client = AsyncGroq(api_key=key)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            kwargs = {
                "model": "llama-3.3-70b-versatile",
                "messages": messages,
                "temperature": 0.0
            }
            if is_json:
                kwargs["response_format"] = {"type": "json_object"}

            completion = await client.chat.completions.create(**kwargs)
            return completion.choices[0].message.content.strip(), completion.choices[0].finish_reason
        except Exception as e:
            error_msg = f"Groq Key {idx + 1} Failure: {str(e)}"
            all_errors.append(error_msg)
            print(error_msg)
            continue

    error_summary = " | ".join(all_errors)
    raise Exception(f"AI Resilient Provider Exhausted: {error_summary}")
""",
        "app/ai/loan_extraction_service.py": """\
import json
from typing import List, Tuple
from app.ai.ai_provider import execute_resilient_ai
from app.schemas.loan_schema import LoanNLPData

class LoanExtractionService:
    def __init__(self, admin_db_client):
        self.db = admin_db_client

    async def parse_loan_text(self, text: str) -> Tuple[List[LoanNLPData], str]:
        system_prompt = ~TRIPLE_QUOTE~You are the PocketMunim Loan Extraction Engine.
Analyze the user text and separate loan actions (creating loans, paying EMIs) from standard expenses/groceries.
NUMBER CONVERSIONS:
- "l", "L", "lakh" = x100,000 (e.g. 5L = 500000)
- "k", "K" = x1,000 (e.g. 50k = 50000)
- "cr", "crore" = x10,000,000

Return ONLY valid JSON matching this schema:
{
  "actions": [
    {
      "action": "CREATE|PAY_EMI",
      "lender_name": "string or null",
      "principal": number or null,
      "annual_interest_rate": number or null,
      "tenure_years": integer or null,
      "disbursement_date": "YYYY-MM-DD or null",
      "first_emi_date": "YYYY-MM-DD or null",
      "emi_amount": number or null,
      "payment_amount": number or null,
      "target_period": "string or null"
    }
  ],
  "other_transactions_text": "string combining non-loan items. Empty string if none."
}~TRIPLE_QUOTE~
        raw_json, _ = await execute_resilient_ai(
            system_prompt=system_prompt,
            user_prompt=text,
            db_client=self.db,
            is_json=True
        )
        data = json.loads(raw_json)
        other_text = data.get("other_transactions_text", "")
        items = data.get("actions", [])
        if isinstance(data, list):
            items = data
        elif "action" in data and "actions" not in data:
            items = [data]

        parsed_actions = [LoanNLPData(**item) for item in items if isinstance(item, dict) and "action" in item]
        return parsed_actions, other_text
""",
        "app/ai/category_pull_service.py": """\
import json
from typing import Optional
from app.ai.ai_provider import execute_resilient_ai

class CategoryPullService:
    def __init__(self, ai_client=None, admin_db_client=None):
        self.admin_db = admin_db_client

    async def manual_category_pull(self, query: str, user_id: str) -> dict:
        result = {"added": 0, "error": None}
        if not self.admin_db:
            result["error"] = "System database missing."
            return result

        existing_res = self.admin_db.table('categories').select('*').eq('user_id', str(user_id)).execute()
        existing_data = existing_res.data or []
        db_map = {}
        existing_items_set = set()

        for row in existing_data:
            cat_key = row['category_name'].strip().lower()
            db_map[cat_key] = row
            for sub in row.get('subcategories', []):
                for item in sub.get('items', []):
                    existing_items_set.add(item.strip().lower())

        exclusion_text = ""
        if existing_items_set:
            existing_items_str = ", ".join(sorted(existing_items_set))
            exclusion_text = f"\\n\\nEXCLUSION LIST (DO NOT GENERATE THESE):\\n[{existing_items_str}]\\n"

        system_prompt = f"You are the Category Engine. Generate 15-20 realistic taxonomy items related to '{query}'.\\nOUTPUT FORMAT JSON:\\n{{\\"taxonomy\\": [{{\\"category_name\\": \\"Groceries\\", \\"subcategories\\": [{{\\"subcategory_name\\": \\"Dairy\\", \\"items\\": [\\"milk\\"]}}]}}]}}{exclusion_text}"

        try:
            raw_content, _ = await execute_resilient_ai(system_prompt, "Generate JSON.", self.admin_db, is_json=True)
            parsed = json.loads(raw_content)
            taxonomy_list = parsed.get("taxonomy", [])
            if not taxonomy_list:
                result["error"] = "AI returned empty taxonomy."
                return result

            for cat_obj in taxonomy_list:
                raw_cat_name = cat_obj.get("category_name", "").strip()
                new_subs = cat_obj.get("subcategories", [])
                if not raw_cat_name or not new_subs:
                    continue
                cat_key = raw_cat_name.lower()

                if cat_key in db_map:
                    existing_row = db_map[cat_key]
                    actual_cat_name = existing_row['category_name']
                    existing_subs = existing_row.get('subcategories', [])
                    sub_dict = {s.get('subcategory_name', 'General').strip().lower(): {"original_name": s.get('subcategory_name', 'General'), "items": {i.strip().lower(): i.strip() for i in s.get('items', [])}} for s in existing_subs}

                    for ns in new_subs:
                        raw_s_name = ns.get('subcategory_name', 'General').strip()
                        s_key = raw_s_name.lower()
                        if s_key not in sub_dict:
                            sub_dict[s_key] = {"original_name": raw_s_name, "items": {}}
                        for i in ns.get('items', []):
                            sub_dict[s_key]["items"][i.strip().lower()] = i.strip()

                    merged_subs = [{"subcategory_name": v["original_name"], "items": list(v["items"].values())} for v in sub_dict.values()]
                    self.admin_db.table('categories').update({"subcategories": merged_subs}).eq('user_id', str(user_id)).eq('category_name', actual_cat_name).execute()
                else:
                    clean_subs = [{"subcategory_name": ns.get('subcategory_name', 'General').strip(), "items": list({i.strip().lower(): i.strip() for i in ns.get('items', [])}.values())} for ns in new_subs]
                    self.admin_db.table('categories').insert({"user_id": str(user_id), "category_name": raw_cat_name, "subcategories": clean_subs}).execute()

                result["added"] += sum(len(sub.get("items", [])) for sub in new_subs)

            return result
        except Exception as e:
            result["error"] = str(e)
            return result

    async def bulk_add_items_to_taxonomy(self, items_list: list[dict], user_id: str) -> None:
        if not self.admin_db or not items_list:
            return
        try:
            res = self.admin_db.table('categories').select('*').eq('user_id', str(user_id)).execute()
            db_map = {row['category_name'].strip().lower(): row for row in (res.data or [])}
            taxonomy_map = {}

            for data in items_list:
                cat_name = data.get("category", "General").strip()
                sub_name = data.get("subcategory", "Miscellaneous").strip()
                item_name = data.get("item", "").strip()
                if not item_name:
                    continue
                cat_key, sub_key = cat_name.lower(), sub_name.lower()
                if cat_key not in taxonomy_map:
                    taxonomy_map[cat_key] = {"name": cat_name, "subs": {}}
                if sub_key not in taxonomy_map[cat_key]["subs"]:
                    taxonomy_map[cat_key]["subs"][sub_key] = {"name": sub_name, "items": set()}
                taxonomy_map[cat_key]["subs"][sub_key]["items"].add(item_name)

            for cat_key, new_cat_data in taxonomy_map.items():
                if cat_key in db_map:
                    existing_row = db_map[cat_key]
                    actual_cat_name = existing_row['category_name']
                    existing_subs = existing_row.get('subcategories', [])
                    sub_dict = {s.get('subcategory_name', 'General').strip().lower(): {"original_name": s.get('subcategory_name', 'General'), "items": {i.strip().lower(): i.strip() for i in s.get('items', [])}} for s in existing_subs}

                    for sub_key, sub_data in new_cat_data["subs"].items():
                        if sub_key not in sub_dict:
                            sub_dict[sub_key] = {"original_name": sub_data["name"], "items": {}}
                        for item in sub_data["items"]:
                            sub_dict[sub_key]["items"][item.lower()] = item

                    merged_subs = [{"subcategory_name": v["original_name"], "items": list(v["items"].values())} for v in sub_dict.values()]
                    self.admin_db.table('categories').update({"subcategories": merged_subs}).eq('user_id', str(user_id)).eq('category_name', actual_cat_name).execute()
                else:
                    clean_subs = [{"subcategory_name": sub_data["name"], "items": list(sub_data["items"])} for sub_data in new_cat_data["subs"].values()]
                    self.admin_db.table('categories').insert({"user_id": str(user_id), "category_name": new_cat_data["name"], "subcategories": clean_subs}).execute()
        except Exception as e:
            print(f"Failed bulk category insert: {e}")

    async def classify_item(self, item_name: str, intent: Optional[str] = None) -> dict:
        system_prompt = "You are the Category Classifier. Return JSON: {\\"category\\": \\"string\\", \\"subcategory\\": \\"string\\", \\"normalized_item\\": \\"clean string\\"}"
        try:
            raw_content, _ = await execute_resilient_ai(system_prompt, f"item: \\"{item_name}\\", intent: \\"{intent}\\"", self.admin_db, is_json=True)
            parsed = json.loads(raw_content)
            return {
                "category": parsed.get("category") or "General",
                "subcategory": parsed.get("subcategory") or "Miscellaneous",
                "normalized_item": parsed.get("normalized_item") or item_name
            }
        except Exception:
            return {"category": "General", "subcategory": "Miscellaneous", "normalized_item": item_name}
""",

        # ==========================================
        # 8. TELEGRAM HANDLERS
        # ==========================================
        "app/telegram/telegram_utils.py": """\
import json
import httpx
import os
import logging

logger = logging.getLogger(__name__)

async def send_telegram_reply(chat_id: int, text: str, reply_markup: dict = None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            logger.error(f"Telegram API Error ({response.status_code}): {response.text}")

async def edit_telegram_message(chat_id: int, message_id: int, text: str = None, reply_markup: dict = None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/"
    payload = {"chat_id": chat_id, "message_id": message_id}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    if text:
        url += "editMessageText"
        payload["text"] = text
        payload["parse_mode"] = "Markdown"
    else:
        url += "editMessageReplyMarkup"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        if response.status_code != 200:
            logger.error(f"Telegram API Edit Error ({response.status_code}): {response.text}")
""",
        "app/telegram/handlers/user_handler.py": """\
import re
import calendar
from datetime import datetime
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply

MALICIOUS_PATTERN = re.compile(
    r'(DROP\\s+TABLE|SELECT\\s+\\*|OR\\s+1=1|<script>|<img|jndi:ldap|rm\\s+-rf|;/|{{.*}}|\\.\\./\\.\\./|"\\s*OR\\s*")',
    re.IGNORECASE
)

class UserHandler:
    @staticmethod
    async def security_check(supabase_admin, chat_id, text):
        if MALICIOUS_PATTERN.search(text):
            try:
                user_res = supabase_admin.table('users').select('security_strikes').eq('telegram_id', chat_id).execute()
                current_strikes = user_res.data[0].get('security_strikes', 0) if user_res.data else 0
                new_strikes = current_strikes + 1
                supabase_admin.table('users').update({'security_strikes': new_strikes}).eq('telegram_id', chat_id).execute()

                if new_strikes >= 3:
                    await send_telegram_reply(chat_id, "⛔ *ACCOUNT SUSPENDED*\\n\\nMultiple security violations detected.")
                else:
                    await send_telegram_reply(chat_id, f"⚠️ *SECURITY WARNING ({new_strikes}/3)*\\n\\nMalicious input format detected.")
            except Exception as e:
                await send_telegram_reply(chat_id, f"Error: `{str(e)}`")
            return False, False

        try:
            user_res = supabase_admin.table('users').select('*').eq('telegram_id', chat_id).execute()
            user_exists = bool(user_res.data)
            if user_exists and user_res.data[0].get('security_strikes', 0) >= 3:
                await send_telegram_reply(chat_id, "⛔ *ACCOUNT SUSPENDED*")
                return False, user_exists
            return True, user_exists
        except Exception as e:
            await send_telegram_reply(chat_id, f"Error: `{str(e)}`")
            return False, False

    @staticmethod
    async def prompt_registration(chat_id):
        copyable_form = "```text\\n/register\\nName: [Your Name]\\nCurrency: INR\\nMonthly Salary: [Amount]\\nBank Account: [Bank Name]\\nCurrent Balance: [Amount]\\n```"
        await send_telegram_reply(chat_id, f"📝 *Registration Mandatory*\\n\\nSend the completed form below:\\n\\n{copyable_form}")

    @staticmethod
    async def register(supabase_admin, chat_id, user_id, text, user_exists):
        if "[" in text or "]" in text or "Your Name" in text or len(text.replace("/register", "").strip()) < 10:
            await send_telegram_reply(chat_id, "⚠️ *Invalid Form*: Replace all bracketed fields with real details.")
            return

        lines = text.split("\\n")
        name, currency, bank_name = "", "INR", ""
        monthly_salary = current_balance = None

        for line in lines:
            if "Name:" in line: name = line.split("Name:")[1].strip().title()
            if "Currency:" in line: currency = line.split("Currency:")[1].strip().upper()
            if "Monthly Salary:" in line:
                try: monthly_salary = float(line.split("Monthly Salary:")[1].strip().replace(",", ""))
                except: pass
            if "Bank Account:" in line: bank_name = line.split("Bank Account:")[1].strip().title()
            if "Current Balance:" in line:
                try: current_balance = float(line.split("Current Balance:")[1].strip().replace(",", ""))
                except: pass

        if not name or monthly_salary is None or not bank_name or current_balance is None:
            await send_telegram_reply(chat_id, "❌ *Registration Failed*: Missing required form fields.")
            return

        if not user_exists:
            try:
                supabase_admin.table('users').insert({
                    "telegram_id": chat_id, "full_name": name, "currency": currency, "security_strikes": 0
                }).execute()
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
                        salary_date = current_dt.replace(year=current_year, month=m, day=last_day, hour=23, minute=59, second=59)
                        month_name = salary_date.strftime('%b %Y')

                        supabase_admin.table('salaries').insert({
                            "user_id": user_id, "year": current_year, "month_number": m,
                            "month_name": month_name, "amount": monthly_salary, "is_deducted": False
                        }).execute()
                        supabase_admin.table('transactions').insert({
                            "user_id": user_id, "amount": monthly_salary, "txn_type": "income",
                            "description": f"Salary for {month_name}", "intent": "income", "category": "Income",
                            "subcategory": "Salary", "date": salary_date.isoformat(), "destination_account": bank_name,
                            "soft_deleted": False
                        }).execute()
                        total_salary_added += monthly_salary

                final_balance = current_balance + total_salary_added
                supabase_admin.table('accounts').update({"balance": final_balance}).eq("id", acc_id).execute()

                if total_salary_added > 0:
                    supabase_admin.table('account_logs').insert({
                        "account_id": acc_id, "user_id": user_id, "log_type": "CREDIT",
                        "amount": total_salary_added, "balance_after": final_balance,
                        "description": "Retroactive Salary Structuring"
                    }).execute()

                await send_telegram_reply(chat_id, f"🎉 *Registration Successful!*\\n\\nWelcome, *{name}*!\\nPrimary Account: **{bank_name}**\\nInitial Balance: **₹{final_balance:,.2f}**")
            except Exception as e:
                await send_telegram_reply(chat_id, f"❌ Registration failed: `{str(e)}`")
        else:
            await send_telegram_reply(chat_id, "💡 You are already registered with PocketMunim!")
""",
        "app/telegram/handlers/account_handler.py": """\
from app.telegram.telegram_utils import send_telegram_reply

class AccountHandler:
    @staticmethod
    def get_account_from_list(accounts_list, target_name=None):
        if not accounts_list:
            return None
        if target_name:
            target_clean = target_name.strip().lower()
            for acc in accounts_list:
                if acc['account_name'].lower() == target_clean:
                    return acc
            return None
        for acc in accounts_list:
            if acc.get('is_default'):
                return acc
        return accounts_list[0]

    @staticmethod
    async def add_account(supabase_admin, chat_id, user_id, text):
        parts = text.replace("/addaccount", "").strip().split()
        if len(parts) < 2:
            await send_telegram_reply(chat_id, "💡 Use format: `/addaccount [BankName] [Balance]`")
            return

        acc_name = " ".join(parts[:-1]).title()
        try:
            acc_bal = float(parts[-1])
        except ValueError:
            await send_telegram_reply(chat_id, "⚠️ Invalid numeric balance amount.")
            return

        try:
            existing_accs = supabase_admin.table('accounts').select('id').eq('user_id', user_id).execute()
            is_first = len(existing_accs.data) == 0
            supabase_admin.table('accounts').insert({
                "user_id": user_id, "account_name": acc_name, "balance": acc_bal, "is_default": is_first
            }).execute()
            await send_telegram_reply(chat_id, f"✅ *Account Added*\\nName: {acc_name}\\nBalance: ₹{acc_bal:,.2f}")
        except Exception as e:
            await send_telegram_reply(chat_id, f"❌ Failed to add account: `{str(e)}`")

    @staticmethod
    async def set_default(supabase_admin, chat_id, user_id, text):
        acc_name = text.replace("/setdefault", "").strip().title()
        if not acc_name:
            await send_telegram_reply(chat_id, "💡 Provide an account name.")
            return

        try:
            acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).ilike('account_name', acc_name).execute()
            if not acc_res.data:
                await send_telegram_reply(chat_id, f"⚠️ Account '{acc_name}' not found.")
                return

            supabase_admin.table('accounts').update({"is_default": False}).eq('user_id', user_id).execute()
            supabase_admin.table('accounts').update({"is_default": True}).eq('id', acc_res.data[0]['id']).execute()
            await send_telegram_reply(chat_id, f"⭐ *{acc_res.data[0]['account_name']}* is now your default account.")
        except Exception as e:
            await send_telegram_reply(chat_id, f"❌ Failed to set default: `{str(e)}`")

    @staticmethod
    async def show_accounts(supabase_admin, chat_id, user_id):
        try:
            acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).order('is_default', desc=True).execute()
            accounts = acc_res.data or []
            if not accounts:
                await send_telegram_reply(chat_id, "🏦 *No Bank Accounts Configured*\\nUse `/addaccount [BankName] [Balance]` to start.")
                return

            total_balance = sum(float(acc['balance']) for acc in accounts)
            msg_lines = ["💼 *Your Linked Accounts*\\n"]
            for acc in accounts:
                icon = "⭐" if acc.get('is_default') else "🏦"
                name = acc['account_name']
                bal = float(acc['balance'])
                msg_lines.append(f"{icon} *{name}*: ₹{bal:,.2f}")

            msg_lines.append(f"\\n💵 *Total Liquid Net Worth:* ₹{total_balance:,.2f}")
            await send_telegram_reply(chat_id, "\\n".join(msg_lines))
        except Exception as e:
            await send_telegram_reply(chat_id, f"❌ System Error: `{str(e)}`")
""",
        "app/telegram/handlers/salary_handler.py": """\
import re
from datetime import datetime
from decimal import Decimal
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply

class SalaryHandler:
    @staticmethod
    async def settle_salary(supabase_admin, chat_id, user_id, text: str):
        match = re.match(r"^/settle\\s+([a-zA-Z]+)(?:\\s+(\\d{2,4}))?$", text.strip(), re.IGNORECASE)
        if not match:
            await send_telegram_reply(chat_id, "💡 Format: `/settle [month]` or `/settle [month] [year]`\\nExample: `/settle jan`")
            return

        month_str = match.group(1).lower()
        year_str = match.group(2)

        month_map = {
            'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
            'apr': 4, 'april': 4, 'may': 5, 'june': 6, 'jun': 6,
            'jul': 7, 'july': 7, 'aug': 8, 'august': 8, 'sep': 9, 'september': 9,
            'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12
        }

        if month_str not in month_map:
            await send_telegram_reply(chat_id, f"⚠️ Unknown month: '{match.group(1)}'.")
            return

        month_num = month_map[month_str]
        month_name_full = datetime(2000, month_num, 1).strftime('%B')
        current_year = datetime.now(TZ_IST).year

        target_year = int(year_str) if year_str else current_year
        if year_str and len(year_str) == 2:
            target_year = 2000 + int(year_str)

        sal_res = supabase_admin.table('salaries').select('*').eq('user_id', user_id).eq('year', target_year).eq('month_number', month_num).execute()
        if not sal_res.data:
            await send_telegram_reply(chat_id, f"⚠️ No salary record found for *{month_name_full} {target_year}*.")
            return

        salary = sal_res.data[0]
        if salary.get('is_deducted'):
            await send_telegram_reply(chat_id, f"💡 Salary for *{month_name_full} {target_year}* is already settled.")
            return

        amount = Decimal(str(salary['amount']))
        acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).eq('is_default', True).execute()
        if not acc_res.data:
            await send_telegram_reply(chat_id, "❌ Default bank account missing.")
            return

        default_acc = acc_res.data[0]
        new_balance = Decimal(str(default_acc['balance'])) - amount

        try:
            supabase_admin.table('accounts').update({"balance": float(new_balance)}).eq('id', default_acc['id']).execute()
            supabase_admin.table('salaries').update({"is_deducted": True}).eq('id', salary['id']).execute()

            desc = f"Settlement for {month_name_full} {target_year}"
            now_iso = datetime.now(TZ_IST).isoformat()

            supabase_admin.table('transactions').insert({
                "user_id": user_id, "amount": float(amount), "txn_type": "expense",
                "intent": "settlement", "category": "Settlement", "subcategory": "Monthly Settlement",
                "source_account": default_acc['account_name'], "description": desc, "date": now_iso, "soft_deleted": False
            }).execute()

            supabase_admin.table('account_logs').insert({
                "account_id": default_acc['id'], "user_id": user_id, "log_type": "DEBIT",
                "amount": float(amount), "balance_after": float(new_balance), "description": desc
            }).execute()

            await send_telegram_reply(chat_id, f"✅ *Settlement Successful*\\nSalary of ₹{float(amount):,.2f} for *{month_name_full} {target_year}* settled.\\nDeducted from: *{default_acc['account_name']}*")
        except Exception as e:
            await send_telegram_reply(chat_id, f"❌ Error executing settlement: `{str(e)}`")
""",
        "app/telegram/handlers/loan_handler.py": """\
from datetime import datetime
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply
from app.services.loan_service import LoanService
from app.ai.loan_extraction_service import LoanExtractionService

class LoanHandler:
    @staticmethod
    async def get_loans(supabase_admin, chat_id, user_id, text=""):
        query_arg = text.replace("/getloans", "").strip()
        db_query = supabase_admin.table('loans').select('*, emi_schedules(*)').eq('user_id', user_id).eq('is_active', True)
        if query_arg:
            db_query = db_query.ilike('lender', f"%{query_arg}%")

        loans_res = db_query.execute()
        loans = loans_res.data
        if not loans:
            await send_telegram_reply(chat_id, "🏦 You have no active loans.")
            return

        current_dt = datetime.now(TZ_IST)
        curr_year_month = current_dt.strftime("%Y-%m")

        for loan in loans:
            schedules = sorted(loan.get('emi_schedules', []), key=lambda x: x['installment_number'])
            pending_emis = [e for e in schedules if e['status'] == 'PENDING']
            total_emi = len(schedules)
            completed_emi = total_emi - len(pending_emis)
            progress = (completed_emi / total_emi * 100) if total_emi > 0 else 0

            bar_color = "🟩" if progress >= 85 else ("🟨" if progress >= 50 else "🟥")
            filled_blocks = int(progress / 10)
            progress_bar = f"{bar_color} {'█' * filled_blocks}{'░' * (10 - filled_blocks)}"

            paid_emis = [e for e in schedules if e['status'] == 'PAID']
            remaining_principal = float(max([e['remaining_balance'] for e in paid_emis], default=loan['principal_amount'])) if paid_emis else float(loan['principal_amount'])

            current_month_paid = any(sched['due_date'].startswith(curr_year_month) and sched['status'] == 'PAID' for sched in schedules)

            msg = [
                f"🏦 *{loan['lender']}*",
                f"{progress_bar} *{int(progress)}% Paid* ({completed_emi}/{total_emi} EMIs)",
                f"⏳ *Remaining Principal:* ₹{remaining_principal:,.2f}",
                f"📊 Original: ₹{float(loan['principal_amount']):,.2f} | Rate: {float(loan['annual_interest_rate'])}%"
            ]

            keyboard = None
            if pending_emis and not current_month_paid:
                next_emi = pending_emis[0]
                msg.append(f"⏰ *Next Due*: {next_emi['due_date']} (₹{float(next_emi['emi_amount']):,.2f})")
                keyboard = {
                    "inline_keyboard": [[{"text": f"💳 Pay EMI (₹{float(next_emi['emi_amount']):,.2f})", "callback_data": f"payemi_{loan['loan_id']}"}]]
                }
            elif current_month_paid:
                msg.append("✅ *Current month EMI paid.*")

            await send_telegram_reply(chat_id, "\\n".join(msg), reply_markup=keyboard)

    @staticmethod
    async def handle_loan_text(supabase_admin, chat_id, user_id, text) -> str:
        extractor = LoanExtractionService(supabase_admin)
        loan_service = LoanService(supabase_admin, user_id)
        try:
            parsed_actions, leftover_text = await extractor.parse_loan_text(text)
            response_messages = []
            for parsed in parsed_actions:
                if parsed.action == "CREATE":
                    msg, _ = await loan_service.create_loan(parsed)
                    response_messages.append(msg)
                elif parsed.action == "PAY_EMI":
                    msg, _ = await loan_service.process_emi_payment_by_id(loan_id=parsed.lender_name)
                    response_messages.append(msg)

            if response_messages:
                await send_telegram_reply(chat_id, "\\n\\n".join(response_messages))
            return leftover_text
        except Exception as e:
            await send_telegram_reply(chat_id, f"❌ Loan Batch Error: `{str(e)}`")
            return ""
""",
        "app/telegram/handlers/callback_handler.py": """\
import os
import httpx
from decimal import Decimal
from app.telegram.telegram_utils import edit_telegram_message
from app.dao.bulk_transaction_dao import BulkTransactionDAO
from app.dao.pending_batch_dao import PendingBatchDAO

class CallbackHandler:
    @staticmethod
    def generate_duplicate_keyboard(batch_id: str, items: list) -> dict:
        keyboard = []
        for i, item in enumerate(items):
            icon = "✅" if item.get("selected") else "⬜"
            keyboard.append([{
                "text": f"{icon} {item['desc']} (₹{float(item['amount']):,.2f})",
                "callback_data": f"btog_{batch_id}_{i}"
            }])
        keyboard.append([
            {"text": "💾 Confirm Selected", "callback_data": f"bconf_{batch_id}"},
            {"text": "❌ Cancel All", "callback_data": f"bcanc_{batch_id}"}
        ])
        return {"inline_keyboard": keyboard}

    @staticmethod
    async def handle(payload: dict, supabase_admin):
        cb = payload["callback_query"]
        chat_id = cb["message"]["chat"]["id"]
        message_id = cb["message"]["message_id"]
        user_id = str(cb["from"]["id"])
        data = cb["data"]

        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if telegram_token:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{telegram_token}/answerCallbackQuery",
                    json={"callback_query_id": cb["id"]}
                )

        batch_dao = PendingBatchDAO(supabase_admin)

        if data.startswith("btog_"):
            parts = data.split("_")
            batch_id, item_id = parts[1], int(parts[2])
            batch = batch_dao.get_batch(batch_id)
            if batch and "items" in batch and 0 <= item_id < len(batch["items"]):
                items = batch["items"]
                items[item_id]["selected"] = not items[item_id]["selected"]
                batch_dao.update_batch_items(batch_id, items)
                await edit_telegram_message(
                    chat_id, message_id,
                    reply_markup=CallbackHandler.generate_duplicate_keyboard(batch_id, items)
                )

        elif data.startswith("bconf_"):
            batch_id = data.split("_")[1]
            batch = batch_dao.get_batch(batch_id)
            if batch and "items" in batch:
                selected_items = [item for item in batch["items"] if item.get("selected")]
                if not selected_items:
                    await edit_telegram_message(chat_id, message_id, text="⚠️ No duplicates selected. Discarded.")
                else:
                    dao = BulkTransactionDAO(supabase_admin, user_id)
                    selected_payloads = [i["payload"] for i in selected_items]
                    acc_res = supabase_admin.table('accounts').select('*').eq('id', batch["account_id"]).execute()
                    if acc_res.data:
                        default_acc_name = acc_res.data[0]['account_name']
                        total_deduction = sum(Decimal(str(p["amount"])) for p in selected_payloads if p.get("source_account") == default_acc_name)
                        total_addition = sum(Decimal(str(p["amount"])) for p in selected_payloads if p.get("destination_account") == default_acc_name)
                        try:
                            dao.execute_bulk_commit(batch["account_id"], selected_payloads, total_deduction, total_addition)
                            await edit_telegram_message(chat_id, message_id, text=f"✅ {len(selected_payloads)} duplicate transactions saved successfully.")
                        except Exception as e:
                            await edit_telegram_message(chat_id, message_id, text=f"❌ Database error: `{str(e)}`")
                batch_dao.delete_batch(batch_id)

        elif data.startswith("bcanc_"):
            batch_id = data.split("_")[1]
            batch_dao.delete_batch(batch_id)
            await edit_telegram_message(chat_id, message_id, text="🗑️ Duplicate batch discarded.")

        elif data.startswith("payemi_"):
            loan_id = data.split("_")[1]
            from app.services.loan_service import LoanService
            service = LoanService(supabase_admin, user_id)
            result_msg, _ = await service.process_emi_payment_by_id(loan_id)
            await edit_telegram_message(chat_id, message_id, text=result_msg)

        elif data == "menu_report":
            from app.telegram.handlers.report_handler import ReportHandler
            base_url = "https://pocket-munim.vercel.app"
            await ReportHandler.generate_report_link(base_url, chat_id, user_id, supabase_admin)

        elif data == "menu_loans":
            from app.telegram.handlers.loan_handler import LoanHandler
            await LoanHandler.get_loans(supabase_admin, chat_id, user_id, "")

        elif data == "menu_accounts":
            from app.telegram.handlers.account_handler import AccountHandler
            await AccountHandler.show_accounts(supabase_admin, chat_id, user_id)

        elif data == "menu_monthly":
            from app.telegram.handlers.report_handler import ReportHandler
            await ReportHandler.monthly_summary(supabase_admin, chat_id, user_id, "")

        return {"ok": True}
""",
        "app/telegram/handlers/nlp_handler.py": """\
import json
import uuid
import asyncio
from decimal import Decimal
from datetime import datetime
from app.ai.ai_provider import execute_resilient_ai
from app.ai.schemas import AITransactionExtraction
from app.cache.category_cache import CategoryCacheManager
from app.services.bulk_transaction_service import BulkTransactionService
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply
from app.telegram.handlers.account_handler import AccountHandler
from app.telegram.handlers.callback_handler import CallbackHandler
from app.dao.pending_batch_dao import PendingBatchDAO

SYSTEM_PROMPT = ~TRIPLE_QUOTE~POCKETMUNIM STRICT NLP ENGINE CONSTITUTION
Extract financial data into STRICT JSON matching AITransactionExtraction.
RULES:
1. Parse Indian units: 1.5L = 150000, 50k = 50000, 2Cr = 20000000.
2. TODAY IS {CURRENT_DATE}.
3. Multilingual English/Hindi/Marathi/Hinglish support.
4. Omit null or default empty keys to save token capacity.
5. JSON Output ONLY.
~TRIPLE_QUOTE~

class NLPHandler:
    @staticmethod
    async def process_text(supabase_admin, supabase, chat_id, user_id, text, category_pull_service):
        try:
            current_dt = datetime.now(TZ_IST)
            dynamic_system_prompt = SYSTEM_PROMPT.replace(
                "{CURRENT_DATE}",
                f"{current_dt.strftime('%Y-%m-%d')} ({current_dt.strftime('%A')})"
            )

            lines = [line.strip() for line in text.split('\\n') if line.strip()]
            CHUNK_SIZE = 10
            chunks = ["\\n".join(lines[i:i + CHUNK_SIZE]) for i in range(0, len(lines), CHUNK_SIZE)] if len(lines) > CHUNK_SIZE else [text]

            transactions_list = []

            async def fetch_chunk(chunk_str):
                try:
                    raw_response_text, finish_reason = await execute_resilient_ai(
                        system_prompt=dynamic_system_prompt,
                        user_prompt=chunk_str,
                        db_client=supabase_admin,
                        is_json=True
                    )
                    raw_json = json.loads(raw_response_text)
                    return AITransactionExtraction(**raw_json)
                except Exception as e:
                    return e

            results = await asyncio.gather(*[fetch_chunk(c) for c in chunks])

            for res in results:
                if not isinstance(res, Exception) and res.transactions:
                    transactions_list.extend(res.transactions)

            if not transactions_list:
                await send_telegram_reply(chat_id, "⚠️ No valid financial transactions were parsed from your message.")
                return

            acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
            user_accounts = acc_res.data or []
            if not user_accounts:
                await send_telegram_reply(chat_id, "🏦 *No Bank Accounts Configured*\\nUse `/addaccount [BankName] [Balance]`")
                return

            cache_manager = CategoryCacheManager(supabase, user_id)

            if len(transactions_list) > 1:
                default_acc = AccountHandler.get_account_from_list(user_accounts)
                bulk_service = BulkTransactionService(supabase_admin, user_id, cache_manager, category_pull_service)
                result = await bulk_service.process_bulk_payload(transactions_list, default_acc)

                if result["unique"]:
                    total_deduction = sum(Decimal(str(p["amount"])) for p in result["unique"] if p["source_account"] == default_acc['account_name'])
                    total_addition = sum(Decimal(str(p["amount"])) for p in result["unique"] if p["destination_account"] == default_acc['account_name'])

                    try:
                        bulk_service.dao.execute_bulk_commit(default_acc['id'], result["unique"], total_deduction, total_addition)
                    except Exception as e:
                        await send_telegram_reply(chat_id, f"❌ Bulk Transaction Failed: `{str(e)}`")
                        return

                    bd_text = "\\n".join(result["breakdown"]) if result["breakdown"] else "None"
                    receipt = (
                        f"🧾 *BULK TRANSACTION SAVED*\\n"
                        f"📊 Total Items: {len(result['unique'])}\\n"
                        f"🏦 Primary Account: {default_acc['account_name']}\\n\\n"
                        f"*Breakdown:*\\n{bd_text}"
                    )
                    await send_telegram_reply(chat_id, receipt)

                if result.get("duplicates"):
                    batch_id = uuid.uuid4().hex[:8]
                    batch_dao = PendingBatchDAO(supabase_admin)
                    batch_dao.create_batch(batch_id, user_id, default_acc['id'], result["duplicates"])
                    keyboard = CallbackHandler.generate_duplicate_keyboard(batch_id, result["duplicates"])
                    await send_telegram_reply(chat_id, "⚠️ *Duplicate Items Found*\\nTap below to select duplicates to keep:", reply_markup=keyboard)
                return

            tx = transactions_list[0]
            amount = getattr(tx, 'amount', None) or Decimal('0.00')
            raw_desc = getattr(tx, 'raw_description', None) or getattr(tx, 'item', text)
            description = str(raw_desc).title()
            norm_val = getattr(tx, 'normalized_item', None) or description
            norm_item = str(norm_val).title()

            if amount > Decimal('0.00'):
                intent = getattr(tx, 'intent', 'expense').lower()
                default_acc = AccountHandler.get_account_from_list(user_accounts)

                is_debit = intent in ["expense", "transfer_other", "loan_payment", "lend"]
                is_credit = intent in ["income", "borrow"]

                net_change = -float(amount) if is_debit else float(amount)
                res = supabase_admin.rpc('atomic_balance_update', {'p_account_id': default_acc['id'], 'p_amount': net_change}).execute()
                new_bal = res.data

                category = getattr(tx, 'category', 'General') or 'General'
                subcategory = getattr(tx, 'subcategory', 'Miscellaneous') or 'Miscellaneous'

                supabase.table("transactions").insert({
                    "user_id": user_id, "amount": float(amount), "txn_type": intent,
                    "description": description, "normalized_item": norm_item, "intent": intent,
                    "category": category, "subcategory": subcategory, "date": current_dt.isoformat(),
                    "source_account": default_acc['account_name'] if is_debit else None,
                    "destination_account": default_acc['account_name'] if is_credit else None,
                    "soft_deleted": False
                }).execute()

                supabase_admin.table('account_logs').insert({
                    "account_id": default_acc['id'], "user_id": user_id,
                    "log_type": "DEBIT" if is_debit else "CREDIT", "amount": float(amount),
                    "balance_after": new_bal, "description": description
                }).execute()

                await send_telegram_reply(chat_id, f"✅ *Transaction Saved*\\n{description}: ₹{float(amount):,.2f}\\nAccount: {default_acc['account_name']} (New Balance: ₹{new_bal:,.2f})")
        except Exception as e:
            await send_telegram_reply(chat_id, f"❌ Execution Error: `{str(e)}`")
""",
        "app/telegram/handlers/report_handler.py": """\
import uuid
from datetime import datetime, timedelta
from fastapi import HTTPException
from app.utils.constants import TZ_IST
from app.telegram.telegram_utils import send_telegram_reply
from app.dao.report_token_dao import ReportTokenDAO

class ReportHandler:
    @staticmethod
    async def generate_report_link(request_url, chat_id, user_id, supabase_admin):
        token = str(uuid.uuid4())
        expires_at = datetime.now(TZ_IST) + timedelta(minutes=15)
        token_dao = ReportTokenDAO(supabase_admin)
        token_dao.create_token(token, user_id, expires_at)

        base_url = str(request_url).split('/webhook')[0].split('/process-task')[0]
        report_url = f"{base_url}/report/view/{token}"

        response_msg = (
            f"📊 *PocketMunim AI Dashboard Ready*\\n\\n"
            f"Your interactive financial analytics report is active.\\n\\n"
            f"🔗 [View Downloadable Report]({report_url})\\n\\n"
            f"⏱️ _Note: Link automatically expires in 15 minutes._"
        )
        await send_telegram_reply(chat_id, response_msg)

    @staticmethod
    async def get_html_report(token: str, supabase_admin):
        token_dao = ReportTokenDAO(supabase_admin)
        token_data = token_dao.get_token(token)
        if not token_data:
            raise HTTPException(status_code=404, detail="Report link invalid or expired.")

        expires_at_str = token_data["expires_at"]
        try:
            if isinstance(expires_at_str, str):
                cleaned_str = expires_at_str.replace("Z", "+00:00")
                expires_at = datetime.fromisoformat(cleaned_str)
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=TZ_IST)
            else:
                expires_at = expires_at_str
        except Exception:
            raise HTTPException(status_code=404, detail="Timestamp parse error.")

        if datetime.now(TZ_IST).timestamp() > expires_at.timestamp():
            token_dao.delete_token(token)
            raise HTTPException(status_code=410, detail="Report link expired.")

        user_id = token_data["user_id"]
        user_res = supabase_admin.table('users').select('*').eq('telegram_id', user_id).execute()
        user_name = user_res.data[0]['full_name'] if user_res.data else "Valued Member"

        acc_res = supabase_admin.table('accounts').select('*').eq('user_id', user_id).execute()
        accounts = acc_res.data or []
        total_balance = sum(float(a['balance']) for a in accounts)

        txn_res = supabase_admin.table('transactions').select('*').eq('user_id', user_id).eq('soft_deleted', False).order('date', desc=True).execute()
        txns = txn_res.data or []

        total_income = sum(float(t['amount']) for t in txns if t['txn_type'] in ['income', 'borrow'])
        total_expense = sum(float(t['amount']) for t in txns if t['txn_type'] in ['expense', 'loan_payment'])
        net_savings = total_income - total_expense

        accounts_html = "".join([
            f'<div class="bg-slate-950 border border-slate-800 p-4 rounded-xl flex justify-between items-center"><span class="font-semibold text-slate-200">{acc["account_name"]}</span><span class="font-mono text-emerald-400">₹{float(acc["balance"]):,.2f}</span></div>'
            for acc in accounts
        ])

        txns_html = "".join([
            f'<tr class="hover:bg-slate-800/50"><td class="py-3 px-4 text-slate-400">{t["date"][:10]}</td><td class="py-3 px-4 font-medium text-white">{t["description"]}</td><td class="py-3 px-4 text-slate-400">{t["category"] or "General"}</td><td class="py-3 px-4"><span class="px-2 py-1 rounded-full text-xs font-semibold {"bg-emerald-500/20 text-emerald-300" if t["txn_type"] in ["income", "borrow"] else "bg-rose-500/20 text-rose-300"}">{t["txn_type"].upper()}</span></td><td class="py-3 px-4 text-right font-mono {"text-emerald-400" if t["txn_type"] in ["income", "borrow"] else "text-rose-400"}">{" " if t["txn_type"] in ["income", "borrow"] else "-"} ₹{float(t["amount"]):,.2f}</td></tr>'
            for t in txns[:50]
        ])

        return f~TRIPLE_QUOTE~<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PocketMunim Financial Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen py-10 px-4 font-sans">
    <div class="max-w-5xl mx-auto space-y-8">
        <div class="bg-slate-900 border border-slate-800 rounded-3xl p-8 flex justify-between items-center">
            <div>
                <h1 class="text-3xl font-bold text-white">Dashboard: {user_name}</h1>
                <p class="text-xs text-slate-400 mt-1">PocketMunim Enterprise Engine</p>
            </div>
            <div class="text-right">
                <p class="text-xs text-slate-400 uppercase tracking-wider">Liquid Net Worth</p>
                <p class="text-3xl font-extrabold text-emerald-400">₹{total_balance:,.2f}</p>
            </div>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-3 gap-6">
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 border-l-4 border-l-emerald-500">
                <p class="text-sm text-slate-400">Total Credits</p>
                <p class="text-2xl font-bold text-emerald-400">₹{total_income:,.2f}</p>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 border-l-4 border-l-rose-500">
                <p class="text-sm text-slate-400">Total Debits</p>
                <p class="text-2xl font-bold text-rose-400">₹{total_expense:,.2f}</p>
            </div>
            <div class="bg-slate-900 border border-slate-800 rounded-2xl p-6 border-l-4 border-l-cyan-500">
                <p class="text-sm text-slate-400">Net Surplus</p>
                <p class="text-2xl font-bold text-cyan-400">₹{net_savings:,.2f}</p>
            </div>
        </div>
        <div class="bg-slate-900 border border-slate-800 rounded-3xl p-6">
            <h2 class="text-xl font-bold text-white mb-4">Linked Accounts</h2>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">{accounts_html}</div>
        </div>
        <div class="bg-slate-900 border border-slate-800 rounded-3xl p-6 overflow-x-auto">
            <h2 class="text-xl font-bold text-white mb-4">Recent Ledger Transactions</h2>
            <table class="w-full text-left text-sm text-slate-300">
                <thead><tr class="text-slate-500 border-b border-slate-800"><th class="pb-3 px-4">Date</th><th class="pb-3 px-4">Description</th><th class="pb-3 px-4">Category</th><th class="pb-3 px-4">Type</th><th class="pb-3 px-4 text-right">Amount</th></tr></thead>
                <tbody class="divide-y divide-slate-800">{txns_html}</tbody>
            </table>
        </div>
    </div>
</body>
</html>~TRIPLE_QUOTE~

    @staticmethod
    async def monthly_summary(supabase_admin, chat_id, user_id, text):
        parts = text.replace("/monthly", "").strip().split()
        if len(parts) < 2:
            await send_telegram_reply(chat_id, "💡 Format: `/monthly [Month] [Year]` (e.g. `/monthly Jan 2026`)")
            return
        try:
            target_dt = datetime.strptime(f"1 {parts[0][:3]} {parts[1]}", "%d %b %Y")
            start_date = target_dt.strftime("%Y-%m-%d")
            end_dt = target_dt.replace(year=target_dt.year + 1, month=1) if target_dt.month == 12 else target_dt.replace(month=target_dt.month + 1)
            end_date = end_dt.strftime("%Y-%m-%d")

            txns = supabase_admin.table('transactions').select('amount, txn_type').eq('user_id', user_id).gte('date', start_date).lt('date', end_date).eq('soft_deleted', False).execute()
            total_income = sum(t['amount'] for t in txns.data if t['txn_type'] in ['income', 'borrow'])
            total_expense = sum(t['amount'] for t in txns.data if t['txn_type'] in ['expense', 'loan_payment'])

            reply = (
                f"📊 *Monthly Report: {target_dt.strftime('%B %Y')}*\\n\\n"
                f"📈 *Total Income:* ₹{total_income:,.2f}\\n"
                f"📉 *Total Expense:* ₹{total_expense:,.2f}\\n"
                f"------------------------\\n"
                f"💰 *Net Surplus:* ₹{(total_income - total_expense):,.2f}"
            )
            await send_telegram_reply(chat_id, reply)
        except ValueError:
            await send_telegram_reply(chat_id, "⚠️ Invalid date format.")
""",

        # ==========================================
        # 9. API / FASTAPI ENTRY POINT
        # ==========================================
        "app/main.py": """\
import os
import re
import httpx
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
from supabase import create_client, Client
from upstash_qstash import Client as QStashClient

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

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY else supabase
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
        {"command": "start", "description": "Show system guide"}
    ]
    async with httpx.AsyncClient() as client:
        res = await client.post(url, json={"commands": commands})
        return res.json()

@app.get("/report/view/{token}", response_class=HTMLResponse)
async def view_report(token: str):
    html_content = await ReportHandler.get_html_report(token, supabase_admin)
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
    elif is_loan_intent:
        leftover_text = await LoanHandler.handle_loan_text(supabase_admin, chat_id, user_id, text)
        if leftover_text and leftover_text.strip():
            await NLPHandler.process_text(supabase_admin, supabase, chat_id, user_id, leftover_text, category_pull_service)
    elif text.startswith("/start"):
        welcome_msg = (
            "💼 *Welcome to PocketMunim Enterprise*\\n\\n"
            "Your AI-powered personal finance engine is live. Speak naturally to record transactions, monitor loans, and track net worth.\\n\\n"
            "📌 *Quick Examples:*\\n"
            "• _\\"Got 85k salary in HDFC today\\"_\\n"
            "• _\\"Paid 450 for Zomato & 1200 for Uber\\"_\\n"
            "• _\\"HDFC loan 5L at 9.5% for 3 years\\"_\\n\\n"
            "Tap below to navigate:"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "📊 Open Dashboard", "callback_data": "menu_report"}],
                [{"text": "🏦 Active Loans", "callback_data": "menu_loans"}, {"text": "💳 Accounts", "callback_data": "menu_accounts"}],
                [{"text": "📈 Monthly Summary", "callback_data": "menu_monthly"}]
            ]
        }
        await send_telegram_reply(chat_id, welcome_msg, reply_markup=keyboard)
    elif text.startswith("/monthly"):
        await ReportHandler.monthly_summary(supabase_admin, chat_id, user_id, text)
    else:
        await NLPHandler.process_text(supabase_admin, supabase, chat_id, user_id, text, category_pull_service)

@app.post("/webhook")
async def telegram_webhook(request: Request, authorized: bool = Depends(authenticate_telegram_request)):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    qstash_token = os.getenv("QSTASH_TOKEN")
    if not qstash_token:
        return await process_telegram_payload(request, payload)

    client = QStashClient(qstash_token)
    base_url = str(request.url).split('/webhook')[0]
    target_url = f"{base_url}/process-task"
    telegram_id = str(request.state.telegram_id)

    try:
        client.publish_json(
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
"""
    }

    # Execute Build Process
    for filepath, content in files.items():
        dir_name = os.path.dirname(filepath)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
            
        final_content = content.replace("~TRIPLE_QUOTE~", '\"\"\"')
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(final_content)
        print(f"  [+] Created: {filepath}")

    print("\n[SUCCESS] PocketMunim Enterprise Phase 13 workspace generated successfully!")
    print("Next Steps:")
    print("  1. Configure your `.env.template` values and rename to `.env` (if testing locally).")
    print("  2. Apply the SQL migrations in `app/dao/migrations/` to your Supabase database.")
    print("  3. Deploy to Vercel and set your environment variables in the Vercel Dashboard.")

if __name__ == "__main__":
    create_workspace()