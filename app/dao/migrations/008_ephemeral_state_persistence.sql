-- PocketMunim Enterprise Schema - Phase 8 Ephemeral State Persistence
CREATE TABLE IF NOT EXISTS pending_batches (
    batch_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    account_id VARCHAR(255) NOT NULL,
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMPTZ DEFAULT (CURRENT_TIMESTAMP + INTERVAL '24 hours')
);

CREATE TABLE IF NOT EXISTS report_tokens (
    token VARCHAR(255) PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE pending_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_tokens ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service Role Full Access pending_batches" ON pending_batches FOR ALL USING (true);
CREATE POLICY "Service Role Full Access report_tokens" ON report_tokens FOR ALL USING (true);
