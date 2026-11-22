# FinSight Existing-to-Target Map

**Version:** 1.0 (Task D deliverable)
**Status:** Read-only investigation
**Date:** 2026-11-22

---

## Target Architecture (from user directives)

```
Browser (NiceGUI /gui)
  │
  └─ FastAPI reconciliation API (/api/v1/*)
        │
        ├─ finance/reconciliation  ← frozen deterministic engine
        │
        ├─ agents/  ← explanation only (P4)
        │
        └─ PostgreSQL (sources · runs · results · exceptions · decisions)
              + S3-compatible (uploaded files, if justified)
```

---

## Capability Map

### 1. Deterministic Reconciliation Engine

| Target Capability | Existing Implementation | Status | Gap |
|---|---|---|---|
| Invoice-charge matching | `finance/reconciliation/matcher.py`, `reconciler.py` | **EXISTING, REUSABLE** | None |
| Payout allocation (fees, refunds, partials, duplicates, ambiguity) | `finance/reconciliation/allocation.py` | **EXISTING, REUSABLE** | None |
| Three-source composition | `finance/reconciliation/statement_workflow.py` | **EXISTING, REUSABLE** | None |
| Operator report (Markdown + JSON + evidence) | `finance/reconciliation/operator_report.py` | **EXISTING, REUSABLE** | Reuse for export (P2/P7) |
| Byte-reproducible golden evidence | `docs/evidence/operator-run/` | **EXISTING, REUSABLE** | None |
| Runtime boundary manifest | `scripts/reconciliation_boundary.py` | **EXISTING, REUSABLE** | None |
| Contract report | `scripts/reconciliation_contract_report.py` | **EXISTING, REUSABLE** | None |
| Financial invariants (A-H) | `finance/reconciliation/allocation.py` (`__post_init__`) | **EXISTING, REUSABLE** | None |

**Verdict: KEEP. No changes needed. This is the product core.**

### 2. CSV Ingestion

| Target Capability | Existing Implementation | Status | Gap |
|---|---|---|---|
| CSV parser | None | **MISSING** | Build in P1 |
| Normalizer (typed records) | `finance/reconciliation/bank.py` (bank normalization), `normalizer.py` | **EXISTING, REUSABLE** | Adapt for all 3 sources |
| Validator (row-level errors) | `finance/reconciliation/bank.py` (RejectReason, RowReject) | **EXISTING, REUSABLE** | Adapt for all 3 sources |
| Preview before accept | None | **MISSING** | Build in P1 |
| Duplicate file detection | `finance/reconciliation/bank.py` (dedupe_deposits) | **EXISTING, REUSABLE** | Adapt for file-level dedup |
| File size/encoding validation | None | **MISSING** | Build in P1 |

**Verdict: Partially exists. Bank normalization provides the pattern; invoice and Stripe normalization must be built.**

### 3. HTTP API

| Target Capability | Existing Implementation | Status | Gap |
|---|---|---|---|
| FastAPI app factory | `apps/api/main.py` | **EXISTING, REUSABLE** | Mount new reconciliation routes |
| Route registration | `apps/api/routes.py` (FP&A routes) | **REFACTOR** | Add reconciliation routes; FP&A routes to be removed |
| Pydantic schemas | `apps/api/schemas.py` (MoneyDecimal) | **EXISTING, REUSABLE** | Add reconciliation schemas |
| Tenant auth middleware | `apps/api/middleware.py` | **EXISTING, REUSABLE** | Verify with real auth |
| Observability (request ID, readiness) | `apps/api/observability.py` | **EXISTING, REUSABLE** | Add budget_check integration |
| NiceGUI console | `apps/api/operator_console.py` | **EXISTING, REUSABLE** | Extend for reconciliation screens |
| Reconciliation endpoints | None | **MISSING** | Build in P2 (15 endpoints per API_CONTRACT.md) |

**Verdict: FastAPI skeleton exists and is reusable. Reconciliation-specific routes must be built.**

### 4. Persistence

