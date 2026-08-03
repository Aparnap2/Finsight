# Proposal: Python Compute Runtime

## Motivation

FinSight currently runs all analytics, validation, transformation, and ML inference **inline** in the request-response cycle of the FastAPI backend (`apps/api/routes.py`). The `_run_full_pipeline()` function orchestrates ingestion, variance computation, root-cause investigation, assertion building, data-quality assessment, policy evaluation, and commentary rendering — all in a single synchronous call within the request handler. This design worked for the MVP but creates structural problems as the system grows:

- **No separation of concerns.** The backend orchestrates *and* computes. Every route that needs financial data re-instantiates engines, database connections, and LLM clients inline (`routes.py:263-372` per-endpoint duplication pattern).
- **No async job lifecycle.** Long-running analytics block the HTTP worker. There is no QUEUED/RUNNING/FAILED model — runs either complete synchronously or exist as a bare `{"status": "started"}` placeholder with no progress tracking.
- **No safe execution sandbox.** Deterministic engines run in-process with full system access. There is no isolation boundary for third-party or LLM-generated Python code.
- **No caching.** The same dataset and pipeline configuration re-executes on every request. The formula engine, variance engine, and KPI engine re-import and re-compute identical results.
- **No export pipeline.** Results are serialized ad-hoc per endpoint (`float(v.actual_amount)` conversions in `routes.py:97-108`). There is no unified export to CSV, Parquet, Excel, or chart data formats.
- **No per-job telemetry.** Duration, CPU, memory, row counts, and cache-hit ratios are not captured. Performance regression cannot be diagnosed without manual profiling.
- **No error classification.** Exceptions propagate as raw tracebacks (`detail=f"Pipeline execution failed: {e}"` pattern throughout `routes.py`). Callers get untyped 500s.

## Problem (Concrete)

1. **Backend orchestrates AND computes** → Violates the layered architecture documented in `CONTRIBUTING.md` ("Domain logic must be independent of web and AI orchestration concerns"). Routes mix HTTP concerns with financial computation.
2. **No async job lifecycle** → A full pipeline run takes 5-30+ seconds (ingestion → LLM calls → engines → commentary). The HTTP connection blocks for the entire duration. There is no polling, no webhook, no status feed.
3. **No safe Python execution** → The evaluation framework (`finance/evaluation/`) and future LLM-generated code execution require a sandbox. Currently any code runs as the main process — a crash or runaway loop kills the entire backend.
4. **No caching** → Identical `PipelineState` inputs produce identical outputs, yet every request re-executes. There is no content-addressable cache keyed on dataset hash + pipeline version + parameters.
5. **No export pipeline** → Each API endpoint invents its own serialization. There is no `ExportProvider` protocol. Callers who want CSV must re-implement the same transformation.
6. **No per-job telemetry** → There is no structured telemetry record per compute invocation. Engineering cannot answer "which jobs are slow" or "what's the p99 latency for variance computation."
7. **No error classification** → Error responses are untyped. Downstream consumers cannot programmatically distinguish "invalid input" from "data source unreachable" from "engine assertion failed."

## Requirements

