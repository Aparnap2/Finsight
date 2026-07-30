# Migration Plan — Applying PostgreSQL Enforcement Layer

> **Layer:** 5 (Database Constraints)  
> **Scope:** Applying all constraints, RLS, audit, and security changes to an existing database  
> **Design Principle:** Zero-downtime where possible. Always have a rollback plan.

---

## 1. Migration Sequence Overview

The migration is organized into 10 phases, each designed to be independently verifiable and reversible.

```
Phase  1: Extensions and Infrastructure
Phase  2: GENERATED Columns
Phase  3: NOT NULL Constraints
Phase  4: CHECK Constraints
Phase  5: UNIQUE Constraints
Phase  6: FOREIGN KEY Enforcement
Phase  7: Partial Indexes
Phase  8: State Machine Triggers
Phase  9: Audit Triggers
Phase 10: Row-Level Security
```

**Total estimated objects:** ~120 constraints, 10 triggers, 27 RLS policies.

---

## 2. Phase 1 — Extensions and Infrastructure

### 2.1 Required Extensions

```sql
BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";       -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "btree_gist";      -- EXCLUDE constraints for state machines
CREATE EXTENSION IF NOT EXISTS "pg_partman";       -- Automated partition management

COMMIT;
```

**Risk:** `btree_gist` is well-tested; `pg_partman` is optional (only needed for automated audit log partitioning).

**Rollback:**
```sql
DROP EXTENSION IF EXISTS pg_partman;
DROP EXTENSION IF EXISTS btree_gist;
-- pgcrypto cannot be dropped if columns depend on it
```

### 2.2 Session Variable Functions

```sql
BEGIN;

-- Create helper functions for setting session context
-- (used by RLS and audit triggers)

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
```

---

## 3. Phase 2 — GENERATED Columns

### 3.1 `trial_balance.balance`

```sql
BEGIN;

-- Step 1: Validate existing data consistency
DO $$
DECLARE
    v_count INT;
BEGIN
    SELECT COUNT(*) INTO v_count FROM trial_balance
    WHERE balance IS DISTINCT FROM (debit - credit);

    IF v_count > 0 THEN
        RAISE EXCEPTION 'Found % rows where balance != debit - credit. Fix data before adding GENERATED column.', v_count;
    END IF;
END $$;

-- Step 2: Drop existing balance column (application must NOT write to it)
-- WARNING: This is a breaking change. Coordinate with application deploy.
ALTER TABLE trial_balance DROP COLUMN balance;

-- Step 3: Add GENERATED column
ALTER TABLE trial_balance
    ADD COLUMN balance NUMERIC(15, 2)
    GENERATED ALWAYS AS (debit - credit) STORED;

COMMIT;
```

**Zero-downtime strategy:**
1. Deploy application code that reads `balance` but does not write to it
2. Add the GENERATED column
3. Remove application writes to `balance` (already covered in step 1)

### 3.2 `variances.variance_amount` and `variances.variance_pct`

```sql
BEGIN;

-- Validate existing data
DO $$
DECLARE
    v_count INT;
BEGIN
    SELECT COUNT(*) INTO v_count FROM variances
    WHERE variance_amount IS DISTINCT FROM (actual_amount - budget_amount);

    IF v_count > 0 THEN
        RAISE EXCEPTION 'Found % rows where variance_amount is inconsistent.', v_count;
    END IF;
END $$;

-- Drop and recreate as GENERATED columns
ALTER TABLE variances DROP COLUMN variance_amount;
ALTER TABLE variances DROP COLUMN variance_pct;

ALTER TABLE variances
    ADD COLUMN variance_amount NUMERIC(15, 2)
    GENERATED ALWAYS AS (actual_amount - budget_amount) STORED;

ALTER TABLE variances
    ADD COLUMN variance_pct NUMERIC(8, 4)
    GENERATED ALWAYS AS (
        CASE WHEN budget_amount != 0
            THEN (actual_amount - budget_amount) / NULLIF(budget_amount, 0)
            ELSE NULL
        END
    ) STORED;

COMMIT;
```

**Rollback:**
```sql
ALTER TABLE trial_balance DROP COLUMN balance;
ALTER TABLE trial_balance ADD COLUMN balance NUMERIC(15, 2);
-- (application will need to recompute balance on writes)

ALTER TABLE variances DROP COLUMN variance_amount;
ALTER TABLE variances DROP COLUMN variance_pct;
ALTER TABLE variances ADD COLUMN variance_amount NUMERIC(15, 2);
ALTER TABLE variances ADD COLUMN variance_pct NUMERIC(8, 4);
```

