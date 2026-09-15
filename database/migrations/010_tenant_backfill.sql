-- 010_tenant_backfill.sql: Backfill tenant_id on all 27 tenant-scoped tables.
--
-- Classified from 006_rls.sql:
--   * 12 tenant_id-boundary tables (column exists since 000, NOT NULL) — no-op guard
--   * 15 entity_id-boundary tables (legacy entity_id boundary) — ADD COLUMN then UPDATE
--
-- Idempotent: second run leaves zero NULLs and raises no errors.
-- Default tenant (acme-corp) UUID: '11111111-1111-4111-8111-111111111111'

BEGIN;

DO $$
DECLARE
    v_default_tenant CONSTANT text := '11111111-1111-4111-8111-111111111111';
    v_table text;
BEGIN
    -- 12 tenant_id-boundary tables: column already exists (NOT NULL); guard keeps
    -- this a safe no-op on partial schemas and on re-run.
    FOREACH v_table IN ARRAY ARRAY[
        'review_decisions', 'action_items', 'commentary_versions', 'audit_logs',
        'pipeline_runs', 'assertions_db', 'tool_result_cache', 'data_quality_snapshots',
        'policy_decision_logs', 'bridge_analysis_results', 'variance_snapshots',
        'root_cause_findings_db'
    ]::text[] LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = v_table
        ) THEN
            EXECUTE format(
                'UPDATE %I SET tenant_id = %L WHERE tenant_id IS NULL;',
                v_table, v_default_tenant
            );
            RAISE NOTICE '010 backfill %: tenant_id-boundary (no-op, NOT NULL)', v_table;
        END IF;
    END LOOP;

    -- 15 entity_id-boundary tables: add the column if missing, then backfill.
    FOREACH v_table IN ARRAY ARRAY[
        'entities', 'gl_accounts', 'trial_balance', 'budget_lines', 'forecast_lines',
        'actuals', 'headcount_data', 'vendor_invoices', 'sales_pipeline', 'agent_runs',
        'variances', 'root_causes', 'commentary_drafts', 'scenarios', 'review_logs'
    ]::text[] LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = v_table
        ) THEN
            EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS tenant_id text;', v_table);
            EXECUTE format(
                'UPDATE %I SET tenant_id = %L WHERE tenant_id IS NULL;',
                v_table, v_default_tenant
            );
            RAISE NOTICE '010 backfill %: tenant_id column added + backfilled', v_table;
        END IF;
    END LOOP;
END $$;

COMMIT;
