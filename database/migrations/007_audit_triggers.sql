-- 007_audit_triggers.sql: Create audit functions and triggers
-- Based on docs/12-database/audit.md

BEGIN;

-- ============================================================================
-- 1. Create trigger functions
-- ============================================================================

-- 1a: Prevent UPDATE/DELETE on append-only tables
CREATE OR REPLACE FUNCTION fn_prevent_update_delete()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Cannot UPDATE table %. This table is append-only.',
            TG_TABLE_NAME
            USING HINT = 'Insert a new record with the corrected values.';
    ELSIF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Cannot DELETE from table %. This table is append-only.',
            TG_TABLE_NAME
            USING HINT = 'Use status=''cancelled'' or similar soft-delete pattern.';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- 1b: Automatic audit logging for data changes
CREATE OR REPLACE FUNCTION fn_audit_data_change()
RETURNS trigger AS $$
DECLARE
    v_tenant_id TEXT;
    v_event_type TEXT;
    v_event_data JSONB;
BEGIN
    -- Determine tenant_id from the row
    v_tenant_id := COALESCE(
        NEW.tenant_id,
        NEW.entity_id,
        OLD.tenant_id,
        OLD.entity_id,
        current_setting('app.tenant_id', true)
    );

    IF TG_OP = 'INSERT' THEN
        v_event_type := 'row_inserted';
        v_event_data := jsonb_build_object(
            'table', TG_TABLE_NAME,
            'new', to_jsonb(NEW)
        );
    ELSIF TG_OP = 'UPDATE' THEN
        v_event_type := 'row_updated';
        v_event_data := jsonb_build_object(
            'table', TG_TABLE_NAME,
            'old', to_jsonb(OLD),
            'new', to_jsonb(NEW),
            'changed_columns', (
                SELECT jsonb_agg(key)
                FROM jsonb_each(to_jsonb(NEW)) n
                JOIN jsonb_each(to_jsonb(OLD)) o USING (key)
                WHERE n.value IS DISTINCT FROM o.value
            )
        );
    ELSIF TG_OP = 'DELETE' THEN
        v_event_type := 'row_deleted';
        v_event_data := jsonb_build_object(
            'table', TG_TABLE_NAME,
            'old', to_jsonb(OLD)
        );
    END IF;

    INSERT INTO audit_logs (
        id, tenant_id, period, event_type, event_data, user_id
    ) VALUES (
        gen_random_uuid()::text,
        v_tenant_id,
        COALESCE(NEW.period, OLD.period, to_char(NOW(), 'YYYY-MM')),
        v_event_type,
        v_event_data,
        current_setting('app.user_id', true)
    );

    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- 1c: Prevent physical DELETE on soft-delete-enabled tables
CREATE OR REPLACE FUNCTION fn_prevent_physical_delete()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Cannot physically DELETE from table %. Use UPDATE deleted_at instead.',
            TG_TABLE_NAME;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- 2. Apply append-only triggers (prevent UPDATE/DELETE)
-- ============================================================================

CREATE TRIGGER trg_prevent_update_delete_audit_logs
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_update_delete();

CREATE TRIGGER trg_prevent_update_delete_assertions
    BEFORE UPDATE OR DELETE ON assertions_db
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_update_delete();

CREATE TRIGGER trg_prevent_update_delete_var_snapshots
    BEFORE UPDATE OR DELETE ON variance_snapshots
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_update_delete();

CREATE TRIGGER trg_prevent_update_delete_findings
    BEFORE UPDATE OR DELETE ON root_cause_findings_db
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_update_delete();

CREATE TRIGGER trg_prevent_update_delete_bridge
    BEFORE UPDATE OR DELETE ON bridge_analysis_results
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_update_delete();

CREATE TRIGGER trg_prevent_update_delete_dq
    BEFORE UPDATE OR DELETE ON data_quality_snapshots
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_update_delete();

CREATE TRIGGER trg_prevent_update_delete_policy_logs
    BEFORE UPDATE OR DELETE ON policy_decision_logs
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_update_delete();

CREATE TRIGGER trg_prevent_update_delete_cache
    BEFORE UPDATE OR DELETE ON tool_result_cache
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_update_delete();

-- ============================================================================
-- 3. Apply audit triggers to mutable tables
-- ============================================================================

CREATE TRIGGER trg_audit_entities
    AFTER INSERT OR UPDATE OR DELETE ON entities
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_gl_accounts
    AFTER INSERT OR UPDATE OR DELETE ON gl_accounts
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_trial_balance
    AFTER INSERT OR UPDATE OR DELETE ON trial_balance
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_budget_lines
    AFTER INSERT OR UPDATE OR DELETE ON budget_lines
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_forecast_lines
    AFTER INSERT OR UPDATE OR DELETE ON forecast_lines
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_actuals
    AFTER INSERT OR UPDATE OR DELETE ON actuals
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_headcount
    AFTER INSERT OR UPDATE OR DELETE ON headcount_data
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_invoices
    AFTER INSERT OR UPDATE OR DELETE ON vendor_invoices
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_pipeline
    AFTER INSERT OR UPDATE OR DELETE ON sales_pipeline
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_agent_runs
    AFTER INSERT OR UPDATE OR DELETE ON agent_runs
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_variances
    AFTER INSERT OR UPDATE OR DELETE ON variances
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_root_causes
    AFTER INSERT OR UPDATE OR DELETE ON root_causes
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_commentary
    AFTER INSERT OR UPDATE OR DELETE ON commentary_drafts
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_scenarios
    AFTER INSERT OR UPDATE OR DELETE ON scenarios
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_review_logs
    AFTER INSERT OR UPDATE OR DELETE ON review_logs
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_review_decisions
    AFTER INSERT OR UPDATE OR DELETE ON review_decisions
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_action_items
    AFTER INSERT OR UPDATE OR DELETE ON action_items
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_commentary_v2
    AFTER INSERT OR UPDATE OR DELETE ON commentary_versions
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

CREATE TRIGGER trg_audit_pipeline_runs
    AFTER INSERT OR UPDATE OR DELETE ON pipeline_runs
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

-- ============================================================================
-- 4. Apply soft-delete support
-- ============================================================================

-- Add deleted_at columns for soft-delete
ALTER TABLE entities ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
ALTER TABLE gl_accounts ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP;

-- Partial indexes to exclude soft-deleted rows
CREATE INDEX IF NOT EXISTS idx_entities_active ON entities(id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_gl_accounts_active ON gl_accounts(id) WHERE deleted_at IS NULL;

-- Prevent physical DELETE on soft-delete-enabled tables
CREATE TRIGGER trg_prevent_delete_entities
    BEFORE DELETE ON entities
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_physical_delete();

CREATE TRIGGER trg_prevent_delete_gl_accounts
    BEFORE DELETE ON gl_accounts
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_physical_delete();

CREATE TRIGGER trg_prevent_delete_agent_runs
    BEFORE DELETE ON agent_runs
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_physical_delete();

COMMIT;