---

## 4. Phase 3 — NOT NULL Constraints

### 4.1 Validate Existing Data First

```sql
-- Find NULL values before adding NOT NULL constraints
DO $$
DECLARE
    violations TEXT[];
    v_count INT;
BEGIN
    -- Check each table systematically
    SELECT COUNT(*) INTO v_count FROM entities WHERE name IS NULL;
    IF v_count > 0 THEN violations := violations || format('entities.name: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM gl_accounts WHERE entity_id IS NULL;
    IF v_count > 0 THEN violations := violations || format('gl_accounts.entity_id: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM trial_balance WHERE period IS NULL;
    IF v_count > 0 THEN violations := violations || format('trial_balance.period: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM budget_lines WHERE amount IS NULL;
    IF v_count > 0 THEN violations := violations || format('budget_lines.amount: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM forecast_lines WHERE amount IS NULL OR version IS NULL;
    IF v_count > 0 THEN violations := violations || format('forecast_lines.amount/version: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM actuals WHERE amount IS NULL;
    IF v_count > 0 THEN violations := violations || format('actuals.amount: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM vendor_invoices WHERE amount IS NULL OR invoice_date IS NULL;
    IF v_count > 0 THEN violations := violations || format('vendor_invoices: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM sales_pipeline WHERE stage IS NULL OR expected_close_date IS NULL;
    IF v_count > 0 THEN violations := violations || format('sales_pipeline: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM agent_runs WHERE status IS NULL OR started_at IS NULL;
    IF v_count > 0 THEN violations := violations || format('agent_runs: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM variances WHERE agent_run_id IS NULL OR account_id IS NULL;
    IF v_count > 0 THEN violations := violations || format('variances: %s nulls', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM root_causes WHERE variance_id IS NULL OR summary IS NULL;
    IF v_count > 0 THEN violations := violations || format('root_causes: %s nulls', v_count); END IF;

    IF array_length(violations, 1) > 0 THEN
        RAISE WARNING 'NOT NULL violations found: %', array_to_string(violations, '; ');
    ELSE
        RAISE NOTICE 'All NOT NULL checks pass — proceeding with constraints.';
    END IF;
END $$;
```

### 4.2 NOT NULL Migration Template

For each column, run:

```sql
BEGIN;

-- Strategy 1: Fill nulls with default values (when safe)
UPDATE trial_balance SET debit = 0 WHERE debit IS NULL;
UPDATE trial_balance SET credit = 0 WHERE credit IS NULL;
UPDATE headcount_data SET headcount = 0 WHERE headcount IS NULL;
UPDATE headcount_data SET total_compensation = 0 WHERE total_compensation IS NULL;
UPDATE headcount_data SET new_hires = 0 WHERE new_hires IS NULL;
UPDATE headcount_data SET departures = 0 WHERE departures IS NULL;

-- Strategy 2: Backfill from related data (when possible)
UPDATE agent_runs
SET entity_id = COALESCE(
    (SELECT entity_id FROM trial_balance tb WHERE tb.entity_id = agent_runs.entity_id LIMIT 1),
    'default_entity'
)
WHERE entity_id IS NULL;

-- Strategy 3: Delete orphaned records (last resort)
DELETE from variances WHERE agent_run_id IS NULL;

COMMIT;
```

### 4.3 Apply NOT NULL Constraints