| Target Capability | Existing Implementation | Status | Gap |
|---|---|---|---|
| SQLAlchemy models | `shared/models/database.py` | **EXISTING, REUSABLE** | Add reconciliation models |
| Alembic migrations | `alembic/` (7 migrations) | **EXISTING, REUSABLE** | Add reconciliation tables migration |
| RLS (tenant isolation) | `database/migrations/` + middleware | **EXISTING, REUSABLE** | Verify with reconciliation tables |
| Repository layer | None | **MISSING** | Build in P2 |
| Unit of work | None | **MISSING** | Build in P2 |
| Reconciliation tables | None | **MISSING** | Build in P2 (12 tables per DATABASE_SCHEMA.md) |

**Verdict: ORM + migration infrastructure exists. Reconciliation-specific persistence must be built.**

### 5. Exception Lifecycle

| Target Capability | Existing Implementation | Status | Gap |
|---|---|---|---|
| Exception codes | `finance/reconciliation/models.py` (ExceptionCode enum) | **EXISTING, REUSABLE** | Engine produces codes; no lifecycle management |
| Exception state machine | None | **MISSING** | Build in P3 (per STATE_MACHINES.md) |
| Human decision recording | None | **MISSING** | Build in P3 (append-only ExceptionDecision) |
| Audit events | `shared/models/database.py` (AuditLog) | **EXISTING, REUSABLE** | Adapt for reconciliation audit |
| Authorization (role checks) | `finplatform/rbac/matrix.py` | **EXISTING, REUSABLE** | Verify with exception decisions |

**Verdict: Exception codes exist from engine. Lifecycle management must be built.**

### 6. AI Investigation

| Target Capability | Existing Implementation | Status | Gap |
|---|---|---|---|
| LLM client (canonical) | `shared/llm/` (consolidated in Slice 5) | **EXISTING, REUSABLE** | FakeLLM for CI, OpenAICompatibleProvider for prod |
| Privacy boundary | `shared/privacy/` | **EXISTING, REUSABLE** | Already wired to 5 LLM call sites |
| Investigation planner | `agents/investigation/planner.py` | **REUSE?** | Assess if adaptable for reconciliation exceptions |
| Structured output validation | `shared/llm/provider.py` (validate_structured_output) | **EXISTING, REUSABLE** | Use for investigation results |
| AI investigation endpoint | None | **MISSING** | Build in P4 |
| Evidence-grounded prompts | `finance/prompts/` (FP&A) | **REFACTOR** | Adapt for reconciliation evidence |

**Verdict: LLM infrastructure exists and is canonical. Investigation service must be built on top of it.**

### 7. NiceGUI Reconciliation Screens

| Target Capability | Existing Implementation | Status | Gap |
|---|---|---|---|
| NiceGUI console mount | `apps/api/operator_console.py` | **EXISTING, REUSABLE** | Extend for reconciliation |
| Upload workflow | None | **MISSING** | Build in P5 |
| Run initiation/progress | None | **MISSING** | Build in P5 |
| Match/allocation inspection | None | **MISSING** | Build in P5 |
| Exception queue/detail | None | **MISSING** | Build in P5 |
| AI investigation display | None | **MISSING** | Build in P5 |
| Human decision interface | None | **MISSING** | Build in P5 |
| Export/download | None | **MISSING** | Build in P5 |
| Empty/loading/success/failure states | None | **MISSING** | Build in P5 |

**Verdict: NiceGUI mount exists. All reconciliation-specific screens must be built.**

### 8. Testing

| Target Capability | Existing Implementation | Status | Gap |
|---|---|---|---|
| Unit tests (engine) | `tests/unit/reconciliation/` (352) | **EXISTING, STRONG** | None |
| Contract tests (invariants) | `tests/unit/reconciliation/test_financial_contract.py` (111) | **EXISTING, STRONG** | None |
| Golden evidence | `tests/unit/reconciliation/test_golden_evidence.py` | **EXISTING, STRONG** | None |
| Boundary manifest | `tests/unit/reconciliation/test_boundary_manifest.py` | **EXISTING, STRONG** | None |
| Integration tests (PG) | `tests/integration/` (~50) | **EXISTING, MODERATE** | Need reconciliation-specific integration tests |
| E2E (Playwright) | `tests/e2e/` (~5) | **EXISTING, WEAK** | Need reconciliation workflow E2E |
| Property-based (Hypothesis) | None | **MISSING** | Add in P1-P2 |
| Mutation testing | None | **MISSING** | Add for financial invariants |
| Failure injection | None | **MISSING** | Add in P6 |

