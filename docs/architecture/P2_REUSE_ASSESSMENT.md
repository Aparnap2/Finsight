# P2 Reuse-versus-Build Assessment

**Status:** Assessment only — no P2 code written yet
**Date:** 2026-11-23
**Authority:** P2 reuse-first, minimum-change rule

## Principle

FinSight is an existing application being productized around its reconciliation
engine, not a new application being built around an old engine. Every proposed
new module must answer: *why can't an existing module do this?*

## Existing capabilities and their reuse decision

| Capability | Existing module | Reuse decision | Evidence |
|---|---|---|---|
| PostgreSQL engine + pool | `apps/api/middleware.py::_default_session_factory` | **Reuse** — bounded QueuePool, statement timeout, pre-ping | middleware.py lines 30-55 |
| Tenant auth + RLS context | `apps/api/middleware.py::TenantAuthMiddleware` | **Reuse** — sets `app.tenant_id` per request, fail-closed | middleware.py lines 64-140 |
| RBAC matrix | `finplatform/rbac/matrix.py` | **Reuse** — already consumed by middleware | middleware.py line 26 |
| Alembic migrations | `alembic/versions/` (6 migrations) | **Reuse** — forward-only, append-only | alembic/versions/ |
| Idempotency ledger | `shared/safety/idempotency.py::IdempotencyStore` | **Reuse** — key→hash binding, crash-safe, `ClaimOutcome` | idempotency.py |
| Persistence guard | `shared/safety/errors.py::persist_guarded` | **Reuse** — SQL errors → `PersistenceError` | errors.py |
| Execution guard | `shared/safety/execution_guard.py` | **Reuse** — execution command gating | (existing) |
| S3 / object store | `finance/object_store/s3_adapter.py::S3Adapter` | **Reuse** for raw source file retention (tenant-scoped, hash-checked) | s3_adapter.py |
| FastAPI app + routers | `apps/api/main.py` | **Reuse** — add reconciliation routers | main.py |
| Evidence models | `finance/evidence/models.py` | **Reuse** — `EvidenceProvenance`, `EvidenceItem` | evidence/models.py |
| Durable byte-box pattern | `finance/p8_durability/postgres_store.py` | **Reuse pattern** — short sessions, append-only audit, `create_all` | postgres_store.py |
| Money boundary | `apps/api/schemas.py::MoneyDecimal` | **Reuse** — rejects float at Pydantic boundary | schemas.py |
| Audit events table | `docs/specs/DATABASE_SCHEMA.md` §3.12 | **Build** — no existing generic audit table; use the spec's `audit_events` (append-only) | schema doc |
| Reconciliation ORM models | none | **Build** — 12 tables from the schema spec; no existing equivalent | schema doc §3 |
| Reconciliation REST routes | none | **Build** — thin routes on the existing app | API_CONTRACT.md |
| Repository functions | none | **Build, but thin** — plain functions using `persist_guarded`, not a generic repository framework | — |

## What must NOT be built

- No generic repository base class or framework.
- No queue, worker, or distributed workflow (no measured need).
- No storage abstraction project: reuse `S3Adapter` directly if raw files need durable retention.
- No new service or process.
- No generic CRUD platform: only the endpoints in `docs/specs/API_CONTRACT.md`.

## Minimal P2 plan (reuse-first)

1. **P2.1 Schema (build, minimal):** add `shared/models/reconciliation.py` with the 12 ORM models, one Alembic migration from the current head, RLS policies. Reuse `Base` from `shared/models/database.py`? No — `p8_durability` uses its own `Base` to stay decoupled. Reconciliation models should use the shared `Base` so Alembic autogenerate sees them; the migration is hand-written anyway. Use the shared `Base`.
2. **P2.2 Repositories (thin functions):** one module `finance/reconciliation/persistence.py` with functions, not classes. Each wraps DB access in `persist_guarded`. Tenant scoping via the existing RLS context + explicit `tenant_id` filter (defense in depth).
3. **P2.3 Import sessions + source files + dedup:** reuse `IdempotencyStore` for the content-hash dedup? No — content-hash dedup is a (tenant, source_type, content_hash) unique constraint on `source_files`, simpler as a DB unique constraint + `IntegrityError` handling. Reuse the `UNIQUE (tenant_id, source_type, content_hash)` from the spec.
4. **P2.4 Persist canonical results:** store `ImportRow` rows from the P1 `IngestionReport`; provenance fields map directly to `raw_data`/`normalized` JSONB.
5. **P2.5 Durable runs:** reuse the transaction pattern from `p8_durability` (short sessions, append-only audit). `start_reconciliation` persists run + matches + allocations + exceptions in one transaction.
6. **P2.6 REST routes:** add one router to `apps/api/main.py`, reusing `TenantAuthMiddleware` for tenant context. Idempotency at the operation boundary via the spec's unique constraints.
7. **P2.7 Integration tests:** reuse the existing pytest + Postgres test harness (`tests/integration/`, PG-gated).

## Raw source file retention decision (P2.3)

The spec requires `storage_ref` (S3 key or local path). For reproducibility of a reconciliation result, the parsed canonical records plus the content hash are sufficient; the raw bytes are needed only for audit re-verification. Decision: store raw bytes via the existing `S3Adapter` when `s3_evidence_bucket` is configured; otherwise store a local path under a tenant-scoped directory. No new storage abstraction.

## Open question for the user

The `tenants` table in §3.1 and the `TenantAuthMiddleware` currently treat the tenant as a header-supplied demo identity. P2 persistence needs real tenant rows. Should P2.1 seed a demo tenant from the existing demo tenant configs (`tenants/demo/*/tenant.yaml`) via a migration data step, or should tenant creation be part of P2.6? Recommendation: seed demo tenants in the migration so the middleware's `X-Tenant-ID` resolves to a real row; real tenant provisioning stays P7.
