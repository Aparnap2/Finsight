# Design: Python Compute Runtime

## Context

The FinSight backend (`apps/api/routes.py`) currently executes all financial computation inline within FastAPI request handlers. As the system adds more data sources, analytics workloads, ML predictors, and export formats, inline execution creates a scalability bottleneck and violates the project's layered architecture (`CONTRIBUTING.md`). The Compute Runtime introduces a dedicated execution layer — a Python-native, protocol-driven pipeline that separates job lifecycle from request handling, computation from orchestration, and export from analytics.

### Stakeholders
- **FP&A Analysts** consume rendered output (commentary, charts, exports) — they need fast, reliable access to results
- **Finance Ops** configures data sources and monitors pipeline health — they need job-level observability
- **Backend developers** extend the system with new engines, importers, and exports — they need clear protocols
- **AI agents** (`finance/cognition/`) trigger compute jobs and consume results — they need async submission with polling

### Constraints
- All monetary values MUST use `Decimal` (`CONTRIBUTING.md` "Monetary Values" rule)
- The layered dependency flow MUST be preserved: `apps → agents → finance → shared` (one direction only)
- The runtime lives at the `finance/` layer (domain logic), not `agents/` or `apps/`
- No new third-party dependency without team consensus (all additions listed as optional-deps group)
- Python 3.12+ only
- Must pass `ruff check .` and `mypy . --strict`

## Goals / Non-Goals

### Goals
- Protocol-driven job lifecycle with async submission and status polling
- Pluggable importers (CSV, Google Sheets, Excel, Postgres) producing typed Datasets
- Dual validation: Pydantic for requests, Pandera for DataFrames
- Composable transform pipeline using Polars
- DuckDB-powered analytical queries
- ML predictor protocol with scikit-learn/XGBoost example
- Safe Python sandbox for untrusted code
- Pluggable exporters (JSON, CSV, Parquet, Excel, Chart Data)
- Content-addressable result cache
- Per-job structured telemetry
- Typed error hierarchy (no raw tracebacks to API)

### Non-Goals
- Real-time stream processing (Phase 2 may add Redpanda integration)
- Multi-tenant job isolation (tenant_id is a label, not a security boundary)
- Distributed execution across nodes (Phase 2 adds Redis worker pool)
- GPU-accelerated computation (future capability)
- Interactive notebook-style execution (the runtime is batch-oriented)
- Replacement of existing `finance/*_engine/` modules — engines remain as pure domain logic called by handlers

## High-Level Architecture

```
                  ┌──────────────────────┐
                  │   FastAPI Backend     │
                  │   (apps/api/)         │
                  │                       │
                  │ POST /jobs/submit ────┼───▶ returns job_id
                  │ GET  /jobs/{id}  ◀────┼─── status + result_url
                  │ GET  /artifacts/{id}  │
                  └──────────┬────────────┘
                             │ dispatch
                  ┌──────────▼────────────┐
                  │   Dispatcher          │
                  │   (python_runtime/)   │
                  │                       │
                  │  ┌─────────────────┐  │
                  │  │  Job State      │  │  QUEUED → RUNNING → SUCCESS|FAILED
                  │  │  Machine        │  │
                  │  └────────┬────────┘  │
                  │           │           │
                  │  ┌────────▼────────┐  │
                  │  │  Handler        │  │  routes job to pipeline
                  │  └────────┬────────┘  │
                  │           │           │
                  │  ┌────────▼────────┐  │
                  │  │  Pipeline       │  │  Import → Validate → Transform → Compute → Export
                  │  └─────────────────┘  │
                  │                       │
                  │  ┌────────┐ ┌──────┐  │  ┌────────┐ ┌────────┐
                  │  │ Cache  │ │Telmty│  │  │Sandbox│ │Predict │
                  │  └────────┘ └──────┘  │  └────────┘ └────────┘
                  └───────────────────────┘
```

## Component Design

### 1. Job Model (`python_runtime/models.py`)

The central data model for all compute jobs. Every job has a lifecycle, a set of parameters, reference to input data, and a result.

