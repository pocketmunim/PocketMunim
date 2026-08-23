-- ==============================================================================
-- ISHITA FINANCIAL INTELLIGENCE SYSTEM (IFIS) - DATABASE VAULT SCHEMA
-- Version: 2.2.0 (Enterprise Production Master)
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Identity & Node Registry
CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_id VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    currency VARCHAR(10) DEFAULT 'INR',
    security_strikes INTEGER DEFAULT 0,
    role VARCHAR(50) DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 2. Liquidity Vaults / Accounts
CREATE TABLE IF NOT EXISTS accounts (
    account_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    account_name VARCHAR(100) NOT NULL,
    balance NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    is_default BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. Account Logs (Immutable Audit Trail)
CREATE TABLE IF NOT EXISTS account_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES accounts(account_id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    amount NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 4. Annual Salary Contracts Matrix
CREATE TABLE IF NOT EXISTS salaries (
    salary_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES accounts(account_id) ON DELETE SET NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    base_amount NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    actual_amount NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    payout_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED',
    paid_at TIMESTAMPTZ NULL,
    is_custom_override BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_user_salary_month UNIQUE(user_id, year, month)
);

-- 5. Loans Management Table (Fixed Missing DDL)
CREATE TABLE IF NOT EXISTS loans (
    loan_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES accounts(account_id) ON DELETE SET NULL,
    loan_name VARCHAR(150) NOT NULL,
    loan_type VARCHAR(20) NOT NULL DEFAULT 'BORROWED', -- 'BORROWED', 'LENT'
    counterparty VARCHAR(150) NOT NULL,
    disbursement_date DATE NOT NULL,
    first_emi_date DATE NULL,
    original_principal NUMERIC(14, 2) NOT NULL,
    pending_principal NUMERIC(14, 2) NOT NULL,
    annual_interest_rate NUMERIC(6, 2) DEFAULT 0.00,
    original_tenure_months INTEGER DEFAULT 0,
    pending_tenure_months INTEGER DEFAULT 0,
    monthly_emi NUMERIC(14, 2) DEFAULT 0.00,
    total_interest_payable NUMERIC(14, 2) DEFAULT 0.00,
    principal_paid NUMERIC(14, 2) DEFAULT 0.00,
    interest_paid NUMERIC(14, 2) DEFAULT 0.00,
    next_emi_date DATE NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE', -- 'ACTIVE', 'CLOSED'
    is_flexible BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 6. Loan Repayments Schedule
CREATE TABLE IF NOT EXISTS loan_repayments (
    repayment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    loan_id UUID REFERENCES loans(loan_id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES accounts(account_id) ON DELETE SET NULL,
    installment_number INTEGER NOT NULL,
    due_date DATE NOT NULL,
    emi_amount NUMERIC(14, 2) NOT NULL,
    principal_component NUMERIC(14, 2) NOT NULL,
    interest_component NUMERIC(14, 2) NOT NULL,
    remaining_principal_after NUMERIC(14, 2) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED', -- 'SCHEDULED', 'PAID'
    paid_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 7. Loan Partial Repayments (Ad-hoc Ledger)
CREATE TABLE IF NOT EXISTS loan_partial_repayments (
    partial_repayment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    loan_id UUID REFERENCES loans(loan_id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES accounts(account_id) ON DELETE SET NULL,
    amount NUMERIC(14, 2) NOT NULL,
    payment_date DATE NOT NULL,
    note TEXT,
    remaining_balance_after NUMERIC(14, 2) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 8. Transactions Ledger (Realized Events)
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES accounts(account_id) ON DELETE CASCADE,
    related_account_id UUID REFERENCES accounts(account_id) ON DELETE SET NULL,
    account_name VARCHAR(100),
    related_account_name VARCHAR(100),
    salary_id UUID REFERENCES salaries(salary_id) ON DELETE SET NULL,
    type VARCHAR(20) NOT NULL,
    category VARCHAR(50) DEFAULT 'General',
    amount NUMERIC(14, 2) NOT NULL,
    transaction_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'CREDITED',
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 9. Zero-Trust Security Nonces
CREATE TABLE IF NOT EXISTS security_nonces (
    nonce VARCHAR(64) PRIMARY KEY,
    device_uuid VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 10. Performance Indexes
CREATE INDEX IF NOT EXISTS idx_users_telegram ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id);
CREATE INDEX IF NOT EXISTS idx_loans_user_status ON loans(user_id, status);
CREATE INDEX IF NOT EXISTS idx_repayments_loan ON loan_repayments(loan_id, status, due_date);
CREATE INDEX IF NOT EXISTS idx_tx_user_date ON transactions(user_id, transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_nonce_lookup ON security_nonces(nonce);

-- 11. Atomic Vault Transfer RPC (Eliminates FIN-01)
CREATE OR REPLACE FUNCTION transfer_vault_funds(
    p_user_id UUID,
    p_src_account_id UUID,
    p_dest_account_id UUID,
    p_amount NUMERIC(14, 2)
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_src_bal NUMERIC(14, 2);
    v_dest_bal NUMERIC(14, 2);
    v_src_name VARCHAR(100);
    v_dest_name VARCHAR(100);
    v_new_src_bal NUMERIC(14, 2);
    v_new_dest_bal NUMERIC(14, 2);
    v_today DATE := CURRENT_DATE;
BEGIN
    IF p_src_account_id = p_dest_account_id THEN
        RAISE EXCEPTION 'Source and destination accounts must be distinct vaults.';
    END IF;

    IF p_amount <= 0 THEN
        RAISE EXCEPTION 'Transfer amount must be strictly greater than 0.';
    END IF;

    -- Lock both account rows to prevent race conditions
    SELECT balance, account_name INTO v_src_bal, v_src_name
    FROM public.accounts
    WHERE account_id = p_src_account_id AND user_id = p_user_id AND is_active = TRUE
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Source vault not found or inactive.';
    END IF;

    IF v_src_bal < p_amount THEN
        RAISE EXCEPTION 'Insufficient funds in % (Available: %, Requested: %)', v_src_name, v_src_bal, p_amount;
    END IF;

    SELECT balance, account_name INTO v_dest_bal, v_dest_name
    FROM public.accounts
    WHERE account_id = p_dest_account_id AND user_id = p_user_id AND is_active = TRUE
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Destination vault not found or inactive.';
    END IF;

    v_new_src_bal := v_src_bal - p_amount;
    v_new_dest_bal := v_dest_bal + p_amount;

    UPDATE public.accounts SET balance = v_new_src_bal WHERE account_id = p_src_account_id;
    UPDATE public.accounts SET balance = v_new_dest_bal WHERE account_id = p_dest_account_id;

    INSERT INTO public.transactions (user_id, account_id, account_name, related_account_id, related_account_name, type, category, amount, transaction_date, status, description)
    VALUES (p_user_id, p_src_account_id, v_src_name, p_dest_account_id, v_dest_name, 'DEBIT', 'Vault Transfer', p_amount, v_today, 'DEBITED', 'Self Transfer: Debited from ' || v_src_name || ' -> ' || v_dest_name);

    INSERT INTO public.transactions (user_id, account_id, account_name, related_account_id, related_account_name, type, category, amount, transaction_date, status, description)
    VALUES (p_user_id, p_dest_account_id, v_dest_name, p_src_account_id, v_src_name, 'CREDIT', 'Vault Transfer', p_amount, v_today, 'CREDITED', 'Self Transfer: Credited to ' || v_dest_name || ' <- ' || v_src_name);

    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description)
    VALUES (p_user_id, p_src_account_id, 'VAULT_TRANSFER_OUT', -p_amount, 'Transferred out to ' || v_dest_name);

    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description)
    VALUES (p_user_id, p_dest_account_id, 'VAULT_TRANSFER_IN', p_amount, 'Received in from ' || v_src_name);

    RETURN jsonb_build_object(
        'status', 'SUCCESS',
        'message', 'Transferred funds successfully.',
        'source_vault', jsonb_build_object('account_id', p_src_account_id, 'account_name', v_src_name, 'balance', v_new_src_bal),
        'destination_vault', jsonb_build_object('account_id', p_dest_account_id, 'account_name', v_dest_name, 'balance', v_new_dest_bal)
    );
END;
$$;

-- 12. Row Level Security & Service Role Policies
ALTER TABLE public.accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.loans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.loan_repayments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.loan_partial_repayments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.account_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow Service Role on accounts" ON public.accounts FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow Service Role on transactions" ON public.transactions FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow Service Role on loans" ON public.loans FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow Service Role on loan_repayments" ON public.loan_repayments FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow Service Role on loan_partial_repayments" ON public.loan_partial_repayments FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY "Allow Service Role on account_logs" ON public.account_logs FOR ALL USING (auth.role() = 'service_role');

CREATE OR REPLACE FUNCTION transfer_vault_funds(
    p_user_id UUID,
    p_src_account_id UUID,
    p_dest_account_id UUID,
    p_amount NUMERIC(15, 2)
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_src_bal NUMERIC(15, 2);
    v_dest_bal NUMERIC(15, 2);
    v_src_name TEXT;
    v_dest_name TEXT;
    v_new_src_bal NUMERIC(15, 2);
    v_new_dest_bal NUMERIC(15, 2);
    v_today DATE := CURRENT_DATE;
BEGIN
    IF p_src_account_id = p_dest_account_id THEN
        RAISE EXCEPTION 'Source and destination accounts must be distinct.';
    END IF;

    IF p_amount <= 0 THEN
        RAISE EXCEPTION 'Transfer amount must be strictly greater than 0.';
    END IF;

    -- Lock both account rows to prevent race conditions
    SELECT balance, account_name INTO v_src_bal, v_src_name
    FROM public.accounts
    WHERE account_id = p_src_account_id AND user_id = p_user_id AND is_active = TRUE
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Source vault not found or inactive.';
    END IF;

    IF v_src_bal < p_amount THEN
        RAISE EXCEPTION 'Insufficient funds in % (Available: %, Requested: %)', v_src_name, v_src_bal, p_amount;
    END IF;

    SELECT balance, account_name INTO v_dest_bal, v_dest_name
    FROM public.accounts
    WHERE account_id = p_dest_account_id AND user_id = p_user_id AND is_active = TRUE
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Destination vault not found or inactive.';
    END IF;

    -- Compute atomic balances
    v_new_src_bal := v_src_bal - p_amount;
    v_new_dest_bal := v_dest_bal + p_amount;

    UPDATE public.accounts SET balance = v_new_src_bal WHERE account_id = p_src_account_id;
    UPDATE public.accounts SET balance = v_new_dest_bal WHERE account_id = p_dest_account_id;

    -- Insert double-entry ledger transactions
    INSERT INTO public.transactions (user_id, account_id, account_name, related_account_id, related_account_name, type, category, amount, transaction_date, status, description)
    VALUES (p_user_id, p_src_account_id, v_src_name, p_dest_account_id, v_dest_name, 'DEBIT', 'Vault Transfer', p_amount, v_today, 'DEBITED', 'Self Transfer: Debited from ' || v_src_name || ' -> ' || v_dest_name);

    INSERT INTO public.transactions (user_id, account_id, account_name, related_account_id, related_account_name, type, category, amount, transaction_date, status, description)
    VALUES (p_user_id, p_dest_account_id, v_dest_name, p_src_account_id, v_src_name, 'CREDIT', 'Vault Transfer', p_amount, v_today, 'CREDITED', 'Self Transfer: Credited to ' || v_dest_name || ' <- ' || v_src_name);

    -- Insert account event logs
    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description)
    VALUES (p_user_id, p_src_account_id, 'VAULT_TRANSFER_OUT', -p_amount, 'Transferred out to ' || v_dest_name);

    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description)
    VALUES (p_user_id, p_dest_account_id, 'VAULT_TRANSFER_IN', p_amount, 'Received in from ' || v_src_name);

    RETURN jsonb_build_object(
        'status', 'SUCCESS',
        'message', 'Transfer processed atomically.',
        'source_vault', jsonb_build_object('account_id', p_src_account_id, 'account_name', v_src_name, 'balance', v_new_src_bal),
        'destination_vault', jsonb_build_object('account_id', p_dest_account_id, 'account_name', v_dest_name, 'balance', v_new_dest_bal)
    );
END;
$$;