```sql
BEGIN;

-- Template for each table
ALTER TABLE entities
    ALTER COLUMN name SET NOT NULL,
    ALTER COLUMN currency SET NOT NULL,
    ALTER COLUMN fiscal_year_start SET NOT NULL;

ALTER TABLE gl_accounts
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN account_number SET NOT NULL,
    ALTER COLUMN account_name SET NOT NULL,
    ALTER COLUMN account_type SET NOT NULL;

ALTER TABLE trial_balance
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN account_id SET NOT NULL,
    ALTER COLUMN debit SET NOT NULL,
    ALTER COLUMN credit SET NOT NULL;

ALTER TABLE budget_lines
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN account_id SET NOT NULL,
    ALTER COLUMN amount SET NOT NULL;

ALTER TABLE forecast_lines
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN account_id SET NOT NULL,
    ALTER COLUMN amount SET NOT NULL,
    ALTER COLUMN version SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE actuals
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN account_id SET NOT NULL,
    ALTER COLUMN amount SET NOT NULL;

ALTER TABLE headcount_data
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN department SET NOT NULL,
    ALTER COLUMN headcount SET NOT NULL,
    ALTER COLUMN total_compensation SET NOT NULL,
    ALTER COLUMN new_hires SET NOT NULL,
    ALTER COLUMN departures SET NOT NULL;

ALTER TABLE vendor_invoices
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN vendor_name SET NOT NULL,
    ALTER COLUMN account_id SET NOT NULL,
    ALTER COLUMN amount SET NOT NULL,
    ALTER COLUMN invoice_date SET NOT NULL,
    ALTER COLUMN status SET NOT NULL;

ALTER TABLE sales_pipeline
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN deal_name SET NOT NULL,
    ALTER COLUMN stage SET NOT NULL,
    ALTER COLUMN expected_close_date SET NOT NULL,
    ALTER COLUMN amount SET NOT NULL;

ALTER TABLE agent_runs
    ALTER COLUMN entity_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN started_at SET NOT NULL;

ALTER TABLE variances
    ALTER COLUMN agent_run_id SET NOT NULL,
    ALTER COLUMN account_id SET NOT NULL,
    ALTER COLUMN actual_amount SET NOT NULL,
    ALTER COLUMN budget_amount SET NOT NULL,
    ALTER COLUMN is_material SET NOT NULL,
    ALTER COLUMN classification SET NOT NULL;

ALTER TABLE root_causes
    ALTER COLUMN variance_id SET NOT NULL,
    ALTER COLUMN summary SET NOT NULL;

ALTER TABLE commentary_drafts
    ALTER COLUMN agent_run_id SET NOT NULL,
    ALTER COLUMN version SET NOT NULL,
    ALTER COLUMN status SET NOT NULL;

ALTER TABLE scenarios
    ALTER COLUMN agent_run_id SET NOT NULL,
    ALTER COLUMN name SET NOT NULL;

ALTER TABLE review_logs
    ALTER COLUMN agent_run_id SET NOT NULL,
    ALTER COLUMN checkpoint SET NOT NULL,
    ALTER COLUMN reviewer SET NOT NULL,
    ALTER COLUMN decision SET NOT NULL;

ALTER TABLE review_decisions
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN assertion_id SET NOT NULL,
    ALTER COLUMN decision SET NOT NULL,
    ALTER COLUMN reviewer SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE action_items
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN action SET NOT NULL,
    ALTER COLUMN domain SET NOT NULL,
    ALTER COLUMN target SET NOT NULL,
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET NOT NULL;

ALTER TABLE commentary_versions
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN version SET NOT NULL,
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE audit_logs
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN event_type SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE pipeline_runs
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN status SET NOT NULL,
    ALTER COLUMN started_at SET NOT NULL;

ALTER TABLE assertions_db
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN assertion_id SET NOT NULL,
    ALTER COLUMN type SET NOT NULL,
    ALTER COLUMN text SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE tool_result_cache
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN tool_name SET NOT NULL,
    ALTER COLUMN query_fingerprint SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN expires_at SET NOT NULL;

ALTER TABLE data_quality_snapshots
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN overall_score SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE policy_decision_logs
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN autonomy_level SET NOT NULL,
    ALTER COLUMN routing_target SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE bridge_analysis_results
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE variance_snapshots
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN is_material SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE root_cause_findings_db
    ALTER COLUMN tenant_id SET NOT NULL,
    ALTER COLUMN period SET NOT NULL,
    ALTER COLUMN created_at SET NOT NULL;

COMMIT;
```

---

## 5. Phase 4 — CHECK Constraints

### 5.1 Validate Existing Data

