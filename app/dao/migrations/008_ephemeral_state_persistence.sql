-- PocketMunim Enterprise Schema - Phase 8 Ephemeral State Persistence
-- Migrates in-memory Python dictionaries (PENDING_BATCHES, REPORT_TOKENS) to Supabase tables

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

CREATE INDEX IF NOT EXISTS idx_pending_batches_user_id ON pending_batches(user_id);
CREATE INDEX IF NOT EXISTS idx_report_tokens_expires_at ON report_tokens(expires_at);

-- RLS Configuration
ALTER TABLE pending_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE report_tokens ENABLE ROW LEVEL SECURITY;

-- Allow service role full access
CREATE POLICY "Service Role Full Access pending_batches" ON pending_batches FOR ALL USING (true);
CREATE POLICY "Service Role Full Access report_tokens" ON report_tokens FOR ALL USING (true);