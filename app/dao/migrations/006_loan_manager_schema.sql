-- PocketMunim Enterprise Schema - Phase 7 Loan Manager

CREATE TABLE loans (
    loan_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    lender_name VARCHAR(100) NOT NULL,
    principal_amount NUMERIC(15, 2) NOT NULL,
    annual_interest_rate NUMERIC(5, 2) NOT NULL,
    tenure_months INTEGER NOT NULL,
    start_date DATE NOT NULL,
    is_imported_schedule BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE emi_schedules (
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

CREATE TABLE loan_prepayments (
    prepayment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    loan_id UUID NOT NULL REFERENCES loans(loan_id) ON DELETE CASCADE,
    client_transaction_id UUID NOT NULL,
    prepayment_date DATE NOT NULL,
    prepayment_amount NUMERIC(15, 2) NOT NULL,
    user_selected_mode VARCHAR(20) NOT NULL CHECK (user_selected_mode IN ('REDUCE_EMI', 'REDUCE_TENURE')),
    previous_emi NUMERIC(15, 2) NOT NULL,
    new_emi NUMERIC(15, 2) NOT NULL,
    previous_tenure_remaining INTEGER NOT NULL,
    new_tenure_remaining INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE loans ENABLE ROW LEVEL SECURITY;
ALTER TABLE emi_schedules ENABLE ROW LEVEL SECURITY;
ALTER TABLE loan_prepayments ENABLE ROW LEVEL SECURITY;
