# FinSight Database Schema Specification

**Version:** 1.0 (Frozen — requires explicit approval to change)
**Status:** Draft for review
**Canonical source:** `docs/specs/DOMAIN_MODEL.md`, `shared/models/database.py`, `alembic/versions/`

---

## 1. Database Engine

- **PostgreSQL 17** (production and staging)
- **SQLAlchemy 2.x** ORM with async support deferred to post-MVP
- **Alembic** for migrations (forward-only; never edit applied migrations)
- **Row-Level Security (RLS)** via `app.tenant_id` session variable

## 2. Migration Strategy

- Migrations are append-only. Never edit an applied migration.
- Schema retirement requires a new forward migration (DROP TABLE, etc.).
- Fresh database = apply all migrations from base to head.
- Migration currency verified in staging: `alembic current` == head.
- Rollback: reverse migration via `alembic downgrade -1` (for development only; production rollback requires tested downgrade scripts).

## 3. Core Tables

### 3.1 tenants

```sql
CREATE TABLE tenants (
    tenant_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(255) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    status      VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'SUSPENDED'))
);
```

### 3.2 import_sessions

```sql
CREATE TABLE import_sessions (
    session_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(tenant_id),
    actor_id     UUID NOT NULL,
    period_start DATE NOT NULL,
    period_end   DATE NOT NULL CHECK (period_end >= period_start),
    status       VARCHAR(20) NOT NULL DEFAULT 'CREATED'
        CHECK (status IN ('CREATED', 'UPLOADING', 'VALIDATING', 'READY', 'REJECTED')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_import_sessions_tenant ON import_sessions(tenant_id);
CREATE INDEX idx_import_sessions_status ON import_sessions(status);
```

### 3.3 source_files

```sql
CREATE TABLE source_files (
    file_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id       UUID NOT NULL REFERENCES import_sessions(session_id),
    tenant_id        UUID NOT NULL REFERENCES tenants(tenant_id),
    source_type      VARCHAR(20) NOT NULL CHECK (source_type IN ('INVOICE', 'STRIPE', 'BANK')),
    filename         VARCHAR(255) NOT NULL,
    content_hash     VARCHAR(64) NOT NULL,
    file_size_bytes  INTEGER NOT NULL CHECK (file_size_bytes > 0),
    row_count        INTEGER NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    storage_ref      VARCHAR(512) NOT NULL,
    uploaded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    uploaded_by      UUID NOT NULL,
    UNIQUE (session_id, source_type),
    UNIQUE (tenant_id, source_type, content_hash)  -- idempotent re-upload
);

CREATE INDEX idx_source_files_tenant ON source_files(tenant_id);
CREATE INDEX idx_source_files_session ON source_files(session_id);
```

### 3.4 import_rows

```sql
CREATE TABLE import_rows (
    row_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id           UUID NOT NULL REFERENCES source_files(file_id),
    session_id        UUID NOT NULL REFERENCES import_sessions(session_id),
    tenant_id         UUID NOT NULL REFERENCES tenants(tenant_id),
    source_type       VARCHAR(20) NOT NULL,
    line_number       INTEGER NOT NULL CHECK (line_number >= 1),
    raw_data          JSONB NOT NULL,
    normalized        JSONB,
    validation_status VARCHAR(10) NOT NULL CHECK (validation_status IN ('VALID', 'INVALID')),
    reject_reason     VARCHAR(50),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_import_rows_file ON import_rows(file_id);
CREATE INDEX idx_import_rows_session ON import_rows(session_id);
CREATE INDEX idx_import_rows_tenant ON import_rows(tenant_id);
CREATE INDEX idx_import_rows_status ON import_rows(validation_status);
```

### 3.5 reconciliation_runs

