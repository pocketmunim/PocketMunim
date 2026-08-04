-- FROZEN: PocketMunim Enterprise Schema - Phase 3 Account Manager

CREATE TABLE accounts (
    account_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    account_name VARCHAR(100) NOT NULL,
    -- UPDATED: Added CREDIT_CARD and INVESTMENT per Founder directive
    account_type VARCHAR(50) NOT NULL CHECK (account_type IN ('BANK', 'CASH', 'WALLET', 'CREDIT_CARD', 'INVESTMENT')),
    current_balance NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, account_name)
);

ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Accounts Tenant Isolation" ON accounts
    FOR ALL USING (user_id = (SELECT user_id FROM users WHERE telegram_id = current_setting('request.jwt.claims')::json->>'telegram_id'));
