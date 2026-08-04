-- PocketMunim Enterprise Schema - Phase 8 Financial Intelligence

CREATE TABLE budgets (
    budget_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    category VARCHAR(50) NOT NULL,
    subcategory VARCHAR(50), 
    monthly_limit NUMERIC(15, 2) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE (user_id, category, subcategory)
);

CREATE TABLE report_exports (
    export_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    export_type VARCHAR(20) NOT NULL CHECK (export_type IN ('HTML_LINK', 'PDF', 'EXCEL')),
    secure_token VARCHAR(255),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE budgets ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_exports ENABLE ROW LEVEL SECURITY;
