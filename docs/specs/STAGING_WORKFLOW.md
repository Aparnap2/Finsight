# FinSight Staging Workflow Specification

**Version:** 1.0 (Frozen — requires explicit approval to change)
**Status:** Draft for review
**Canonical source:** `docs/PRODUCT.md` §9, `.github/workflows/`

---

## 1. Overview

The staging workflow proves that the application can be built, migrated, started, exercised, monitored, recovered, and diagnosed. It runs in GitHub Actions using Docker Compose.

## 2. Workflow Files

| File | Purpose |
|---|---|
| `.github/workflows/quality.yml` | Lint, format, typecheck, unit/contract tests |
| `.github/workflows/integration.yml` | PostgreSQL-gated integration tests |
| `.github/workflows/staging.yml` | Full staging verification (new) |
| `.github/workflows/ai-evals.yml` | Golden-dataset and LLM evals |
| `.github/workflows/security.yml` | Security scanning (new) |

## 3. Staging Workflow Sequence

```
checkout
  ↓
build immutable image (record SHA + digest)
  ↓
start PostgreSQL + required services
  ↓
start FinSight (docker compose up)
  ↓
apply migrations (alembic upgrade head)
  ↓
verify readiness (/health/ready)
  ↓
seed deterministic fixtures
  ↓
API integration tests
  ↓
full reconciliation workflow (upload → reconcile → inspect → investigate → decide → export)
  ↓
exception lifecycle E2E
  ↓
AI deterministic investigation E2E
  ↓
export and audit verification
  ↓
security and tenant isolation
  ↓
failure injection and recovery
  ↓
Playwright browser E2E
  ↓
collect logs / metrics / traces
  ↓
generate verification report
  ↓
cleanup (always, even on failure)
```

## 4. Job Dependency Graph

```
build ──→ provision ──→ migrate ──→ ready ──→ seed ──→ test-api
                                                           │
                                                           ├── test-workflow
                                                           ├── test-exceptions
                                                           ├── test-ai (deterministic)
                                                           ├── test-export
                                                           ├── test-security
                                                           ├── test-failure-injection
                                                           └── test-e2e (Playwright)
                                                           │
                                                           ↓
                                                     collect-diagnostics
                                                           │
                                                           ↓
                                                     generate-report
                                                           │
                                                           ↓
                                                     cleanup (always)
```

## 5. Docker Image Lifecycle

- **Build**: `docker build -t finsight-staging:${GITHUB_SHA} .` (default runtime target)
- **Tag**: Record image digest (`docker inspect --format='{{.Id}}'`)
- **Push**: Not pushed to registry (ephemeral staging). Image is local to the runner.
- **Verify**: `docker build` must succeed with zero errors.

## 6. Service Provisioning

```yaml
services:
  postgres:
    image: postgres:17-alpine
    env:
      POSTGRES_DB: finsight_test
      POSTGRES_USER: finsight
      POSTGRES_PASSWORD: test_password
    options: >-
      --health-cmd pg_isready
      --health-interval 5s
      --health-timeout 5s
      --health-retries 10
  # S3-compatible (MinIO) — only if object storage is used
  minio:
    image: minio/minio:latest
    env:
      MINIO_ROOT_USER: test
      MINIO_ROOT_PASSWORD: test_password
    command: server /data
```

## 7. Migration Process

1. Start PostgreSQL.
2. Wait for health check.
3. Run `alembic upgrade head`.
4. Verify `alembic current` == head.
5. Run `SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'` (expect ≥ 13 tables).

## 8. Test Fixture Strategy

- Deterministic CSV files in `tests/fixtures/reconciliation/staging/` (3 files: invoices, stripe, bank).
- Fixed tenant ID, actor ID, period (2026-01-01 to 2026-01-31).
- No random data. No LLM calls (use FakeLLM/ReplayProvider).
- Cleanup: delete all test data after run (or use transaction rollback per test).

## 9. Failure Injection

| Scenario | Method | Expected Outcome |
|---|---|---|
| Invalid CSV | Upload malformed file | 400 with row-level errors |
| Duplicate upload | Upload same file twice | 409 Conflict, no duplicate records |
| DB disconnect | Stop PostgreSQL mid-run | 503, run status = FAILED, no partial commit |
| Provider timeout | Configure FakeLLM to hang | 504, investigation FAILED, financial data intact |
| Concurrent requests | 10 parallel run requests | All idempotent, no duplicate runs |
| Restart mid-run | Kill API container, restart | Run reaches terminal state (FAILED or SUCCEEDED) |
| Cross-tenant access | Request with wrong tenant header | 403, no data leaked |

## 10. Diagnostics and Artifacts

On failure, collect:
- Application logs (JSON, last 1000 lines)
- PostgreSQL logs
- Docker container status
- Test output (pytest log)
- Verification report (JSON)
- Metrics snapshot (if available)
- Trace export (if available)

Upload as GitHub Actions artifacts with `if-no-files-found: error`.

## 11. Cleanup

- `docker compose down -v --remove-orphans` (always, even on failure)
- Remove temporary images
- Upload artifacts before cleanup

## 12. Local Reproduction Commands

```bash
make staging-up        # Start staging stack
make staging-migrate   # Apply migrations
make staging-seed      # Seed deterministic fixtures
make staging-test      # Run API integration tests
make staging-failure   # Run failure injection tests
make staging-e2e       # Run Playwright E2E
make staging-report    # Generate verification report
make staging-down      # Tear down (always)
```

Each command must have a real implementation. No placeholders.