# Row-Level Security — Multi-Tenant Isolation

> **Layer:** 5 (Database Constraints)  
> **Scope:** All tenant-scoped tables in `shared/models/database.py`  
> **Design Principle:** The database enforces tenant isolation — no application code path can accidentally read another tenant's data.

---

## 1. Tenant Boundary Analysis

### 1.1 Tenant Identification Strategy

Two tenant identifier columns exist across the schema:

| Identifier | Tables | Notes |
|-----------|--------|-------|
| `entity_id` | 15 legacy tables (entities, gl_accounts, trial_balance, budget_lines, forecast_lines, actuals, headcount_data, vendor_invoices, sales_pipeline, agent_runs, variances, root_causes, commentary_drafts, scenarios, review_logs) | Entity-scoped — acts as the tenant boundary for the FP&A domain |
| `tenant_id` | 12 PRD §7 tables (review_decisions, action_items, commentary_versions, audit_logs, pipeline_runs, assertions_db, tool_result_cache, data_quality_snapshots, policy_decision_logs, bridge_analysis_results, variance_snapshots, root_cause_findings_db) | Explicit tenant boundary for the new domain model |

**Design decision:** Both `entity_id` and `tenant_id` serve as the tenant partitioning key. The RLS policy will use the `app.tenant_id` session variable (`current_setting('app.tenant_id')`), as used throughout the SQL examples below and in the live migrations (`001_extensions.sql`, `006_rls.sql`, `007_audit_triggers.sql`). Legacy tables with `entity_id` will be treated as tenant-scoped using `entity_id`.

### 1.2 Tables Without Tenant Scope

These tables are NOT tenant-scoped and will have no RLS policy:

| Table | Reason |
|-------|--------|
| `state_transitions` | Cross-tenant configuration |
| `audit_logs` | Append-only, tenant identified via `tenant_id` column (RLS still applied for read isolation) |

---

## 2. RLS Policy Implementation

### 2.1 Enable RLS on All Tenant Tables

```sql
-- Legacy tables (entity_id boundary)
ALTER TABLE entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE gl_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE trial_balance ENABLE ROW LEVEL SECURITY;
ALTER TABLE budget_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE forecast_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE actuals ENABLE ROW LEVEL SECURITY;
ALTER TABLE headcount_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE vendor_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE sales_pipeline ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE variances ENABLE ROW LEVEL SECURITY;
ALTER TABLE root_causes ENABLE ROW LEVEL SECURITY;
ALTER TABLE commentary_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE scenarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_logs ENABLE ROW LEVEL SECURITY;

-- PRD §7 tables (tenant_id boundary)
ALTER TABLE review_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE commentary_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE assertions_db ENABLE ROW LEVEL SECURITY;
ALTER TABLE tool_result_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_quality_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE policy_decision_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE bridge_analysis_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE variance_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE root_cause_findings_db ENABLE ROW LEVEL SECURITY;
```

### 2.2 Set Application Tenant Context

The application sets the tenant ID at the start of each session/request:

**From asyncpg / psycopg:**

```python
import asyncpg

async def set_tenant_context(conn: asyncpg.Connection, tenant_id: str) -> None:
    await conn.execute(
        "SELECT set_config('app.tenant_id', $1, false)", tenant_id
    )
```

**From SQLAlchemy session:**

```python
from sqlalchemy import text
from sqlalchemy.orm import Session

def set_tenant_context(session: Session, tenant_id: str) -> None:
    session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, false)"),
        {"tenant_id": tenant_id}
    )
```

**From FastAPI middleware:**

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        tenant_id = request.headers.get("X-Tenant-ID")
        if not tenant_id:
            # Extract from JWT or route parameter
            tenant_id = extract_from_auth(request)

        async with request.app.state.db_session() as session:
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": tenant_id}
            )
            request.state.tenant_id = tenant_id
            response = await call_next(request)
            return response
