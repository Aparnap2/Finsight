# Database Constraints — PostgreSQL Enforcement Layer

> **Layer:** 5 (Database Constraints)  
> **Scope:** All 18 ORM models in `shared/models/database.py`  
> **Design Principle:** The database is the source of truth for data integrity. Application-level validation is defense-in-depth, not the primary barrier.

---

## 1. Constraint Inventory by Table

### 1.1 `entities` — Legal entity / tenant boundary

```sql
ALTER TABLE entities
  ALTER COLUMN id          SET NOT NULL,   -- PK, implicit
  ALTER COLUMN name        SET NOT NULL,
  ALTER COLUMN currency    SET NOT NULL,
  ALTER COLUMN fiscal_year_start SET NOT NULL;

ALTER TABLE entities
  ADD CONSTRAINT chk_entities_currency
    CHECK (currency ~ '^[A-Z]{3}$'),                          -- ISO 4217
  ADD CONSTRAINT chk_entities_fiscal_year_start
    CHECK (fiscal_year_start ~ '^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$');  -- MM-DD
```

| Column | Constraint | Rationale |
|--------|-----------|-----------|
| `id` | `PRIMARY KEY` | UUID identity |
| `name` | `NOT NULL` | Every entity must have a name |
| `currency` | `NOT NULL`, `CHECK (~ '^[A-Z]{3}$')` | ISO 4217 uppercase code |
| `fiscal_year_start` | `NOT NULL`, `CHECK (~ '^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$')` | MM-DD format |

---

### 1.2 `gl_accounts` — Chart of accounts

```sql
ALTER TABLE gl_accounts
  ALTER COLUMN entity_id       SET NOT NULL,
  ALTER COLUMN account_number  SET NOT NULL,
  ALTER COLUMN account_name    SET NOT NULL,
  ALTER COLUMN account_type    SET NOT NULL;

ALTER TABLE gl_accounts
  ADD CONSTRAINT chk_gl_accounts_type
    CHECK (account_type IN (
      'asset', 'liability', 'equity',
      'revenue', 'expense',
      'contra_asset', 'contra_liability', 'contra_equity',
      'contra_revenue', 'contra_expense'
    )),
  ADD CONSTRAINT uq_gl_accounts_entity_number
    UNIQUE (entity_id, account_number);                       -- No duplicate account numbers within entity

CREATE INDEX idx_gl_accounts_entity ON gl_accounts(entity_id);
CREATE INDEX idx_gl_accounts_type ON gl_accounts(account_type);
```

| Column | Constraint | Rationale |
|--------|-----------|-----------|
| `entity_id` | `NOT NULL`, `FK → entities(id)` | Tenant-scoped |
| `account_number` | `NOT NULL`, `UNIQUE(entity_id, account_number)` | GL number unique per entity |
| `account_type` | `NOT NULL`, `CHECK (10 standard types)` | GAAP/IFRS categories |

---

### 1.3 `trial_balance` — Period-end balances

```sql
ALTER TABLE trial_balance
  ALTER COLUMN period     SET NOT NULL,
  ALTER COLUMN account_id SET NOT NULL,
  ALTER COLUMN debit      SET NOT NULL,
  ALTER COLUMN credit     SET NOT NULL;

ALTER TABLE trial_balance
  ADD CONSTRAINT chk_tb_period_format
    CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$'),             -- YYYY-MM
  ADD CONSTRAINT chk_tb_debit_non_negative
    CHECK (debit >= 0),
  ADD CONSTRAINT chk_tb_credit_non_negative
    CHECK (credit >= 0),
  ADD CONSTRAINT chk_tb_not_both_zero
    CHECK (debit > 0 OR credit > 0),                         -- At least one side has value
  ADD CONSTRAINT uq_tb_period_account
    UNIQUE (entity_id, period, account_id);                  -- One balance per account per period

-- Generate balance from debit/credit
ALTER TABLE trial_balance
  ADD COLUMN balance NUMERIC(15, 2)
    GENERATED ALWAYS AS (debit - credit) STORED;

-- Partial index: only non-zero balances (common query pattern)
CREATE INDEX idx_tb_non_zero ON trial_balance(entity_id, period)
  WHERE debit != 0 OR credit != 0;
```