```sql
BEGIN;

-- Find CHECK constraint violations before adding them
DO $$
DECLARE
    v_count INT;
BEGIN
    -- Period format violations
    SELECT COUNT(*) INTO v_count FROM trial_balance WHERE period !~ '^\d{4}-(0[1-9]|1[0-2])$';
    IF v_count > 0 THEN RAISE WARNING 'trial_balance: % rows with invalid period format', v_count; END IF;

    -- Amount violations
    SELECT COUNT(*) INTO v_count FROM vendor_invoices WHERE amount <= 0;
    IF v_count > 0 THEN RAISE WARNING 'vendor_invoices: % rows with non-positive amount', v_count; END IF;

    -- Status violations
    SELECT COUNT(*) INTO v_count FROM agent_runs WHERE status NOT IN ('pending', 'running', 'completed', 'failed', 'cancelled');
    IF v_count > 0 THEN RAISE WARNING 'agent_runs: % rows with invalid status', v_count; END IF;

    -- Timestamp violations
    SELECT COUNT(*) INTO v_count FROM agent_runs WHERE completed_at IS NOT NULL AND completed_at <= started_at;
    IF v_count > 0 THEN RAISE WARNING 'agent_runs: % rows with completed_at <= started_at', v_count; END IF;

    -- Confidence violations
    SELECT COUNT(*) INTO v_count FROM variances WHERE confidence_score < 0 OR confidence_score > 1;
    IF v_count > 0 THEN RAISE WARNING 'variances: % rows with out-of-range confidence', v_count; END IF;

    RAISE NOTICE 'Validation complete. Fix violations before adding constraints.';
END $$;

COMMIT;
```

### 5.2 Fix Violations

```sql
BEGIN;

-- Fix invalid period formats (example: '2026-7' → '2026-07')
UPDATE trial_balance
SET period = regexp_replace(period, '^(\d{4})-(\d)$', '\1-0\2')
WHERE period ~ '^\d{4}-\d$';

-- Fix non-positive invoice amounts (flag for manual review)
UPDATE vendor_invoices
SET amount = ABS(amount)
WHERE amount < 0;

-- Fix invalid statuses (map to nearest valid status)
UPDATE agent_runs
SET status = 'failed'
WHERE status NOT IN ('pending', 'running', 'completed', 'failed', 'cancelled');

-- Fix timestamp order
UPDATE agent_runs
SET completed_at = started_at + INTERVAL '1 second'
WHERE completed_at IS NOT NULL AND completed_at <= started_at;

-- Fix out-of-range confidence
UPDATE variances
SET confidence_score = GREATEST(0, LEAST(1, confidence_score))
WHERE confidence_score < 0 OR confidence_score > 1;

COMMIT;
```

### 5.3 Apply CHECK Constraints

All CHECK constraints are defined in [`constraints.md`](./constraints.md), sections 1.1–1.27. Apply them in order:

```sql
BEGIN;

-- Period format (apply to every table with period)
ALTER TABLE trial_balance ADD CONSTRAINT chk_tb_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
ALTER TABLE budget_lines ADD CONSTRAINT chk_budget_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
ALTER TABLE forecast_lines ADD CONSTRAINT chk_forecast_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
ALTER TABLE actuals ADD CONSTRAINT chk_actuals_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
ALTER TABLE headcount_data ADD CONSTRAINT chk_hc_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
ALTER TABLE vendor_invoices ADD CONSTRAINT chk_invoice_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
ALTER TABLE sales_pipeline ADD CONSTRAINT chk_pipeline_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
ALTER TABLE agent_runs ADD CONSTRAINT chk_agentrun_period_format CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$');
-- ... (audit_logs, pipeline_runs, etc.)

-- Monetary amount constraints
ALTER TABLE vendor_invoices ADD CONSTRAINT chk_invoice_amount_positive CHECK (amount > 0);
ALTER TABLE sales_pipeline ADD CONSTRAINT chk_pipeline_amount_positive CHECK (amount > 0);
ALTER TABLE budget_lines ADD CONSTRAINT chk_budget_amount_non_zero CHECK (amount != 0);
ALTER TABLE forecast_lines ADD CONSTRAINT chk_forecast_amount_non_zero CHECK (amount != 0);
ALTER TABLE actuals ADD CONSTRAINT chk_actuals_amount_non_zero CHECK (amount != 0);
ALTER TABLE trial_balance ADD CONSTRAINT chk_tb_debit_non_negative CHECK (debit >= 0);
ALTER TABLE trial_balance ADD CONSTRAINT chk_tb_credit_non_negative CHECK (credit >= 0);

-- Status enum constraints
ALTER TABLE vendor_invoices ADD CONSTRAINT chk_invoice_status
    CHECK (status IN ('draft', 'submitted', 'approved', 'paid', 'cancelled', 'disputed'));
ALTER TABLE sales_pipeline ADD CONSTRAINT chk_pipeline_stage
    CHECK (stage IN ('prospecting', 'qualification', 'proposal', 'negotiation', 'closed_won', 'closed_lost'));
ALTER TABLE agent_runs ADD CONSTRAINT chk_agentrun_status
    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'));
-- ... (all other status enums)

-- Confidence range constraints
ALTER TABLE variances ADD CONSTRAINT chk_var_confidence
    CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1));
ALTER TABLE root_causes ADD CONSTRAINT chk_rc_confidence
    CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1));
-- ... (all other confidence columns)

COMMIT;
```