```

**Critical setting:** The third parameter to `set_config` is `true` (= session-local) so the setting is automatically cleared when the database connection is returned to the pool.

### 2.3 Tenant Isolation Policy (Legacy Tables — `entity_id`)

For all legacy tables using `entity_id`:

```sql
CREATE POLICY p_tenant_isolation_entities ON entities
  FOR ALL
  USING (id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_gl_accounts ON gl_accounts
  FOR ALL
  USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_trial_balance ON trial_balance
  FOR ALL
  USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_budget_lines ON budget_lines
  FOR ALL
  USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_forecast_lines ON forecast_lines
  FOR ALL
  USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_actuals ON actuals
  FOR ALL
  USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_headcount ON headcount_data
  FOR ALL
  USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_invoices ON vendor_invoices
  FOR ALL
  USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_pipeline ON sales_pipeline
  FOR ALL
  USING (entity_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_agent_runs ON agent_runs
  FOR ALL
  USING (entity_id = current_setting('app.tenant_id')::text);

-- Variances and root_causes are scoped through agent_runs → entity_id
CREATE POLICY p_tenant_isolation_variances ON variances
  FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM agent_runs ar
      WHERE ar.id = variances.agent_run_id
        AND ar.entity_id = current_setting('app.tenant_id')::text
    )
  );

CREATE POLICY p_tenant_isolation_root_causes ON root_causes
  FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM variances v
      JOIN agent_runs ar ON ar.id = v.agent_run_id
      WHERE v.id = root_causes.variance_id
        AND ar.entity_id = current_setting('app.tenant_id')::text
    )
  );

CREATE POLICY p_tenant_isolation_commentary ON commentary_drafts
  FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM agent_runs ar
      WHERE ar.id = commentary_drafts.agent_run_id
        AND ar.entity_id = current_setting('app.tenant_id')::text
    )
  );

CREATE POLICY p_tenant_isolation_scenarios ON scenarios
  FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM agent_runs ar
      WHERE ar.id = scenarios.agent_run_id
        AND ar.entity_id = current_setting('app.tenant_id')::text
    )
  );

CREATE POLICY p_tenant_isolation_review_logs ON review_logs
  FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM agent_runs ar
      WHERE ar.id = review_logs.agent_run_id
        AND ar.entity_id = current_setting('app.tenant_id')::text
    )
  );
```

### 2.4 Tenant Isolation Policy (PRD §7 Tables — `tenant_id`)

For all new tables using explicit `tenant_id`:

```sql
-- Template policy for any table with tenant_id column
CREATE POLICY p_tenant_isolation_review_decisions ON review_decisions
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_action_items ON action_items
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_commentary_versions ON commentary_versions
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_audit_logs ON audit_logs
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_pipeline_runs ON pipeline_runs
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_assertions ON assertions_db
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_cache ON tool_result_cache
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_dq_snapshots ON data_quality_snapshots
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_policy_logs ON policy_decision_logs
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_bridge ON bridge_analysis_results
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_var_snapshots ON variance_snapshots
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id')::text);

CREATE POLICY p_tenant_isolation_findings ON root_cause_findings_db
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id')::text);
```

---

## 3. Admin Override Policy

### 3.1 Admin Bypass

The `finsight_admin` role bypasses RLS entirely:

```sql
-- Admin role bypasses RLS
ALTER TABLE entities FORCE ROW LEVEL SECURITY;
-- ... repeat for all tenant tables

-- This is the simpler approach: grant admin to a role that has BYPASSRLS
CREATE ROLE finsight_admin WITH LOGIN BYPASSRLS;
```

### 3.2 Selective Admin Access (Without BYPASSRLS)

If you need admin to see all tenants without full BYPASSRLS, create a separate policy:

```sql
CREATE POLICY p_admin_full_access ON entities
  FOR ALL
  USING (
    current_setting('app.role', true) = 'admin'
    OR id = current_setting('app.tenant_id')::text
  );

-- Apply the same pattern to all tenant tables
```

### 3.3 Audit of Admin Access

For compliance, log all admin cross-tenant reads:

```sql
CREATE POLICY p_admin_audit_access ON audit_logs
  FOR SELECT
  USING (
    current_setting('app.role', true) = 'admin'
    OR tenant_id = current_setting('app.tenant_id')::text
  );

