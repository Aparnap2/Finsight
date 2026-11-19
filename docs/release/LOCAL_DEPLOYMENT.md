# Local deployment — reproducible procedure

Scope: local, reproducible startup of the API and the operator demo. This is a
release-candidate procedure, **not** a production-readiness claim. Cloud
deployment, secrets management, and autoscaling are out of scope.

Baseline: `feat/reconciliation-three-source-workflow`. This document describes
the configuration as of the release-preparation change set that followed
`a77b974`; reconciliation behaviour and evidence are unchanged by it.

---

## 1. What runs

| Piece | Image / command | Notes |
|---|---|---|
| API (FastAPI + Compute Runtime) | `Dockerfile` | `python:3.12-slim`, non-root uid 10001, uvicorn `apps.api.main:app` on 8000; ships `alembic/` and `database/` so the migration sequence below runs inside the container |
| PostgreSQL | `postgres:17-alpine` | authority for financial state |
| S3 emulator | `localstack/localstack:3.8`, `SERVICES=s3` | `docker-compose.ministack.yml`; contract tests only |
| Operator demo | `python -m finance.reconciliation.operator_report` | deterministic; no DB, no network, no LLM |

The nine-service `docker-compose.yml` (`--profile full`) is a development
convenience (Redis, Qdrant, Redpanda, Temporal, Jaeger, LiteLLM). It is not the
recommended demo stack.

---

## 2. Start the API with PostgreSQL

```bash
docker compose -f docker-compose.yml --profile full up -d postgres compute-runtime
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/v1/health   # 200
curl -s -H 'X-Tenant-ID: tenant-a' -H 'X-Role: director' http://localhost:8000/ready
```

`/ready` returns `{"status":"ready"}` only when Postgres answers `SELECT 1`.

Staging-shaped stack (API + Postgres only, host port 8100):

```bash
cp .env.example .env                                  # required by env_file
docker compose -f docker-compose.staging.yml up -d --build
curl -s -H 'X-Tenant-ID: acme' -H 'X-Role: director' http://localhost:8100/ready
docker compose -f docker-compose.staging.yml down
```

The stack builds from the repository `Dockerfile`; the `image:` tag is kept so
the pinned name from earlier validation still resolves.

---

## 3. Run the operator demo

```bash
# Host
python -m finance.reconciliation.operator_report

# Inside the deployed image (no mount needed; the fixture is packaged)
docker run --rm finsight-audit:local python -m finance.reconciliation.operator_report
```

Exit codes: `0` all expectations and invariants pass, `1` a check failed,
`2` input problem (missing/empty/directory/invalid JSON/wrong shape).

**Fixture packaging decision.** The image contains exactly one test path —
`tests/fixtures/reconciliation/triangle/` (three small JSON files) — because the
demo resolves its defaults relative to the module, not the working directory.
The rest of `tests/` is never packaged; test runs mount it read-only
(`docker-compose.test.yml`). Do not replace this with a blanket `COPY tests/`.

---

## 4. Health versus readiness

| Endpoint | Meaning | Auth |
|---|---|---|
| `GET /api/v1/health` | liveness only: static `{"status":"healthy"}`; no DB probe | none |
| `GET /live` | process alive | requires `X-Tenant-ID` + `X-Role` |
| `GET /ready` | `SELECT 1` against Postgres; `200` / `503` | requires `X-Tenant-ID` + `X-Role` |
| `GET /gui/` | operator console page chrome | none (page mount only) |
| `GET /openapi.json` | schema | requires headers |

Valid roles: `analyst` < `manager` < `director` < `cfo` (cumulative). Missing
headers → `401`; unknown role → `403`. `X-User-ID` is optional.

The Docker `HEALTHCHECK` uses `/api/v1/health`, so a container can report
`healthy` while Postgres is unreachable. Use `/ready` with headers when you
need to prove database connectivity. This split is intentional; do not widen
the middleware exemption list to make probes anonymous.

---

## 5. Fresh-database migrations

Current alembic head: `b7e2d9f4a516` (6 revisions). The sequence below was
verified end to end on a fresh `postgres:17-alpine`; it mirrors
`tests/integration/test_tenant_isolation.py::_apply_migrations`, which is the
executable authority. `shared/migrations.py` records applied SQL versions in
`schema_migrations`.

Order is load-bearing:

1. `alembic upgrade head` — creates base tables (`webhook_events`, ledger keys).
2. SQL `000`–`010` — extensions, constraints, RLS, audit triggers, identity.
3. ORM `create_all` for `finance.exceptions.models.Base` — `exceptions`,
   `exception_audits` (created by no alembic revision).
4. SQL `011`–`013` — RLS for exceptions, audit allowlist widening, ledger RLS.