```python
from enum import StrEnum, auto
from uuid import UUID, uuid4
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel

class JobStatus(StrEnum):
    QUEUED = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()

class ComputeError(BaseModel):
    code: str          # e.g., "IMPORT_ERROR", "VALIDATION_ERROR", "SANDBOX_TIMEOUT"
    message: str       # human-readable
    details: dict | None = None

class JobTelemetry(BaseModel):
    duration_ms: int
    peak_memory_mb: float
    input_rows: int = 0
    output_rows: int = 0
    cache_hit: bool = False
    pipeline_version: str
    stages: dict[str, int] = {}  # stage_name → duration_ms

class Job(BaseModel):
    id: UUID = uuid4()
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    tenant_id: str
    pipeline: str                # which pipeline to run
    params: dict                 # pipeline-specific parameters
    dataset_ref: str | None      # reference to stored dataset
    result_ref: str | None       # reference to stored artifact
    error: ComputeError | None = None
    telemetry: JobTelemetry | None = None
```

### 2. Dispatcher (`python_runtime/dispatcher.py`)

Routes incoming jobs to the correct handler. In Phase 1, dispatch is in-process (thread pool). The Dispatcher owns the state machine transitions.

```
Job submitted → Dispatcher.dispatch(job)
  ├─ validate job model (Pydantic)
  ├─ set status = QUEUED
  ├─ enqueue (in-process ThreadPoolExecutor or Redis)
  └─ return job_id to caller

Worker picks up job:
  ├─ set status = RUNNING
  ├─ call pipeline handler
  ├─ set status = SUCCESS | FAILED
  └─ write telemetry
```

Key interfaces:
```python
class Dispatcher:
    def submit(self, job: Job) -> UUID: ...
    def get_status(self, job_id: UUID) -> JobStatus: ...
    def get_result(self, job_id: UUID) -> JobResult | None: ...
    def cancel(self, job_id: UUID) -> bool: ...

class JobHandler(Protocol):
    """Handles one pipeline variant."""
    async def handle(self, job: Job) -> JobResult: ...
```

### 3. Importer Protocol + Dataset (`python_runtime/importers/`)

Extends the existing `SpreadsheetProvider` protocol pattern from `finance/integration/protocol.py`. An `Importer` reads from a source and produces a `Dataset`.

```python
from typing import Protocol
import polars as pl

class Dataset(BaseModel):
    """Typed container for imported tabular data."""
    data: pl.DataFrame      # the actual data, owned by this Dataset
    schema: pl.Schema       # polars schema
    row_count: int
    source: str             # e.g., "csv", "google_sheets"
    imported_at: datetime
    hash: str               # content hash for caching
    metadata: dict = {}

class Importer(Protocol):
    """Reads from a source and returns a Dataset."""
    def import_data(self, source_uri: str, **kwargs) -> Dataset: ...
```

Initial implementations:
- `CSVImporter` — reads local CSV, produces Dataset with inferred schema
- `GoogleSheetsImporter` — wraps existing `GoogleSheetsProvider`, returns DataFrame
- `ExcelImporter` — reads `.xlsx` via Polars or openpyxl
- `PostgresImporter` — executes SQL query against configured connection, returns Dataset

### 4. Validator (`python_runtime/validation/`)

Dual-layer validation:

**Layer 1 — Pydantic (request boundary):**
```python
class JobRequest(BaseModel):
    pipeline: str
    source_type: Literal["csv", "google_sheets", "excel", "postgres"]
    source_uri: str
    params: dict = {}
    # Pydantic validates this at the API layer
```

**Layer 2 — Pandera (DataFrame boundary):**
```python
import pandera as pa

class FinancialDatasetSchema(pa.DataFrameModel):
    account_id: str = pa.Field(nullable=False)
    period: str = pa.Field(nullable=False)
    amount: Decimal = pa.Field(nullable=False, ge=0)
    department: str = pa.Field(nullable=True)

# Pandera validates the imported DataFrame before any transform/compute
```

The validators are composable — each pipeline variant can declare its own Pandera schema.

### 5. Transform Pipeline (`python_runtime/transforms/`)

A sequence of pure functions operating on `pl.DataFrame`:

```python
class TransformStep(BaseModel):
    name: str
    fn: Callable[[pl.DataFrame], pl.DataFrame]
    description: str = ""

class TransformPipeline:
    steps: list[TransformStep]

    def apply(self, data: pl.DataFrame) -> pl.DataFrame:
        """Apply each step in order. Each step is a pure function."""
        for step in self.steps:
            data = step.fn(data)
        return data
```

Built-in transform steps:
- `FilterRows` — `filter(col("amount") > 0)`
- `SelectColumns` — `select(["account_id", "period", "amount"])`
- `RenameColumn` — `rename({"old": "new"})`
- `DeriveColumn` — `with_columns((col("a") / col("b")).alias("ratio"))`
- `JoinDatasets` — `join(other, on="account_id", how="left")`
- `Aggregate` — `group_by("department").agg(sum("amount"))`

### 6. Analytics Handler (`python_runtime/handlers/analytics_handler.py`)

Executes DuckDB SQL queries against in-memory Polars DataFrames:

```python
import duckdb

class AnalyticsHandler:
    def execute(
        self,
        dataset: Dataset,
        query: str,
        params: dict | None = None,
    ) -> Dataset:
        """Register DataFrame as DuckDB view, execute SQL, return result Dataset."""
        conn = duckdb.connect()
        conn.register("data", dataset.data.to_pandas())  # DuckDB > Pandas zero-copy
        result = conn.execute(query, params or {}).fetchdf()
        return Dataset(
            data=pl.from_pandas(result),
            source="duckdb",
            hash=...,
            ...
        )
```

### 7. Predictor Protocol (`python_runtime/predictors/`)

```python
class PredictionResult(BaseModel):
    predictions: list  # typed predictions
    confidence: float
    model_name: str
    model_version: str
    features_used: list[str]
    metadata: dict = {}

class Predictor(Protocol):
    """A serialized ML model that produces typed predictions."""
    def predict(self, dataset: Dataset) -> PredictionResult: ...
    def load(self, model_path: str) -> None: ...
```

Concrete implementations:
- `SklearnPredictor` — loads `.pkl` via joblib, runs `predict()` / `predict_proba()`
- `XGBoostPredictor` — loads `.json` model, runs XGBoost predict

The `RiskProvider` concept from the PRD (v1, §4 Reason Layer) maps to a Predictor that returns risk scores/classifications.

### 8. Sandbox Executor (`python_runtime/sandbox/`)

Executes untrusted Python code in an isolated subprocess with strict resource limits:

```python
class SandboxInput(BaseModel):
    code: str
    entry_point: str = "run"  # function name to call
    input_data: dict = {}
    timeout_seconds: int = 30
    max_memory_mb: int = 256

class SandboxOutput(BaseModel):
    result: Any = None
    stdout: str = ""
    stderr: str = ""
    error: ComputeError | None = None
    duration_ms: int = 0
```

Implementation approach (Phase 1):
- Subprocess with restricted builtins (`__builtins__` limited)
- `socket` module disabled via `disable_socket` or by removing from path
- `subprocess` import blocked
- `os.system`, `os.popen`, `shutil` imports blocked
- SIGALRM-based timeout (Unix)
- Resource limit via `resource.setrlimit(RLIMIT_AS, ...)`

Phase 2 enhancement: Docker container per sandbox execution with seccomp profile.

### 9. Export Pipeline (`python_runtime/exporters/`)

```python
class Artifact(BaseModel):
    id: UUID
    job_id: UUID
    format: str  # "json", "csv", "parquet", "xlsx", "chart_data"
    size_bytes: int
    created_at: datetime
    storage_path: str       # local path or S3 URI
    content_type: str

class Exporter(Protocol):
    format: str
    content_type: str
    def export(self, dataset: Dataset, artifact: Artifact) -> Artifact: ...
```

Implementations:
- `JSONExporter` — `dataset.data.write_json()`
- `CSVExporter` — `dataset.data.write_csv()`
- `ParquetExporter` — `dataset.data.write_parquet()`
- `ExcelExporter` — writes to XLSX via Polars `write_excel()` (or openpyxl for complex sheets)
- `ChartDataExporter` — column-oriented dict format designed for frontend charts

