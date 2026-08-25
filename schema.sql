-- ==============================================================================
-- ISHITA FINANCIAL INTELLIGENCE SYSTEM (IFIS) - DATABASE VAULT SCHEMA
-- Version: 2.4.1 (Enterprise Production Master - Hardened)
-- ==============================================================================
DROP TABLE IF EXISTS security_nonces,users ,transactions ,accounts ,account_logs   ,salaries ,loans ,loan_partial_repayments ,loan_repayments, sip_contracts  CASCADE;


CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

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

-- 2. Liquidity Vaults / Accounts (HARDENED: Added Solvency Check)
CREATE TABLE public.accounts (
    account_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_name VARCHAR(100) NOT NULL,
    balance NUMERIC(14, 2) NOT NULL DEFAULT 0.00 CHECK (balance >= 0.00),
    is_default BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. Account Logs (HARDENED: Strict amount constraint)
CREATE TABLE public.account_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    amount NUMERIC(14, 2) NOT NULL,
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
    base_amount NUMERIC(14, 2) NOT NULL DEFAULT 0.00 CHECK (base_amount >= 0.00),
    actual_amount NUMERIC(14, 2) NOT NULL DEFAULT 0.00 CHECK (actual_amount >= 0.00),
    payout_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED' CHECK (status IN ('SCHEDULED', 'PAID', 'SETTLED')),
    paid_at TIMESTAMPTZ NULL,
    is_custom_override BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT unique_user_salary_month UNIQUE(user_id, year, month)
);

-- 5. Loans Management Table (HARDENED: Added domain checks)
CREATE TABLE public.loans (
    loan_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
    loan_name VARCHAR(150) NOT NULL,
    loan_type VARCHAR(20) NOT NULL DEFAULT 'BORROWED' CHECK (loan_type IN ('BORROWED', 'LENT')),
    counterparty VARCHAR(150) NOT NULL,
    disbursement_date DATE NOT NULL,
    first_emi_date DATE NULL,
    original_principal NUMERIC(14, 2) NOT NULL CHECK (original_principal > 0),
    pending_principal NUMERIC(14, 2) NOT NULL CHECK (pending_principal >= 0),
    annual_interest_rate NUMERIC(6, 2) DEFAULT 0.00 CHECK (annual_interest_rate >= 0),
    original_tenure_months INTEGER DEFAULT 0 CHECK (original_tenure_months >= 0),
    pending_tenure_months INTEGER DEFAULT 0 CHECK (pending_tenure_months >= 0),
    monthly_emi NUMERIC(14, 2) DEFAULT 0.00 CHECK (monthly_emi >= 0),
    total_interest_payable NUMERIC(14, 2) DEFAULT 0.00 CHECK (total_interest_payable >= 0),
    principal_paid NUMERIC(14, 2) DEFAULT 0.00 CHECK (principal_paid >= 0),
    interest_paid NUMERIC(14, 2) DEFAULT 0.00 CHECK (interest_paid >= 0),
    next_emi_date DATE NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'CLOSED', 'DEFAULTED')),
    is_flexible BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 6. Loan Repayments Schedule
