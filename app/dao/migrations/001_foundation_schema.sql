-- PocketMunim Enterprise Schema - Phase 2 Foundation
-- Enforces Multi-Tenant RLS & 1-Month Purge Policy

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id VARCHAR(255) UNIQUE NOT NULL,
    role VARCHAR(50) DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE transactions (
    txn_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    amount NUMERIC(15, 2) NOT NULL,
    txn_type VARCHAR(50) NOT NULL,
    description TEXT,
    date TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    soft_deleted BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS intent VARCHAR(20);
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS category VARCHAR(50);
ALTER TABLE transactions DISABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Tenant Isolation Policy" ON transactions
    FOR ALL
    USING (user_id = (SELECT user_id FROM users WHERE telegram_id = current_setting('request.jwt.claims')::json->>'telegram_id'));

CREATE OR REPLACE FUNCTION purge_expired_records()
RETURNS void AS $$
BEGIN
    DELETE FROM transactions 
    WHERE soft_deleted = TRUE 
    AND deleted_at < NOW() - INTERVAL '1 month';
END;
$$ LANGUAGE plpgsql;