### 10. Cache (`python_runtime/cache.py`)

```python
class ComputeCache:
    """Content-addressable cache for compute results.

    Key = hash(dataset.data) + "|" + pipeline_version + "|" + hash(params)
    """

    def get(self, key: str) -> Artifact | None: ...
    def set(self, key: str, artifact: Artifact, ttl_seconds: int = 3600) -> None: ...
    def invalidate(self, dataset_hash: str) -> int: ...
```

Phase 1: in-process `dict[str, Artifact]` with LRU eviction.
Phase 2: Redis-backed with TTL.

### 11. Telemetry (`python_runtime/telemetry.py`)

```python
class TelemetryStore:
    def record(self, job: Job) -> None:
        """Write job telemetry: duration, memory, rows, status, error code."""
        # Phase 1: structured JSON log line
        # Phase 2: write to telemetry DB / metrics system
```

## Data Flow

```
Request (HTTP POST /jobs/submit)
  │
  ▼
Pydantic Validation (JobRequest schema)
  │
  ▼
Dispatcher.submit(job)
  │  status = QUEUED
  │  returns job_id
  │
  ▼
Worker picks up job (in-process or Redis)
  │  status = RUNNING
  │
  ├──▶ Importer.import_data(source_uri) → Dataset
  │      │
  │      ▼
  │    Pandera Validation (FinancialDatasetSchema)
  │      │
  │      ▼
  │    Check Cache (hash lookup)
  │      │
  │      ├── HIT → return cached Artifact
  │      │
  │      └── MISS → continue
  │
  ├──▶ TransformPipeline.apply(dataset) → normalized Dataset
  │
  ├──▶ AnalyticsHandler.execute(dataset, query) → result Dataset
  │      │  (or Predictor.predict(dataset) or SandboxExecutor.run(input))
  │
  ├──▶ Exporter.export(result_dataset) → Artifact
  │
  ├──▶ Cache.set(key, artifact)
  │
  ├──▶ TelemetryStore.record(job)
  │
  └──▶ status = SUCCESS

Polling: GET /jobs/{id} → current status + artifact reference
```

## Directory Structure

```
finsight/
├── python_runtime/                         # NEW: Compute Runtime package
│   ├── __init__.py
│   ├── models.py                           # Job, JobStatus, ComputeError, JobTelemetry
│   ├── dispatcher.py                       # Dispatcher, JobHandler protocol
│   ├── cache.py                            # ComputeCache (Phase 1: in-memory)
│   ├── telemetry.py                        # TelemetryStore
│   │
│   ├── importers/                          # Protocol-based data import
│   │   ├── __init__.py
│   │   ├── protocol.py                     # Importer protocol, Dataset model
│   │   ├── csv_importer.py                 # CSVImporter
│   │   ├── google_sheets_importer.py       # wraps existing GoogleSheetsProvider
│   │   ├── excel_importer.py               # ExcelImporter (optional dep)
│   │   └── postgres_importer.py            # PostgresImporter
│   │
│   ├── validation/                         # DataFrame-level validation
│   │   ├── __init__.py
│   │   ├── schemas.py                      # Pandera DataFrameModel definitions
│   │   └── validator.py                    # DualValidator (Pydantic + Pandera)
│   │
│   ├── transforms/                         # Transform pipeline
│   │   ├── __init__.py
│   │   ├── pipeline.py                     # TransformPipeline, TransformStep
│   │   └── builtins.py                     # Filter, Select, Rename, Derive, Join, Aggregate
│   │
│   ├── handlers/                           # Pipeline handlers (one per pipeline variant)
│   │   ├── __init__.py
│   │   ├── base.py                         # Handler protocol mixin
│   │   ├── analytics_handler.py            # DuckDB SQL execution
│   │   ├── transform_handler.py            # Transform-only pipeline
│   │   └── custom_handler.py               # Sandbox-based custom code pipeline
│   │
│   ├── predictors/                         # ML model predictors
│   │   ├── __init__.py
│   │   ├── protocol.py                     # Predictor protocol, PredictionResult
│   │   ├── sklearn_predictor.py            # scikit-learn model loader
│   │   └── xgboost_predictor.py            # XGBoost model loader
│   │
│   ├── sandbox/                            # Safe Python execution
│   │   ├── __init__.py
│   │   ├── executor.py                     # SandboxExecutor (subprocess + resource limits)
│   │   ├── restrictions.py                 # Builtin restrictions, module blocklist
│   │   └── models.py                       # SandboxInput, SandboxOutput
│   │
│   ├── exporters/                          # Export pipeline
│   │   ├── __init__.py
│   │   ├── protocol.py                     # Exporter protocol, Artifact model
│   │   ├── json_exporter.py                # JSON export
│   │   ├── csv_exporter.py                 # CSV export
│   │   ├── parquet_exporter.py             # Parquet export (optional)
│   │   ├── excel_exporter.py               # Excel export (optional)
│   │   └── chart_data_exporter.py          # Column-oriented chart format
│   │
│   └── deploy/                             # Deployment configs
│       ├── __init__.py
│       └── modal.py                        # Phase 3: Modal deployment definition
│
├── tests/
│   └── test_python_runtime/                # Mirrors python_runtime/ structure
│       ├── test_dispatcher.py
│       ├── test_importers/
│       │   ├── test_csv_importer.py
│       │   └── test_google_sheets_importer.py
│       ├── test_validation/
│       │   └── test_validator.py
│       ├── test_handlers/
│       │   └── test_analytics_handler.py
│       ├── test_sandbox/
│       │   └── test_executor.py
│       ├── test_exporters/
│       │   └── test_exporters.py
│       └── test_cache.py
│
└── pyproject.toml                          # + optional-deps groups for polars, duckdb, etc.
```

