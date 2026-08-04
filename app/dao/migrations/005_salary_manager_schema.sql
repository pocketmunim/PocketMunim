-- PocketMunim Enterprise Schema - Phase 6 Salary Manager

-- 1. Bank Holidays Ledger
CREATE TABLE bank_holidays (
    holiday_date DATE PRIMARY KEY,
    description VARCHAR(100) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE
);

-- 2. Salary Configuration Master
CREATE TABLE salaries (
    salary_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    financial_year INTEGER NOT NULL,
    default_monthly_amount NUMERIC(15, 2) NOT NULL,
    expected_day_of_month INTEGER NOT NULL CHECK (expected_day_of_month BETWEEN 1 AND 31),
    monthly_overrides JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, financial_year)
);

-- 3. Row-Level Security
ALTER TABLE salaries ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Salary Tenant Isolation" ON salaries
    FOR ALL USING (user_id = (SELECT user_id FROM users WHERE telegram_id = current_setting('request.jwt.claims')::json->>'telegram_id'));
