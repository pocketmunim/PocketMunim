-- PocketMunim Enterprise Schema - Phase 9 Atomic Transactions
-- Resolves race conditions via PostgreSQL locking for Bulk Commits

CREATE OR REPLACE FUNCTION atomic_bulk_commit(
    p_account_id UUID,
    p_user_id UUID,
    p_net_change NUMERIC,
    p_max_amount NUMERIC,
    p_payloads JSONB
)
RETURNS NUMERIC
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_current_balance NUMERIC;
    v_new_balance NUMERIC;
BEGIN
    -- 1. Acquire row-level lock on the account to prevent race conditions
    SELECT balance INTO v_current_balance
    FROM accounts
    WHERE id = p_account_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Account not found';
    END IF;

    -- 2. Exact NUMERIC math computation
    v_new_balance := v_current_balance + p_net_change;

    -- 3. Pre-transaction validation
    IF v_new_balance < 0 THEN
        RAISE EXCEPTION 'Insufficient balance';
    END IF;

    -- 4. Execute atomic balance update
    UPDATE accounts
    SET balance = v_new_balance
    WHERE id = p_account_id;

    -- 5. Audit Log Insertion
    IF p_max_amount > 0 THEN
        INSERT INTO account_logs (
            account_id, user_id, log_type, amount, balance_after, description
        ) VALUES (
            p_account_id, p_user_id, 'BULK_UPDATE', p_max_amount, v_new_balance, 'Bulk Transaction'
        );
    END IF;

    -- 6. Batch Ledger Insertion using jsonb iteration
    IF jsonb_array_length(p_payloads) > 0 THEN
        INSERT INTO transactions (
            user_id, amount, txn_type, description, intent, category, subcategory, date, source_account, destination_account, soft_deleted
        )
        SELECT
            (x->>'user_id')::UUID,
            (x->>'amount')::NUMERIC,
            x->>'txn_type',
            x->>'description',
            x->>'intent',
            x->>'category',
            x->>'subcategory',
            (x->>'date')::TIMESTAMPTZ,
            x->>'source_account',
            x->>'destination_account',
            (x->>'soft_deleted')::BOOLEAN
        FROM jsonb_array_elements(p_payloads) AS x;
    END IF;

    RETURN v_new_balance;
END;
$$;