## API Contract

### Job Submission

```http
POST /api/v1/jobs/submit
Content-Type: application/json

{
  "pipeline": "analytics",
  "source_type": "csv",
  "source_uri": "/data/revenue_2026Q1.csv",
  "params": {
    "query": "SELECT department, SUM(amount) FROM data GROUP BY department",
    "validation_schema": "financial_dataset"
  },
  "tenant_id": "CF001"
}

→ 202 Accepted
{
  "job_id": "f1a2b3c4-...",
  "status": "queued",
  "created_at": "2026-07-29T12:00:00Z",
  "poll_url": "/api/v1/jobs/f1a2b3c4/status",
  "result_url": "/api/v1/jobs/f1a2b3c4/result"
}
```

### Job Status Polling

```http
GET /api/v1/jobs/{job_id}/status

→ 200 OK
{
  "job_id": "f1a2b3c4-...",
  "status": "success",
  "created_at": "2026-07-29T12:00:00Z",
  "started_at": "2026-07-29T12:00:01Z",
  "completed_at": "2026-07-29T12:00:05Z",
  "duration_ms": 4231,
  "result": {
    "artifact_id": "art_abc123",
    "format": "json",
    "size_bytes": 24580,
    "content_type": "application/json"
  }
}
```

### Artifact Retrieval

```http
GET /api/v1/artifacts/{artifact_id}
Accept: application/json

→ 200 OK
{ "rows": [...], "columns": [...], "row_count": 150 }

# or with Accept: text/csv
→ 200 OK
Content-Type: text/csv
...
```

### Error Response

```http
GET /api/v1/jobs/{job_id}/status  (when FAILED)

→ 200 OK
{
  "job_id": "f1a2b3c4-...",
  "status": "failed",
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Dataset failed Pandera validation: column 'amount' has 3 null values",
    "details": {
      "schema": "financial_dataset",
      "errors": [
        {"column": "amount", "check": "not_null", "failure_count": 3}
      ]
    }
  }
}
```

### WebSocket Subscription (Phase 2)

```
WS /ws/jobs/{job_id}

→ {"event": "status_change", "status": "queued"}
→ {"event": "status_change", "status": "running"}
→ {"event": "status_change", "status": "success", "artifact_id": "art_abc123"}
```

## Integration Points

### With Agent Runtime (`finance/cognition/`)

