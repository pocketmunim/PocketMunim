-- ==============================================================================
-- ISHITA FINANCIAL INTELLIGENCE SYSTEM (IFIS) - DATABASE VAULT SCHEMA
-- Version: 2.4.0 (Enterprise Production Master - Clean Slate Rebuild)
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==============================================================================
-- PART 1: COMPLETE TEARDOWN (DROP EXISTING ARTIFACTS TO PREVENT CONFLICTS)
-- ==============================================================================

-- 1.1 Drop all functions (RPCs) and triggers (accounting for all overloaded signatures)
DROP FUNCTION IF EXISTS public.transfer_vault_funds(UUID, UUID, UUID, NUMERIC) CASCADE;
DROP FUNCTION IF EXISTS public.transfer_vault_funds(UUID, UUID, UUID, NUMERIC(14, 2)) CASCADE;
DROP FUNCTION IF EXISTS public.transfer_vault_funds(UUID, UUID, UUID, NUMERIC(15, 2)) CASCADE;
DROP FUNCTION IF EXISTS public.register_loan_atomic(JSONB) CASCADE;
DROP FUNCTION IF EXISTS public.pay_loan_emi_atomic(JSONB) CASCADE;
DROP FUNCTION IF EXISTS public.settle_past_emis_atomic(JSONB) CASCADE;
DROP FUNCTION IF EXISTS public.repay_flexible_loan_atomic(JSONB) CASCADE;
DROP FUNCTION IF EXISTS public.clean_expired_nonces() CASCADE;

-- 1.2 Drop all tables (CASCADE automatically destroys attached RLS policies, indexes, and foreign keys)
DROP TABLE IF EXISTS public.account_logs CASCADE;
DROP TABLE IF EXISTS public.transactions CASCADE;
DROP TABLE IF EXISTS public.loan_partial_repayments CASCADE;
DROP TABLE IF EXISTS public.loan_repayments CASCADE;
DROP TABLE IF EXISTS public.loans CASCADE;
DROP TABLE IF EXISTS public.salaries CASCADE;
DROP TABLE IF EXISTS public.accounts CASCADE;
DROP TABLE IF EXISTS public.security_nonces CASCADE;
DROP TABLE IF EXISTS public.users CASCADE;


-- ==============================================================================
-- PART 2: TABLE DEFINITIONS
-- ==============================================================================

