-- 012_audit_event_type_idempotency.sql: admit IDEMPOTENCY_CONFLICT writes.
-- apps/api/webhooks.py persists event_type='IDEMPOTENCY_CONFLICT' on webhook
-- idempotency conflicts, but 003's chk_audit_event_type allowlist omits it,
-- so live conflicts crash with CheckViolation. This upgrade is idempotent:
-- on fresh DBs 003 creates the old constraint and this file widens it; on
-- already-migrated DBs 003 is skipped by version tracking and this file
-- performs the same widening. No other constraint is touched.
DO $$ BEGIN
    ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS chk_audit_event_type;
    ALTER TABLE audit_logs ADD CONSTRAINT chk_audit_event_type CHECK (event_type IN ('pipeline_started','pipeline_completed','pipeline_failed','assertion_created','assertion_validated','action_proposed','action_approved','action_rejected','commentary_submitted','commentary_reviewed','user_login','export_downloaded','config_changed','anomaly_detected','data_quality_alert','row_inserted','row_updated','row_deleted','rls_violation_attempted','admin_cross_tenant_access','IDEMPOTENCY_CONFLICT'));
END $$;