**Design decision:** `balance` is a `GENERATED ALWAYS` column — the database computes it. Application code must not write to it directly.

---

### 1.4 `budget_lines` — Budget data

```sql
ALTER TABLE budget_lines
  ALTER COLUMN amount SET NOT NULL;

ALTER TABLE budget_lines
  ADD CONSTRAINT chk_budget_period_format
    CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$'),
  ADD CONSTRAINT chk_budget_amount_non_zero
    CHECK (amount != 0),                                     -- Zero-budget lines are meaningless
  ADD CONSTRAINT uq_budget_line
    UNIQUE (entity_id, period, account_id, COALESCE(department, '_null_'));

CREATE INDEX idx_budget_entity_period ON budget_lines(entity_id, period);
```

**Note on `COALESCE` UNIQUE:** PostgreSQL unique constraints treat NULLs as distinct values. For `department` which is nullable, we use a partial unique index instead:

```sql
-- Better approach: two partial unique indexes
CREATE UNIQUE INDEX uq_budget_with_dept
  ON budget_lines(entity_id, period, account_id, department)
  WHERE department IS NOT NULL;

CREATE UNIQUE INDEX uq_budget_without_dept
  ON budget_lines(entity_id, period, account_id)
  WHERE department IS NULL;
```

---

### 1.5 `forecast_lines` — Forecast data

```sql
ALTER TABLE forecast_lines
  ALTER COLUMN version SET NOT NULL,
  ALTER COLUMN created_at SET NOT NULL,
  ALTER COLUMN amount SET NOT NULL;

ALTER TABLE forecast_lines
  ADD CONSTRAINT chk_forecast_period_format
    CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$'),
  ADD CONSTRAINT chk_forecast_amount_non_zero
    CHECK (amount != 0),
  ADD CONSTRAINT chk_forecast_version_positive
    CHECK (version > 0),
  ADD CONSTRAINT uq_forecast_line
    UNIQUE (entity_id, period, account_id, COALESCE(department, '_null_'), version);

CREATE INDEX idx_forecast_entity_period ON forecast_lines(entity_id, period);
-- Partial index: only latest version is queried 90% of the time
CREATE INDEX idx_forecast_latest ON forecast_lines(entity_id, period)
  WHERE version = (SELECT MAX(f2.version) FROM forecast_lines f2
                   WHERE f2.entity_id = forecast_lines.entity_id
                     AND f2.period = forecast_lines.period
                     AND f2.account_id = forecast_lines.account_id);
-- ↑ This requires a custom solution; simpler: application-level "latest version" tracking
```

---

### 1.6 `actuals` — Actual financial data

```sql
ALTER TABLE actuals
  ALTER COLUMN amount SET NOT NULL;

ALTER TABLE actuals
  ADD CONSTRAINT chk_actuals_period_format
    CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$'),
  ADD CONSTRAINT chk_actuals_amount_non_zero
    CHECK (amount != 0),
  ADD CONSTRAINT uq_actuals_line
    UNIQUE (entity_id, period, account_id, COALESCE(department, '_null_'));

CREATE INDEX idx_actuals_entity_period ON actuals(entity_id, period);
```

---

### 1.7 `headcount_data` — People metrics

```sql
ALTER TABLE headcount_data
  ALTER COLUMN headcount           SET NOT NULL,
  ALTER COLUMN total_compensation  SET NOT NULL,
  ALTER COLUMN new_hires           SET NOT NULL,
  ALTER COLUMN departures          SET NOT NULL;

ALTER TABLE headcount_data
  ADD CONSTRAINT chk_hc_period_format
    CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$'),
  ADD CONSTRAINT chk_hc_headcount_non_negative
    CHECK (headcount >= 0),
  ADD CONSTRAINT chk_hc_compensation_non_negative
    CHECK (total_compensation >= 0),
  ADD CONSTRAINT chk_hc_new_hires_non_negative
    CHECK (new_hires >= 0),
  ADD CONSTRAINT chk_hc_departures_non_negative
    CHECK (departures >= 0),
  ADD CONSTRAINT uq_hc_period_dept
    UNIQUE (entity_id, period, department);
```

---

### 1.8 `vendor_invoices` — AP invoices

**Schema gap identified:** No `status` column exists. This must be added.

