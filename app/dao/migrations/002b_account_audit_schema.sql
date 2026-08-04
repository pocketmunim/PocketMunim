-- PocketMunim Enterprise Schema - Phase 3 Account Audit
CREATE TABLE account_audit_log (
    audit_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    operation VARCHAR(50) NOT NULL CHECK (operation IN ('ACCOUNT_CREATION', 'EXPENSE', 'INCOME', 'TRANSFER_OUT', 'TRANSFER_IN', 'BALANCE_ADJUSTMENT')),
    old_balance NUMERIC(15, 2) NOT NULL,
    new_balance NUMERIC(15, 2) NOT NULL,
    client_transaction_id UUID, -- Links to the transactions table
    request_source VARCHAR(50) DEFAULT 'TELEGRAM_BOT',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE account_audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Audit Tenant Isolation" ON account_audit_log
    FOR ALL USING (user_id = (SELECT user_id FROM users WHERE telegram_id = current_setting('request.jwt.claims')::json->>'telegram_id'));