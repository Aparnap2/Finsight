# DevSecOps — Foundation Layer

**Layer**: Foundation (Layer 0 of 5)
**Dependency direction**: Provides infrastructure for all upper layers (DataOps → MLOps → LLMOps → AgentOps)
**Last updated**: 2026-07-29

---

## Purpose

DevSecOps is the bedrock of the FinSight Operations OS. It owns everything that keeps the platform running, secure, and recoverable — from the CI/CD pipeline that gates every line of code to the observability stack that surfaces every degraded mode. Upper layers (DataOps, MLOps, LLMOps, AgentOps) assume the foundation is stable: databases respond, containers restart, secrets are injected at deploy time, and a single `docker compose up` reproduces the entire environment. DevSecOps makes that assumption true.

---

## Key Capabilities

| Capability | What it owns |
|---|---|
| **CI/CD pipeline** | Ruff linting, mypy strict type checking, pytest gate (342 tests), conventional commit enforcement |
| **Infrastructure as Code** | Docker Compose topology (7 services), PostgreSQL 16 schema via Alembic, containerized builds |
| **Observability** | Structured logging (ERROR/WARNING/INFO/DEBUG), `.reasoning_traces/` for pipeline telemetry, Jaeger distributed tracing, Langfuse LLM observability |
| **Secrets management** | Zero secrets in repo — all credentials injected via environment variables through Pydantic `BaseSettings` |
| **Security** | Tenant isolation at the database row level (`tenant_id` on every table), `Decimal`-only monetary values with float rejection at the Pydantic boundary, dependency pinning |
| **Deployment** | Docker Compose for local development; architecture documented for Modal serverless migration |
| **Recovery** | Health-checked service dependencies, degraded-mode enums, graceful pipeline degradation when upstream data is stale or missing |
| **Rollback** | Git revert to baseline, Alembic migration reversal, golden dataset regression detection |

---

## Implementation Map

### 1. CI/CD Pipeline

**Gates (three-strike enforcement):**

```mermaid
flowchart LR
    A[Commit] --> B[ruff check .]
    B -->|pass| C[mypy .]
    B -->|fail| A
    C -->|pass| D[pytest]
    C -->|fail| A
    D -->|342 tests pass| E[Merge]
    D -->|fail| A
```

**Configuration files and what they enforce:**

| File | Gate | Config reference |
|---|---|---|
| `pyproject.toml` | Ruff lint — `select = ["E", "F", "I", "N", "UP", "B", "A", "SIM"]`, line-length = 100, target `py312` | Lines 41–46 |
| `pyproject.toml` | mypy strict — `strict = true`, `pydantic.mypy` plugin, Python 3.12 | Lines 48–51 |
| `pyproject.toml` | Pytest — `asyncio_mode = "auto"`, test paths under `tests/` | Lines 53–56 |
| `CONTRIBUTING.md` | Conventional commits enforced (`feat:`, `fix:`, `docs:`, etc.) | Commit Conventions section |

**Invocation pattern (never use `pytest` directly — always the module):**

```bash
uv run ruff check .      # lint
uv run mypy .            # type-check
python -m pytest         # test
```

**Test suite breakdown (342 tests across three tiers):**

```
tests/
├── unit/                              # Pure logic, no I/O (~120 tests)
│   ├── api/
│   │   └── test_decimal_layer.py      # MoneyDecimal, float rejection
│   └── test_finance/
│       ├── test_formula_engine.py     # 449 lines — registration, resolution, eval
│       ├── test_materiality.py        # 523 lines — thresholds, tiers, edge cases
│       ├── test_calendar.py           # 349 lines — fiscal periods, linking, lifecycle
│       ├── test_cognition_*.py        # Cognitive pipeline — harness, nodes, registry
│       ├── test_evaluation.py         # Evaluation framework benchmarks
│       └── test_validation_harness.py # Validation pipeline tests
├── backend/                           # Integration + agent tests
│   ├── agents/                        # 16 test files — mocked LLM, pipeline wiring
│   │   ├── test_agentic_*.py          # Formatting, hallucination, type safety, tool calls
│   │   ├── test_commentary_agent.py
│   │   ├── test_orchestrator.py
│   │   └── test_state_machine.py
│   ├── api/
│   │   ├── test_routes.py             # FastAPI endpoint contracts
│   │   └── test_schemas.py            # Request/response validation
│   ├── models/                        # ORM model tests
│   ├── validators/                    # Claim validator unit tests
│   └── test_config.py                 # Settings loading (3 tests)
├── llm/
│   └── test_providers.py              # LLM provider fallback chain
└── conftest.py                        # sys.path setup, shared fixtures
```

