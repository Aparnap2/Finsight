-- 001_extensions.sql: Required PostgreSQL extensions
BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;
-- pg_partman requires system-level install; not available in 15-alpine

-- Create session context helper functions (used by RLS and audit triggers)
CREATE OR REPLACE FUNCTION set_tenant_context(p_tenant_id TEXT)
RETURNS void AS $$
BEGIN
    PERFORM set_config('app.tenant_id', p_tenant_id, true);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION set_user_context(p_user_id TEXT)
RETURNS void AS $$
BEGIN
    PERFORM set_config('app.user_id', p_user_id, true);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION set_role_context(p_role TEXT)
RETURNS void AS $$
BEGIN
    PERFORM set_config('app.role', p_role, true);
END;
$$ LANGUAGE plpgsql;

COMMIT;