CREATE TABLE public.loan_repayments (
    repayment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    loan_id UUID REFERENCES public.loans(loan_id) ON DELETE CASCADE,
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
    installment_number INTEGER NOT NULL CHECK (installment_number > 0),
    due_date DATE NOT NULL,
    emi_amount NUMERIC(14, 2) NOT NULL CHECK (emi_amount >= 0),
    principal_component NUMERIC(14, 2) NOT NULL CHECK (principal_component >= 0),
    interest_component NUMERIC(14, 2) NOT NULL CHECK (interest_component >= 0),
    remaining_principal_after NUMERIC(14, 2) NOT NULL CHECK (remaining_principal_after >= 0),
    status VARCHAR(20) NOT NULL DEFAULT 'SCHEDULED' CHECK (status IN ('SCHEDULED', 'PAID', 'OVERDUE')),
    paid_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 7. Loan Partial Repayments (Ad-hoc Ledger)
CREATE TABLE public.loan_partial_repayments (
    partial_repayment_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    loan_id UUID REFERENCES public.loans(loan_id) ON DELETE CASCADE,
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
    amount NUMERIC(14, 2) NOT NULL CHECK (amount > 0),
    payment_date DATE NOT NULL,
    note TEXT,
    remaining_balance_after NUMERIC(14, 2) NOT NULL CHECK (remaining_balance_after >= 0),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 8. Transactions Ledger (HARDENED: Added domain checks)
CREATE TABLE public.transactions (
    transaction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.users(user_id) ON DELETE CASCADE,
    account_id UUID REFERENCES public.accounts(account_id) ON DELETE CASCADE,
    related_account_id UUID REFERENCES public.accounts(account_id) ON DELETE SET NULL,
    account_name VARCHAR(100),
    related_account_name VARCHAR(100),
    salary_id UUID REFERENCES public.salaries(salary_id) ON DELETE SET NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('CREDIT', 'DEBIT')),
    category VARCHAR(50) DEFAULT 'General',
    amount NUMERIC(14, 2) NOT NULL CHECK (amount >= 0),
    transaction_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'CREDITED' CHECK (status IN ('CREDITED', 'DEBITED', 'PENDING', 'FAILED')),
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
-- PERFORMANCE INDEXES
-- ==============================================================================
CREATE INDEX idx_users_telegram ON public.users(telegram_id);
CREATE INDEX idx_accounts_user ON public.accounts(user_id);
CREATE INDEX idx_loans_user_status ON public.loans(user_id, status);
CREATE INDEX idx_repayments_loan ON public.loan_repayments(loan_id, status, due_date);
CREATE INDEX idx_tx_user_date ON public.transactions(user_id, transaction_date DESC);
CREATE INDEX idx_nonce_lookup ON public.security_nonces(nonce);

-- ==============================================================================
-- MEMORY MANAGEMENT TRIGGERS
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
-- ROW LEVEL SECURITY & SERVICE POLICIES
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
-- ATOMIC STORED PROCEDURES (ACID RPCs)
-- ==============================================================================

-- 6.1 RPC: Atomic Vault Transfers (HARDENED: Deadlock Prevention via Lexicographical Locking)
CREATE OR REPLACE FUNCTION transfer_vault_funds(
    p_user_id UUID,
    p_src_account_id UUID,
    p_dest_account_id UUID,
    p_amount NUMERIC(14, 2)
) RETURNS JSONB LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE
    v_src_bal NUMERIC(14, 2);
    v_dest_bal NUMERIC(14, 2);
    v_src_name VARCHAR(100);
    v_dest_name VARCHAR(100);
    v_today DATE := CURRENT_DATE;
BEGIN
    IF p_src_account_id = p_dest_account_id THEN
        RAISE EXCEPTION 'Source and destination accounts must be distinct vaults.';
    END IF;
    IF p_amount <= 0 THEN
        RAISE EXCEPTION 'Transfer amount must be strictly greater than 0.';
    END IF;

    -- Deadlock Prevention: Always acquire locks in deterministic UUID order
    IF p_src_account_id < p_dest_account_id THEN
        SELECT balance, account_name INTO v_src_bal, v_src_name FROM public.accounts WHERE account_id = p_src_account_id AND user_id = p_user_id AND is_active = TRUE FOR UPDATE;
        SELECT balance, account_name INTO v_dest_bal, v_dest_name FROM public.accounts WHERE account_id = p_dest_account_id AND user_id = p_user_id AND is_active = TRUE FOR UPDATE;
    ELSE
        SELECT balance, account_name INTO v_dest_bal, v_dest_name FROM public.accounts WHERE account_id = p_dest_account_id AND user_id = p_user_id AND is_active = TRUE FOR UPDATE;
        SELECT balance, account_name INTO v_src_bal, v_src_name FROM public.accounts WHERE account_id = p_src_account_id AND user_id = p_user_id AND is_active = TRUE FOR UPDATE;
    END IF;

    IF v_src_name IS NULL THEN RAISE EXCEPTION 'Source vault not found or inactive.'; END IF;
    IF v_dest_name IS NULL THEN RAISE EXCEPTION 'Destination vault not found or inactive.'; END IF;

    IF v_src_bal < p_amount THEN
        RAISE EXCEPTION 'Insufficient funds in % (Available: %, Requested: %)', v_src_name, v_src_bal, p_amount;
    END IF;

    -- Execute Unified Updates
    UPDATE public.accounts SET balance = balance - p_amount WHERE account_id = p_src_account_id;
    UPDATE public.accounts SET balance = balance + p_amount WHERE account_id = p_dest_account_id;

    -- Double Entry Accounting Logs
    INSERT INTO public.transactions (user_id, account_id, account_name, related_account_id, related_account_name, type, category, amount, transaction_date, status, description)
    VALUES (p_user_id, p_src_account_id, v_src_name, p_dest_account_id, v_dest_name, 'DEBIT', 'Vault Transfer', p_amount, v_today, 'DEBITED', 'Self Transfer: Debited from ' || v_src_name || ' -> ' || v_dest_name);

    INSERT INTO public.transactions (user_id, account_id, account_name, related_account_id, related_account_name, type, category, amount, transaction_date, status, description)
    VALUES (p_user_id, p_dest_account_id, v_dest_name, p_src_account_id, v_src_name, 'CREDIT', 'Vault Transfer', p_amount, v_today, 'CREDITED', 'Self Transfer: Credited to ' || v_dest_name || ' <- ' || v_src_name);

    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description)
    VALUES (p_user_id, p_src_account_id, 'VAULT_TRANSFER_OUT', p_amount, 'Transferred out to ' || v_dest_name);

    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description)
    VALUES (p_user_id, p_dest_account_id, 'VAULT_TRANSFER_IN', p_amount, 'Received in from ' || v_src_name);

    RETURN jsonb_build_object(
        'status', 'SUCCESS',
        'message', 'Transferred funds successfully.',
        'source_vault', jsonb_build_object('account_id', p_src_account_id, 'account_name', v_src_name, 'balance', v_src_bal - p_amount),
        'destination_vault', jsonb_build_object('account_id', p_dest_account_id, 'account_name', v_dest_name, 'balance', v_dest_bal + p_amount)
    );