1. **Async job lifecycle** — A state machine with `QUEUED → RUNNING → SUCCESS | FAILED` transitions. The API submits a job and immediately returns a `job_id`. Callers poll `/jobs/{id}/status` or subscribe via WebSocket for state transitions.
2. **Protocol-based importers** — An `Importer` protocol (extending the existing `SpreadsheetProvider` pattern from `finance/integration/protocol.py`) supporting Google Sheets, CSV, Excel, and Postgres sources. Importers produce a `Dataset` (a typed DataFrame container), not raw dicts.
3. **Dual validation** — Pydantic models validate the job request schema at the API boundary. Pandera DataFrames validate the imported dataset at the pipeline boundary. Schema and business rule violations are caught before computation begins.
4. **Transformation layer** — A `Transform` pipeline of composable steps (filter, join, aggregate, derive column) operating on Polars DataFrames. Each step is a pure function with typed inputs and outputs.
5. **Analytics engine** — DuckDB SQL execution against in-memory DataFrames for ad-hoc analytical queries (supported by the existing deterministic engines for structured computation).
6. **ML predictors** — A `Predictor` protocol backed by scikit-learn, XGBoost, or any serialized model. Predictors are loaded on demand and return typed `PredictionResult` models. The existing `RiskProvider` concept from the PRD is formalized here.
7. **Safe Python sandbox** — A `Sandbox` executor that runs user-defined or LLM-generated Python code with **no internet access, no shell access, a hard CPU-time timeout, and memory limits**. The sandbox communicates only via a `SandboxInput`/`SandboxOutput` envelope.
8. **Export pipeline** — An `Exporter` protocol with implementations for JSON, CSV, Parquet, Excel (XLSX), and Chart Data (column-oriented format for frontend visualization).
9. **Result caching** — A content-addressable cache keyed on `hash(dataset) + pipeline_version + parameters_hash`. Cache hits return in <1ms and bypass the entire pipeline. Cache entries have a configurable TTL and are invalidated on dataset refresh.
10. **Per-job telemetry** — A `JobTelemetry` record captured at job completion containing duration (ms), peak memory (MB), input row count, output row count, cache hit/miss, and error classification.
11. **Error classification** — A `ComputeError` hierarchy (`ValidationError`, `ImportError`, `SandboxError`, `TimeoutError`, `EngineError`, `ExportError`) with structured codes and human-readable messages. No raw tracebacks leak to API consumers.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Next.js Frontend                                 │
│  (UI never touches dataframes — only rendered results & chart data)     │
└───────────────────────────┬─────────────────────────────────────────────┘
                            │ REST (submit job, poll status, fetch artifact)
┌───────────────────────────▼─────────────────────────────────────────────┐
│                         FastAPI Backend (apps/api/)                       │
│  Routes receive requests → validate with Pydantic → create Job →         │
│  return job_id immediately. Polling endpoints expose status & artifacts. │
└───────────────────────────┬─────────────────────────────────────────────┘
                            │ dispatch (async via Redis queue or in-process)
┌───────────────────────────▼─────────────────────────────────────────────┐
│                      Python Compute Runtime (python_runtime/)             │
│                                                                           │
│  ┌──────────┐   ┌───────────┐   ┌──────────┐   ┌───────────┐            │
│  │ Import   │──▶│ Validate  │──▶│Transform │──▶│ Compute  │            │
│  │(Importer)│   │(Pandera)  │   │ (Polars) │   │(DuckDB)  │            │
│  └──────────┘   └───────────┘   └──────────┘   └────┬──────┘            │
│                                                      │                   │
│              ┌───────────┐    ┌──────────┐           │                   │
│              │  Predict  │    │ Sandbox  │           │                   │
│              │(Provider) │    │(Executor)│           │                   │
│              └───────────┘    └──────────┘           │                   │
│                                                      ▼                   │
│              ┌──────────┐    ┌───────────┐    ┌──────────────┐          │
│              │  Cache   │───▶│  Export   │───▶│  Artifact    │          │
│              │(hash-key)│    │(Exporter) │    │  (stored)    │          │
│              └──────────┘    └───────────┘    └──────────────┘          │
│                                                                           │
│  ┌────────────┐                                                          │
│  │ Telemetry  │◀─── per-job lifecycle events                             │
│  └────────────┘                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Sandbox security** — Escaped Python sandbox executes arbitrary code | Low | Critical | Use `subprocess` with resource limits + `seccomp` (Phase 2). Phase 1: restricted builtins, no network via `disable_socket` |
| **Cache invalidation** — Stale results served after data refresh | Medium | High | Key includes dataset content hash. Add explicit `invalidate` endpoint. TTL-based expiry as fallback |
| **Job queue backpressure** — Redis queue fills under high load | Medium | Medium | Max queue depth with `429 Too Many Requests`. Worker pool with bounded concurrency. Dead-letter queue for failed jobs |
| **Migration from inline to async** — Existing callers expect synchronous responses | High | Medium | Phase 1: support both sync (blocking wait) and async (polling) modes. Deprecate sync mode in Phase 2 |
| **DuckDB concurrency** — Concurrent in-memory DuckDB instances exhaust RAM | Medium | Medium | Pooled DuckDB connections with max concurrency. Spill-to-disk for large datasets |
| **Polars vs Pandas familiarity** — Team knows Pandas, not Polars | Medium | Low | Polars lazy API is similar. Provide Pandas-compat shim for simple transforms. Migration documented |