```sql
CREATE TABLE reconciliation_runs (
    run_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id          UUID NOT NULL REFERENCES import_sessions(session_id),
    tenant_id           UUID NOT NULL REFERENCES tenants(tenant_id),
    actor_id            UUID NOT NULL,
    idempotency_key     VARCHAR(255) NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED', 'VALIDATING', 'PROCESSING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
    engine_version      VARCHAR(64) NOT NULL,
    input_fingerprint   VARCHAR(64) NOT NULL,
    input_snapshot_ref  VARCHAR(512) NOT NULL,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_code          VARCHAR(50),
    error_detail        TEXT,
    UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX idx_reconciliation_runs_tenant ON reconciliation_runs(tenant_id);
CREATE INDEX idx_reconciliation_runs_session ON reconciliation_runs(session_id);
CREATE INDEX idx_reconciliation_runs_status ON reconciliation_runs(status);
CREATE INDEX idx_reconciliation_runs_created ON reconciliation_runs(created_at);
```

### 3.6 reconciliation_matches

```sql
CREATE TABLE reconciliation_matches (
    match_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id             UUID NOT NULL REFERENCES reconciliation_runs(run_id),
    tenant_id          UUID NOT NULL REFERENCES tenants(tenant_id),
    invoice_id         VARCHAR(255) NOT NULL,
    charge_id          VARCHAR(255) NOT NULL,
    outcome            VARCHAR(20) NOT NULL
        CHECK (outcome IN ('MATCHED', 'TOLERANCE_MATCHED', 'EXCEPTION', 'PENDING_EVIDENCE')),
    expected_amount    NUMERIC(19, 4) NOT NULL CHECK (expected_amount >= 0),
    observed_amount    NUMERIC(19, 4) NOT NULL CHECK (observed_amount >= 0),
    difference         NUMERIC(19, 4) NOT NULL,
    variance           NUMERIC(19, 4) NOT NULL CHECK (variance >= 0),
    tolerance_applied  NUMERIC(19, 4) NOT NULL CHECK (tolerance_applied >= 0),
    currency           VARCHAR(3) NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    exception_code     VARCHAR(50),
    materiality        VARCHAR(12) NOT NULL CHECK (materiality IN ('MATERIAL', 'IMMATERIAL')),
    fingerprint        VARCHAR(64) NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (outcome != 'EXCEPTION' OR exception_code IS NOT NULL),
    CHECK (outcome = 'EXCEPTION' OR exception_code IS NULL)
);

CREATE INDEX idx_reconciliation_matches_run ON reconciliation_matches(run_id);
CREATE INDEX idx_reconciliation_matches_tenant ON reconciliation_matches(tenant_id);
CREATE INDEX idx_reconciliation_matches_invoice ON reconciliation_matches(invoice_id);
CREATE INDEX idx_reconciliation_matches_charge ON reconciliation_matches(charge_id);
```

### 3.7 payout_allocations

```sql
CREATE TABLE payout_allocations (
    allocation_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES reconciliation_runs(run_id),
    tenant_id           UUID NOT NULL REFERENCES tenants(tenant_id),
    deposit_id          VARCHAR(255) NOT NULL,
    outcome             VARCHAR(20) NOT NULL
        CHECK (outcome IN ('MATCHED', 'TOLERANCE_MATCHED', 'EXCEPTION', 'PENDING_EVIDENCE', 'REQUIRES_HUMAN')),
    allocated_total     NUMERIC(19, 4) NOT NULL CHECK (allocated_total >= 0),
    eligible_net_total  NUMERIC(19, 4) NOT NULL CHECK (eligible_net_total >= 0),
    open_balance        NUMERIC(19, 4) NOT NULL CHECK (open_balance >= 0),
    unallocated_deposit  NUMERIC(19, 4) NOT NULL CHECK (unallocated_deposit >= 0),
    fee_total           NUMERIC(19, 4) NOT NULL CHECK (fee_total >= 0),
    refund_total         NUMERIC(19, 4) NOT NULL CHECK (refund_total >= 0),
    exception_code      VARCHAR(50),
    fingerprint         VARCHAR(64) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (outcome != 'EXCEPTION' OR exception_code IS NOT NULL),
    CHECK (outcome = 'EXCEPTION' OR exception_code IS NULL)
);

CREATE INDEX idx_payout_allocations_run ON payout_allocations(run_id);
CREATE INDEX idx_payout_allocations_tenant ON payout_allocations(tenant_id);
CREATE INDEX idx_payout_allocations_deposit ON payout_allocations(deposit_id);
```

### 3.8 allocation_legs