---

## 6. Phase 5 — UNIQUE Constraints

### 6.1 Validate Existing Data for Uniqueness

```sql
BEGIN;

-- Find duplicate records before adding UNIQUE constraints
DO $$
DECLARE
    v_count INT;
BEGIN
    SELECT COUNT(*) - COUNT(DISTINCT (entity_id, period, account_id)) INTO v_count
    FROM trial_balance;
    IF v_count > 0 THEN RAISE WARNING 'trial_balance: % duplicate (entity, period, account) combinations', v_count; END IF;

    SELECT COUNT(*) - COUNT(DISTINCT (entity_id, account_number)) INTO v_count
    FROM gl_accounts;
    IF v_count > 0 THEN RAISE WARNING 'gl_accounts: % duplicate account numbers per entity', v_count; END IF;

    RAISE NOTICE 'Uniqueness validation complete.';
END $$;

COMMIT;
```

### 6.2 Deduplication Strategy

```sql
BEGIN;

-- Deduplicate trial_balance: keep the row with the latest balance
DELETE FROM trial_balance
WHERE id IN (
    SELECT id FROM (
        SELECT id, ROW_NUMBER() OVER (
            PARTITION BY entity_id, period, account_id
            ORDER BY GREATEST(debit, credit) DESC
        ) AS rn
        FROM trial_balance
    ) sub WHERE rn > 1
);

-- Deduplicate gl_accounts: keep the one with the name
DELETE FROM gl_accounts
WHERE id IN (
    SELECT id FROM (
        SELECT id, ROW_NUMBER() OVER (
            PARTITION BY entity_id, account_number
            ORDER BY created_at DESC NULLS LAST
        ) AS rn
        FROM gl_accounts
    ) sub WHERE rn > 1
);

COMMIT;
```

### 6.3 Apply UNIQUE Constraints

```sql
BEGIN;

ALTER TABLE gl_accounts ADD CONSTRAINT uq_gl_accounts_entity_number UNIQUE (entity_id, account_number);
ALTER TABLE trial_balance ADD CONSTRAINT uq_tb_period_account UNIQUE (entity_id, period, account_id);
-- ... all other UNIQUE constraints from constraints.md

COMMIT;
```

---

## 7. Phase 6 — FOREIGN KEY Enforcement

### 7.1 Orphaned Record Detection

```sql
BEGIN;

DO $$
DECLARE
    violations TEXT[];
    v_count INT;
BEGIN
    SELECT COUNT(*) INTO v_count FROM gl_accounts ga WHERE NOT EXISTS (SELECT 1 FROM entities e WHERE e.id = ga.entity_id);
    IF v_count > 0 THEN violations := violations || format('gl_accounts: %d orphaned entity_id', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM trial_balance tb WHERE NOT EXISTS (SELECT 1 FROM entities e WHERE e.id = tb.entity_id);
    IF v_count > 0 THEN violations := violations || format('trial_balance: %d orphaned entity_id', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM trial_balance tb WHERE NOT EXISTS (SELECT 1 FROM gl_accounts ga WHERE ga.id = tb.account_id);
    IF v_count > 0 THEN violations := violations || format('trial_balance: %d orphaned account_id', v_count); END IF;

    SELECT COUNT(*) INTO v_count FROM variances v WHERE NOT EXISTS (SELECT 1 FROM agent_runs ar WHERE ar.id = v.agent_run_id);
    IF v_count > 0 THEN violations := violations || format('variances: %d orphaned agent_run_id', v_count); END IF;

    IF array_length(violations, 1) > 0 THEN
        RAISE WARNING 'Foreign key violations found: %', array_to_string(violations, '; ');
    ELSE
        RAISE NOTICE 'All foreign key checks pass.';
    END IF;
END $$;

COMMIT;
```

### 7.2 Orphan Remediation

