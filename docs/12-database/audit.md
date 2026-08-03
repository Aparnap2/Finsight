# Append-Only Audit Trail

> **Layer:** 5 (Database Constraints)  
> **Scope:** Immutable audit logging for all financial data changes  
> **Design Principle:** Financial data must never be destroyed. All changes create a new record. Deletion is a logical operation (status = 'cancelled'), never a physical one.

---

## 1. Audit Log Table Schema

### 1.1 `audit_logs` — Application and Data Change Events

The `audit_logs` table already exists in the ORM. Below is the full DDL with constraints:

```sql
CREATE TABLE audit_logs (
    id              VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tenant_id       VARCHAR NOT NULL,
    period          VARCHAR(7) NOT NULL,
    event_type      VARCHAR NOT NULL,
    event_data      JSONB,
    user_id         VARCHAR,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT chk_audit_period_format
        CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$'),
    CONSTRAINT chk_audit_event_type
        CHECK (event_type IN (
            'pipeline_started', 'pipeline_completed', 'pipeline_failed',
            'assertion_created', 'assertion_validated',
            'action_proposed', 'action_approved', 'action_rejected',
            'commentary_submitted', 'commentary_reviewed',
            'user_login', 'export_downloaded', 'config_changed',
            'anomaly_detected', 'data_quality_alert',
            'row_inserted', 'row_updated', 'row_deleted',
            'rls_violation_attempted',
            'admin_cross_tenant_access'
        ))
);

-- Indexes for query patterns
CREATE INDEX idx_audit_tenant_event
    ON audit_logs(tenant_id, event_type, created_at DESC);
CREATE INDEX idx_audit_tenant_period
    ON audit_logs(tenant_id, period, created_at DESC);
CREATE INDEX idx_audit_user
    ON audit_logs(user_id, created_at DESC)
    WHERE user_id IS NOT NULL;

-- Partition by month for retention management
CREATE TABLE audit_logs_y2026m07
    PARTITION OF audit_logs
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
-- ... additional partitions created monthly via pg_partman or cron
```

### 1.2 Partition Strategy

| Partition key | Strategy | Rationale |
|---------------|----------|-----------|
| `created_at` | Range (monthly) | Enables efficient retention — drop old partitions instead of DELETE |
| Retention | 7 years (regulatory) | Partition drop after 84 months |
| Future-proofing | Automated monthly partition creation via `pg_partman` | |

---

## 2. Trigger Functions for Audit

### 2.1 BEFORE UPDATE Trigger — Prevent Physical Updates

All financial tables must have a trigger that **blocks** UPDATE operations on immutable records. If the application needs to change a value, it must INSERT a new version and mark the old one as superseded.

**Pattern: "No updates, no deletes" for append-only tables:**

```sql
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
    RETURN NULL;  -- Never reached
END;
$$ LANGUAGE plpgsql;
```

### 2.2 Apply to Append-Only Tables

These tables must be truly append-only (no UPDATE, no DELETE):

```sql
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
    FOR Each ROW EXECUTE FUNCTION fn_prevent_update_delete();

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
```

### 2.3 Automatic Audit Logging Trigger

For tables that ARE mutable (financial data), log all changes to `audit_logs`:

```sql
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
```

### 2.4 Tables to Audit

