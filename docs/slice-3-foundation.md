# Slice 3 — Cloud Production Foundation: Evidence (GitHub #100 / APA-74)

Bounded contract: minimum managed-infrastructure controls to preserve
FinSight's deterministic safety invariants. No app-logic changes, no
managed cloud provisioned here (no GCP credentials in this environment);
everything below was qualified locally against scratch Postgres and is
recorded so Slice 4 can re-run it against managed infrastructure.

## 1. Container (Dockerfile)

- Fixed incomplete `COPY` set: the image omitted `agents/`,
  `finance/`, `finplatform/` while the runtime imports all three
  (`apps.api.middleware` imports `finplatform.rbac.matrix`).
  Verified without building: every module loaded by
  `apps.api.main` resolves inside the `COPY` set (script output:
  `modules outside COPY set: NONE`).
- Added non-root runtime user (`finsight`, uid 10001).
- `.dockerignore` already excludes `.env` (no env-file secrets in image).
- `HEALTHCHECK` targets `/api/v1/health`, which the middleware
  exempts from tenant headers (`endswith("/health")`).

## 2. Managed PostgreSQL controls (settings + middleware + migrations)

- `Settings` gains (all env-driven, dev-safe defaults):
  `migration_postgres_uri` ("" = same as runtime),
  `db_pool_size` (5), `db_pool_max_overflow` (5),
  `db_pool_timeout_s` (10.0), `db_statement_timeout_ms` (30000).
- The middleware's default engine now uses a bounded `QueuePool`
  with `pool_pre_ping` and a per-connection `statement_timeout`, so a
  hung database fails requests instead of exhausting the service.
- `alembic/env.py` honors `MIGRATION_POSTGRES_URI`, separating the
  migration role from the runtime role at the connection level.
- Residual: the five `shared/utils/tools/*_tools.py` engine
  constructors still use unbounded defaults; they are peripheral
  (non-request-path) and tracked for the deployment slice.

## 3. RLS decision (013_ledger_rls.sql) — the Slice 3 gap, closed

Recon found RLS already covered 27 finance tables (006) plus
exceptions/audits/webhook_events (011), but NOT the P9 ledger:
`execution_records` and `idempotency_keys` relied on app-level
scoping only. New `database/migrations/013_ledger_rls.sql` follows
the 011 convention exactly (deny-by-default,
`current_setting('app.tenant_id', true)`, guarded `DO` blocks,
tenant-first indexes).

Qualified by `tests/integration/test_ledger_rls.py` (PG-gated,
skips without a database): RLS flags on, no-GUC sees nothing,
tenant-A sees only A, owner bypass documented. 4/4 pass; the
existing `test_tenant_isolation.py` suite still passes (9/9 combined).

## 4. Backup/restore drill (scratch Postgres 16)

`pg_dump` of a fully-migrated database (alembic head + SQL 000-013 +
RLS + seeds) restored into an isolated database with zero errors.
Verified post-restore: `alembic_version` = `a3f6c1e8b2d4`, seed rows
present, `relrowsecurity` flags and both tenant policies intact.

Restore lesson (recorded, not a blocker): dumping with
`--no-privileges` strips role `GRANTs`, so a restored database needs
its grants re-applied before limited roles work. The restore
procedure must include a grant step; role/grant creation for the
migration vs application roles is a deployment-slice deliverable.

## 5. Observability / failure behavior (unchanged, confirmed)

`/live` + `/ready` routers, request-ID middleware, typed persistence
failures, and the PII/secret sanitizer suite all stand; nothing in
this slice alters log content or error semantics.

## Machine-verifiable record

```text
container → COPY set complete (import-coverage script), non-root, .env excluded
database → RLS on ledger (013 + 4 PG-gated tests), bounded pool + statement timeout in settings
storage → out of scope locally (no cloud); tenant-key convention to qualify in Slice 4
secrets → env-only settings, no new secrets, .env excluded from image
identity → migration/runtime URI split; least-privilege roles are deployment-slice work
backup → configured pattern + restore drill passed (policies/head/data survive)
health → /live, /ready, /api/v1/health present; healthcheck path header-exempt
timeouts → pool checkout + statement timeout wired
failure behavior → unchanged deterministic semantics; pool exhaustion now fails fast
PII/secret leakage → sanitizer suites green, no new log content
```

## Residuals for Slice 4/5

- Re-run this entire record against managed Cloud SQL / Cloud Run.
- Role + grant creation (migration vs application vs read-only) as managed steps.
- Object-storage tenant scoping + failure drill.
- Connection-pool sizing against real Cloud Run concurrency.
- `shared/utils/tools/*` engine constructors still unbounded.
