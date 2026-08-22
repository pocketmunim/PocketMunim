-- ==============================================================================
-- ISHITA FINANCIAL INTELLIGENCE SYSTEM (IFIS) - DATABASE VAULT SCHEMA
-- Version: 2.1.0 (Production Master)
-- ==============================================================================

-- 0. Core Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==============================================================================
-- 1. Identity & Node Registry (No Salary Columns)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY,
    telegram_id VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    currency VARCHAR(10) DEFAULT 'INR',
    security_strikes INTEGER DEFAULT 0,
    role VARCHAR(50) DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ==============================================================================
-- 2. Liquidity Vaults / Accounts
-- ==============================================================================
CREATE TABLE IF NOT EXISTS accounts (
    account_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    account_name VARCHAR(100) NOT NULL,
    balance NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ==============================================================================
-- 3. Account Logs (Immutable Audit Trail)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS account_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES accounts(account_id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL, -- e.g., 'GENESIS_INITIALIZATION', 'SALARY_HISTORICAL_CREDIT', 'SALARY_OVERRIDE_ADJUSTMENT', 'SALARY_PAST_SETTLEMENT', 'QSTASH_AUTO_SALARY_CREDIT'
    amount NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ==============================================================================
-- 4. Annual Salary Contracts Matrix
-- ==============================================================================
CREATE TABLE IF NOT EXISTS salaries (
    salary_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES accounts(account_id) ON DELETE SET NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    base_amount NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    actual_amount NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    payout_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED', -- 'SCHEDULED', 'PAID', 'SETTLED'
    paid_at TIMESTAMPTZ NULL,
    is_custom_override BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_user_salary_month UNIQUE(user_id, year, month)
);

-- ==============================================================================
-- 5. Transactions Ledger (Realized & Credited Events Only)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES accounts(account_id) ON DELETE CASCADE,
    salary_id UUID REFERENCES salaries(salary_id) ON DELETE SET NULL,
    type VARCHAR(20) NOT NULL, -- 'INCOME', 'EXPENSE', 'TRANSFER', 'SALARY'
    category VARCHAR(50) DEFAULT 'Salary',
    amount NUMERIC(14, 2) NOT NULL,
    transaction_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'CREDITED', -- Realized entries only
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ==============================================================================
-- 6. Zero-Trust Security Nonces (Anti-Replay Protection)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS security_nonces (
    nonce VARCHAR(64) PRIMARY KEY,
    device_uuid VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- ==============================================================================
-- 7. High-Performance Query Indexes
-- ==============================================================================
CREATE INDEX IF NOT EXISTS idx_users_telegram ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_account_logs_user ON account_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_account_logs_account ON account_logs(account_id);
CREATE INDEX IF NOT EXISTS idx_account_logs_created ON account_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_salaries_user_yr ON salaries(user_id, year);
CREATE INDEX IF NOT EXISTS idx_salaries_cron_payout ON salaries(status, payout_date);
CREATE INDEX IF NOT EXISTS idx_tx_user_date ON transactions(user_id, transaction_date);
CREATE INDEX IF NOT EXISTS idx_tx_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_nonce_lookup ON security_nonces(nonce);

-- ==============================================================================
-- 8. Automated Nonce Pruning Trigger (Memory Management)
-- ==============================================================================
CREATE OR REPLACE FUNCTION clean_expired_nonces()
RETURNS trigger AS $$
BEGIN
  DELETE FROM security_nonces WHERE created_at < NOW() - INTERVAL '5 minutes';
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trigger_clean_nonces
AFTER INSERT ON security_nonces
EXECUTE PROCEDURE clean_expired_nonces();