# IMPLEMENTATION_PLAN.md
_Last updated: 2026-11-23 by agent_

## Goal
Durable, tenant-isolated reconciliation workflow accessible over HTTP: import
all three sources, persist them, execute reconciliation, retrieve results, and
survive a restart.

## Status
- Total tasks: 7
- Completed: 0
- Remaining: 7

## Tasks

### Task 1: P2.1 — PostgreSQL schema and migrations — 🔄 IN PROGRESS
- **Scope:** SQLAlchemy ORM models for the 12 reconciliation tables in
  `docs/specs/DATABASE_SCHEMA.md`, Alembic migration from the current head,
  RLS policies keyed on `app.tenant_id`.
- **Acceptance criteria:** `alembic upgrade head` applies cleanly on a fresh
  database; `alembic current == head`; tables and constraints match the spec;
  RLS policies present on every tenant-scoped table.
- **Test phase:** Integration
- **Depends on:** none

### Task 2: P2.2 — Tenant-scoped repositories
- **Scope:** Repository classes for import sessions, source files, import rows,
  reconciliation runs, matches, allocations, exceptions, investigations.
  Tenant scoping on every query (application-level + RLS).
- **Acceptance criteria:** unit tests for each repository; cross-tenant access
  returns nothing; `TenantIsolationError` on mismatched tenant context.
- **Test phase:** Unit + Integration
- **Depends on:** Task 1

### Task 3: P2.3 — Import sessions, source metadata, content-hash deduplication
- **Scope:** `create_import_session`, `upload_source_file` (idempotent on content
  hash), `validate_import`, `get_import_session`, per-row persistence of
  `ImportRow` from the P1 `IngestionReport`.
- **Acceptance criteria:** re-uploading identical bytes returns the existing
  `SourceFile` (409 DUPLICATE_IMPORT); session status transitions per state
  machine.
- **Test phase:** Integration
- **Depends on:** Task 2

### Task 4: P2.4 — Persist canonical ingestion results
- **Scope:** Persist accepted canonical records (with provenance) and rejected
  rows as `ImportRow` records; expose persisted validation preview.
- **Acceptance criteria:** re-ingesting identical input yields identical
  persisted rows; provenance survives round-trip.
- **Test phase:** Integration
- **Depends on:** Task 3

### Task 5: P2.5 — Durable reconciliation runs and results
- **Scope:** `start_reconciliation` with idempotency key, engine-version
  capture, input fingerprint, transactional persistence of matches,
  allocations, exceptions; no partially persisted results.
- **Acceptance criteria:** concurrent runs with the same idempotency key return
  the same run; crash mid-run leaves no partial results; restart resumes
  safely.
- **Test phase:** Integration
- **Depends on:** Task 4

### Task 6: P2.6 — REST endpoints and idempotency
- **Scope:** FastAPI routes under `/api/v1` for sessions, uploads, validation,
  reconciliation runs, results, exceptions, and tenant-scoped audit retrieval.
- **Acceptance criteria:** OpenAPI matches `docs/specs/API_CONTRACT.md`;
  idempotency enforced at the DB layer; tenant from authenticated context
  only.
- **Test phase:** Integration + E2E
- **Depends on:** Task 5

### Task 7: P2.7 — Integration tests and failure recovery
- **Scope:** HTTP workflow test (import 3 sources → persist → reconcile →
  retrieve → restart), tenant-isolation tests, idempotency tests, failure
  recovery (process interruption, retry).
- **Acceptance criteria:** P2 completion gate demonstrated end-to-end.
- **Test phase:** Integration + E2E
- **Depends on:** Task 6

## Known Risks / Gotchas
- `shared/models/database.py` still carries FP&A models; reconciliation models
  go in a new `shared/models/reconciliation.py` to avoid coupling to a Slice 8
  deletion target.
- Alembic migrations are forward-only; never edit applied migrations.
- Tenant identity must never come from the request body.
- No queues, workers, or distributed workflows unless measured requirements
  justify them.
- No generic CRUD platform; only the defined reconciliation workflow endpoints.

## P2 completion gate
Demonstrate a real HTTP workflow that imports all three sources, persists them,
executes reconciliation, retrieves results and survives a restart. Include
tenant-isolation tests, idempotency tests and failure-recovery tests.