```sql
ALTER TABLE vendor_invoices
  ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'draft'
    CONSTRAINT chk_invoice_status
      CHECK (status IN ('draft', 'submitted', 'approved', 'paid', 'cancelled', 'disputed')),
  ALTER COLUMN invoice_date SET NOT NULL,
  ALTER COLUMN amount       SET NOT NULL;

ALTER TABLE vendor_invoices
  ADD CONSTRAINT chk_invoice_period_format
    CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$'),
  ADD CONSTRAINT chk_invoice_amount_positive
    CHECK (amount > 0),                                      -- Invoices are always positive
  ADD CONSTRAINT uq_invoice_dedup
    UNIQUE (entity_id, vendor_name, period, amount, invoice_date);  -- Duplicate detection

CREATE INDEX idx_invoices_entity_period ON vendor_invoices(entity_id, period);
CREATE INDEX idx_invoices_status ON vendor_invoices(status) WHERE status IN ('draft', 'submitted', 'disputed');
```

**State machine for `status`:**

```
draft ──→ submitted ──→ approved ──→ paid
  │                      │
  └──────→ cancelled     └──→ cancelled
              ↑
         disputed ────────┘
```

Enforced via trigger (see §3.2):

```sql
CREATE OR REPLACE FUNCTION fn_enforce_invoice_status_transition()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status THEN
    IF NOT CASE OLD.status
      WHEN 'draft'     THEN NEW.status IN ('submitted', 'cancelled')
      WHEN 'submitted' THEN NEW.status IN ('approved', 'cancelled', 'disputed')
      WHEN 'approved'  THEN NEW.status IN ('paid', 'cancelled')
      WHEN 'disputed'  THEN NEW.status IN ('cancelled', 'draft')
      WHEN 'paid'      THEN FALSE                               -- Terminal state
      WHEN 'cancelled' THEN FALSE                               -- Terminal state
      ELSE FALSE
    END THEN
      RAISE EXCEPTION 'Invalid invoice status transition: % → %', OLD.status, NEW.status
        USING HINT = format('Legal transitions from %s: %s', OLD.status,
          CASE OLD.status
            WHEN 'draft'     THEN 'submitted, cancelled'
            WHEN 'submitted' THEN 'approved, cancelled, disputed'
            WHEN 'approved'  THEN 'paid, cancelled'
            WHEN 'disputed'  THEN 'cancelled, draft'
            ELSE 'none (terminal state)'
          END);
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_enforce_invoice_status
  BEFORE UPDATE ON vendor_invoices
  FOR EACH ROW
  EXECUTE FUNCTION fn_enforce_invoice_status_transition();
```

---

### 1.9 `sales_pipeline` — Deal tracking

```sql
ALTER TABLE sales_pipeline
  ALTER COLUMN stage               SET NOT NULL,
  ALTER COLUMN expected_close_date SET NOT NULL;

ALTER TABLE sales_pipeline
  ADD CONSTRAINT chk_pipeline_period_format
    CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$'),
  ADD CONSTRAINT chk_pipeline_amount_positive
    CHECK (amount > 0),
  ADD CONSTRAINT chk_pipeline_stage
    CHECK (stage IN (
      'prospecting', 'qualification', 'proposal',
      'negotiation', 'closed_won', 'closed_lost'
    ));

CREATE INDEX idx_pipeline_entity_stage ON sales_pipeline(entity_id, stage);
-- Partial index: active deals (not yet closed)
CREATE INDEX idx_pipeline_active ON sales_pipeline(entity_id)
  WHERE stage NOT IN ('closed_won', 'closed_lost');
```

**State machine for `stage`:**

```
prospecting → qualification → proposal → negotiation → closed_won
                                                         → closed_lost
```

---

### 1.10 `agent_runs` — AI pipeline execution tracking

```sql
ALTER TABLE agent_runs
  ALTER COLUMN entity_id SET NOT NULL,
  ALTER COLUMN period    SET NOT NULL,
  ALTER COLUMN status    SET NOT NULL,
  ALTER COLUMN started_at SET NOT NULL;

ALTER TABLE agent_runs
  ADD CONSTRAINT chk_agentrun_period_format
    CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$'),
  ADD CONSTRAINT chk_agentrun_status
    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
  ADD CONSTRAINT chk_agentrun_times
    CHECK (completed_at IS NULL OR completed_at > started_at);

-- Partial index: only pending/running runs (common polling query)
CREATE INDEX idx_agentrun_active ON agent_runs(entity_id, period)
  WHERE status IN ('pending', 'running');
```