```sql
CREATE TABLE allocation_legs (
    leg_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    allocation_id  UUID NOT NULL REFERENCES payout_allocations(allocation_id),
    tenant_id      UUID NOT NULL REFERENCES tenants(tenant_id),
    payment_id     VARCHAR(255) NOT NULL,
    gross          NUMERIC(19, 4) NOT NULL CHECK (gross >= 0),
    fee            NUMERIC(19, 4) NOT NULL CHECK (fee >= 0),
    refund         NUMERIC(19, 4) NOT NULL CHECK (refund >= 0),
    net            NUMERIC(19, 4) NOT NULL,
    allocated      NUMERIC(19, 4) NOT NULL CHECK (allocated > 0),
    fingerprint    VARCHAR(64) NOT NULL,
    CHECK (net = gross - fee - refund),
    CHECK (allocated <= net)
);

CREATE INDEX idx_allocation_legs_allocation ON allocation_legs(allocation_id);
CREATE INDEX idx_allocation_legs_tenant ON allocation_legs(tenant_id);
CREATE INDEX idx_allocation_legs_payment ON allocation_legs(payment_id);
```

### 3.9 reconciliation_exceptions

```sql
CREATE TABLE reconciliation_exceptions (
    exception_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES reconciliation_runs(run_id),
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id),
    exception_code  VARCHAR(50) NOT NULL,
    severity        VARCHAR(10) NOT NULL CHECK (severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')),
    status          VARCHAR(20) NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'INVESTIGATING', 'UNDER_REVIEW', 'RESOLVED', 'REOPENED')),
    title           VARCHAR(255) NOT NULL,
    description     TEXT NOT NULL,
    evidence_refs   JSONB NOT NULL DEFAULT '[]',
    assigned_to     UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_reconciliation_exceptions_run ON reconciliation_exceptions(run_id);
CREATE INDEX idx_reconciliation_exceptions_tenant ON reconciliation_exceptions(tenant_id);
CREATE INDEX idx_reconciliation_exceptions_status ON reconciliation_exceptions(status);
CREATE INDEX idx_reconciliation_exceptions_severity ON reconciliation_exceptions(severity);
```

### 3.10 exception_decisions (append-only)

```sql
CREATE TABLE exception_decisions (
    decision_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exception_id    UUID NOT NULL REFERENCES reconciliation_exceptions(exception_id),
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id),
    actor_id        UUID NOT NULL,
    decision_type   VARCHAR(20) NOT NULL
        CHECK (decision_type IN ('APPROVE', 'REJECT', 'REOPEN', 'ASSIGN')),
    reason          TEXT NOT NULL,
    evidence_refs   JSONB,
    previous_status VARCHAR(20) NOT NULL,
    new_status      VARCHAR(20) NOT NULL,
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_exception_decisions_exception ON exception_decisions(exception_id);
CREATE INDEX idx_exception_decisions_tenant ON exception_decisions(tenant_id);
CREATE INDEX idx_exception_decisions_decided ON exception_decisions(decided_at);

-- Append-only enforcement
CREATE OR REPLACE FUNCTION prevent_exception_decision_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'exception_decisions is append-only: UPDATE and DELETE are prohibited';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_exception_decisions_append_only
    BEFORE UPDATE OR DELETE ON exception_decisions
    FOR EACH ROW
    EXECUTE FUNCTION prevent_exception_decision_mutation();
```

### 3.11 investigations

```sql
CREATE TABLE investigations (
    investigation_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exception_id      UUID NOT NULL REFERENCES reconciliation_exceptions(exception_id),
    tenant_id         UUID NOT NULL REFERENCES tenants(tenant_id),
    status            VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED')),
    provider          VARCHAR(50),
    model             VARCHAR(100),
    prompt_fingerprint VARCHAR(64),
    result_text       TEXT,
    evidence_refs     JSONB NOT NULL DEFAULT '[]',
    error_code        VARCHAR(50),
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by        UUID NOT NULL
);

CREATE INDEX idx_investigations_exception ON investigations(exception_id);
CREATE INDEX idx_investigations_tenant ON investigations(tenant_id);
CREATE INDEX idx_investigations_status ON investigations(status);
```