### 2. Infrastructure as Code

**Docker Compose topology** (`docker-compose.yml`, 131 lines — the full stack in one file):

```
Services:
├── postgres:15-alpine          # Primary OLTP — port 5432
│   ├── healthcheck: pg_isready
│   └── resource limit: 512M
├── redis:7-alpine              # Cache + rate limiting — port 6380
│   ├── healthcheck: redis-cli ping
│   └── resource limit: 128M
├── qdrant/qdrant:v1.7.0       # Vector store for RAG — ports 6333/6334
│   ├── healthcheck: /healthz
│   └── resource limit: 512M
├── redpanda:v24.2.1            # Event streaming (Kafka-compatible) — port 9092
│   └── resource limit: 384M
├── temporalio/auto-setup       # Workflow orchestration — port 7233
│   ├── depends_on: postgres (healthy)
│   └── resource limit: 512M
├── temporalio/ui               # Workflow visibility — port 8081
│   └── resource limit: 256M
├── jaegertracing/all-in-one    # Distributed tracing — ports 16686, 4317
│   └── resource limit: 256M
└── litellm:main-latest         # LLM proxy — port 4000
    ├── config: litellm-config.yaml
    ├── env: GROQ_API_KEY, OPENROUTER_API_KEY
    └── resource limit: 256M
```

**Infrastructure decisions:**

| Decision | Rationale | Code reference |
|---|---|---|
| PostgreSQL 15 (not 16) | Image availability at time of setup; migration path to 16 documented in ADR | `docker-compose.yml:3` |
| Redis on port 6380 (not 5433) | Avoids collision with PostgreSQL if both run on host | `docker-compose.yml:25` |
| RedPanda over Kafka | Single binary, no JVM dependency, memory-efficient | `docker-compose.yml:53` |
| Temporal over Celery | Built-in retry, saga patterns, visibility UI | `docker-compose.yml:70` |
| Jaeger all-in-one | Dev-only; production would use separate collector + storage | `docker-compose.yml:102` |
| LiteLLM proxy | Single endpoint for Poolside/Groq/OpenRouter fallback | `docker-compose.yml:114` |

**Container build definitions:**

| Artifact | Dockerfile | Key layers |
|---|---|---|
| Backend API | `Dockerfile.backend` (18 lines) | `python:3.12-slim`, `uv sync --no-dev`, uvicorn on port 8000 |
| Frontend | `Dockerfile.frontend` (14 lines) | `node:22-alpine`, pnpm frozen lockfile, static build |

**Database migrations (Alembic):**

```
alembic/
├── env.py            # SQLAlchemy engine, Base.metadata target
├── script.py.mako    # Migration template
└── versions/         # Ordered migration scripts
```

Migration lifecycle:
```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head       # apply
alembic downgrade -1        # rollback one step
```

### 3. Observability

**Logging levels (enforced across all modules):**

| Level | Usage | Example source |
|---|---|---|
| `ERROR` | Pipeline failures, unrecoverable errors, security violations | `apps/api/routes.py:407` — `HTTPException(status_code=500)` |
| `WARNING` | Degraded modes, data quality issues, retry events | `shared/models/degraded_mode.py` — 7 degraded mode enums |
| `INFO` | Pipeline lifecycle (started, completed), user actions | `apps/api/routes.py:125` — run completion logging |
| `DEBUG` | Development-only — never enabled in production | `.reasoning_traces/` directory (gitignored) |

**Degraded mode enum** (`shared/models/degraded_mode.py`):

```python
class DegradedMode(str, Enum):
    NONE = "none"
    PRELIMINARY_ONLY = "preliminary_only"
    MISSING_FX = "missing_fx"
    LOW_COVERAGE = "low_coverage"
    STALE_SOURCE = "stale_source"
    INSUFFICIENT_CAUSAL_EVIDENCE = "insufficient_causal_evidence"
    FACT_VERIFIED_CAUSE_UNVERIFIED = "fact_verified_cause_unverified"
    PRECEDENT_ONLY_SUPPORT = "precedent_only_support"
```