**State machine trigger** — same pattern as invoices:

```sql
CREATE OR REPLACE FUNCTION fn_enforce_agentrun_status_transition()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.status IS DISTINCT FROM NEW.status THEN
    IF NOT CASE OLD.status
      WHEN 'pending' THEN NEW.status IN ('running', 'cancelled')
      WHEN 'running' THEN NEW.status IN ('completed', 'failed')
      WHEN 'completed' THEN FALSE
      WHEN 'failed'    THEN FALSE
      WHEN 'cancelled' THEN FALSE
      ELSE FALSE
    END THEN
      RAISE EXCEPTION 'Invalid agent_run status transition: % → %', OLD.status, NEW.status;
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_enforce_agentrun_status
  BEFORE UPDATE ON agent_runs
  FOR EACH ROW
  EXECUTE FUNCTION fn_enforce_agentrun_status_transition();
```

---

### 1.11 `variances` — Computed variance analysis

```sql
ALTER TABLE variances
  ALTER COLUMN agent_run_id   SET NOT NULL,
  ALTER COLUMN account_id     SET NOT NULL,
  ALTER COLUMN actual_amount  SET NOT NULL,
  ALTER COLUMN budget_amount  SET NOT NULL,
  ALTER COLUMN is_material    SET NOT NULL,
  ALTER COLUMN classification SET NOT NULL;

ALTER TABLE variances
  ADD CONSTRAINT chk_var_confidence
    CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)),
  ADD CONSTRAINT chk_var_classification
    CHECK (classification IN (
      'favorable', 'unfavorable', 'neutral', 'critical', 'non_material'
    )),
  ADD CONSTRAINT uq_variance_run_account
    UNIQUE (agent_run_id, account_id, COALESCE(department, '_null_'));

-- Generate variance_amount from actual and budget
ALTER TABLE variances
  ADD COLUMN variance_amount NUMERIC(15, 2)
    GENERATED ALWAYS AS (actual_amount - budget_amount) STORED;

-- Generate variance_pct — safe division
ALTER TABLE variances
  ADD COLUMN variance_pct NUMERIC(8, 4)
    GENERATED ALWAYS AS (
      CASE WHEN budget_amount != 0
        THEN (actual_amount - budget_amount) / NULLIF(budget_amount, 0)
        ELSE NULL
      END
    ) STORED;

-- Partial index: only material variances (primary query pattern)
CREATE INDEX idx_var_material ON variances(agent_run_id)
  WHERE is_material = true;
```

**Critical design decision:** `variance_amount` and `variance_pct` are `GENERATED ALWAYS` columns. Application code must never write to them. They are derived from `actual_amount` and `budget_amount` which are the source of truth.

---

### 1.12 `root_causes` — Variance root cause analysis

```sql
ALTER TABLE root_causes
  ALTER COLUMN variance_id SET NOT NULL,
  ALTER COLUMN summary     SET NOT NULL;

ALTER TABLE root_causes
  ADD CONSTRAINT chk_rc_confidence
    CHECK (confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)),
  ADD CONSTRAINT uq_root_cause_variance
    UNIQUE (variance_id);                                     -- One root cause per variance
```

---

### 1.13 `commentary_drafts` — AI-generated commentary

```sql
ALTER TABLE commentary_drafts
  ALTER COLUMN agent_run_id SET NOT NULL,
  ALTER COLUMN version      SET NOT NULL,
  ALTER COLUMN status       SET NOT NULL;

ALTER TABLE commentary_drafts
  ADD CONSTRAINT chk_commentary_status
    CHECK (status IN ('draft', 'reviewed', 'approved', 'archived')),
  ADD CONSTRAINT chk_commentary_version_positive
    CHECK (version > 0);

CREATE INDEX idx_commentary_agent_run ON commentary_drafts(agent_run_id);
```

---

### 1.14 `scenarios` — What-if modeling

