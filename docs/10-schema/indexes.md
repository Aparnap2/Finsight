# Index Design

## Table-Level Index Strategy

### actuals

| Index | Columns | Type | Purpose |
|-------|---------|------|---------|
| pk_actuals | (id) | B-tree, PK | Row lookup |
| idx_actuals_entity_period | (entity_id, period) | B-tree | Tenant-scoped period queries |
| idx_actuals_account_period | (account_id, period) | B-tree | Account trending |
| idx_actuals_entity_period_account | (entity_id, period, account_id) INCLUDE (amount) | B-tree covering | Core variance query |

### trial_balance

| Index | Columns | Type | Purpose |
|-------|---------|------|---------|
| pk_trial_balance | (id) | B-tree, PK | Row lookup |
| idx_tb_entity_period | (entity_id, period) | B-tree | Period rollup |
| idx_tb_account_period | (account_id, period) | B-tree | Account drill-down |
| idx_tb_entity_period_account | (entity_id, period, account_id) INCLUDE (balance) | B-tree covering | Balance lookup |

### budget_lines

| Index | Columns | Type | Purpose |
|-------|---------|------|---------|
| pk_budget | (id) | B-tree, PK | Row lookup |
| idx_budget_entity_period | (entity_id, period) | B-tree | Period budget query |
| idx_budget_entity_period_account | (entity_id, period, account_id) | B-tree | Variance calc |

### forecast_lines

| Index | Columns | Type | Purpose |
|-------|---------|------|---------|
| pk_forecast | (id) | B-tree, PK | Row lookup |
| idx_forecast_entity_period | (entity_id, period) | B-tree | Period query |
| idx_forecast_entity_period_account | (entity_id, period, account_id, version) | B-tree | Versioned lookup |

### gl_accounts

| Index | Columns | Type | Purpose |
|-------|---------|------|---------|
| pk_gl_accounts | (id) | B-tree, PK | Row lookup |
| idx_gl_entity | (entity_id) | B-tree | Tenant scope |
| idx_gl_parent | (parent_id) WHERE parent_id IS NOT NULL | Partial B-tree | Hierarchy traversal |

### agent_runs

| Index | Columns | Type | Purpose |
|-------|---------|------|---------|
| pk_agent_runs | (id) | B-tree, PK | Row lookup |
| idx_agent_entity_period | (entity_id, period) | B-tree | Pipeline query |
| idx_agent_status | (status) WHERE status NOT IN ('completed', 'failed') | Partial B-tree | Active run monitor |

### audit_logs

| Index | Columns | Type | Purpose |
|-------|---------|------|---------|
| pk_audit_logs | (id) | B-tree, PK | Row lookup |
| idx_audit_tenant_period | (tenant_id, period) | B-tree | Tenant audit trail |
| idx_audit_created | (created_at) | B-tree | Time-range queries |
| idx_audit_event_type | (tenant_id, event_type, created_at) | B-tree | Event-type drill-down |

### PRD §7 Tables

| Table | Primary Index | Key Query Index | Notes |
|-------|--------------|-----------------|-------|
| review_decisions | PK(id) | (tenant_id, period) | |
| action_items | PK(id) | (tenant_id, status) | Partial: open items |
| commentary_versions | PK(id) | (tenant_id, period) | |
| pipeline_runs | PK(id) | (tenant_id, period) | |
| assertions_db | PK(id) | (tenant_id, assertion_id) | |
| tool_result_cache | PK(id) | (tool_name, query_fingerprint) | Unique + TTL index |
| data_quality_snapshots | PK(id) | (tenant_id, period) | |
| policy_decision_logs | PK(id) | (tenant_id, period) | |
| bridge_analysis_results | PK(id) | (tenant_id, account_id, period) | BRIN for time range |
| variance_snapshots | PK(id) | (tenant_id, account_id) | BRIN for created_at |
| root_cause_findings_db | PK(id) | (tenant_id, account_id) | |

## DDL

```sql
-- Covering index for variance query
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_actuals_variance
ON actuals (entity_id, period, account_id) INCLUDE (amount);

-- Partial index for active agent runs
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_agent_active
ON agent_runs (status) WHERE status NOT IN ('completed', 'failed');

-- BRIN for time-series audit_logs
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_created_brin
ON audit_logs USING BRIN (created_at) WITH (pages_per_range = 32);
```

## Size Estimate

| Table | Row Est. | Base Size | Index Overhead | Total Est. |
|-------|----------|-----------|----------------|------------|
| actuals | 5M | 500 MB | ~200 MB | 700 MB |
| trial_balance | 2M | 300 MB | ~120 MB | 420 MB |
| budget_lines | 500K | 80 MB | ~30 MB | 110 MB |
| forecast_lines | 1M | 160 MB | ~60 MB | 220 MB |
| gl_accounts | 50K | 8 MB | ~4 MB | 12 MB |
| audit_logs | 20M | 2 GB | ~500 MB | 2.5 GB |
| agent_runs | 100K | 15 MB | ~6 MB | 21 MB |