**Pipeline telemetry traces** (`.reasoning_traces/` — local dev only, not for production):

Each trace file (96 traces on disk as of 2026-07-28) captures:
```json
{
  "run_id": "run_031802f4fba6",
  "timestamp": "2026-07-28T06:12:45.243213+00:00",
  "step_count": 25,
  "iteration_count": 5,
  "overall_confidence": 0.0,
  "loop_decision": "finalize",
  "trace": [
    {
      "node_name": "planner",
      "execution_order": 1,
      "confidence": 0.5,
      "message": "Decomposed goal into 1 actions",
      "result": { ... }
    }
  ]
}
```

**Distributed tracing:**

- **Jaeger** (port 16686): OTLP collector on port 4317, traces from Temporal workflows and agent nodes
- **Langfuse** (cloud): LLM call observability — prompt/response pairs, token counts, latency per call. Configured via `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` env vars

**What NOT to log** (from `SECURITY.md`):
- API keys, tokens, or secrets
- Full database connection strings
- Individual PII values — use anonymized references
- Raw LLM prompts containing sensitive financial data — log structure, not content

### 4. Secrets Management

**Architecture:**

```
.env (gitignored) → pydantic-settings BaseSettings → os.environ (never accessed directly)
```

**The chain** (`shared/config/config.py`, 33 lines):

```python
class Settings(BaseSettings):
    postgres_uri: str = "postgresql://finsight:finsight@localhost:5432/finsight"
    openai_api_key: str = "sk-placeholder"
    groq_api_key: str = ""
    langfuse_public_key: str | None = None
    # ... 20+ settings, all with env var overrides

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
```

**Rules enforced across the codebase:**

| Rule | Enforcement |
|---|---|
| No secrets in code | `.env` in `.gitignore`, `env.example` has placeholders only |
| No `os.environ` in application code | All settings go through `get_settings()` from `shared/config/config.py` |
| No secrets in Docker config | `docker-compose.yml` references `${VARIABLE}` for API keys only |
| No secrets in logs | `SECURITY.md` prohibits logging credentials, keys, or PII |

**`.env.example` template:**

```env
POSTGRES_URI=postgresql://finsight:finsight@localhost:5432/finsight
QDRANT_URL=http://localhost:6333
REDIS_URL=redis://localhost:6380/0
OPENAI_API_KEY=sk-your-key-here
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
```

### 5. Security

**Tenant isolation — database level (`shared/models/database.py`, 349 lines):**

Every newer table carries a `tenant_id` column with a non-nullable constraint and an index:

```python
class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, nullable=False, index=True)  # ← every row
    period = Column(String(7), nullable=False)
    event_type = Column(String, nullable=False)
    event_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
```

Tables with `tenant_id` isolation (18 tables):

| Table | Class | Purpose |
|---|---|---|
| `review_decisions` | `ReviewDecision` | Human review approval/rejection |
| `action_items` | `ActionItemDB` | Gated action items |
| `commentary_versions` | `CommentaryVersion` | Versioned commentary drafts |
| `audit_logs` | `AuditLog` | Append-only audit trail |
| `pipeline_runs` | `PipelineRun` | End-to-end pipeline tracking |
| `assertions_db` | `AssertionDB` | Persistent assertion records |
| `tool_result_cache` | `ToolResultCache` | Tool call result caching |
| `data_quality_snapshots` | `DataQualitySnapshot` | Data quality metrics |
| `policy_decision_logs` | `PolicyDecisionLog` | Autonomy/routing decisions |
| `bridge_analysis_results` | `BridgeAnalysisResult` | Period-to-period bridge analysis |
| `variance_snapshots` | `VarianceSnapshot` | Point-in-time variance records |
| `root_cause_findings_db` | `RootCauseFindingDB` | Root cause findings |

**View-layer isolation** — all API routes accept and propagate `tenant_id`:

```python
@router.post("/pipeline/run")
async def trigger_pipeline(req: PipelineRunRequest):
    # req.tenant_id is threaded through every downstream call
    state: PipelineState = {
        "period": req.period,
        "tenant_id": req.tenant_id,  # ← passed to ingestion, variance, commentary
        ...
    }
```

**Monetary value protection:**