```sql
ALTER TABLE scenarios
  ALTER COLUMN agent_run_id SET NOT NULL,
  ALTER COLUMN name         SET NOT NULL;

ALTER TABLE scenarios
  ADD CONSTRAINT chk_scenario_probability
    CHECK (probability IN ('low', 'medium', 'high', 'very_high'));

CREATE INDEX idx_scenarios_agent_run ON scenarios(agent_run_id);
```

---

### 1.15 `review_logs` — Human review checkpoint log

```sql
ALTER TABLE review_logs
  ALTER COLUMN agent_run_id SET NOT NULL,
  ALTER COLUMN checkpoint   SET NOT NULL,
  ALTER COLUMN reviewer     SET NOT NULL,
  ALTER COLUMN decision     SET NOT NULL;

ALTER TABLE review_logs
  ADD CONSTRAINT chk_review_decision
    CHECK (decision IN ('approved', 'rejected', 'escalated', 'needs_revision'));

CREATE INDEX idx_review_logs_agent_run ON review_logs(agent_run_id);
```

---

### 1.16 `review_decisions` (PRD §7) — Assertion review decisions

```sql
ALTER TABLE review_decisions
  ALTER COLUMN decision  SET NOT NULL,
  ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE review_decisions
  ADD CONSTRAINT chk_review_decision_v2
    CHECK (decision IN ('approved', 'rejected', 'escalated')),
  ADD CONSTRAINT chk_review_confidence
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  ADD CONSTRAINT uq_review_assertion
    UNIQUE (tenant_id, period, assertion_id);

CREATE INDEX idx_review_decisions_period ON review_decisions(tenant_id, period);
```

---

### 1.17 `action_items` (PRD §7) — Gated action items

```sql
ALTER TABLE action_items
  ALTER COLUMN status     SET NOT NULL,
  ALTER COLUMN created_at SET NOT NULL,
  ALTER COLUMN updated_at SET NOT NULL;

ALTER TABLE action_items
  ADD CONSTRAINT chk_action_status
    CHECK (status IN ('proposed', 'approved', 'in_progress', 'completed', 'cancelled', 'blocked')),
  ADD CONSTRAINT chk_action_verb
    CHECK (action IN ('reduce', 'increase', 'optimize', 'restructure', 'maintain', 'investigate')),
  ADD CONSTRAINT chk_action_domain
    CHECK (domain IN ('cost', 'revenue', 'margin', 'headcount', 'capex', 'working_capital')),
  ADD CONSTRAINT chk_action_updated_after_created
    CHECK (updated_at >= created_at);

-- Partial index: open action items
CREATE INDEX idx_action_items_open ON action_items(tenant_id, period)
  WHERE status IN ('proposed', 'approved', 'in_progress', 'blocked');

-- Prevent concurrent status updates (EXCLUDE)
-- ALTER TABLE action_items ADD CONSTRAINT excl_action_no_concurrent
--   EXCLUDE USING gist (id WITH =, period WITH =)
--   WHERE (status IN ('proposed', 'approved', 'in_progress'));
-- ^ Exclude constraints require btree_gist extension
```

**State machine for `status`:**

```
proposed ──→ approved ──→ in_progress ──→ completed
  │            │               │
  └──→ cancelled               └──→ blocked ──→ in_progress (unblocked)
```

---

### 1.18 `commentary_versions` (PRD §7) — Versioned commentary

```sql
ALTER TABLE commentary_versions
  ALTER COLUMN version    SET NOT NULL,
  ALTER COLUMN status     SET NOT NULL,
  ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE commentary_versions
  ADD CONSTRAINT chk_commentary_version_v2_status
    CHECK (status IN ('draft', 'submitted', 'reviewed', 'approved')),
  ADD CONSTRAINT chk_commentary_version_v2_positive
    CHECK (version > 0),
  ADD CONSTRAINT uq_commentary_version
    UNIQUE (tenant_id, period, version);

CREATE INDEX idx_commentary_versions_period ON commentary_versions(tenant_id, period);
```

---

### 1.19 `audit_logs` (PRD §7) — Application event log