| Table | Audit? | Trigger | Reason |
|-------|--------|---------|--------|
| `entities` | Yes | `trg_audit_entities` | Entity master data |
| `gl_accounts` | Yes | `trg_audit_gl_accounts` | Chart of accounts changes |
| `trial_balance` | Yes | `trg_audit_trial_balance` | Financial statements |
| `budget_lines` | Yes | `trg_audit_budget_lines` | Budget changes |
| `forecast_lines` | Yes | `trg_audit_forecast_lines` | Forecast versioning |
| `actuals` | Yes | `trg_audit_actuals` | Actual financial data |
| `headcount_data` | Yes | `trg_audit_headcount` | People costs |
| `vendor_invoices` | Yes | `trg_audit_invoices` | AP data |
| `sales_pipeline` | Yes | `trg_audit_pipeline` | Revenue forecast |
| `agent_runs` | Yes | `trg_audit_agent_runs` | AI pipeline execution |
| `variances` | Yes | `trg_audit_variances` | Variance analysis |
| `root_causes` | Yes | `trg_audit_root_causes` | Root cause findings |
| `commentary_drafts` | Yes | `trg_audit_commentary` | Commentary versions |
| `scenarios` | Yes | `trg_audit_scenarios` | What-if modeling |
| `review_logs` | Yes | `trg_audit_review_logs` | Review decisions |
| `review_decisions` | Yes | `trg_audit_review_decisions` | Assertion review |
| `action_items` | Yes | `trg_audit_action_items` | Action item lifecycle |
| `commentary_versions` | Yes | `trg_audit_commentary_v2` | Versioned commentary |
| `pipeline_runs` | Yes | `trg_audit_pipeline_runs` | Pipeline executions |
| `audit_logs` | **No** | `trg_prevent_update_delete` | Immutable by design |
| `assertions_db` | **No** | `trg_prevent_update_delete` | Append-only |
| `tool_result_cache` | **No** | `trg_prevent_update_delete` | Cache, not financial data |
| `data_quality_snapshots` | **No** | `trg_prevent_update_delete` | Append-only snapshots |
| `policy_decision_logs` | **No** | `trg_prevent_update_delete` | Append-only decisions |
| `bridge_analysis_results` | **No** | `trg_prevent_update_delete` | Append-only analysis |
| `variance_snapshots` | **No** | `trg_prevent_update_delete` | Append-only snapshots |
| `root_cause_findings_db` | **No** | `trg_prevent_update_delete` | Append-only findings |

**Install audit triggers on all mutable tables:**

```sql
-- Template: apply to each table
CREATE TRIGGER trg_audit_entities
    AFTER INSERT OR UPDATE OR DELETE ON entities
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

-- Repeat for: gl_accounts, trial_balance, budget_lines, forecast_lines,
-- actuals, headcount_data, vendor_invoices, sales_pipeline, agent_runs,
-- variances, root_causes, commentary_drafts, scenarios, review_logs,
-- review_decisions, action_items, commentary_versions, pipeline_runs
```

---

## 3. Soft-Delete Pattern for Mutable Tables

### 3.1 Tables That Support Soft-Delete

Some tables need logical deletion via status change rather than physical DELETE:

```sql
-- Add deleted_at column for soft-delete support
ALTER TABLE entities ADD COLUMN deleted_at TIMESTAMPTZ;
ALTER TABLE gl_accounts ADD COLUMN deleted_at TIMESTAMPTZ;
ALTER TABLE agent_runs ADD COLUMN deleted_at TIMESTAMPTZ;

-- Partial index to exclude soft-deleted rows from queries
CREATE INDEX idx_entities_active ON entities(id)
    WHERE deleted_at IS NULL;
CREATE INDEX idx_gl_accounts_active ON gl_accounts(id)
    WHERE deleted_at IS NULL;
```

### 3.2 Soft-Delete Validation Trigger

Prevent physical DELETE on soft-delete-enabled tables:

```sql
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

CREATE TRIGGER trg_prevent_delete_entities
    BEFORE DELETE ON entities
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_physical_delete();

-- Apply to gl_accounts, agent_runs
```

---

## 4. Data Retention and Partitioning

### 4.1 Retention Policy

| Data Category | Retention | Action at Expiry |
|---------------|-----------|------------------|
| Audit logs | 7 years | Drop monthly partition |
| Financial data (trial_balance, actuals, budget) | 10 years | Archive to cold storage |
| Agent run logs | 2 years | Drop partition |
| Forecast versions | 3 years | Keep latest version only |
| Cache entries | 24 hours | Automatic expiry + cleanup |
| Snapshots (variance, bridge, DQ) | 3 years | Drop partition |

### 4.2 Automated Partition Management

```sql
-- Requires pg_partman extension
CREATE EXTENSION IF NOT EXISTS pg_partman;

SELECT partman.create_parent(
    p_parent_table := 'public.audit_logs',
    p_control := 'created_at',
    p_type := 'native',
    p_interval := '1 month',
    p_premake := 3
);

-- Retention: drop partitions older than 7 years (84 months)
SELECT partman.undo_partition(
    p_parent_table := 'public.audit_logs',
    p_retention := '84 months',
    p_keep_table := false  -- Drop the partition, don't detach
);
```

---

## 5. Monitoring and Alerting

### 5.1 Audit Log Bloat Detection