END;
$$;

-- 1. Drop the old broken function
DROP FUNCTION IF EXISTS public.atomic_balance_update(uuid, numeric);

-- 2. Create the corrected atomic function
CREATE OR REPLACE FUNCTION public.atomic_balance_update(p_account_id uuid, p_amount numeric)
RETURNS numeric
LANGUAGE plpgsql SECURITY DEFINER
AS $$
DECLARE
    v_current_balance NUMERIC;
    v_new_balance NUMERIC;
BEGIN
    -- Lock the exact account row
    SELECT balance INTO v_current_balance
    FROM public.accounts
    WHERE account_id = p_account_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Account not found';
    END IF;

    -- Calculate new balance
    v_new_balance := v_current_balance + p_amount;

    -- Strict Solvency Check
    IF v_new_balance < 0 THEN
        RAISE EXCEPTION 'Insufficient balance';
    END IF;

    -- Execute Update using the correct column name
    UPDATE public.accounts
    SET balance = v_new_balance
    WHERE account_id = p_account_id;

    RETURN v_new_balance;
END;
$$;

-- 3. Reload PostgREST schema cache
NOTIFY pgrst, 'reload schema';

-- 1. Create SIP Contracts Table
CREATE TABLE public.sip_contracts (
    sip_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.users(user_id) ON DELETE CASCADE,
    asset_name VARCHAR(255) NOT NULL,
    monthly_amount NUMERIC(14,2) NOT NULL,
    frequency VARCHAR(20) DEFAULT 'MONTHLY',
    deduction_day INTEGER,
    duration_months INTEGER,
    paid_installments INTEGER DEFAULT 0,
    total_invested NUMERIC(14,2) DEFAULT 0.00,
    reminder_preference VARCHAR(50) DEFAULT '1_DAY_BEFORE',
    snoozed_until DATE,
    start_date DATE DEFAULT CURRENT_DATE,
    next_due_date DATE DEFAULT CURRENT_DATE,
    last_paid_date DATE,
    status VARCHAR(50) DEFAULT 'ACTIVE',
    is_flexible BOOLEAN DEFAULT FALSE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Enable Row Level Security (RLS)
ALTER TABLE public.sip_contracts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow Service Role on sip_contracts" ON public.sip_contracts FOR ALL USING (auth.role() = 'service_role');

-- 3. Reload the API Schema Cache
NOTIFY pgrst, 'reload schema';

CREATE OR REPLACE FUNCTION public.settle_salary_atomic(payload JSONB)
RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER
AS $$
DECLARE
    v_user_id UUID := (payload->>'user_id')::UUID;
    v_salary_id UUID := (payload->>'salary_id')::UUID;
    v_target_aid UUID := NULLIF(payload->>'target_account_id', '')::UUID;
    v_sal RECORD;
    v_acc RECORD;
    v_start_d DATE;
    v_end_d DATE;
    v_other_income NUMERIC(14,2) := 0;
    v_total_inflow NUMERIC(14,2) := 0;
    v_total_debits NUMERIC(14,2) := 0;
    v_sweep_amount NUMERIC(14,2) := 0;
    v_new_bal NUMERIC(14,2);
    v_month_name VARCHAR;
BEGIN
    -- 1. Lock Salary Record
    SELECT * INTO v_sal FROM public.salaries WHERE salary_id = v_salary_id AND user_id = v_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Salary record not found.';
    END IF;
    IF v_sal.status = 'SETTLED' THEN
        RAISE EXCEPTION 'Salary is already settled.';
    END IF;
    IF v_sal.status != 'PAID' THEN
        RAISE EXCEPTION 'Salary must be in PAID state to settle. Current status: %', v_sal.status;
    END IF;

    -- 2. Determine & Lock Vault
    IF v_target_aid IS NULL THEN
        v_target_aid := v_sal.account_id;
    END IF;
    IF v_target_aid IS NULL THEN
        SELECT account_id INTO v_target_aid FROM public.accounts WHERE user_id = v_user_id AND is_active = TRUE ORDER BY is_default DESC LIMIT 1;
    END IF;

    SELECT * INTO v_acc FROM public.accounts WHERE account_id = v_target_aid AND user_id = v_user_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Account vault not found or inactive.';
    END IF;

    -- 3. Date Range
    v_start_d := make_date(v_sal.year, v_sal.month, 1);
    v_end_d := (v_start_d + interval '1 month - 1 day')::date;

    -- 4. Aggregate Transactions for Month
    SELECT COALESCE(SUM(amount), 0) INTO v_other_income
    FROM public.transactions
    WHERE user_id = v_user_id AND type IN ('CREDIT', 'INCOME') AND status = 'CREDITED'
      AND transaction_date >= v_start_d AND transaction_date <= v_end_d
      AND (salary_id IS NULL OR salary_id != v_salary_id);

    v_total_inflow := v_sal.actual_amount + v_other_income;

    SELECT COALESCE(SUM(amount), 0) INTO v_total_debits
    FROM public.transactions
    WHERE user_id = v_user_id AND type IN ('DEBIT', 'EXPENSE')
      AND transaction_date >= v_start_d AND transaction_date <= v_end_d;

    -- 5. Validation Check
    IF v_total_debits > v_total_inflow THEN
        RAISE EXCEPTION 'Settlement Blocked: Total debits (₹%) exceed total incoming funds (₹%).', v_total_debits, v_total_inflow;
    END IF;

    v_sweep_amount := v_total_inflow - v_total_debits;
    v_month_name := to_char(v_start_d, 'Month');

    -- 6. Execute Sweep if > 0
    IF v_sweep_amount > 0 THEN
        IF v_acc.balance < v_sweep_amount THEN
            RAISE EXCEPTION 'Settlement Blocked: Insufficient vault balance (Available: ₹%, Required: ₹%).', v_acc.balance, v_sweep_amount;
        END IF;

        v_new_bal := v_acc.balance - v_sweep_amount;
        UPDATE public.accounts SET balance = v_new_bal WHERE account_id = v_target_aid;

        INSERT INTO public.transactions (user_id, account_id, account_name, salary_id, type, category, amount, transaction_date, status, description)
        VALUES (v_user_id, v_target_aid, v_acc.account_name, v_salary_id, 'DEBIT', 'Salary Settlement', v_sweep_amount, CURRENT_DATE, 'DEBITED', 'Bulk Month Settlement Sweep - ' || trim(v_month_name) || ' ' || v_sal.year);

        INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description)
        VALUES (v_user_id, v_target_aid, 'SALARY_MONTH_SETTLED_DEBIT', -v_sweep_amount, 'Month closed and balance swept for ' || trim(v_month_name) || ' ' || v_sal.year);
    END IF;

    -- 7. Mark as Settled
    UPDATE public.salaries SET status = 'SETTLED', account_id = v_target_aid WHERE salary_id = v_salary_id;

    RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'Month ' || trim(v_month_name) || ' closed. ₹' || v_sweep_amount || ' swept from vault.');