```sql
BEGIN;

-- Option A: Delete orphans (if data is unrecoverable)
DELETE FROM variances WHERE NOT EXISTS (SELECT 1 FROM agent_runs ar WHERE ar.id = variances.agent_run_id);

-- Option B: Set to NULL (if FK is nullable)
UPDATE variances SET agent_run_id = NULL WHERE NOT EXISTS (SELECT 1 FROM agent_runs ar WHERE ar.id = variances.agent_run_id);

-- Option C: Create placeholder parent
INSERT INTO entities (id, name, currency, fiscal_year_start)
SELECT DISTINCT entity_id, 'Orphaned Entity', 'USD', '01-01'
FROM trial_balance tb
WHERE NOT EXISTS (SELECT 1 FROM entities e WHERE e.id = tb.entity_id);

COMMIT;
```

---

## 8. Phase 7 — Partial Indexes

### 8.1 Create All Partial Indexes

```sql
BEGIN;

-- Performance indexes (no data validation needed)
CREATE INDEX idx_tb_non_zero ON trial_balance(entity_id, period) WHERE debit != 0 OR credit != 0;
CREATE INDEX idx_invoices_status ON vendor_invoices(status) WHERE status IN ('draft', 'submitted', 'disputed');
CREATE INDEX idx_pipeline_active ON sales_pipeline(entity_id) WHERE stage NOT IN ('closed_won', 'closed_lost');
CREATE INDEX idx_agentrun_active ON agent_runs(entity_id, period) WHERE status IN ('pending', 'running');
CREATE INDEX idx_var_material ON variances(agent_run_id) WHERE is_material = true;
CREATE INDEX idx_action_items_open ON action_items(tenant_id, period) WHERE status IN ('proposed', 'approved', 'in_progress', 'blocked');
CREATE INDEX idx_cache_expires ON tool_result_cache(expires_at) WHERE expires_at < NOW() + INTERVAL '1 hour';
CREATE INDEX idx_pipeline_runs_active ON pipeline_runs(tenant_id, period) WHERE status IN ('pending', 'running');
CREATE INDEX idx_var_snapshots_material ON variance_snapshots(tenant_id, period) WHERE is_material = true;
CREATE INDEX idx_audit_logs_event_type ON audit_logs(tenant_id, event_type, created_at DESC);

-- Unique partial indexes for nullable department columns
CREATE UNIQUE INDEX uq_budget_with_dept ON budget_lines(entity_id, period, account_id, department) WHERE department IS NOT NULL;
CREATE UNIQUE INDEX uq_budget_without_dept ON budget_lines(entity_id, period, account_id) WHERE department IS NULL;
-- ... repeat for actuals, forecast_lines

COMMIT;
```

**Zero-downtime:** Index creation with `CONCURRENTLY`:

```sql
-- For large tables, create indexes CONCURRENTLY to avoid table locks
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tb_non_zero
    ON trial_balance(entity_id, period)
    WHERE debit != 0 OR credit != 0;
```

**Note:** `CREATE INDEX CONCURRENTLY` cannot run inside a transaction block.

---

## 9. Phase 8 — State Machine Triggers

### 9.1 Create All Trigger Functions

```sql
BEGIN;

-- All state machine trigger functions (defined in constraints.md §3)
-- fn_enforce_invoice_status_transition()
-- fn_enforce_agentrun_status_transition()
-- fn_enforce_action_status_transition()
-- fn_enforce_pipeline_status_transition()
-- fn_enforce_commentary_status_transition()

-- Apply triggers
CREATE TRIGGER trg_enforce_invoice_status
    BEFORE UPDATE ON vendor_invoices
    FOR EACH ROW
    EXECUTE FUNCTION fn_enforce_invoice_status_transition();

CREATE TRIGGER trg_enforce_agentrun_status
    BEFORE UPDATE ON agent_runs
    FOR EACH ROW
    EXECUTE FUNCTION fn_enforce_agentrun_status_transition();

CREATE TRIGGER trg_enforce_action_status
    BEFORE UPDATE ON action_items
    FOR EACH ROW
    EXECUTE FUNCTION fn_enforce_action_status_transition();

COMMIT;
```

**Validation:**
```sql
-- Test each state machine (see constraints.md §5.2)
BEGIN;
SAVEPOINT test_transition;
UPDATE vendor_invoices SET status = 'submitted' WHERE status = 'draft' LIMIT 1;  -- Should succeed
UPDATE vendor_invoices SET status = 'draft' WHERE status = 'submitted' LIMIT 1;  -- Should fail
ROLLBACK TO test_transition;
COMMIT;
```