```sql
-- Check audit log size by partition
SELECT
    schemaname || '.' || tablename AS table_name,
    pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) AS total_size,
    pg_size_pretty(pg_relation_size(schemaname || '.' || tablename)) AS table_size,
    pg_size_pretty(pg_indexes_size(schemaname || '.' || tablename)) AS index_size
FROM pg_tables
WHERE tablename LIKE 'audit_logs%'
ORDER BY tablename;
```

### 5.2 Unauthorized Delete Attempt Alert

```sql
-- Monitor for blocked DELETE attempts on append-only tables
SELECT
    aud.tenant_id,
    aud.event_data->>'table' AS target_table,
    aud.user_id,
    aud.created_at
FROM audit_logs aud
WHERE aud.event_type = 'rls_violation_attempted'
  AND aud.created_at >= NOW() - INTERVAL '24 hours'
ORDER BY aud.created_at DESC;
```

### 5.3 Orphaned Record Detection

```sql
-- Find rows deleted via soft-delete that are still referenced
SELECT
    'gl_accounts' AS table_name,
    ga.id,
    ga.deleted_at
FROM gl_accounts ga
WHERE ga.deleted_at IS NOT NULL
  AND EXISTS (
      SELECT 1 FROM trial_balance tb
      WHERE tb.account_id = ga.id
        AND tb.period >= to_char(ga.deleted_at - INTERVAL '3 months', 'YYYY-MM')
  );
```

---

## 6. Compliance

### 6.1 SOX Compliance Requirements

| Requirement | Implementation |
|-------------|---------------|
| All financial data changes logged | `fn_audit_data_change()` on all financial tables |
| No data destruction | `fn_prevent_update_delete()` on append-only tables, `fn_prevent_physical_delete()` on soft-delete tables |
| User attribution | `app.user_id` session variable recorded in every audit log |
| Tamper-evident | Audit logs are append-only; no UPDATE/DELETE allowed |
| Retention period | 7 years for audit logs, 10 years for financial data |
| Regular review | Monthly automated partition audit |

### 6.2 GDPR Compliance

```sql
-- GDPR: anonymize user references in audit logs after retention
CREATE OR REPLACE FUNCTION fn_gdpr_anonymize_user(p_user_id TEXT)
RETURNS void AS $$
BEGIN
    UPDATE audit_logs
    SET event_data = jsonb_set(
        event_data,
        '{user_id}',
        '"REDACTED"'
    )
    WHERE user_id = p_user_id
      AND created_at < NOW() - INTERVAL '7 years';
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

---

## 7. Audit Appendix: DDL for Audit Functions and Triggers

### 7.1 Complete Setup Script

```sql
-- 1. Create extension
CREATE EXTENSION IF NOT EXISTS pg_partman;

-- 2. Create audit functions
-- (fn_prevent_update_delete, fn_audit_data_change, fn_prevent_physical_delete as above)

-- 3. Create partitioned audit_logs table
-- (DDL from §1.1)

-- 4. Enable RLS on audit_logs
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY p_audit_isolation ON audit_logs
    FOR ALL
    USING (tenant_id = current_setting('app.tenant_id')::text);

-- 5. Apply append-only trigger to immutable tables
-- (from §2.2)

-- 6. Apply audit triggers to mutable tables
-- (from §2.4)

-- 7. Apply soft-delete support
-- (from §3)

-- 8. Set up partition management
SELECT partman.create_parent('public.audit_logs', 'created_at', 'native', '1 month', p_premake := 3);
```

### 7.2 Rollback Script

```sql
-- Remove all audit triggers
DROP TRIGGER IF EXISTS trg_audit_entities ON entities;
-- ... repeat for all tables ...

-- Remove append-only triggers
DROP TRIGGER IF EXISTS trg_prevent_update_delete_audit_logs ON audit_logs;
-- ... repeat ...

-- Remove functions
DROP FUNCTION IF EXISTS fn_audit_data_change();
DROP FUNCTION IF EXISTS fn_prevent_update_delete();
DROP FUNCTION IF EXISTS fn_prevent_physical_delete();
DROP FUNCTION IF EXISTS fn_gdpr_anonymize_user(text);

-- Drop partition management
SELECT partman.undo_partition('public.audit_logs', 0);
DROP EXTENSION IF EXISTS pg_partman;
```