### 3.12 audit_events (append-only)

```sql
CREATE TABLE audit_events (
    event_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      UUID NOT NULL REFERENCES tenants(tenant_id),
    entity_type    VARCHAR(50) NOT NULL,
    entity_id      UUID NOT NULL,
    action         VARCHAR(50) NOT NULL,
    actor_id       UUID,
    previous_state VARCHAR(50),
    new_state      VARCHAR(50),
    metadata       JSONB,
    correlation_id UUID,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_events_tenant ON audit_events(tenant_id);
CREATE INDEX idx_audit_events_entity ON audit_events(entity_type, entity_id);
CREATE INDEX idx_audit_events_created ON audit_events(created_at);
CREATE INDEX idx_audit_events_correlation ON audit_events(correlation_id);

-- Append-only enforcement
CREATE OR REPLACE FUNCTION prevent_audit_event_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: UPDATE and DELETE are prohibited';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_events_append_only
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_event_mutation();
```

### 3.13 export_artifacts

```sql
CREATE TABLE export_artifacts (
    export_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id         UUID NOT NULL REFERENCES reconciliation_runs(run_id),
    tenant_id      UUID NOT NULL REFERENCES tenants(tenant_id),
    status         VARCHAR(20) NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'GENERATING', 'COMPLETED', 'FAILED')),
    format         VARCHAR(10) NOT NULL CHECK (format IN ('CSV', 'JSON', 'MARKDOWN')),
    storage_ref    VARCHAR(512),
    file_size_bytes INTEGER,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at   TIMESTAMPTZ,
    created_by     UUID NOT NULL,
    error_code     VARCHAR(50)
);

CREATE INDEX idx_export_artifacts_run ON export_artifacts(run_id);
CREATE INDEX idx_export_artifacts_tenant ON export_artifacts(tenant_id);
CREATE INDEX idx_export_artifacts_status ON export_artifacts(status);
```

---

## 4. Row-Level Security

All business tables with `tenant_id` column get RLS:

```sql
ALTER TABLE import_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_import_sessions ON import_sessions
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

-- Repeat for: source_files, import_rows, reconciliation_runs,
-- reconciliation_matches, payout_allocations, allocation_legs,
-- reconciliation_exceptions, exception_decisions, investigations,
-- audit_events, export_artifacts
```

**Rule**: `app.tenant_id` is set per-request via `SELECT set_config('app.tenant_id', :tenant_id, true)` in the TenantAuthMiddleware. All downstream queries are filtered by tenant.

---

## 5. Transaction Boundaries

| Operation | Transaction scope | Rollback behavior |
|---|---|---|
| Create import session | Single transaction | Full rollback on failure |
| Upload source file | Single transaction (file metadata + rows) | Full rollback; file storage cleaned up |
| Validate import | Read-only (no writes) | N/A |
| Start reconciliation | Single transaction (run + matches + allocations + exceptions) | Full rollback; run status stays QUEUED |
| Record decision | Single transaction (decision + exception status update + audit event) | Full rollback |
| Create export | Single transaction (export record) | Full rollback; partial file cleaned up |
| AI investigation | Single transaction (investigation record) | Full rollback; provider failure recorded |

**Rule**: No partial commits. A reconciliation run either fully persists (SUCCEEDED) or rolls back (FAILED). No intermediate state is visible.

---

## 6. Idempotency

| Operation | Idempotency key | Behavior on duplicate |
|---|---|---|
| Create import session | (tenant_id, period_start, period_end) | Return existing session |
| Upload source file | (tenant_id, source_type, content_hash) | Return existing file |
| Start reconciliation | (tenant_id, idempotency_key) from request | Return existing run |
| Record decision | (exception_id, actor_id, decision_type, decided_at) | Reject duplicate (409 Conflict) |

---

## 7. Migration and Rollback

- Forward migrations only in production. Downgrade is for development.
- Each migration must be tested on a fresh database in CI.
- Migration `c9d5e7f1a204` (p8 durability tables) is in the main chain and must not be edited.
- New tables for reconciliation entities require a new migration.
- Schema changes must be backward-compatible where possible (additive columns, not destructive renames).