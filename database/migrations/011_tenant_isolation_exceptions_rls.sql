-- 011_tenant_isolation_exceptions_rls.sql: RLS for P5-03 tenant→case boundary
-- Covers tables missed by 006_rls.sql: exceptions, exception_audits, webhook_events (if present).
-- Tenant isolation is fail-closed: tenant_id = current_setting('app.tenant_id')::text, no fallback.
-- Quarantined rows (tenant_id = 'UNROUTABLE') are visible only when GUC is 'UNROUTABLE'.

-- ============================================================================
-- Step 1: Enable RLS
-- ============================================================================

ALTER TABLE exceptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE exception_audits ENABLE ROW LEVEL SECURITY;
-- webhook_events may not exist in all envs — guard with DO block
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'webhook_events') THEN
        EXECUTE 'ALTER TABLE webhook_events ENABLE ROW LEVEL SECURITY';
    END IF;
END $$;

-- ============================================================================
-- Step 2: Tenant isolation policies (deny-by-default, GUC-driven)
-- ============================================================================

-- exceptions: tenant-scoped case lookup (boundary #2)
DROP POLICY IF EXISTS p_tenant_isolation_exceptions ON exceptions;
CREATE POLICY p_tenant_isolation_exceptions ON exceptions
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

-- exception_audits: tenant-scoped audit trail (boundary #10)
DROP POLICY IF EXISTS p_tenant_isolation_exception_audits ON exception_audits;
CREATE POLICY p_tenant_isolation_exception_audits ON exception_audits
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

-- webhook_events: tenant-scoped webhook idempotency (boundary #1, #10)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'webhook_events') THEN
        EXECUTE 'DROP POLICY IF EXISTS p_tenant_isolation_webhook_events ON webhook_events';
        EXECUTE 'CREATE POLICY p_tenant_isolation_webhook_events ON webhook_events USING (tenant_id = current_setting(''app.tenant_id'', true)) WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))';
    END IF;
END $$;

-- ============================================================================
-- Step 3: Composite index for tenant→case covering lookup (boundary #2)
-- ============================================================================

CREATE INDEX IF NOT EXISTS ix_exceptions_tenant_case ON exceptions (tenant_id, exception_id);
CREATE INDEX IF NOT EXISTS ix_exception_audits_tenant_exception ON exception_audits (tenant_id, exception_id);