| Layer | Enforcement | File reference |
|---|---|---|
| Pydantic boundary | `MoneyDecimal` type alias with `_reject_float_money` validator | `apps/api/schemas.py:21` |
| ORM models | All monetary columns use `Numeric(15, 2)` — never `Float` | `shared/models/database.py` |
| Domain models | All `Decimal` fields in Pydantic models | `shared/models/state.py:11` |
| JSON serialization | `DecimalEncoder` serializes as strings — no float precision loss | `shared/utils/encoders.py:11` |

**Dependency security:**

- All dependencies pinned to specific versions in `pyproject.toml` (range bounds on all 27+ packages)
- `uv sync` with integrity verification
- Pre-audited libraries preferred (FastAPI, Pydantic v2, SQLAlchemy, LangChain)
- `SECURITY.md` mandates CVE review before dependency upgrades

### 6. Recovery & Degraded Operation

**Service health chain** — Docker Compose health checks enforce dependency ordering:

```
postgres (healthy) → temporal (healthy) → temporal-ui
                  → litellm (healthy)   → app backend
```

**Graceful degradation in pipeline execution** — from `apps/api/routes.py:258`:

```python
def _run_full_pipeline(period: str, tenant_id: str) -> dict:
    result = run_assertion_pipeline(variances, tool_results)
    quality_report = assess_batch(tool_results)
    policy_decision = evaluate_from_pipeline_result(
        result, degraded_modes=result.degraded_modes  # ← modes propagate up
    )
```

When data quality fails, the pipeline doesn't crash — it records a `DegradedMode` and the policy engine adjusts the autonomy level:

```python
# shared/utils/policy.py:110
if has_critical_degraded:  # LOW_COVERAGE, STALE_SOURCE, etc.
    level = AutonomyLevel.MANAGER_APPROVAL  # locks to human review
    routing_target = "manager_review"
```

**Degraded mode propagation path:**

```
ingestion_node → assertion_pipeline → policy_engine → routing_decision
      ↓                ↓                    ↓
  quality gaps    degraded_modes[]    autonomy_level    auto_publish / review / cfo_review
```

### 7. Rollback

**Code rollback — git revert:**

```bash
git revert HEAD                  # undo last commit
git revert <sha>..HEAD --no-edit # roll back a range
git checkout main && git pull    # full baseline recovery
```

**Database rollback — Alembic downgrade:**

```bash
alembic downgrade -1    # revert one migration
alembic downgrade <rev> # revert to specific revision
```

**Data rollback — golden dataset regression:**

- Golden datasets in `tests/backend/agents/` capture known-correct outputs
- Before/after comparison detects regressions:
  ```bash
  python -m pytest tests/backend/agents/ -k "golden"
  ```
- Output deviation requires explicit review and golden dataset update

---

## Interfaces

### What DevSecOps provides to layers above (DataOps, MLOps, LLMOps, AgentOps):

| Interface | What it provides | How upper layers consume it |
|---|---|---|
| **CI/CD gates** | Type-safe, linted, tested codebase | `ruff`, `mypy`, `pytest` run before every merge — guarantees upstream code quality |
| **Database connection** | PostgreSQL, Redis, Qdrant — healthy and configured | `get_settings().postgres_uri`, `get_settings().redis_url`, `get_settings().qdrant_url` |
| **Secrets injection** | API keys, connection strings at runtime | `Settings` model auto-loads from environment — upper layers call `get_settings()` |
| **Tenant isolation** | `tenant_id` on every table + API validation | Routes accept `tenant_id` parameter; agents receive it in `PipelineState` |
| **Observability pipeline** | Traces, logs, metrics stream to Jaeger + Langfuse | Agent nodes emit structured events consumed by Langfuse; Temporal pushes to Jaeger |
| **Container runtime** | Reproducible `docker compose up` for full stack | All services defined in `docker-compose.yml` with versioned images |
| **Degraded mode framework** | Enums, detection, propagation | `DegradedMode` enum imported by assertion pipeline, policy engine |
| **Rollback mechanism** | Git revert, Alembic downgrade, golden dataset | Three independent recovery paths for code, schema, and data |
| **Decimal money enforcement** | Float rejection at Pydantic boundary | `MoneyDecimal` type alias used in all API schemas and domain models |
| **LLM proxy** | LiteLLM running on port 4000 with provider fallback | `LLMClient` routes through Poolside → Groq → OpenRouter automatically |