END;
$$;

NOTIFY pgrst, 'reload schema';

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS fcm_token TEXT;
NOTIFY pgrst, 'reload schema';

CREATE OR REPLACE FUNCTION public.process_due_salaries_atomic(p_target_date DATE)
RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER
AS $$
DECLARE
    v_sal RECORD;
    v_acc RECORD;
    v_processed_count INTEGER := 0;
    v_total_disbursed NUMERIC(14,2) := 0.00;
    v_month_name VARCHAR;
BEGIN
    -- 1. Loop through all due salaries that are still SCHEDULED
    -- SKIP LOCKED ensures multiple concurrent cron triggers won't deadlock
    FOR v_sal IN
        SELECT * FROM public.salaries
        WHERE status = 'SCHEDULED'
          AND payout_date <= p_target_date
        FOR UPDATE SKIP LOCKED
    LOOP
        -- 2. Lock the target account vault
        SELECT * INTO v_acc FROM public.accounts
        WHERE account_id = v_sal.account_id
        FOR UPDATE;

        IF FOUND AND v_acc.is_active = TRUE THEN
            -- 3. Update account balance atomically
            UPDATE public.accounts
            SET balance = balance + v_sal.actual_amount
            WHERE account_id = v_sal.account_id;

            -- Convert integer month to text name (e.g., 'August')
            v_month_name := trim(to_char(to_timestamp(v_sal.month::text, 'MM'), 'Month'));

            -- 4. Insert Ledger Transaction
            INSERT INTO public.transactions (
                user_id, account_id, account_name, salary_id,
                type, category, amount, transaction_date, status, description
            ) VALUES (
                v_sal.user_id, v_sal.account_id, v_acc.account_name, v_sal.salary_id,
                'CREDIT', 'Salary', v_sal.actual_amount, p_target_date, 'CREDITED',
                'Automated Salary Credit - ' || v_month_name || ' ' || v_sal.year
            );

            -- 5. Insert Immutable Log
            INSERT INTO public.account_logs (
                user_id, account_id, event_type, amount, description
            ) VALUES (
                v_sal.user_id, v_sal.account_id, 'QSTASH_AUTO_SALARY_CREDIT', v_sal.actual_amount,
                'Automated cron dispersal for ' || v_month_name || ' ' || v_sal.year || ' (Payout Date: ' || v_sal.payout_date || ')'
            );

            -- 6. Close the Salary Contract
            UPDATE public.salaries
            SET status = 'PAID', paid_at = NOW()
            WHERE salary_id = v_sal.salary_id;

            -- 7. Update Aggregates
            v_processed_count := v_processed_count + 1;
            v_total_disbursed := v_total_disbursed + v_sal.actual_amount;
        END IF;
    END LOOP;

    RETURN jsonb_build_object(
        'status', 'COMPLETED',
        'processed_count', v_processed_count,
        'total_disbursed', v_total_disbursed,
        'date', p_target_date
    );
