-- PocketMunim Enterprise Schema - Phase 3 Category Master
CREATE TABLE IF NOT EXISTS categories (
    category_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id VARCHAR(255) NOT NULL,
    category_name VARCHAR(100) NOT NULL,
    subcategories JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, category_name)
);

ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