---

## 10. Phase 9 — Audit Triggers

### 10.1 Create Audit Functions and Triggers

```sql
BEGIN;

-- Create fn_audit_data_change() (see audit.md §2.3)
-- Create fn_prevent_update_delete() (see audit.md §2.1)
-- Create fn_prevent_physical_delete() (see audit.md §3.2)

-- Apply append-only triggers to immutable tables
CREATE TRIGGER trg_prevent_update_delete_audit_logs
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION fn_prevent_update_delete();

-- ... repeat for all immutable tables

-- Apply audit triggers to mutable tables
CREATE TRIGGER trg_audit_entities
    AFTER INSERT OR UPDATE OR DELETE ON entities
    FOR EACH ROW EXECUTE FUNCTION fn_audit_data_change();

-- ... repeat for all mutable tables

COMMIT;
```

---

## 11. Phase 10 — Row-Level Security

### 11.1 Enable RLS on All Tables

```sql
BEGIN;

-- Enable RLS (must be done before creating policies)
ALTER TABLE entities ENABLE ROW LEVEL SECURITY;
-- ... repeat for all 27 tenant-scoped tables

COMMIT;
```

### 11.2 Create RLS Policies

```sql
BEGIN;

-- Tenant isolation policies (see rls.md §2.3, §2.4)
CREATE POLICY p_tenant_isolation_entities ON entities
    FOR ALL
    USING (id = current_setting('app.tenant_id')::text);

-- ... repeat for all tables (27 policies total)

COMMIT;
```

---

## 12. Zero-Downtime Strategy

### 12.1 Safe Operations (No Locking)

| Operation | Safe? | Notes |
|-----------|-------|-------|
| `CREATE INDEX CONCURRENTLY` | ✅ Yes | Use for all new indexes on large tables |
| `ALTER TABLE ... ADD CONSTRAINT CHECK` | ✅ Yes | Quick `SHARE ROW EXCLUSIVE` lock |
| `ALTER TABLE ... ALTER COLUMN SET NOT NULL` | ⚠️ Partial | Fails fast if nulls exist; table scan |
| `ALTER TABLE ... ADD CONSTRAINT UNIQUE` | ⚠️ Partial | Requires `ACCESS EXCLUSIVE` — use `CONCURRENTLY` trick |
| `ALTER TABLE ... DROP COLUMN` | ❌ No | Requires `ACCESS EXCLUSIVE` — plan maintenance window |
| `CREATE TRIGGER` | ✅ Yes | Instant operation |
| `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` | ✅ Yes | Instant operation |
| `CREATE POLICY` | ✅ Yes | Instant operation |

### 12.2 Recommended Deployment Sequence

```
Deploy 1: Application code changes only
  - Remove writes to GENERATED columns
  - Add tenant context middleware
  - Add `set_tenant_context()` to all DB sessions

Deploy 2: Extensions + Functions + GENERATED columns
  - Phase 1 (extensions)
  - Phase 2 (GENERATED columns)
  - Requires application code from Deploy 1

Deploy 3: Constraints (off-peak maintenance window preferred)
  - Phase 3 (NOT NULL)
  - Phase 4 (CHECK)
  - Phase 5 (UNIQUE)

Deploy 4: Indexes + Triggers + RLS
  - Phase 7 (indexes — use CONCURRENTLY)
  - Phase 8 (state machine triggers)
  - Phase 9 (audit triggers)
  - Phase 10 (RLS)
```

---

## 13. Rollback Plan

### 13.1 Full Rollback Script