**Verdict: Strong engine tests. API, persistence, E2E, and failure-injection tests must be built.**

### 9. Deployment

| Target Capability | Existing Implementation | Status | Gap |
|---|---|---|---|
| Docker image (API) | `Dockerfile` (multi-stage) | **EXISTING, VERIFIED** | Build verified in slice 2 |
| Docker Compose (staging) | `docker-compose.staging.yml` | **EXISTING, VERIFIED** | API + PostgreSQL |
| Docker Compose (dev) | `docker-compose.yml` | **EXISTING** | FP&A stack (needs cleanup) |
| Docker Compose (test) | `docker-compose.test.yml` | **EXISTING, VERIFIED** | Integration test orchestration |
| Migrations | Alembic (7 migrations) | **EXISTING, VERIFIED** | Add reconciliation tables |
| Health endpoints | `apps/api/observability.py` (create_readiness_router) | **EXISTING, REUSABLE** | Add /health/live, /health/ready per spec |
| Staging workflow | `.github/workflows/staging.yml` | **MISSING** | Build in P6 |

**Verdict: Docker infrastructure exists and is verified. Reconciliation-specific deployment config must be added.**

### 10. Observability

| Target Capability | Existing Implementation | Status | Gap |
|---|---|---|---|
| Structured logging | `shared/` (logging) | **EXISTING, REUSABLE** | Ensure JSON format per spec |
| Request ID middleware | `apps/api/observability.py` | **EXISTING, REUSABLE** | Keep |
| Readiness router | `apps/api/observability.py` | **EXISTING, REUSABLE** | Add migration check |
| Metrics (Prometheus) | None | **MISSING** | Build in P2-P3 |
| Tracing (OpenTelemetry) | `shared/tracing/` (needs consolidation) | **REFACTOR** | Consolidate in Slice 6 |
| Health endpoints | `apps/api/observability.py` | **EXISTING, REUSABLE** | Add /health/live, /health/ready |

**Verdict: Basic observability exists. Metrics, tracing, and structured logging per spec must be added.**

---

## Summary: Existing vs. Missing

### Existing and reusable (KEEP)
- Deterministic reconciliation engine (352 tests, 266 checks)
- LLM framework (shared/llm/, consolidated)
- Privacy boundary (shared/privacy/)
- Tenant auth middleware (apps/api/middleware.py)
- RLS infrastructure (database/migrations/)
- NiceGUI console mount (apps/api/operator_console.py)
- Alembic migrations (7, head b7e2d9f4a516)
- S3 adapter (finance/object_store/s3_adapter.py)
- Docker build (verified)
- Operator report (Markdown + JSON + evidence)
- Golden evidence bundle (byte-reproducible)
- Boundary manifest (computed)
- Contract report script (machine-readable)

### Existing but needs refactoring (REFACTOR)
- FastAPI routes (FP&A → reconciliation)
- Pydantic schemas (add reconciliation schemas)
- NiceGUI console (extend for reconciliation screens)
- Observability (add metrics, tracing, structured logs)
- Tracing (consolidate shared/tracing/)

### Missing (must be built)
- CSV ingestion (parser, normalizer, validator, preview)
- Reconciliation persistence (tables, repository, migration)
- Reconciliation API (routes, schemas, service layer)
- Exception lifecycle (state machine, decisions, audit)
- AI investigation (endpoint, wiring, structured output)
- NiceGUI reconciliation screens
- HTTP E2E tests (Playwright)
- Real authentication (replace demo headers)
- Metrics endpoint
- Export service (CSV/JSON/Markdown)

### To be removed (pending slices)
- ~25,000 LOC FP&A generation (finance/, agents/)
- ~5,000 LOC unreachable shared/finplatform/python_runtime
- ~21 historical architecture contract docs
- Unused compose services (Temporal, Redpanda, Qdrant, etc.)

### Protected (do not touch)
- `finance/reconciliation/` (engine, 352 tests)
- `tests/unit/reconciliation/` (all tests)
- `docs/evidence/operator-run/` (golden evidence)
- `finance/evaluation/` (CI dependency)
- `shared/llm/` (canonical LLM framework)
- `apps/api/operator_console.py` (NiceGUI)