END;
$$;

-- Reload schema so PostgREST recognizes the new RPC immediately
NOTIFY pgrst, 'reload schema';

CREATE OR REPLACE FUNCTION public.pay_loan_emi_atomic(payload JSONB)
RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER
AS $$
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
    -- 1. Lock Loan
    SELECT * INTO v_loan FROM public.loans WHERE loan_id = v_loan_id AND user_id = v_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Loan contract not found.'; END IF;
    IF v_loan.status != 'ACTIVE' THEN RAISE EXCEPTION 'This loan is already CLOSED.'; END IF;

    IF v_target_aid IS NULL THEN v_target_aid := v_loan.account_id; END IF;
    SELECT * INTO v_acc FROM public.accounts WHERE account_id = v_target_aid AND user_id = v_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'No active liquidity vault available for EMI deduction.'; END IF;

    -- 2. Lock Next Scheduled EMI
    SELECT * INTO v_next_emi FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'SCHEDULED' ORDER BY installment_number ASC LIMIT 1 FOR UPDATE;
    IF NOT FOUND THEN
        UPDATE public.loans SET status = 'CLOSED', pending_principal = 0.00 WHERE loan_id = v_loan_id;
        RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'All EMIs for this loan have been completed.');
    END IF;

    -- 3. Duplicate EMI Guard (Bypassed if user explicitly confirms advance payment)
    IF NOT v_is_advance THEN
        SELECT EXISTS (
            SELECT 1 FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'PAID'
            AND due_date >= date_trunc('month', v_today)::DATE AND due_date <= (date_trunc('month', v_today) + interval '1 month - 1 day')::DATE
        ) INTO v_cur_paid;

        IF v_cur_paid THEN
            RAISE EXCEPTION 'DUPLICATE_CURRENT_MONTH';
        END IF;
    END IF;

    IF v_loan.loan_type = 'BORROWED' AND v_acc.balance < v_next_emi.emi_amount THEN
        RAISE EXCEPTION 'Insufficient balance in %. Required: ₹%', v_acc.account_name, v_next_emi.emi_amount;
    END IF;

    IF v_loan.loan_type = 'BORROWED' THEN
        v_new_bal := v_acc.balance - v_next_emi.emi_amount;
        v_tx_type := 'DEBIT';
        v_status_label := 'DEBITED';
    ELSE
        v_new_bal := v_acc.balance + v_next_emi.emi_amount;
        v_tx_type := 'CREDIT';
        v_status_label := 'CREDITED';
    END IF;

    v_new_pend_prin := v_next_emi.remaining_principal_after;
    v_new_pend_tenure := GREATEST(0, v_loan.pending_tenure_months - 1);

    IF v_new_pend_prin <= 0 OR v_new_pend_tenure = 0 THEN
        v_loan_status := 'CLOSED';
    ELSE
        v_loan_status := 'ACTIVE';
    END IF;

    -- 4. Execute Ledger & Vault Updates
    UPDATE public.accounts SET balance = v_new_bal WHERE account_id = v_target_aid;
    UPDATE public.loan_repayments SET status = 'PAID', paid_at = NOW(), account_id = v_target_aid WHERE repayment_id = v_next_emi.repayment_id;

    SELECT due_date INTO v_new_next_date FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'SCHEDULED' ORDER BY installment_number ASC LIMIT 1;
    IF v_new_next_date IS NULL THEN v_new_next_date := v_today; END IF;

    UPDATE public.loans SET pending_principal = v_new_pend_prin, pending_tenure_months = v_new_pend_tenure, principal_paid = v_loan.principal_paid + v_next_emi.principal_component, interest_paid = v_loan.interest_paid + v_next_emi.interest_component, next_emi_date = v_new_next_date, status = v_loan_status WHERE loan_id = v_loan_id;

    -- Insert Global Transaction record so it reflects across all accounts on the dashboard ledger feed
    INSERT INTO public.transactions (user_id, account_id, account_name, type, category, amount, transaction_date, status, description)
    VALUES (v_user_id, v_target_aid, v_acc.account_name, v_tx_type, 'Debt & EMI', v_next_emi.emi_amount, v_today, v_status_label, 'Loan EMI #' || v_next_emi.installment_number || ' (' || v_loan.loan_name || ')');

    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description)
    VALUES (v_user_id, v_target_aid, 'LOAN_EMI_' || v_tx_type, CASE WHEN v_tx_type = 'DEBIT' THEN -v_next_emi.emi_amount ELSE v_next_emi.emi_amount END, 'EMI #' || v_next_emi.installment_number || ' cleared.');

    RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'Installment #' || v_next_emi.installment_number || ' settled successfully.', 'new_pending_principal', v_new_pend_prin, 'loan_status', v_loan_status, 'next_due_date', v_new_next_date);
