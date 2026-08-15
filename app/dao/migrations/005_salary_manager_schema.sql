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
