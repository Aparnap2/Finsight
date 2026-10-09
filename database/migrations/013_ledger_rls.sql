-- 013_ledger_rls.sql: RLS for the P9 execution/idempotency ledger (Slice 3)
-- Covers the tables 006_rls.sql and 011 missed: execution_records and
-- idempotency_keys, created by the alembic chain (fresh path) or the
-- runtime models. Same convention as 011: deny-by-default,
-- tenant_id = current_setting('app.tenant_id', true), no fallback.
-- Missing GUC yields NULL, and NULL comparisons hide every row.
-- Table owners bypass RLS by design (documented, probed in tests).

-- ============================================================================
-- Step 1: Enable RLS (guarded: ledger tables exist only post-alembic)
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'execution_records') THEN
        EXECUTE 'ALTER TABLE execution_records ENABLE ROW LEVEL SECURITY';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'idempotency_keys') THEN
        EXECUTE 'ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY';
    END IF;
END $$;

-- ============================================================================
-- Step 2: Tenant isolation policies (deny-by-default, GUC-driven)
-- ============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'execution_records') THEN
        EXECUTE 'DROP POLICY IF EXISTS p_tenant_isolation_execution_records ON execution_records';
        EXECUTE 'CREATE POLICY p_tenant_isolation_execution_records ON execution_records USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'idempotency_keys') THEN
        EXECUTE 'DROP POLICY IF EXISTS p_tenant_isolation_idempotency_keys ON idempotency_keys';
        EXECUTE 'CREATE POLICY p_tenant_isolation_idempotency_keys ON idempotency_keys USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))';
    END IF;
END $$;

-- ============================================================================
-- Step 3: Tenant-first lookup indexes (append-only, IF NOT EXISTS)
-- ============================================================================

CREATE INDEX IF NOT EXISTS ix_execution_records_tenant_key
    ON execution_records (tenant_id, idempotency_key);
CREATE INDEX IF NOT EXISTS ix_idempotency_keys_tenant_key
    ON idempotency_keys (tenant_id, idempotency_key);