```bash
export POSTGRES_URI='postgresql+psycopg://finsight:finsight@localhost:5432/finsight'
export PSQL_DSN='postgresql://finsight:finsight@localhost:5432/finsight'

python -m alembic upgrade head

for f in database/migrations/00*.sql database/migrations/010_*.sql; do
  psql "$PSQL_DSN" -v ON_ERROR_STOP=1 -f "$f" || exit 1
done

python - <<'PY'
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from finance.exceptions.models import Base

engine = create_engine(
    "postgresql+psycopg://finsight:finsight@localhost:5432/finsight",
    isolation_level="AUTOCOMMIT",
    poolclass=NullPool,
)
Base.metadata.create_all(engine)
# Alembic's audit_logs lacks 000_init's DEFAULT NOW(); restore it before 002's
# NOT NULL applies to probe inserts.
with engine.connect() as conn:
    conn.execute(text("ALTER TABLE audit_logs ALTER COLUMN created_at SET DEFAULT NOW()"))
engine.dispose()
PY

for f in database/migrations/01[123]_*.sql; do
  psql "$PSQL_DSN" -v ON_ERROR_STOP=1 -f "$f" || exit 1
done

python -m alembic current      # b7e2d9f4a516 (head)
```

Post-conditions verified on a fresh database:

- `alembic_version = b7e2d9f4a516`
- `pg_class.relrowsecurity` is true for `execution_records` and `idempotency_keys`
- `chk_audit_event_type` includes `IDEMPOTENCY_CONFLICT`

`docs/release/STAGING_VALIDATION.md` records head `c9d5e7f1a204` and SQL through
`011`; that snapshot predates revisions `a3f6c1e8b2d4`, `b7e2d9f4a516`, `012`,
and `013`. Use the sequence above, not the older one.

---

## 6. Configuration contract

- `POSTGRES_URI` is the only runtime database variable (`shared/config/config.py`).
  `DATABASE_URL` is read by nothing and is not used in any compose file.
- Use the `postgresql+psycopg://` driver. `psycopg2` is not installed in the
  image; `asyncpg` is present but not the configured driver.
- `MIGRATION_POSTGRES_URI` optionally separates the migration role; empty means
  "same as `POSTGRES_URI`".
- `.env.example` is the template: `cp .env.example .env`. `docker-compose.staging.yml`
  declares `env_file: .env` as `required: true`, so a fresh clone must create it.
  Provider keys may stay blank; the deterministic path never calls an LLM.

---

## 7. What this procedure does not prove

- No HTTP-level end-to-end suite exists yet. `tests/e2e` are in-process; the
  integration tier uses `TestClient` against real Postgres, not a running server.
- The deployed API exposes no reconciliation route. Reconciliation runs through
  `python -m finance.reconciliation.operator_report` (host or container), which
  is a separate path from the HTTP service.
- `/ready` proves connectivity, not schema currency. Run the migration sequence
  before treating a `200` as "database is usable".
- The full `--profile full` stack is memory-hungry; on a 16 GB machine run only
  `postgres` + `compute-runtime`.

---

## 8. Verification record

Run on 2026-11-19 against this change set (`a77b974` + release-prep commits).

| Check | Result |
|---|---|
| `docker build -t finsight-audit:local .` | exit 0 |
| `docker run --rm finsight-audit:local python -m finance.reconciliation.operator_report` | exit 0, `Verdict: PASS`, no mount |
| `python -m finance.reconciliation.operator_report` vs `docs/evidence/operator-run/report.md` | body identical (only the `Command:` line differs) |
| dev compose: `POSTGRES_URI` in container, `/ready` with headers | `{"status":"ready"}` 200 |
| `docker compose -f docker-compose.test.yml up --exit-code-from test` | 206 passed, 6 skipped, 0 failed |
| `docker compose -f docker-compose.staging.yml up -d --build` (fresh `.env` from `.env.example`) | api + pg healthy, `/ready` 200 |
| fresh-DB migration sequence | 6 alembic revisions, SQL 000–010, create_all, 011–013; `alembic current` = `b7e2d9f4a516` |
| `pytest tests/unit tests/contract` | 3625 passed, 1 skipped |
| `ruff check` / `ruff format --check` | pass / 750 files formatted |
| `mypy` + baseline | recorded 1137, current 1137, new 0 |

Two defects surfaced while running this and are fixed in the same change set:

1. The test image had no `pytest` (`uv sync --no-dev`), so the compose
   integration tier failed with `No module named pytest`. The `test` build
   stage now installs dev tooling; the runtime image is unchanged.
2. The image did not contain `database/`, so `discover_migrations` found zero
   SQL files and the integration suites ran against a schema with RLS disabled
   (7 tenant-isolation failures). `database/` is now packaged, and both suites
   raise instead of silently proceeding with zero migrations.
