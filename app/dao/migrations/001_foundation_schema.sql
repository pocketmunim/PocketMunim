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