---

## Operational Metrics

### CI/CD Health

| Metric | Target | How to measure |
|---|---|---|
| Build time | < 3 minutes | GitHub Actions workflow duration |
| Test pass rate | 100% | `python -m pytest` exit code |
| Type coverage | 100% strict | `mypy .` exit code (no `Any` leaks) |
| Lint pass rate | 100% | `ruff check .` exit code (zero warnings) |
| Test count trend | Monotonic increase | `python -m pytest --collect-only | grep tests` |
| Monetary float leaks | 0 | `grep -r "float" apps/api/schemas.py` (only in validators) |

### Infrastructure Health

| Metric | Target | How to measure |
|---|---|---|
| Service uptime | 99.9% | Docker health check pass rate |
| Database connections | < 80% pool utilization | `SELECT count(*) FROM pg_stat_activity` |
| Migration latency | < 5 seconds | `time alembic upgrade head` |
| Container startup | < 30 seconds cold start | `docker compose up` end-to-end |

### Security Posture

| Metric | Target | How to measure |
|---|---|---|
| Tenant isolation compliance | 100% | Every table has `tenant_id` with NOT NULL + index |
| Secrets in code | 0 | `git secrets --scan` pre-commit hook |
| CVE exposure | 0 critical | `uv audit` or `pip-audit` |
| Dependency freshness | < 90 days | `uv outdated` review |

### Observability Coverage

| Metric | Target | How to measure |
|---|---|---|
| Trace capture rate | 100% of pipeline runs | Langfuse trace count vs. pipeline run count |
| Degraded mode detection latency | < 1 second | Time from ingestion failure to `DegradedMode` emission |
| Log noise ratio | < 5% WARN/ERROR | Log level distribution analysis |

---

## Failure Modes

### Detection matrix

| Failure mode | Symptom | Detection | Recovery |
|---|---|---|---|
| **PostgreSQL down** | Pipeline hangs on `create_engine()`, health check fails | Docker health check (5s intervals, 5 retries) | `docker compose up -d postgres` — connections retry via SQLAlchemy pool |
| **Qdrant unavailable** | RAG queries return empty, vector search errors | `shared/utils/tools/rag_tools.py` returns `insufficient_data=True` | Pipeline enters `LOW_COVERAGE` degraded mode; agent falls back to deterministic analysis |
| **Redis unreachable** | Cache misses, rate limiter fails open | `redis_url` connection refused | Application reads through to database (no caching degradation only) |
| **LLM provider key expired** | `LLMClient.generate()` raises `RuntimeError: No LLM API key configured` | `shared/utils/llm_client.py:41` — caught by pipeline error handler | LiteLLM proxy provides fallback chain; if all keys fail, pipeline returns error to caller |
| **Alembic migration conflict** | `alembic upgrade head` fails with `Target database is not up to date` | CI/CD pipeline gate catches before deploy | `alembic stamp head` to sync, then retry; or `alembic downgrade` to rollback |
| **Monetary float leak** | `MoneyDecimal` validator raises `ValueError("Float values are not allowed...")` | Pydantic validation — caught at API boundary | Response returns 422; float value logged as error for debugging |
| **Cross-tenant data leak** | Query without `tenant_id` filter returns another tenant's rows | Code review + ORM default scope (future: per-query middleware) | Immediate incident response per `SECURITY.md` |
| **`pyproject.toml` version drift** | `uv sync` installs wrong dependency range | `uv.lock` mismatch detected in CI | Pin to `uv.lock`, rerun `uv sync --frozen-lockfile` |
| **Disk space exhaustion** | PostgreSQL write failure, `.reasoning_traces/` disk full | Container logs show `No space left on device` | Log rotation policy (TTL-based cleanup for `.reasoning_traces/`); volume monitoring alert |

### Incident response (summarized from `SECURITY.md`)

```
IDENTIFY → CONTAIN → INVESTIGATE → REMEDIATE → DOCUMENT
   │          │            │             │            │
   │      rotate keys   determine    fix vuln    update policy
   │      isolate       scope        rotate      security log
   │      services                  secrets
```

---

## Security Model

### Three pillars

#### 1. Tenant Isolation

