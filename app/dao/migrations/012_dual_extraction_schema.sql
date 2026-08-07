-- PocketMunim Enterprise Schema - Phase 12 Dual Extraction
-- Adds normalized_item to the ledger for high-performance analytics

-- 1. Add the new column
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS normalized_item VARCHAR(150);

-- 2. Replace the Bulk RPC to include the new column
DROP FUNCTION IF EXISTS atomic_bulk_commit(UUID, VARCHAR, NUMERIC, NUMERIC, JSONB);

CREATE OR REPLACE FUNCTION atomic_bulk_commit(
    p_account_id UUID,
    p_user_id VARCHAR,
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
    SELECT balance INTO v_current_balance FROM accounts WHERE id = p_account_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Account not found'; END IF;

    v_new_balance := v_current_balance + p_net_change;
    IF v_new_balance < 0 THEN RAISE EXCEPTION 'Insufficient balance'; END IF;

    UPDATE accounts SET balance = v_new_balance WHERE id = p_account_id;

    IF p_max_amount > 0 THEN
        INSERT INTO account_logs (account_id, user_id, log_type, amount, balance_after, description)
        VALUES (p_account_id, p_user_id, 'BULK_UPDATE', p_max_amount, v_new_balance, 'Bulk Transaction');
    END IF;

    IF jsonb_array_length(p_payloads) > 0 THEN
        INSERT INTO transactions (
            user_id, amount, txn_type, description, normalized_item, intent, category, subcategory, date, source_account, destination_account, soft_deleted
        )
        SELECT
            (x->>'user_id')::VARCHAR,
            (x->>'amount')::NUMERIC,
            x->>'txn_type',
            x->>'description',
            x->>'normalized_item',   -- NEW COLUMN INGESTION
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