The Agent runtime (`ReasoningHarness` in `finance/cognition/harness.py`) orchestrates the cognitive loop (plan → execute → verify → reflect). Currently, agent nodes call engines directly. With the Compute Runtime:

1. **Agent nodes submit compute jobs** instead of calling engines inline. A node submits a job, receives a `job_id`, and polls until completion.
2. **The `FinanceTool` protocol** (if it exists) gains a `submit_compute(job: Job) -> UUID` method.
3. **Result polling** happens in a new `compute_poll` node that blocks until the job completes (with timeout).
4. **Cache integration** — if the same computation was performed by a previous agent iteration, the runtime returns the cached artifact, avoiding redundant LLM-triggered recomputation.

```
Before: VarianceNode → call variance_engine directly
After:  VarianceNode → submit Job("variance", params) → poll → read Artifact
```

### With SpreadsheetProvider (`finance/integration/`)

The existing `SpreadsheetProvider` protocol (`finance/integration/protocol.py`) reads cell ranges as `list[list[str]]`. The Compute Runtime's `Importer` protocol wraps this:

```python
class GoogleSheetsImporter:
    def __init__(self, provider: GoogleSheetsProvider):
        self._provider = provider

    def import_data(self, source_uri: str, **kwargs) -> Dataset:
        # Parse spreadsheet_id and range from URI
        raw = self._provider.read_range(spreadsheet_id, range)
        # Convert list[list[str]] → polars DataFrame with type inference
        df = pl.DataFrame(raw[1:], schema=raw[0], orient="row")
        return Dataset(data=df, ...)
```

This means the existing `GoogleSheetsProvider`, `CSVProvider`, and `MockProvider` remain unchanged. The Runtime's importers are adapters that produce `Dataset`.

### With Evaluation Framework (`finance/evaluation/`)

The evaluation framework (`finance/evaluation/runner.py`) runs golden datasets through the cognitive harness to measure quality. With the Compute Runtime:

1. **Evaluation jobs become compute jobs.** An evaluation is a `Job` with pipeline="evaluation" and parameters referencing a golden dataset.
2. **Regression harness** (`finance/evaluation/regression.py`) can target the runtime directly: submit each golden dataset as a compute job, collect timing and correctness metrics.
3. **Telemetry feeds evaluation metrics.** Job duration, row counts, and error rates become part of the evaluation dashboard.

### With Existing Deterministic Engines (`finance/*_engine/`)

The six engines (formula, variance, KPI, scenario, driver, forecast) remain as **pure domain logic** in `finance/`. They do not move into the runtime. Instead, the runtime calls them through handler adapters:

```python
class VarianceAnalysisHandler:
    def handle(self, job: Job) -> JobResult:
        dataset = self.importer.import_data(job.source_uri)
        df = dataset.data.to_pandas()  # engines currently use pandas/dicts
        result = variance_engine.compute(df, **job.params)
        return JobResult(data=result)
```

This preserves the layered architecture: the runtime depends on `finance/*_engine/`, not the other way around.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| DataFrame library | **Polars** (not Pandas) | Lazy evaluation, zero-copy with DuckDB, strongly typed, Arrow-native. Engines still use Pandas internally — adapters convert at the boundary |
| Analytics engine | **DuckDB** (not SQLAlchemy/Spark) | In-process, zero-copy from Polars/Pandas, fast for analytical queries, no external dependency |
| Sandbox approach | **Subprocess + resource limits** (not Docker in Phase 1) | Simpler deployment, no Docker-in-Docker. Phase 2 upgrades to container-per-sandbox |
| Cache key | `hash(dataset.data) + pipeline_version + hash(params)` | Content-addressable: same data + same config = same result. Pipeline version bumps invalidate all |
| Job queue | **In-process ThreadPoolExecutor** (Phase 1), **arq/Redis** (Phase 2) | Phase 1: zero infrastructure, proves the API. Phase 2: production durability |
| Error hierarchy | **Typed `ComputeError` model** (not exceptions) | API-friendly, serializable, programmatically actionable. Exceptions are caught at the handler boundary and converted |
| Package name | `python_runtime/` (not `compute/` or `engine/`) | Avoids confusion with existing `finance/*_engine/` modules. Describes what it is: a runtime for Python-native workloads |

