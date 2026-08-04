-- PocketMunim Enterprise Schema - Phase 4 Category Master

-- 1. Relational Category Master
CREATE TABLE categories (
    category_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    parent_id UUID REFERENCES categories(category_id) ON DELETE CASCADE, -- NULL for top-level categories
    level VARCHAR(20) NOT NULL CHECK (level IN ('CATEGORY', 'SUBCATEGORY', 'ITEM')),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, name, parent_id)
);

-- 2. JSONB Cache Table for High-Speed Lookups
CREATE TABLE category_cache (
    user_id UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    cache_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. Row-Level Security
ALTER TABLE categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE category_cache ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Category Tenant Isolation" ON categories
    FOR ALL USING (user_id = (SELECT user_id FROM users WHERE telegram_id = current_setting('request.jwt.claims')::json->>'telegram_id'));

CREATE POLICY "Cache Tenant Isolation" ON category_cache
    FOR ALL USING (user_id = (SELECT user_id FROM users WHERE telegram_id = current_setting('request.jwt.claims')::json->>'telegram_id'));

-- Note: PostgreSQL Trigger for automatic JSONB cache rebuilding will be implemented in DAO logic to allow application-level formatting control.