```sql
ALTER TABLE audit_logs
  ALTER COLUMN event_type SET NOT NULL,
  ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE audit_logs
  ADD CONSTRAINT chk_audit_event_type
    CHECK (event_type IN (
      'pipeline_started', 'pipeline_completed', 'pipeline_failed',
      'assertion_created', 'assertion_validated',
      'action_proposed', 'action_approved', 'action_rejected',
      'commentary_submitted', 'commentary_reviewed',
      'user_login', 'export_downloaded', 'config_changed',
      'anomaly_detected', 'data_quality_alert'
    ));

CREATE INDEX idx_audit_logs_event_type ON audit_logs(tenant_id, event_type, created_at DESC);
```

**This table is APPEND-ONLY.** It must have a trigger preventing UPDATE and DELETE (see `docs/12-database/audit.md`).

---

### 1.20 `pipeline_runs` (PRD §7) — Pipeline execution tracking

```sql
ALTER TABLE pipeline_runs
  ALTER COLUMN status     SET NOT NULL,
  ALTER COLUMN started_at SET NOT NULL;

ALTER TABLE pipeline_runs
  ADD CONSTRAINT chk_pipeline_status
    CHECK (status IN ('pending', 'running', 'completed', 'failed')),
  ADD CONSTRAINT chk_pipeline_times
    CHECK (completed_at IS NULL OR completed_at > started_at);

CREATE INDEX idx_pipeline_runs_active ON pipeline_runs(tenant_id, period)
  WHERE status IN ('pending', 'running');
```

---

### 1.21 `assertions_db` (PRD §7) — Persisted assertions

```sql
ALTER TABLE assertions_db
  ALTER COLUMN type        SET NOT NULL,
  ALTER COLUMN created_at  SET NOT NULL;

ALTER TABLE assertions_db
  ADD CONSTRAINT chk_assertion_type
    CHECK (type IN ('numeric', 'comparative', 'causal', 'forecast', 'quality')),
  ADD CONSTRAINT chk_assertion_support_level
    CHECK (support_level IS NULL OR support_level IN ('verified', 'probable', 'weak', 'contested')),
  ADD CONSTRAINT chk_assertion_confidence
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  ADD CONSTRAINT uq_assertion_id_per_period
    UNIQUE (tenant_id, period, assertion_id);

CREATE INDEX idx_assertions_type ON assertions_db(tenant_id, period, type);
```

---

### 1.22 `tool_result_cache` (PRD §7) — External API cache

```sql
ALTER TABLE tool_result_cache
  ALTER COLUMN created_at SET NOT NULL,
  ALTER COLUMN expires_at SET NOT NULL;

ALTER TABLE tool_result_cache
  ADD CONSTRAINT chk_cache_expiry
    CHECK (expires_at > created_at),
  ADD CONSTRAINT uq_cache_entry
    UNIQUE (tenant_id, tool_name, query_fingerprint);

-- Partial index with STABLE function is not allowed in PG.
-- Use application-level filtering: WHERE expires_at < NOW() + INTERVAL '1 hour'
CREATE INDEX idx_cache_expires ON tool_result_cache(expires_at);
```

---

### 1.23 `data_quality_snapshots` (PRD §7)

```sql
ALTER TABLE data_quality_snapshots
  ALTER COLUMN overall_score SET NOT NULL,
  ALTER COLUMN created_at    SET NOT NULL;

ALTER TABLE data_quality_snapshots
  ADD CONSTRAINT chk_dq_score
    CHECK (overall_score >= 0 AND overall_score <= 1);

CREATE INDEX idx_dq_snapshots_period ON data_quality_snapshots(tenant_id, period);
```

---

### 1.24 `policy_decision_logs` (PRD §7)

```sql
ALTER TABLE policy_decision_logs
  ALTER COLUMN autonomy_level SET NOT NULL,
  ALTER COLUMN routing_target SET NOT NULL,
  ALTER COLUMN created_at     SET NOT NULL;

ALTER TABLE policy_decision_logs
  ADD CONSTRAINT chk_policy_autonomy
    CHECK (autonomy_level IN ('autonomous', 'semi_autonomous', 'review_required', 'manual_only')),
  ADD CONSTRAINT chk_policy_routing
    CHECK (routing_target IN ('auto_approve', 'human_review', 'escalate', 'block')),
  ADD CONSTRAINT chk_policy_confidence
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1));

CREATE INDEX idx_policy_logs_period ON policy_decision_logs(tenant_id, period);
```