## Migration Plan

### Phase 1 — Foundation (same container, in-process queue)

All jobs run in the same Python process as the FastAPI backend, but through an async dispatcher with a proper state machine. This phase proves the architecture without deployment changes:

- New `python_runtime/` package (sibling to `finance/`, `agents/`, `apps/`)
- Job lifecycle state machine (in-memory + optional DB persistence)
- Dispatcher routes jobs to handlers
- Importer protocol + CSV implementation
- Pydantic + Pandera dual validation
- DuckDB analytics handler
- Export pipeline (JSON, CSV)
- Simple in-process `dict` cache
- Telemetry recording to structured logs
- All existing routes can delegate to the runtime (opt-in per endpoint)

### Phase 2 — Worker Pool (multi-container)

Jobs are dispatched to a separate worker process (or container) via Redis:

- Redis-backed job queue (`rq` or `arq`)
- Worker pool with configurable concurrency
- Sandbox executor via `subprocess`
- ML predictor loading (scikit-learn, XGBoost)
- Parquet + Excel export
- Cache backed by Redis
- Telemetry to metrics system
- Sync-to-async migration complete — inline routes call runtime with `wait=True`

### Phase 3 — Serverless (Modal)

Heavy compute jobs (ML training, large-scale analytics) offloaded to Modal:

- Modal deployment definition in `python_runtime/deploy/modal.py`
- `Importer` downloads data in worker, runs remotely
- Large JSON/Parquet artifacts stored in S3/GCS
- Cache shared across Modal and API workers via Redis
- Evaluation harness (`finance/evaluation/`) targets compute jobs

## Acceptance Criteria

- [ ] Job lifecycle state machine implemented with QUEUED → RUNNING → SUCCESS/FAILED transitions
- [ ] One importer (CSV) works end-to-end: file upload → Dataset → pipeline execution → artifact
- [ ] Pandera DataFrame validation runs and rejects invalid rows with structured errors
- [ ] DuckDB SQL query executes against an imported Dataset and returns typed results
- [ ] ML predictor (scikit-learn classifier) returns typed `PredictionResult`
- [ ] Export pipeline produces both JSON and CSV artifacts from the same JobResult
- [ ] Cache hit returns artifact in <1ms and bypasses all pipeline stages
- [ ] Sandbox executor rejects `socket.connect()` and `subprocess.run()` calls
- [ ] Telemetry record written per job with duration, row counts, and status
- [ ] All Phase 1 tasks gated at `--strict` mypy compliance

## Impact

- **Affected specs:** None yet (openspec/specs/ is empty — this is the first capability spec)
- **Affected code:**
  - `apps/api/routes.py` — Routes will delegate to runtime instead of inline computation
  - `apps/api/schemas.py` — New job submission/status/artifact schemas
  - `finance/*_engine/` — Engines remain as pure domain logic; runtime calls them
  - `finance/integration/` — Importer protocol extends existing SpreadsheetProvider pattern
  - `finance/evaluation/` — Evaluation harness will target compute jobs as test subjects
  - `shared/` — May gain new base models (e.g., `ComputeError`, `JobStatus`)
- **New dependencies:** `polars`, `duckdb`, `pandera`, `pyarrow`, `openpyxl` (optional-deps group)
- **No breaking changes** to existing API contracts — all current endpoints continue to work identically in Phase 1