-- Admin SELECTs are not restricted, but we log them via the audit trigger
-- (see audit.md for the function that logs cross-tenant reads)
```

---

## 4. RLS + Foreign Keys — Cascade Behavior

### 4.1 Challenge

RLS policies on child tables may reference parent tables. When a user deletes a parent row, the cascade delete inside a trigger or CQL must also pass RLS checks on child rows.

### 4.2 Solution: `security_invoker = true` on Views

```sql
-- When using views for cross-table access:
CREATE VIEW tenant_variance_summary WITH (security_invoker = true) AS
SELECT v.*, ar.entity_id, ar.period
FROM variances v
JOIN agent_runs ar ON ar.id = v.agent_run_id;
```

### 4.3 Solution: Owner-Based RLS Bypass for Cascades

The table owner (or superuser) bypasses RLS. Ensure cascade deletes are owned by `finsight_admin`:

```sql
ALTER TABLE trial_balance OWNER TO finsight_admin;
ALTER TABLE budget_lines OWNER TO finsight_admin;
-- ... all tables owned by finsight_admin
```

Cascade behavior will work because the owner can delete rows regardless of RLS.

---

## 5. Enforcing RLS at the Connection Pool Level

### 5.1 Connection Pool Configuration

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Create engine without tenant context
engine = create_async_engine(
    settings.postgres_uri,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

# Session factory that enforces tenant context
async def get_tenant_session(tenant_id: str) -> AsyncSession:
    session = AsyncSession(bind=engine)
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": tenant_id}
    )
    return session
```

### 5.2 FastAPI Dependency

```python
from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession

async def get_db_session(
    x_tenant_id: str = Header(None, alias="X-Tenant-ID")
) -> AsyncSession:
    if not x_tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header required")

    session = AsyncSession(bind=engine)
    try:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": x_tenant_id}
        )
        yield session
    finally:
        await session.close()
```

---

## 6. Test Queries to Verify Isolation

### 6.1 Verify Tenant Cannot See Other Tenant's Data

```sql
-- As tenant "tenant_a":
SET app.tenant_id = 'tenant_a';

-- Should return only tenant_a's entities
SELECT COUNT(*) FROM entities;

-- Should return only tenant_a's GL accounts
SELECT COUNT(*) FROM gl_accounts;

-- Should return only tenant_a's trial balance
SELECT COUNT(*) FROM trial_balance;
```

### 6.2 Verify Tenant Cannot INSERT Data for Another Tenant

```sql
-- As tenant "tenant_a":
SET app.tenant_id = 'tenant_a';

-- Should FAIL — cannot insert entity with different ID
INSERT INTO entities (id, name, currency, fiscal_year_start)
VALUES ('tenant_b', 'Other Entity', 'USD', '01-01');
```

### 6.3 Verify Admin Bypass

```sql
-- As admin role:
SET ROLE finsight_admin;

-- Should return ALL entities across tenants
SELECT COUNT(*) FROM entities;

-- Should return all records
SELECT COUNT(*) FROM gl_accounts;
```

### 6.4 Verify Cascade Through RLS (Agent Runs → Variances)

```sql
-- As tenant_a:
SET app.tenant_id = 'tenant_a';

-- Create a test run
INSERT INTO agent_runs (id, entity_id, period, status, started_at)
VALUES ('test-run-1', 'tenant_a', '2026-07', 'running', NOW());

-- Create a variance for that run
INSERT INTO variances (id, agent_run_id, account_id, actual_amount, budget_amount)
VALUES ('var-1', 'test-run-1', 'acct-1', 1000, 900);

-- Should see the variance through the join
SELECT v.* FROM variances v
JOIN agent_runs ar ON ar.id = v.agent_run_id;
```

---

## 7. RLS Policy Inventory Summary

| Policy Pattern | Tables | Count |
|---------------|--------|-------|
| Direct `entity_id = app.tenant_id` | entities, gl_accounts, trial_balance, budget_lines, forecast_lines, actuals, headcount_data, vendor_invoices, sales_pipeline, agent_runs | 10 |
| `JOIN through agent_runs.entity_id` | variances, root_causes, commentary_drafts, scenarios, review_logs | 5 |
| Direct `tenant_id = app.tenant_id` | review_decisions, action_items, commentary_versions, audit_logs, pipeline_runs, assertions_db, tool_result_cache, data_quality_snapshots, policy_decision_logs, bridge_analysis_results, variance_snapshots, root_cause_findings_db | 12 |
| **Total tenant-scoped tables** | | **27** |

---

## 8. Security Considerations

| Concern | Mitigation |
|---------|-----------|
| RLS bypass via direct connection | All application connections use the `finsight_app` role which cannot bypass RLS |
| `app.tenant_id` not set | Default policy returns zero rows (safe failure) |
| Connection pooling reuse | `set_config(..., true)` = session-local; auto-cleared on pool return |
| SQL injection in tenant_id | Tenant ID is validated against UUID/JWT before being passed to `set_config` |
| Superuser access | `finsight_admin` role has `BYPASSRLS` but is never used by application code — only for migration and emergency access |