---

### 1.25 `bridge_analysis_results` (PRD §7)

```sql
ALTER TABLE bridge_analysis_results
  ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE bridge_analysis_results
  ADD CONSTRAINT chk_bridge_confidence
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1));

CREATE INDEX idx_bridge_period ON bridge_analysis_results(tenant_id, period);
```

---

### 1.26 `variance_snapshots` (PRD §7)

```sql
ALTER TABLE variance_snapshots
  ALTER COLUMN is_material SET NOT NULL,
  ALTER COLUMN created_at  SET NOT NULL;

CREATE INDEX idx_var_snapshots_material ON variance_snapshots(tenant_id, period)
  WHERE is_material = true;
```

---

### 1.27 `root_cause_findings_db` (PRD §7)

```sql
ALTER TABLE root_cause_findings_db
  ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE root_cause_findings_db
  ADD CONSTRAINT chk_finding_confidence
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1));

CREATE INDEX idx_findings_period ON root_cause_findings_db(tenant_id, period);
```

---

## 2. Cross-Cutting Constraints

### 2.1 Period Format Validation

All `period` columns use format `YYYY-MM`. A reusable CHECK constraint pattern:

```sql
-- Template for any table with a period column
CHECK (period ~ '^\d{4}-(0[1-9]|1[0-2])$')
```

### 2.2 Confidence Score Validation

All `confidence` / `confidence_score` columns use `NUMERIC(5, 4)` with range `[0, 1]`:

```sql
CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
```

### 2.3 Monetary Value Validation

All monetary columns use `NUMERIC(15, 2)`:

```sql
-- Positive-only amounts (invoices, pipeline)
CHECK (amount > 0)

-- Non-negative (debits, credits)
CHECK (debit >= 0)

-- Non-zero (budget lines, actuals)
CHECK (amount != 0)
```

### 2.4 Timestamp Validation

For tables with `started_at` / `completed_at`:

```sql
CHECK (completed_at IS NULL OR completed_at > started_at)
```

For tables with `updated_at` / `created_at`:

```sql
CHECK (updated_at >= created_at)
```

---

## 3. State Machine Enforcement

### 3.1 Simple State Validation (CHECK constraint)

Use when only valid states need enforcement, not transitions:

```sql
CHECK (status IN ('draft', 'submitted', 'approved', 'paid', 'cancelled', 'disputed'))
```

### 3.2 Full State Transition Enforcement (Trigger)

Use when illegal transitions must be blocked at the database level:

The `fn_enforce_invoice_status_transition()` trigger (shown in §1.8) validates that status changes follow the defined graph. Apply the same pattern to:

| Table | States | Transition trigger needed? |
|-------|--------|---------------------------|
| `vendor_invoices` | draft → submitted → approved → paid / cancelled / disputed | **Yes** |
| `agent_runs` | pending → running → completed / failed / cancelled | **Yes** |
| `action_items` | proposed → approved → in_progress → completed / blocked / cancelled | **Yes** |
| `pipeline_runs` | pending → running → completed / failed | **Yes** |
| `sales_pipeline` | prospecting → qualification → proposal → negotiation → closed_won/lost | Medium |
| `commentary_versions` | draft → submitted → reviewed → approved | Medium |
| `commentary_drafts` | draft → reviewed → approved → archived | Low (legacy) |
| `review_decisions` | Single-value write, no transitions | No |

### 3.3 Generic State Machine Trigger

A reusable trigger that reads legal transitions from a configuration table:

```sql
-- State transition configuration table
CREATE TABLE state_transitions (
  table_name    TEXT NOT NULL,
  from_state    TEXT NOT NULL,
  to_state      TEXT NOT NULL,
  PRIMARY KEY (table_name, from_state, to_state)
);

-- Generic validation function
CREATE OR REPLACE FUNCTION fn_enforce_state_transition()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE'
     AND OLD.status IS DISTINCT FROM NEW.status
     AND NOT EXISTS (
       SELECT 1 FROM state_transitions
       WHERE table_name = TG_TABLE_NAME::text
         AND from_state = OLD.status
         AND to_state = NEW.status
     )
  THEN
    RAISE EXCEPTION 'Invalid state transition in %: % → %',
      TG_TABLE_NAME, OLD.status, NEW.status;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

## 4. ORM Mapping Considerations

### 4.1 Handling GENERATED Columns in SQLAlchemy

Generated columns must be marked as `READONLY` in SQLAlchemy to prevent writes:

```python
from sqlalchemy import FetchedValue