-- 1. Identity & Node Registry
CREATE TABLE public.users (
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
CREATE TABLE public.accounts (
    account_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_name VARCHAR(100) NOT NULL,
    balance NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    is_default BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. Account Logs (Immutable Audit Trail)
CREATE TABLE public.account_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    amount NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 4. Annual Salary Contracts Matrix
CREATE TABLE public.salaries (
    salary_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
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

-- 5. Loans Management Table
CREATE TABLE public.loans (
    loan_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
    loan_name VARCHAR(150) NOT NULL,
    loan_type VARCHAR(20) NOT NULL DEFAULT 'BORROWED',
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
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    is_flexible BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 6. Loan Repayments Schedule
CREATE TABLE public.loan_repayments (
    repayment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    loan_id UUID REFERENCES public.loans(loan_id) ON DELETE CASCADE,
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
    installment_number INTEGER NOT NULL,
    due_date DATE NOT NULL,
    emi_amount NUMERIC(14, 2) NOT NULL,
    principal_component NUMERIC(14, 2) NOT NULL,
    interest_component NUMERIC(14, 2) NOT NULL,
    remaining_principal_after NUMERIC(14, 2) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED',
    paid_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 7. Loan Partial Repayments (Ad-hoc Ledger)
CREATE TABLE public.loan_partial_repayments (
    partial_repayment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    loan_id UUID REFERENCES public.loans(loan_id) ON DELETE CASCADE,
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
    amount NUMERIC(14, 2) NOT NULL,
    payment_date DATE NOT NULL,
    note TEXT,
    remaining_balance_after NUMERIC(14, 2) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 8. Transactions Ledger (Realized Events)
CREATE TABLE public.transactions (
    transaction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE CASCADE,
    related_account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
    account_name VARCHAR(100),
    related_account_name VARCHAR(100),
    salary_id UUID REFERENCES public.salaries(salary_id) ON DELETE SET NULL,
    type VARCHAR(20) NOT NULL,
    category VARCHAR(50) DEFAULT 'General',
    amount NUMERIC(14, 2) NOT NULL,
    transaction_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'CREDITED',
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 9. Zero-Trust Security Nonces
CREATE TABLE public.security_nonces (
    nonce VARCHAR(64) PRIMARY KEY,
    device_uuid VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);


-- ==============================================================================
-- PART 3: PERFORMANCE INDEXES
-- ==============================================================================
CREATE INDEX idx_users_telegram ON public.users(telegram_id);
CREATE INDEX idx_accounts_user ON public.accounts(user_id);
CREATE INDEX idx_loans_user_status ON public.loans(user_id, status);
CREATE INDEX idx_repayments_loan ON public.loan_repayments(loan_id, status, due_date);
CREATE INDEX idx_tx_user_date ON public.transactions(user_id, transaction_date DESC);
CREATE INDEX idx_nonce_lookup ON public.security_nonces(nonce);


-- ==============================================================================
-- PART 4: MEMORY MANAGEMENT TRIGGERS
-- ==============================================================================
CREATE OR REPLACE FUNCTION clean_expired_nonces()
RETURNS trigger AS $$
BEGIN
  DELETE FROM public.security_nonces WHERE created_at < NOW() - INTERVAL '5 minutes';
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trigger_clean_nonces
AFTER INSERT ON public.security_nonces
FOR EACH STATEMENT EXECUTE PROCEDURE clean_expired_nonces();


-- ==============================================================================
-- PART 5: ROW LEVEL SECURITY & SERVICE POLICIES
-- ==============================================================================
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


-- ==============================================================================
-- PART 6: ATOMIC STORED PROCEDURES (ACID RPCs)
-- ==============================================================================

-- 6.1 RPC: Atomic Vault Transfers
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

-- 6.2 RPC: Atomic Loan Registration
CREATE OR REPLACE FUNCTION register_loan_atomic(payload JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_user_id UUID := (payload->>'user_id')::UUID;
    v_account_id UUID := (payload->>'account_id')::UUID;
    v_loan_name VARCHAR := payload->>'loan_name';
    v_loan_type VARCHAR := payload->>'loan_type';
    v_counterparty VARCHAR := payload->>'counterparty';
    v_disbursement_date DATE := (payload->>'disbursement_date')::DATE;
    v_first_emi_date DATE := (payload->>'first_emi_date')::DATE;
    v_principal NUMERIC(14,2) := (payload->>'original_principal')::NUMERIC(14,2);
    v_interest_rate NUMERIC(6,2) := (payload->>'annual_interest_rate')::NUMERIC(6,2);
    v_tenure INTEGER := (payload->>'original_tenure_months')::INTEGER;
    v_monthly_emi NUMERIC(14,2) := (payload->>'monthly_emi')::NUMERIC(14,2);
    v_total_interest NUMERIC(14,2) := (payload->>'total_interest_payable')::NUMERIC(14,2);
    v_is_flexible BOOLEAN := (payload->>'is_flexible')::BOOLEAN;
    v_schedule JSONB := payload->'schedule';

    v_acc_bal NUMERIC(14,2);
    v_acc_name VARCHAR(100);
    v_new_bal NUMERIC(14,2);
    v_loan_id UUID;
    v_tx_type VARCHAR(20);
    v_status_label VARCHAR(20);
    v_sched_item JSONB;
BEGIN
    -- Deduplication Guard
    IF EXISTS (SELECT 1 FROM public.loans WHERE user_id = v_user_id AND loan_name ILIKE v_loan_name) THEN
        RAISE EXCEPTION 'A loan titled ''%'' already exists. Please use a unique title.', v_loan_name;
    END IF;

    -- Fallback to Default Vault if none provided
    IF v_account_id IS NULL THEN
        SELECT account_id INTO v_account_id FROM public.accounts WHERE user_id = v_user_id AND is_default = TRUE AND is_active = TRUE LIMIT 1;
        IF v_account_id IS NULL THEN
            SELECT account_id INTO v_account_id FROM public.accounts WHERE user_id = v_user_id AND is_active = TRUE LIMIT 1;
        END IF;
    END IF;

    IF v_account_id IS NULL THEN RAISE EXCEPTION 'No active account vault found for loan disbursement.'; END IF;

    -- Lock Account
    SELECT balance, account_name INTO v_acc_bal, v_acc_name
    FROM public.accounts WHERE account_id = v_account_id AND user_id = v_user_id AND is_active = TRUE FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Account vault not found or inactive.'; END IF;

    -- Solvency Check
    IF v_loan_type = 'LENT' AND v_acc_bal < v_principal THEN
        RAISE EXCEPTION 'Insufficient balance in % to lend. Available: %', v_acc_name, v_acc_bal;
    END IF;

    -- Insert Loan Contract
    INSERT INTO public.loans (user_id, account_id, loan_name, loan_type, counterparty, disbursement_date, first_emi_date, original_principal, pending_principal, annual_interest_rate, original_tenure_months, pending_tenure_months, monthly_emi, total_interest_payable, principal_paid, interest_paid, next_emi_date, status, is_flexible)
    VALUES (v_user_id, v_account_id, v_loan_name, v_loan_type, v_counterparty, v_disbursement_date, v_first_emi_date, v_principal, v_principal, v_interest_rate, v_tenure, v_tenure, v_monthly_emi, v_total_interest, 0.00, 0.00, v_first_emi_date, 'ACTIVE', v_is_flexible)
    RETURNING loan_id INTO v_loan_id;

    -- Insert Amortization Schedule
    IF NOT v_is_flexible AND jsonb_array_length(v_schedule) > 0 THEN
        FOR v_sched_item IN SELECT * FROM jsonb_array_elements(v_schedule)
        LOOP
            INSERT INTO public.loan_repayments (loan_id, user_id, account_id, installment_number, due_date, emi_amount, principal_component, interest_component, remaining_principal_after, status)
            VALUES (v_loan_id, v_user_id, v_account_id, (v_sched_item->>'installment_number')::INT, (v_sched_item->>'due_date')::DATE, (v_sched_item->>'emi_amount')::NUMERIC(14,2), (v_sched_item->>'principal_component')::NUMERIC(14,2), (v_sched_item->>'interest_component')::NUMERIC(14,2), (v_sched_item->>'remaining_principal_after')::NUMERIC(14,2), 'SCHEDULED');
        END LOOP;
    END IF;

    -- Update Liquidity Vault
    v_tx_type := CASE WHEN v_loan_type = 'BORROWED' THEN 'CREDIT' ELSE 'DEBIT' END;
    v_status_label := CASE WHEN v_tx_type = 'CREDIT' THEN 'CREDITED' ELSE 'DEBITED' END;
    v_new_bal := CASE WHEN v_tx_type = 'CREDIT' THEN v_acc_bal + v_principal ELSE v_acc_bal - v_principal END;

    UPDATE public.accounts SET balance = v_new_bal WHERE account_id = v_account_id;

    -- Insert Double-Entry Transactions
    INSERT INTO public.transactions (user_id, account_id, account_name, type, category, amount, transaction_date, status, description)
    VALUES (v_user_id, v_account_id, v_acc_name, v_tx_type, 'Debt & EMI', v_principal, v_disbursement_date, v_status_label, 'Loan Disbursement: ' || v_loan_name || ' (' || v_counterparty || ')');

    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description)
    VALUES (v_user_id, v_account_id, 'LOAN_DISBURSEMENT_' || v_tx_type, CASE WHEN v_tx_type = 'CREDIT' THEN v_principal ELSE -v_principal END, 'Loan disbursement processed for ' || v_loan_name);

    RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'Loan registered successfully.', 'loan_id', v_loan_id, 'monthly_emi', v_monthly_emi);
END;
$$;

-- 6.3 RPC: Atomic EMI Payment Processing
CREATE OR REPLACE FUNCTION pay_loan_emi_atomic(payload JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_user_id UUID := (payload->>'user_id')::UUID;
    v_loan_id UUID := (payload->>'loan_id')::UUID;
    v_target_aid UUID := (payload->>'account_id')::UUID;
    v_is_advance BOOLEAN := COALESCE((payload->>'is_advance_confirmed')::BOOLEAN, FALSE);

    v_loan RECORD;
    v_acc RECORD;
    v_next_emi RECORD;
    v_cur_paid BOOLEAN;
    v_today DATE := CURRENT_DATE;
    v_new_bal NUMERIC(14,2);
    v_tx_type VARCHAR(20);
    v_status_label VARCHAR(20);
    v_new_pend_prin NUMERIC(14,2);
    v_new_pend_tenure INTEGER;
    v_loan_status VARCHAR(20);
    v_new_next_date DATE;
BEGIN
    -- Lock Loan
    SELECT * INTO v_loan FROM public.loans WHERE loan_id = v_loan_id AND user_id = v_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Loan contract not found.'; END IF;
    IF v_loan.status != 'ACTIVE' THEN RAISE EXCEPTION 'This loan is already CLOSED.'; END IF;

    IF v_target_aid IS NULL THEN v_target_aid := v_loan.account_id; END IF;
    SELECT * INTO v_acc FROM public.accounts WHERE account_id = v_target_aid AND user_id = v_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'No active liquidity vault available for EMI deduction.'; END IF;

    -- Lock Next Scheduled EMI
    SELECT * INTO v_next_emi FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'SCHEDULED' ORDER BY installment_number ASC LIMIT 1 FOR UPDATE;
    IF NOT FOUND THEN
        UPDATE public.loans SET status = 'CLOSED', pending_principal = 0.00 WHERE loan_id = v_loan_id;
        RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'All EMIs for this loan have been completed.');
    END IF;

    -- Duplicate EMI Guard
    IF NOT v_is_advance THEN
        SELECT EXISTS (
            SELECT 1 FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'PAID'
            AND due_date >= date_trunc('month', v_today)::DATE AND due_date <= (date_trunc('month', v_today) + interval '1 month - 1 day')::DATE
        ) INTO v_cur_paid;
        IF v_cur_paid THEN RAISE EXCEPTION 'DUPLICATE_CURRENT_MONTH'; END IF;
    END IF;

    IF v_loan.loan_type = 'BORROWED' AND v_acc.balance < v_next_emi.emi_amount THEN
        RAISE EXCEPTION 'Insufficient balance in %. Required: %', v_acc.account_name, v_next_emi.emi_amount;
    END IF;

    IF v_loan.loan_type = 'BORROWED' THEN
        v_new_bal := v_acc.balance - v_next_emi.emi_amount; v_tx_type := 'DEBIT'; v_status_label := 'DEBITED';
    ELSE
        v_new_bal := v_acc.balance + v_next_emi.emi_amount; v_tx_type := 'CREDIT'; v_status_label := 'CREDITED';
    END IF;

    v_new_pend_prin := v_next_emi.remaining_principal_after;
    v_new_pend_tenure := GREATEST(0, v_loan.pending_tenure_months - 1);
    IF v_new_pend_prin <= 0 OR v_new_pend_tenure = 0 THEN v_loan_status := 'CLOSED'; ELSE v_loan_status := 'ACTIVE'; END IF;

    UPDATE public.accounts SET balance = v_new_bal WHERE account_id = v_target_aid;
    UPDATE public.loan_repayments SET status = 'PAID', paid_at = NOW(), account_id = v_target_aid WHERE repayment_id = v_next_emi.repayment_id;

    SELECT due_date INTO v_new_next_date FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'SCHEDULED' ORDER BY installment_number ASC LIMIT 1;
    IF v_new_next_date IS NULL THEN v_new_next_date := v_today; END IF;

    UPDATE public.loans SET pending_principal = v_new_pend_prin, pending_tenure_months = v_new_pend_tenure, principal_paid = v_loan.principal_paid + v_next_emi.principal_component, interest_paid = v_loan.interest_paid + v_next_emi.interest_component, next_emi_date = v_new_next_date, status = v_loan_status WHERE loan_id = v_loan_id;

    INSERT INTO public.transactions (user_id, account_id, account_name, type, category, amount, transaction_date, status, description)
    VALUES (v_user_id, v_target_aid, v_acc.account_name, v_tx_type, 'Debt & EMI', v_next_emi.emi_amount, v_today, v_status_label, 'Loan EMI #' || v_next_emi.installment_number || ' (' || v_loan.loan_name || ')');

    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description)
    VALUES (v_user_id, v_target_aid, 'LOAN_EMI_' || v_tx_type, CASE WHEN v_tx_type = 'DEBIT' THEN -v_next_emi.emi_amount ELSE v_next_emi.emi_amount END, 'EMI #' || v_next_emi.installment_number || ' cleared.');

    RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'Installment #' || v_next_emi.installment_number || ' settled.', 'new_pending_principal', v_new_pend_prin, 'loan_status', v_loan_status, 'next_due_date', v_new_next_date);
END;
$$;

-- 6.4 RPC: Atomic Batch Settle Past EMIs
CREATE OR REPLACE FUNCTION settle_past_emis_atomic(payload JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_user_id UUID := (payload->>'user_id')::UUID;
    v_loan_id UUID := (payload->>'loan_id')::UUID;
    v_target_aid UUID := (payload->>'account_id')::UUID;

    v_loan RECORD;
    v_acc RECORD;
    v_today DATE := CURRENT_DATE;
    v_total NUMERIC(14,2); v_prin NUMERIC(14,2); v_int NUMERIC(14,2); v_count INTEGER;
    v_last_prin NUMERIC(14,2); v_new_bal NUMERIC(14,2);
    v_tx_type VARCHAR(20); v_status VARCHAR(20); v_next_date DATE;
BEGIN
    SELECT * INTO v_loan FROM public.loans WHERE loan_id = v_loan_id AND user_id = v_user_id FOR UPDATE;
    IF v_target_aid IS NULL THEN v_target_aid := v_loan.account_id; END IF;
    SELECT * INTO v_acc FROM public.accounts WHERE account_id = v_target_aid AND user_id = v_user_id FOR UPDATE;

    SELECT COUNT(*), COALESCE(SUM(emi_amount),0), COALESCE(SUM(principal_component),0), COALESCE(SUM(interest_component),0)
    INTO v_count, v_total, v_prin, v_int FROM public.loan_repayments WHERE loan_id = v_loan_id AND due_date <= v_today AND status = 'SCHEDULED';

    IF v_count = 0 THEN RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'No pending past EMIs.'); END IF;

    SELECT remaining_principal_after INTO v_last_prin FROM public.loan_repayments WHERE loan_id = v_loan_id AND due_date <= v_today AND status = 'SCHEDULED' ORDER BY installment_number DESC LIMIT 1;

    IF v_loan.loan_type = 'BORROWED' AND v_acc.balance < v_total THEN RAISE EXCEPTION 'Insufficient balance to settle % EMIs.', v_count; END IF;

    IF v_loan.loan_type = 'BORROWED' THEN v_new_bal := v_acc.balance - v_total; v_tx_type := 'DEBIT'; ELSE v_new_bal := v_acc.balance + v_total; v_tx_type := 'CREDIT'; END IF;
    IF v_last_prin <= 0 OR (v_loan.pending_tenure_months - v_count) <= 0 THEN v_status := 'CLOSED'; ELSE v_status := 'ACTIVE'; END IF;

    UPDATE public.accounts SET balance = v_new_bal WHERE account_id = v_target_aid;
    UPDATE public.loan_repayments SET status = 'PAID', paid_at = NOW(), account_id = v_target_aid WHERE loan_id = v_loan_id AND due_date <= v_today AND status = 'SCHEDULED';

    SELECT due_date INTO v_next_date FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'SCHEDULED' ORDER BY installment_number ASC LIMIT 1;
    IF v_next_date IS NULL THEN v_next_date := v_today; END IF;

    UPDATE public.loans SET pending_principal = v_last_prin, pending_tenure_months = GREATEST(0, v_loan.pending_tenure_months - v_count), principal_paid = v_loan.principal_paid + v_prin, interest_paid = v_loan.interest_paid + v_int, next_emi_date = v_next_date, status = v_status WHERE loan_id = v_loan_id;

    INSERT INTO public.transactions (user_id, account_id, account_name, type, category, amount, transaction_date, status, description) VALUES (v_user_id, v_target_aid, v_acc.account_name, v_tx_type, 'Debt & EMI', v_total, v_today, CASE WHEN v_tx_type = 'DEBIT' THEN 'DEBITED' ELSE 'CREDITED' END, 'Batch Settlement (' || v_count || ' Past EMIs)');
    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description) VALUES (v_user_id, v_target_aid, 'BATCH_SETTLEMENT', CASE WHEN v_tx_type = 'DEBIT' THEN -v_total ELSE v_total END, 'Settled ' || v_count || ' historical EMIs.');

    RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'Successfully settled ' || v_count || ' past EMIs.', 'new_pending_principal', v_last_prin);
END;
$$;

-- 6.5 RPC: Atomic Flexible / Ad-Hoc Repayment
CREATE OR REPLACE FUNCTION repay_flexible_loan_atomic(payload JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_user_id UUID := (payload->>'user_id')::UUID;
    v_loan_id UUID := (payload->>'loan_id')::UUID;
    v_target_aid UUID := (payload->>'account_id')::UUID;
    v_amount NUMERIC(14,2) := (payload->>'amount')::NUMERIC(14,2);
    v_date DATE := (payload->>'payment_date')::DATE;
    v_note TEXT := payload->>'note';

    v_loan RECORD; v_acc RECORD; v_new_bal NUMERIC(14,2); v_new_pend NUMERIC(14,2); v_tx_type VARCHAR; v_status VARCHAR;
BEGIN
    SELECT * INTO v_loan FROM public.loans WHERE loan_id = v_loan_id AND user_id = v_user_id FOR UPDATE;
    IF v_loan.status != 'ACTIVE' THEN RAISE EXCEPTION 'This loan is already CLOSED.'; END IF;
    IF v_amount > v_loan.pending_principal THEN RAISE EXCEPTION 'Repayment exceeds outstanding balance.'; END IF;

    IF v_target_aid IS NULL THEN v_target_aid := v_loan.account_id; END IF;
    SELECT * INTO v_acc FROM public.accounts WHERE account_id = v_target_aid AND user_id = v_user_id FOR UPDATE;

    IF v_loan.loan_type = 'BORROWED' AND v_acc.balance < v_amount THEN RAISE EXCEPTION 'Insufficient balance.'; END IF;

    IF v_loan.loan_type = 'BORROWED' THEN v_new_bal := v_acc.balance - v_amount; v_tx_type := 'DEBIT'; ELSE v_new_bal := v_acc.balance + v_amount; v_tx_type := 'CREDIT'; END IF;
    v_new_pend := v_loan.pending_principal - v_amount;
    IF v_new_pend <= 0 THEN v_status := 'CLOSED'; ELSE v_status := 'ACTIVE'; END IF;

    UPDATE public.accounts SET balance = v_new_bal WHERE account_id = v_target_aid;
    UPDATE public.loans SET pending_principal = v_new_pend, principal_paid = v_loan.principal_paid + v_amount, status = v_status WHERE loan_id = v_loan_id;

    INSERT INTO public.loan_partial_repayments (loan_id, user_id, account_id, amount, payment_date, note, remaining_balance_after) VALUES (v_loan_id, v_user_id, v_target_aid, v_amount, v_date, COALESCE(v_note, 'Ad-hoc repayment'), v_new_pend);
    INSERT INTO public.transactions (user_id, account_id, account_name, type, category, amount, transaction_date, status, description) VALUES (v_user_id, v_target_aid, v_acc.account_name, v_tx_type, 'Debt & EMI', v_amount, v_date, CASE WHEN v_tx_type = 'DEBIT' THEN 'DEBITED' ELSE 'CREDITED' END, 'P2P Repayment: ' || v_loan.loan_name);
    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description) VALUES (v_user_id, v_target_aid, 'LOAN_PARTIAL_' || v_tx_type, CASE WHEN v_tx_type = 'DEBIT' THEN -v_amount ELSE v_amount END, 'Partial repayment logged.');

    RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'Logged repayment.', 'new_pending_principal', v_new_pend, 'loan_status', v_status);
END;
$$;-- ==============================================================================
-- ISHITA FINANCIAL INTELLIGENCE SYSTEM (IFIS) - DATABASE VAULT SCHEMA
-- Version: 2.4.0 (Enterprise Production Master - Clean Slate Rebuild)
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ==============================================================================
-- PART 1: COMPLETE TEARDOWN (DROP EXISTING ARTIFACTS TO PREVENT CONFLICTS)
-- ==============================================================================

-- 1.1 Drop all functions (RPCs) and triggers (accounting for all overloaded signatures)
DROP FUNCTION IF EXISTS public.transfer_vault_funds(UUID, UUID, UUID, NUMERIC) CASCADE;
DROP FUNCTION IF EXISTS public.transfer_vault_funds(UUID, UUID, UUID, NUMERIC(14, 2)) CASCADE;
DROP FUNCTION IF EXISTS public.transfer_vault_funds(UUID, UUID, UUID, NUMERIC(15, 2)) CASCADE;
DROP FUNCTION IF EXISTS public.register_loan_atomic(JSONB) CASCADE;
DROP FUNCTION IF EXISTS public.pay_loan_emi_atomic(JSONB) CASCADE;
DROP FUNCTION IF EXISTS public.settle_past_emis_atomic(JSONB) CASCADE;
DROP FUNCTION IF EXISTS public.repay_flexible_loan_atomic(JSONB) CASCADE;
DROP FUNCTION IF EXISTS public.clean_expired_nonces() CASCADE;

-- 1.2 Drop all tables (CASCADE automatically destroys attached RLS policies, indexes, and foreign keys)
DROP TABLE IF EXISTS public.account_logs CASCADE;
DROP TABLE IF EXISTS public.transactions CASCADE;
DROP TABLE IF EXISTS public.loan_partial_repayments CASCADE;
DROP TABLE IF EXISTS public.loan_repayments CASCADE;
DROP TABLE IF EXISTS public.loans CASCADE;
DROP TABLE IF EXISTS public.salaries CASCADE;
DROP TABLE IF EXISTS public.accounts CASCADE;
DROP TABLE IF EXISTS public.security_nonces CASCADE;
DROP TABLE IF EXISTS public.users CASCADE;


-- ==============================================================================
-- PART 2: TABLE DEFINITIONS
-- ==============================================================================

-- 1. Identity & Node Registry
CREATE TABLE public.users (
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
CREATE TABLE public.accounts (
    account_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_name VARCHAR(100) NOT NULL,
    balance NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    is_default BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. Account Logs (Immutable Audit Trail)
CREATE TABLE public.account_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    amount NUMERIC(14, 2) NOT NULL DEFAULT 0.00,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 4. Annual Salary Contracts Matrix
CREATE TABLE public.salaries (
    salary_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
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

-- 5. Loans Management Table
CREATE TABLE public.loans (
    loan_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
    loan_name VARCHAR(150) NOT NULL,
    loan_type VARCHAR(20) NOT NULL DEFAULT 'BORROWED',
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
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE',
    is_flexible BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 6. Loan Repayments Schedule
CREATE TABLE public.loan_repayments (
    repayment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    loan_id UUID REFERENCES public.loans(loan_id) ON DELETE CASCADE,
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
    installment_number INTEGER NOT NULL,
    due_date DATE NOT NULL,
    emi_amount NUMERIC(14, 2) NOT NULL,
    principal_component NUMERIC(14, 2) NOT NULL,
    interest_component NUMERIC(14, 2) NOT NULL,
    remaining_principal_after NUMERIC(14, 2) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED',
    paid_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 7. Loan Partial Repayments (Ad-hoc Ledger)
CREATE TABLE public.loan_partial_repayments (
    partial_repayment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    loan_id UUID REFERENCES public.loans(loan_id) ON DELETE CASCADE,
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
    amount NUMERIC(14, 2) NOT NULL,
    payment_date DATE NOT NULL,
    note TEXT,
    remaining_balance_after NUMERIC(14, 2) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 8. Transactions Ledger (Realized Events)
CREATE TABLE public.transactions (
    transaction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE CASCADE,
    related_account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
    account_name VARCHAR(100),
    related_account_name VARCHAR(100),
    salary_id UUID REFERENCES public.salaries(salary_id) ON DELETE SET NULL,
    type VARCHAR(20) NOT NULL,
    category VARCHAR(50) DEFAULT 'General',
    amount NUMERIC(14, 2) NOT NULL,
    transaction_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'CREDITED',
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 9. Zero-Trust Security Nonces
CREATE TABLE public.security_nonces (
    nonce VARCHAR(64) PRIMARY KEY,
    device_uuid VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);


-- ==============================================================================
-- PART 3: PERFORMANCE INDEXES
-- ==============================================================================
CREATE INDEX idx_users_telegram ON public.users(telegram_id);
CREATE INDEX idx_accounts_user ON public.accounts(user_id);
CREATE INDEX idx_loans_user_status ON public.loans(user_id, status);
CREATE INDEX idx_repayments_loan ON public.loan_repayments(loan_id, status, due_date);
CREATE INDEX idx_tx_user_date ON public.transactions(user_id, transaction_date DESC);
CREATE INDEX idx_nonce_lookup ON public.security_nonces(nonce);


-- ==============================================================================
-- PART 4: MEMORY MANAGEMENT TRIGGERS
-- ==============================================================================
CREATE OR REPLACE FUNCTION clean_expired_nonces()
RETURNS trigger AS $$
BEGIN
  DELETE FROM public.security_nonces WHERE created_at < NOW() - INTERVAL '5 minutes';
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER trigger_clean_nonces
AFTER INSERT ON public.security_nonces
FOR EACH STATEMENT EXECUTE PROCEDURE clean_expired_nonces();


-- ==============================================================================
-- PART 5: ROW LEVEL SECURITY & SERVICE POLICIES
-- ==============================================================================
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


-- ==============================================================================
-- PART 6: ATOMIC STORED PROCEDURES (ACID RPCs)
-- ==============================================================================

-- 6.1 RPC: Atomic Vault Transfers
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

-- 6.2 RPC: Atomic Loan Registration
CREATE OR REPLACE FUNCTION register_loan_atomic(payload JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_user_id UUID := (payload->>'user_id')::UUID;
    v_account_id UUID := (payload->>'account_id')::UUID;
    v_loan_name VARCHAR := payload->>'loan_name';
    v_loan_type VARCHAR := payload->>'loan_type';
    v_counterparty VARCHAR := payload->>'counterparty';
    v_disbursement_date DATE := (payload->>'disbursement_date')::DATE;
    v_first_emi_date DATE := (payload->>'first_emi_date')::DATE;
    v_principal NUMERIC(14,2) := (payload->>'original_principal')::NUMERIC(14,2);
    v_interest_rate NUMERIC(6,2) := (payload->>'annual_interest_rate')::NUMERIC(6,2);
    v_tenure INTEGER := (payload->>'original_tenure_months')::INTEGER;
    v_monthly_emi NUMERIC(14,2) := (payload->>'monthly_emi')::NUMERIC(14,2);
    v_total_interest NUMERIC(14,2) := (payload->>'total_interest_payable')::NUMERIC(14,2);
    v_is_flexible BOOLEAN := (payload->>'is_flexible')::BOOLEAN;
    v_schedule JSONB := payload->'schedule';

    v_acc_bal NUMERIC(14,2);
    v_acc_name VARCHAR(100);
    v_new_bal NUMERIC(14,2);
    v_loan_id UUID;
    v_tx_type VARCHAR(20);
    v_status_label VARCHAR(20);
    v_sched_item JSONB;
BEGIN
    -- Deduplication Guard
    IF EXISTS (SELECT 1 FROM public.loans WHERE user_id = v_user_id AND loan_name ILIKE v_loan_name) THEN
        RAISE EXCEPTION 'A loan titled ''%'' already exists. Please use a unique title.', v_loan_name;
    END IF;

    -- Fallback to Default Vault if none provided
    IF v_account_id IS NULL THEN
        SELECT account_id INTO v_account_id FROM public.accounts WHERE user_id = v_user_id AND is_default = TRUE AND is_active = TRUE LIMIT 1;
        IF v_account_id IS NULL THEN
            SELECT account_id INTO v_account_id FROM public.accounts WHERE user_id = v_user_id AND is_active = TRUE LIMIT 1;
        END IF;
    END IF;

    IF v_account_id IS NULL THEN RAISE EXCEPTION 'No active account vault found for loan disbursement.'; END IF;

    -- Lock Account
    SELECT balance, account_name INTO v_acc_bal, v_acc_name
    FROM public.accounts WHERE account_id = v_account_id AND user_id = v_user_id AND is_active = TRUE FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Account vault not found or inactive.'; END IF;

    -- Solvency Check
    IF v_loan_type = 'LENT' AND v_acc_bal < v_principal THEN
        RAISE EXCEPTION 'Insufficient balance in % to lend. Available: %', v_acc_name, v_acc_bal;
    END IF;

    -- Insert Loan Contract
    INSERT INTO public.loans (user_id, account_id, loan_name, loan_type, counterparty, disbursement_date, first_emi_date, original_principal, pending_principal, annual_interest_rate, original_tenure_months, pending_tenure_months, monthly_emi, total_interest_payable, principal_paid, interest_paid, next_emi_date, status, is_flexible)
    VALUES (v_user_id, v_account_id, v_loan_name, v_loan_type, v_counterparty, v_disbursement_date, v_first_emi_date, v_principal, v_principal, v_interest_rate, v_tenure, v_tenure, v_monthly_emi, v_total_interest, 0.00, 0.00, v_first_emi_date, 'ACTIVE', v_is_flexible)
    RETURNING loan_id INTO v_loan_id;

    -- Insert Amortization Schedule
    IF NOT v_is_flexible AND jsonb_array_length(v_schedule) > 0 THEN
        FOR v_sched_item IN SELECT * FROM jsonb_array_elements(v_schedule)
        LOOP
            INSERT INTO public.loan_repayments (loan_id, user_id, account_id, installment_number, due_date, emi_amount, principal_component, interest_component, remaining_principal_after, status)
            VALUES (v_loan_id, v_user_id, v_account_id, (v_sched_item->>'installment_number')::INT, (v_sched_item->>'due_date')::DATE, (v_sched_item->>'emi_amount')::NUMERIC(14,2), (v_sched_item->>'principal_component')::NUMERIC(14,2), (v_sched_item->>'interest_component')::NUMERIC(14,2), (v_sched_item->>'remaining_principal_after')::NUMERIC(14,2), 'SCHEDULED');
        END LOOP;
    END IF;

    -- Update Liquidity Vault
    v_tx_type := CASE WHEN v_loan_type = 'BORROWED' THEN 'CREDIT' ELSE 'DEBIT' END;
    v_status_label := CASE WHEN v_tx_type = 'CREDIT' THEN 'CREDITED' ELSE 'DEBITED' END;
    v_new_bal := CASE WHEN v_tx_type = 'CREDIT' THEN v_acc_bal + v_principal ELSE v_acc_bal - v_principal END;

    UPDATE public.accounts SET balance = v_new_bal WHERE account_id = v_account_id;

    -- Insert Double-Entry Transactions
    INSERT INTO public.transactions (user_id, account_id, account_name, type, category, amount, transaction_date, status, description)
    VALUES (v_user_id, v_account_id, v_acc_name, v_tx_type, 'Debt & EMI', v_principal, v_disbursement_date, v_status_label, 'Loan Disbursement: ' || v_loan_name || ' (' || v_counterparty || ')');

    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description)
    VALUES (v_user_id, v_account_id, 'LOAN_DISBURSEMENT_' || v_tx_type, CASE WHEN v_tx_type = 'CREDIT' THEN v_principal ELSE -v_principal END, 'Loan disbursement processed for ' || v_loan_name);

    RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'Loan registered successfully.', 'loan_id', v_loan_id, 'monthly_emi', v_monthly_emi);
END;
$$;

-- 6.3 RPC: Atomic EMI Payment Processing
CREATE OR REPLACE FUNCTION pay_loan_emi_atomic(payload JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_user_id UUID := (payload->>'user_id')::UUID;
    v_loan_id UUID := (payload->>'loan_id')::UUID;
    v_target_aid UUID := (payload->>'account_id')::UUID;
    v_is_advance BOOLEAN := COALESCE((payload->>'is_advance_confirmed')::BOOLEAN, FALSE);

    v_loan RECORD;
    v_acc RECORD;
    v_next_emi RECORD;
    v_cur_paid BOOLEAN;
    v_today DATE := CURRENT_DATE;
    v_new_bal NUMERIC(14,2);
    v_tx_type VARCHAR(20);
    v_status_label VARCHAR(20);
    v_new_pend_prin NUMERIC(14,2);
    v_new_pend_tenure INTEGER;
    v_loan_status VARCHAR(20);
    v_new_next_date DATE;
BEGIN
    -- Lock Loan
    SELECT * INTO v_loan FROM public.loans WHERE loan_id = v_loan_id AND user_id = v_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Loan contract not found.'; END IF;
    IF v_loan.status != 'ACTIVE' THEN RAISE EXCEPTION 'This loan is already CLOSED.'; END IF;

    IF v_target_aid IS NULL THEN v_target_aid := v_loan.account_id; END IF;
    SELECT * INTO v_acc FROM public.accounts WHERE account_id = v_target_aid AND user_id = v_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'No active liquidity vault available for EMI deduction.'; END IF;

    -- Lock Next Scheduled EMI
    SELECT * INTO v_next_emi FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'SCHEDULED' ORDER BY installment_number ASC LIMIT 1 FOR UPDATE;
    IF NOT FOUND THEN
        UPDATE public.loans SET status = 'CLOSED', pending_principal = 0.00 WHERE loan_id = v_loan_id;
        RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'All EMIs for this loan have been completed.');
    END IF;

    -- Duplicate EMI Guard
    IF NOT v_is_advance THEN
        SELECT EXISTS (
            SELECT 1 FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'PAID'
            AND due_date >= date_trunc('month', v_today)::DATE AND due_date <= (date_trunc('month', v_today) + interval '1 month - 1 day')::DATE
        ) INTO v_cur_paid;
        IF v_cur_paid THEN RAISE EXCEPTION 'DUPLICATE_CURRENT_MONTH'; END IF;
    END IF;

    IF v_loan.loan_type = 'BORROWED' AND v_acc.balance < v_next_emi.emi_amount THEN
        RAISE EXCEPTION 'Insufficient balance in %. Required: %', v_acc.account_name, v_next_emi.emi_amount;
    END IF;

    IF v_loan.loan_type = 'BORROWED' THEN
        v_new_bal := v_acc.balance - v_next_emi.emi_amount; v_tx_type := 'DEBIT'; v_status_label := 'DEBITED';
    ELSE
        v_new_bal := v_acc.balance + v_next_emi.emi_amount; v_tx_type := 'CREDIT'; v_status_label := 'CREDITED';
    END IF;

    v_new_pend_prin := v_next_emi.remaining_principal_after;
    v_new_pend_tenure := GREATEST(0, v_loan.pending_tenure_months - 1);
    IF v_new_pend_prin <= 0 OR v_new_pend_tenure = 0 THEN v_loan_status := 'CLOSED'; ELSE v_loan_status := 'ACTIVE'; END IF;

    UPDATE public.accounts SET balance = v_new_bal WHERE account_id = v_target_aid;
    UPDATE public.loan_repayments SET status = 'PAID', paid_at = NOW(), account_id = v_target_aid WHERE repayment_id = v_next_emi.repayment_id;

    SELECT due_date INTO v_new_next_date FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'SCHEDULED' ORDER BY installment_number ASC LIMIT 1;
    IF v_new_next_date IS NULL THEN v_new_next_date := v_today; END IF;

    UPDATE public.loans SET pending_principal = v_new_pend_prin, pending_tenure_months = v_new_pend_tenure, principal_paid = v_loan.principal_paid + v_next_emi.principal_component, interest_paid = v_loan.interest_paid + v_next_emi.interest_component, next_emi_date = v_new_next_date, status = v_loan_status WHERE loan_id = v_loan_id;

    INSERT INTO public.transactions (user_id, account_id, account_name, type, category, amount, transaction_date, status, description)
    VALUES (v_user_id, v_target_aid, v_acc.account_name, v_tx_type, 'Debt & EMI', v_next_emi.emi_amount, v_today, v_status_label, 'Loan EMI #' || v_next_emi.installment_number || ' (' || v_loan.loan_name || ')');

    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description)
    VALUES (v_user_id, v_target_aid, 'LOAN_EMI_' || v_tx_type, CASE WHEN v_tx_type = 'DEBIT' THEN -v_next_emi.emi_amount ELSE v_next_emi.emi_amount END, 'EMI #' || v_next_emi.installment_number || ' cleared.');

    RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'Installment #' || v_next_emi.installment_number || ' settled.', 'new_pending_principal', v_new_pend_prin, 'loan_status', v_loan_status, 'next_due_date', v_new_next_date);
END;
$$;

-- 6.4 RPC: Atomic Batch Settle Past EMIs
CREATE OR REPLACE FUNCTION settle_past_emis_atomic(payload JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_user_id UUID := (payload->>'user_id')::UUID;
    v_loan_id UUID := (payload->>'loan_id')::UUID;
    v_target_aid UUID := (payload->>'account_id')::UUID;

    v_loan RECORD;
    v_acc RECORD;
    v_today DATE := CURRENT_DATE;
    v_total NUMERIC(14,2); v_prin NUMERIC(14,2); v_int NUMERIC(14,2); v_count INTEGER;
    v_last_prin NUMERIC(14,2); v_new_bal NUMERIC(14,2);
    v_tx_type VARCHAR(20); v_status VARCHAR(20); v_next_date DATE;
BEGIN
    SELECT * INTO v_loan FROM public.loans WHERE loan_id = v_loan_id AND user_id = v_user_id FOR UPDATE;
    IF v_target_aid IS NULL THEN v_target_aid := v_loan.account_id; END IF;
    SELECT * INTO v_acc FROM public.accounts WHERE account_id = v_target_aid AND user_id = v_user_id FOR UPDATE;

    SELECT COUNT(*), COALESCE(SUM(emi_amount),0), COALESCE(SUM(principal_component),0), COALESCE(SUM(interest_component),0)
    INTO v_count, v_total, v_prin, v_int FROM public.loan_repayments WHERE loan_id = v_loan_id AND due_date <= v_today AND status = 'SCHEDULED';

    IF v_count = 0 THEN RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'No pending past EMIs.'); END IF;

    SELECT remaining_principal_after INTO v_last_prin FROM public.loan_repayments WHERE loan_id = v_loan_id AND due_date <= v_today AND status = 'SCHEDULED' ORDER BY installment_number DESC LIMIT 1;

    IF v_loan.loan_type = 'BORROWED' AND v_acc.balance < v_total THEN RAISE EXCEPTION 'Insufficient balance to settle % EMIs.', v_count; END IF;

    IF v_loan.loan_type = 'BORROWED' THEN v_new_bal := v_acc.balance - v_total; v_tx_type := 'DEBIT'; ELSE v_new_bal := v_acc.balance + v_total; v_tx_type := 'CREDIT'; END IF;
    IF v_last_prin <= 0 OR (v_loan.pending_tenure_months - v_count) <= 0 THEN v_status := 'CLOSED'; ELSE v_status := 'ACTIVE'; END IF;

    UPDATE public.accounts SET balance = v_new_bal WHERE account_id = v_target_aid;
    UPDATE public.loan_repayments SET status = 'PAID', paid_at = NOW(), account_id = v_target_aid WHERE loan_id = v_loan_id AND due_date <= v_today AND status = 'SCHEDULED';

    SELECT due_date INTO v_next_date FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'SCHEDULED' ORDER BY installment_number ASC LIMIT 1;
    IF v_next_date IS NULL THEN v_next_date := v_today; END IF;

    UPDATE public.loans SET pending_principal = v_last_prin, pending_tenure_months = GREATEST(0, v_loan.pending_tenure_months - v_count), principal_paid = v_loan.principal_paid + v_prin, interest_paid = v_loan.interest_paid + v_int, next_emi_date = v_next_date, status = v_status WHERE loan_id = v_loan_id;

    INSERT INTO public.transactions (user_id, account_id, account_name, type, category, amount, transaction_date, status, description) VALUES (v_user_id, v_target_aid, v_acc.account_name, v_tx_type, 'Debt & EMI', v_total, v_today, CASE WHEN v_tx_type = 'DEBIT' THEN 'DEBITED' ELSE 'CREDITED' END, 'Batch Settlement (' || v_count || ' Past EMIs)');
    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description) VALUES (v_user_id, v_target_aid, 'BATCH_SETTLEMENT', CASE WHEN v_tx_type = 'DEBIT' THEN -v_total ELSE v_total END, 'Settled ' || v_count || ' historical EMIs.');

    RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'Successfully settled ' || v_count || ' past EMIs.', 'new_pending_principal', v_last_prin);
END;
$$;

-- 6.5 RPC: Atomic Flexible / Ad-Hoc Repayment
CREATE OR REPLACE FUNCTION repay_flexible_loan_atomic(payload JSONB)
RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_user_id UUID := (payload->>'user_id')::UUID;
    v_loan_id UUID := (payload->>'loan_id')::UUID;
    v_target_aid UUID := (payload->>'account_id')::UUID;
    v_amount NUMERIC(14,2) := (payload->>'amount')::NUMERIC(14,2);
    v_date DATE := (payload->>'payment_date')::DATE;
    v_note TEXT := payload->>'note';

    v_loan RECORD; v_acc RECORD; v_new_bal NUMERIC(14,2); v_new_pend NUMERIC(14,2); v_tx_type VARCHAR; v_status VARCHAR;
BEGIN
    SELECT * INTO v_loan FROM public.loans WHERE loan_id = v_loan_id AND user_id = v_user_id FOR UPDATE;
    IF v_loan.status != 'ACTIVE' THEN RAISE EXCEPTION 'This loan is already CLOSED.'; END IF;
    IF v_amount > v_loan.pending_principal THEN RAISE EXCEPTION 'Repayment exceeds outstanding balance.'; END IF;

    IF v_target_aid IS NULL THEN v_target_aid := v_loan.account_id; END IF;
    SELECT * INTO v_acc FROM public.accounts WHERE account_id = v_target_aid AND user_id = v_user_id FOR UPDATE;

    IF v_loan.loan_type = 'BORROWED' AND v_acc.balance < v_amount THEN RAISE EXCEPTION 'Insufficient balance.'; END IF;

    IF v_loan.loan_type = 'BORROWED' THEN v_new_bal := v_acc.balance - v_amount; v_tx_type := 'DEBIT'; ELSE v_new_bal := v_acc.balance + v_amount; v_tx_type := 'CREDIT'; END IF;
    v_new_pend := v_loan.pending_principal - v_amount;
    IF v_new_pend <= 0 THEN v_status := 'CLOSED'; ELSE v_status := 'ACTIVE'; END IF;

    UPDATE public.accounts SET balance = v_new_bal WHERE account_id = v_target_aid;
    UPDATE public.loans SET pending_principal = v_new_pend, principal_paid = v_loan.principal_paid + v_amount, status = v_status WHERE loan_id = v_loan_id;

    INSERT INTO public.loan_partial_repayments (loan_id, user_id, account_id, amount, payment_date, note, remaining_balance_after) VALUES (v_loan_id, v_user_id, v_target_aid, v_amount, v_date, COALESCE(v_note, 'Ad-hoc repayment'), v_new_pend);
    INSERT INTO public.transactions (user_id, account_id, account_name, type, category, amount, transaction_date, status, description) VALUES (v_user_id, v_target_aid, v_acc.account_name, v_tx_type, 'Debt & EMI', v_amount, v_date, CASE WHEN v_tx_type = 'DEBIT' THEN 'DEBITED' ELSE 'CREDITED' END, 'P2P Repayment: ' || v_loan.loan_name);
    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description) VALUES (v_user_id, v_target_aid, 'LOAN_PARTIAL_' || v_tx_type, CASE WHEN v_tx_type = 'DEBIT' THEN -v_amount ELSE v_amount END, 'Partial repayment logged.');

    RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'Logged repayment.', 'new_pending_principal', v_new_pend, 'loan_status', v_status);
END;
$$;