- **Enforcement point**: Database row level — `tenant_id` column on every multi-tenant table (18 tables in `shared/models/database.py`)
- **Propagation**: API endpoint receives `tenant_id` → threads into `PipelineState` → passed to every agent node → used in all queries
- **Validation boundary**: API routes validate that the authenticated user's tenant matches the requested `tenant_id` (enforcement point at route handler)
- **Vector isolation**: Qdrant queries include `tenant_id` metadata filter at query time
- **Current gap**: No middleware-layer filter injection yet — queries explicitly reference `tenant_id` in WHERE clauses. A future enhancement will add SQLAlchemy event listeners to auto-inject tenant filters.

#### 2. Secrets Protection

- **Zero secrets in source code**: All secrets loaded at runtime from environment variables via `pydantic-settings`
- **No direct `os.environ` access**: The entire codebase routes through `get_settings()` from `shared/config/config.py`
- **`.env` is gitignored**: `.env.example` serves as the template with placeholder values
- **Security-by-design in LLM layer**: LiteLLM config references keys via `os.environ/...` syntax — keys never appear in YAML

#### 3. Monetary Value Integrity

- **Float rejected at every boundary**: `MoneyDecimal` validator in `apps/api/schemas.py:21` catches floats before they enter the domain
- **`Numeric(15, 2)` in the database**: SQLAlchemy `Numeric` columns prevent floating-point rounding errors
- **`Decimal` in domain models**: All `Variance.actual_amount`, `BudgetLine.amount`, etc. are Python `Decimal`
- **String serialization**: `DecimalEncoder` in `shared/utils/encoders.py` serializes to strings to prevent JSON float precision loss

### Trust boundaries

```
[Internet] → TLS 1.2+ → [API Gateway / FastAPI]
                            │
                     authenticate + authorize
                            │
                    tenant_id validation
                            │
              ┌─────────────┼─────────────┐
              │             │             │
         [PostgreSQL]  [Qdrant]    [Redis]
         (encrypted   (tenant      (internal
          at rest)     metadata)    network)
              │             │             │
              └─────────────┼─────────────┘
                            │
                    [Agent Layer]
                   (service-level
                    LLM credentials)
```

### Security audit trail

All pipeline execution, review decisions, and data mutations are recorded in `audit_logs` table with `tenant_id`, `event_type`, `event_data` (JSON), and `user_id`. This provides an immutable forensic record for compliance and incident investigation.

---

## Migration Paths

### Target: Modal Serverless Deployment

The current Docker Compose topology is designed for local development. The intended production target is Modal.

| Current (Docker Compose) | Target (Modal) | Migration effort |
|---|---|---|
| PostgreSQL 15 container | Modal Volume + serverless PostgreSQL (Neon/Timescale) | Medium — connection string change, no schema change |
| Redis 7 container | Modal KV or Upstash Redis | Low — same API surface |
| Qdrant container | Modal Volume + Qdrant cloud | Medium — same client library |
| RedPanda container | Modal concurrency + Kafka-compatible service | High — event model compatibility |
| Temporal container | Temporal Cloud | Medium — same SDK |
| Jaeger container | Modal observability or Grafana Cloud | Low — OTLP standard |
| LiteLLM container | Modal GPU + LiteLLM serverless | Low — same config |

**No code changes required** for migration — all configurations are environment-driven. The deployment layer is abstracted by `get_settings()`.

### Target: Production Security Hardening

| Current | Target | Migration step |
|---|---|---|
| Single user (default `CF001`) | Multi-user with RBAC | Add user model, JWT auth, permission middleware |
| Tenant isolation in WHERE clauses | Auto-injected tenant filters | SQLAlchemy `before_execute` event |
| No transport encryption | mTLS between services | Service mesh (Istio/Linkerd) |
| Default passwords | Rotation + Vault | HashiCorp Vault integration |
| Plain health checks | Authenticated health probes | Sidecar proxy |

---

*DevSecOps is the foundation. When this layer is stable, every layer above — DataOps, MLOps, LLMOps, AgentOps — operates on known ground. Instability here propagates upward instantly: a failing health check stalls the entire stack, a leaked secret compromises every tenant, a float leak corrupts every variance calculation. The discipline enforced by this layer — lint gates, type safety, tenant isolation, monetary integrity — is what makes the FinSight Operations OS auditable, recoverable, and trustworthy.*