class TrialBalance(Base):
    __tablename__ = "trial_balance"
    # ... other columns ...
    balance = Column(
        Numeric(15, 2),
        server_default=FetchedValue(),   # Mark as database-computed
    )
```

### 4.2 Handling CHECK Constraints in SQLAlchemy

SQLAlchemy can declare CHECK constraints declaratively:

```python
from sqlalchemy import CheckConstraint, UniqueConstraint

class VendorInvoice(Base):
    __tablename__ = "vendor_invoices"
    # ... columns ...
    __table_args__ = (
        CheckConstraint("amount > 0", name="chk_invoice_amount_positive"),
        CheckConstraint("status IN ('draft','submitted','approved','paid','cancelled','disputed')",
                        name="chk_invoice_status"),
    )
```

### 4.3 Migration Strategy for New Constraints

See `docs/12-database/migrations.md` for the complete migration plan.

---

## 5. Verification Queries

### 5.1 List All Constraints

```sql
SELECT
  conrelid::regclass AS table_name,
  conname AS constraint_name,
  contype AS constraint_type,   -- p=PK, f=FK, u=UNIQUE, c=CHECK, t=TRIGGER, x=EXCLUDE
  pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid IN (
  'entities'::regclass, 'gl_accounts'::regclass, 'trial_balance'::regclass,
  'budget_lines'::regclass, 'forecast_lines'::regclass, 'actuals'::regclass,
  'headcount_data'::regclass, 'vendor_invoices'::regclass, 'sales_pipeline'::regclass,
  'agent_runs'::regclass, 'variances'::regclass, 'root_causes'::regclass,
  'commentary_drafts'::regclass, 'scenarios'::regclass, 'review_logs'::regclass,
  'review_decisions'::regclass, 'action_items'::regclass, 'commentary_versions'::regclass,
  'audit_logs'::regclass, 'pipeline_runs'::regclass, 'assertions_db'::regclass,
  'tool_result_cache'::regclass, 'data_quality_snapshots'::regclass,
  'policy_decision_logs'::regclass, 'bridge_analysis_results'::regclass,
  'variance_snapshots'::regclass, 'root_cause_findings_db'::regclass
)
ORDER BY table_name, constraint_name;
```

### 5.2 Validate State Machine Trigger Works

```sql
-- Should succeed
UPDATE vendor_invoices SET status = 'submitted' WHERE status = 'draft' LIMIT 1;

-- Should fail with: ERROR:  Invalid invoice status transition: submitted → draft
UPDATE vendor_invoices SET status = 'draft' WHERE status = 'submitted' LIMIT 1;
```

### 5.3 Verify GENERATED Column Cannot Be Written

```sql
-- Should fail with: ERROR:  cannot insert into column "balance"
INSERT INTO trial_balance (id, entity_id, period, account_id, debit, credit, balance)
VALUES ('test', 'e1', '2026-07', 'a1', 100, 0, 50);
```

### 5.4 Verify Period Format

```sql
-- Should fail with: ERROR:  new row for relation "budget_lines" violates check constraint
INSERT INTO budget_lines (id, entity_id, period, account_id, amount)
VALUES ('test', 'e1', '2026-13', 'a1', 1000);
```

---

## 6. Summary of All New Constraints

| Constraint type | Count | Examples |
|----------------|-------|---------|
| `NOT NULL` additions | ~40 | `status`, `created_at`, `version` |
| `CHECK` | ~35 | Amount ranges, period format, status enums |
| `UNIQUE` | ~15 | Entity+period+account+dept |
| `GENERATED ALWAYS` | 3 | `trial_balance.balance`, `variances.variance_amount`, `variances.variance_pct` |
| `FK` (existing) | 18 | Already present in migrations |
| Partial indexes | ~10 | Material variances, active runs, open action items |
| State machine triggers | 3 | Invoices, agent_runs, action_items |

**Total: ~120 new constraint objects across 18 tables.**