## Risks / Trade-offs

| Risk | Impact | Mitigation |
|------|--------|------------|
| Job lifecycle overhead adds latency for simple computations | Medium | Optimistic path: cache hit bypasses queue entirely. Sync mode: `wait=True` parameter blocks inline |
| Pandera + Polars type system conflicts | Low | Pandera supports Polars natively (pandera>=0.20). Pin compatible versions |
| DuckDB zero-copy from Polars is not truly zero-copy | Low | Acceptable for Phase 1. Profile and optimize in Phase 2 with `duckdb` native Parquet reads |
| Subprocess sandbox does not prevent all escape vectors | Medium | Phase 1 sandbox constrains honest code, not malicious. Document as "defense-in-depth, not a security boundary". Phase 2 adds Docker |
| Team learns Polars + DuckDB + Pandera simultaneously | Medium | One-day spike recommended before Phase 1 starts. Each developer implements one importer |

## Migration Plan

### Step 1 — Runtime scaffold (no behavior change)
- Create `python_runtime/` directory with `models.py`, `dispatcher.py`, `cache.py`
- Implement `Job`, `JobStatus`, `ComputeError`, `JobTelemetry` models
- Implement `Dispatcher` with in-process `ThreadPoolExecutor`
- Add `polars`, `duckdb`, `pandera` to `pyproject.toml` `[project.optional-dependencies]` as `compute`
- All existing routes continue to work identically

### Step 2 — First pipeline: CSV import → DuckDB query → JSON export
- Implement `CSVImporter`, `Dataset` model
- Implement `DualValidator` (Pydantic request + Pandera DataFrame)
- Implement `AnalyticsHandler` (DuckDB)
- Implement `JSONExporter`, `CSVExporter`
- Implement `ComputeCache` (in-memory dict)
- Implement `TelemetryStore` (structured logging)
- Add `/api/v1/jobs/submit` and `/api/v1/jobs/{id}/status` endpoints
- Verify: POST CSV → get job_id → poll → get JSON result

### Step 3 — Port existing inline endpoints (one per PR)
- Each existing route in `routes.py` gets a new code path: submit a Job and poll
- Old inline path remains with deprecation warning
- Example: `POST /api/v1/pipeline/execute` submits a job instead of calling `_run_full_pipeline()` directly

### Step 4 — ML Predictors + Sandbox
- Implement `Predictor` protocol, `SklearnPredictor`
- Implement `SandboxExecutor` with resource limits
- Add custom pipeline handler that accepts Python code strings

### Step 5 — Switch to async queue (Phase 2)
- Replace in-process queue with `arq` (Redis-based)
- Worker process reads from Redis queue
- WebSocket subscription for real-time status

## Rollback

1. **Per-endpoint rollback**: Each ported endpoint retains its old inline code path. Set `feature_flag.use_compute_runtime = false` to revert.
2. **Phase 1 → inline fallback**: If the runtime crashes, the dispatcher catches the error and the existing `_run_full_pipeline()` executes as fallback.
3. **Cache clear**: Call `GET /admin/cache/clear` to invalidate all cache entries.
4. **Version pin**: `pyproject.toml` records exact versions of new dependencies. `uv lock` rollback via git revert.

## Open Questions

1. Should the runtime support **streaming results** (e.g., chunked JSON for large datasets)?
   - Phase 1: no. Artifacts are written to disk/S3 and served via download URL.
2. Should the runtime be a **standalone service** or a library loaded by the existing backend?
   - Phase 1: library (same process, separate package). Phase 2: standalone worker service.
3. What is the **cache eviction policy**?
   - Phase 1: LRU with max 1000 entries. Phase 2: Redis TTL + explicit invalidate.
4. Should the `Predictor` protocol support **online learning** (model updates)?
   - No. Predictors are read-only. Model training is a separate capability.
5. How does the runtime handle **large datasets** (>1GB)?
   - Phase 1: document 1GB limit. Phase 2: DuckDB can query Parquet directly without loading into memory.