END;
$$;

NOTIFY pgrst, 'reload schema';

CREATE OR REPLACE FUNCTION public.pay_loan_emi_atomic(payload JSONB)
RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER
AS $$
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
    -- 1. Lock Loan
    SELECT * INTO v_loan FROM public.loans WHERE loan_id = v_loan_id AND user_id = v_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Loan contract not found.'; END IF;
    IF v_loan.status != 'ACTIVE' THEN RAISE EXCEPTION 'This loan is already CLOSED.'; END IF;

    IF v_target_aid IS NULL THEN v_target_aid := v_loan.account_id; END IF;
    SELECT * INTO v_acc FROM public.accounts WHERE account_id = v_target_aid AND user_id = v_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'No active liquidity vault available for EMI deduction.'; END IF;

    -- 2. Lock Next Scheduled EMI
    SELECT * INTO v_next_emi FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'SCHEDULED' ORDER BY installment_number ASC LIMIT 1 FOR UPDATE;
    IF NOT FOUND THEN
        UPDATE public.loans SET status = 'CLOSED', pending_principal = 0.00 WHERE loan_id = v_loan_id;
        RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'All EMIs for this loan have been completed.');
    END IF;

    -- 3. Duplicate EMI Guard (Bypassed if user explicitly confirms advance payment)
    IF NOT v_is_advance THEN
        SELECT EXISTS (
            SELECT 1 FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'PAID'
            AND due_date >= date_trunc('month', v_today)::DATE AND due_date <= (date_trunc('month', v_today) + interval '1 month - 1 day')::DATE
        ) INTO v_cur_paid;

        IF v_cur_paid THEN
            RAISE EXCEPTION 'DUPLICATE_CURRENT_MONTH';
        END IF;
    END IF;

    IF v_loan.loan_type = 'BORROWED' AND v_acc.balance < v_next_emi.emi_amount THEN
        RAISE EXCEPTION 'Insufficient balance in %. Required: ₹%', v_acc.account_name, v_next_emi.emi_amount;
    END IF;

    IF v_loan.loan_type = 'BORROWED' THEN
        v_new_bal := v_acc.balance - v_next_emi.emi_amount;
        v_tx_type := 'DEBIT';
        v_status_label := 'DEBITED';
    ELSE
        v_new_bal := v_acc.balance + v_next_emi.emi_amount;
        v_tx_type := 'CREDIT';
        v_status_label := 'CREDITED';
    END IF;

    v_new_pend_prin := v_next_emi.remaining_principal_after;
    v_new_pend_tenure := GREATEST(0, v_loan.pending_tenure_months - 1);

    IF v_new_pend_prin <= 0 OR v_new_pend_tenure = 0 THEN
        v_loan_status := 'CLOSED';
    ELSE
        v_loan_status := 'ACTIVE';
    END IF;

    -- 4. Execute Ledger & Vault Updates
    UPDATE public.accounts SET balance = v_new_bal WHERE account_id = v_target_aid;
    UPDATE public.loan_repayments SET status = 'PAID', paid_at = NOW(), account_id = v_target_aid WHERE repayment_id = v_next_emi.repayment_id;

    SELECT due_date INTO v_new_next_date FROM public.loan_repayments WHERE loan_id = v_loan_id AND status = 'SCHEDULED' ORDER BY installment_number ASC LIMIT 1;
    IF v_new_next_date IS NULL THEN v_new_next_date := v_today; END IF;

    UPDATE public.loans SET pending_principal = v_new_pend_prin, pending_tenure_months = v_new_pend_tenure, principal_paid = v_loan.principal_paid + v_next_emi.principal_component, interest_paid = v_loan.interest_paid + v_next_emi.interest_component, next_emi_date = v_new_next_date, status = v_loan_status WHERE loan_id = v_loan_id;

    -- Insert Global Transaction record so it reflects across all accounts on the dashboard ledger feed
    INSERT INTO public.transactions (user_id, account_id, account_name, type, category, amount, transaction_date, status, description)
    VALUES (v_user_id, v_target_aid, v_acc.account_name, v_tx_type, 'Debt & EMI', v_next_emi.emi_amount, v_today, v_status_label, 'Loan EMI #' || v_next_emi.installment_number || ' (' || v_loan.loan_name || ')');

    INSERT INTO public.account_logs (user_id, account_id, event_type, amount, description)
    VALUES (v_user_id, v_target_aid, 'LOAN_EMI_' || v_tx_type, CASE WHEN v_tx_type = 'DEBIT' THEN -v_next_emi.emi_amount ELSE v_next_emi.emi_amount END, 'EMI #' || v_next_emi.installment_number || ' cleared.');

    RETURN jsonb_build_object('status', 'SUCCESS', 'message', 'Installment #' || v_next_emi.installment_number || ' settled successfully.', 'new_pending_principal', v_new_pend_prin, 'loan_status', v_loan_status, 'next_due_date', v_new_next_date);
END;
$$;

NOTIFY pgrst, 'reload schema';