```sql
-- 1. Drop RLS policies
DROP POLICY IF EXISTS p_tenant_isolation_entities ON entities;
-- ... repeat for all tables

-- 2. Disable RLS
ALTER TABLE entities DISABLE ROW LEVEL SECURITY;
-- ... repeat for all tables

-- 3. Drop audit triggers
DROP TRIGGER IF EXISTS trg_audit_entities ON entities;
-- ... repeat for all tables

-- 4. Drop state machine triggers
DROP TRIGGER IF EXISTS trg_enforce_invoice_status ON vendor_invoices;
-- ... repeat

-- 5. Drop partial indexes
DROP INDEX IF EXISTS idx_tb_non_zero;
-- ... repeat for all new indexes

-- 6. Drop UNIQUE constraints
ALTER TABLE gl_accounts DROP CONSTRAINT IF EXISTS uq_gl_accounts_entity_number;
-- ... repeat

-- 7. Drop CHECK constraints
ALTER TABLE trial_balance DROP CONSTRAINT IF EXISTS chk_tb_period_format;
-- ... repeat for all CHECK constraints

-- 8. Drop GENERATED columns (restore as regular columns)
ALTER TABLE trial_balance DROP COLUMN balance;
ALTER TABLE trial_balance ADD COLUMN balance NUMERIC(15, 2);

ALTER TABLE variances DROP COLUMN variance_amount;
ALTER TABLE variances DROP COLUMN variance_pct;
ALTER TABLE variances ADD COLUMN variance_amount NUMERIC(15, 2);
ALTER TABLE variances ADD COLUMN variance_pct NUMERIC(8, 4);

-- 9. Drop extensions
DROP EXTENSION IF EXISTS pg_partman;
DROP EXTENSION IF EXISTS btree_gist;
```

### 13.2 Rollback Verification

```sql
-- Verify rollback: should return no rows
SELECT conname FROM pg_constraint
WHERE conname LIKE 'chk_%' OR conname LIKE 'uq_%' OR conname LIKE 'fk_%';

-- Verify no GENERATED columns remain
SELECT column_name, is_generated
FROM information_schema.columns
WHERE is_generated = 'ALWAYS';
```

---

## 14. Alembic Integration

### 14.1 Migration File Organization

```
migrations/
  versions/
    0001_extensions.py
    0002_generated_columns.py
    0003_not_null_constraints.py
    0004_check_constraints.py
    0005_unique_constraints.py
    0006_partial_indexes.py
    0007_state_machine_triggers.py
    0008_audit_triggers.py
    0009_rls_policies.py
```

### 14.2 Alembic migration_helpers

```python
# migrations/helpers.py
from alembic import op
import sqlalchemy as sa


def check_not_null_violations(table: str, column: str) -> int:
    """Check how many rows would violate a new NOT NULL constraint."""
    conn = op.get_bind()
    result = conn.execute(
        sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL")
    )
    return result.scalar()


def check_duplicate_violations(table: str, columns: list[str]) -> int:
    """Check for duplicates before adding a UNIQUE constraint."""
    cols = ", ".join(columns)
    conn = op.get_bind()
    result = conn.execute(
        sa.text(f"""
            SELECT COUNT(*) - COUNT(DISTINCT ({cols}))
            FROM {table}
        """)
    )
    return result.scalar()
```

### 14.3 Alembic Migration Template

```python
"""add check constraints for trial_balance

Revision ID: 0004_check_constraints
Revises: 0003_not_null
Create Date: 2026-07-30
"""
from alembic import op


def upgrade():
    # Period format
    op.create_check_constraint(
        "chk_tb_period_format",
        "trial_balance",
        sa.text("period ~ '^\\d{4}-(0[1-9]|1[0-2])$'"),
    )
    # Debit/credit non-negative
    op.create_check_constraint(
        "chk_tb_debit_non_negative",
        "trial_balance",
        sa.text("debit >= 0"),
    )
    op.create_check_constraint(
        "chk_tb_credit_non_negative",
        "trial_balance",
        sa.text("credit >= 0"),
    )


def downgrade():
    op.drop_constraint("chk_tb_period_format", "trial_balance")
    op.drop_constraint("chk_tb_debit_non_negative", "trial_balance")
    op.drop_constraint("chk_tb_credit_non_negative", "trial_balance")
```

---

## 15. Migration Timeline

| Phase | Duration | Downtime | Risk |
|-------|----------|----------|------|
| 1 — Extensions | 5 min | None | Low |
| 2 — GENERATED columns | 10 min | None (read-only) | Medium |
| 3 — NOT NULL | 15 min | None | Medium |
| 4 — CHECK | 10 min | None | Low |
| 5 — UNIQUE | 15 min | None | Medium |
| 6 — FK validation | 10 min | None | Low |
| 7 — Indexes (CONCURRENTLY) | 30 min | None | Low |
| 8 — Triggers | 5 min | None | Low |
| 9 — Audit triggers | 5 min | None | Low |
| 10 — RLS | 5 min | None | Medium |
| **Total** | **~2 hours** | **None** | **Controlled** |

**Rollback time:** ~30 minutes (run rollback script, verify, restore app config).
