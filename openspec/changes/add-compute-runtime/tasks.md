# Tasks: Python Compute Runtime

Change ID: `add-compute-runtime`
Target merge: Phase 1 (Foundation) into `main`

---

## Phase 1 — Foundation (4 weeks)

### 1.1 — Runtime Scaffold

**Dependencies:** `pyproject.toml`, team consensus on Polars/DuckDB/Pandera

- [x] **1.1.1** Add optional-deps group `compute` to `pyproject.toml`:
  - `polars>=1.0,<2.0`
  - `duckdb>=1.0,<2.0`
  - `pandera[polars]>=0.20,<1.0`
  - `pyarrow>=17.0,<18.0`
  - `openpyxl>=3.1,<4.0` (Excel export)
- [x] **1.1.2** Create `python_runtime/` package with `__init__.py`
- [x] **1.1.3** Implement `python_runtime/models.py`:
  - `JobStatus` enum (`QUEUED`, `RUNNING`, `SUCCESS`, `FAILED`)
  - `ComputeError` model (`code: str`, `message: str`, `details: dict | None`)
  - `JobTelemetry` model (`duration_ms`, `peak_memory_mb`, `input_rows`, `output_rows`, `cache_hit`, `pipeline_version`, `stages`)
  - `Job` model (id, status, timestamps, tenant_id, pipeline, params, result_ref, error, telemetry)
- [x] **1.1.4** Implement `python_runtime/dispatcher.py`:
  - `Dispatcher` class with `submit()`, `get_status()`, `get_result()`, `cancel()`
  - In-process `ThreadPoolExecutor` backend (Phase 1)
  - `JobHandler` protocol for pipeline handlers
- [x] **1.1.5** Implement `python_runtime/cache.py`:
  - `ComputeCache` with `get(key)`, `set(key, artifact, ttl)`, `invalidate(dataset_hash)`
  - Phase 1: in-memory `dict` with LRU eviction (max 1000 entries)
  - Key formula: `sha256(dataset.data) + "|" + pipeline_version + "|" + sha256(params)`
- [x] **1.1.6** Implement `python_runtime/telemetry.py`:
  - `TelemetryStore` with `record(job)` method
  - Phase 1: writes structured JSON log lines (one per job completion)
- [x] **1.1.7** Run `uv lock` to resolve new dependencies
- [x] **1.1.8** Verify `ruff check .` and `mypy . --strict` pass with the new package

### 1.2 — Importer Protocol + CSV Importer

**Dependencies:** 1.1 (models + dispatcher)

- [x] **1.2.1** Implement `python_runtime/importers/protocol.py`:
  - `Dataset` model (data: `pl.DataFrame`, schema, row_count, source, imported_at, hash, metadata)
  - `Importer` protocol class with `import_data(source_uri, **kwargs) -> Dataset`
  - Helper function `compute_dataset_hash(df: pl.DataFrame) -> str`
- [x] **1.2.2** Implement `python_runtime/importers/csv_importer.py`:
  - `CSVImporter` implementing `Importer` protocol
  - Reads local CSV files via `pl.read_csv()`
  - Infers schema from Polars type inference
  - Computes content hash from DataFrame
- [x] **1.2.3** Write unit tests: `tests/test_python_runtime/test_importers/test_csv_importer.py`
  - Test with valid CSV → correct Dataset
  - Test with empty CSV → handled gracefully
  - Test with mixed types → schema inference matches expectations
  - Test hash stability: same CSV → same hash

### 1.3 — Dual Validation (Pydantic + Pandera)

**Dependencies:** 1.1 (models), 1.2 (Dataset)

- [x] **1.3.1** Implement `python_runtime/validation/schemas.py`:
  - `FinancialDatasetSchema` Pandera `DataFrameModel` (account_id, period, amount, department)
  - `VarianceInputSchema` (actual_amount, budget_amount, variance_pct)
  - Base class registry for pipeline-specific schemas
- [x] **1.3.2** Implement `python_runtime/validation/validator.py`:
  - `validate_request(model: type[BaseModel], data: dict) -> BaseModel` — standard Pydantic
  - `validate_dataset(schema: type[pa.DataFrameModel], dataset: Dataset) -> Dataset` — Pandera check
  - `DualValidator` that runs both: request then dataset
  - Returns structured `ComputeError` on failure (never raises raw exception to API)
- [x] **1.3.3** Write unit tests: `tests/test_python_runtime/test_validation/test_validator.py`
  - Test Pydantic validation of job request
  - Test Pandera validation of Dataset (pass + fail cases)
  - Test structured error output format

### 1.4 — Transform Pipeline

**Dependencies:** 1.2 (Dataset)

- [x] **1.4.1** Implement `python_runtime/transforms/pipeline.py`:
  - `TransformStep` model (name, fn: `Callable[[pl.DataFrame], pl.DataFrame]`, description)
  - `TransformPipeline` with `apply(data: pl.DataFrame) -> pl.DataFrame` and step chaining
  - Error handling: each step wrapped to capture `ComputeError`
- [x] **1.4.2** Implement `python_runtime/transforms/builtins.py`:
  - `FilterRows(condition: str)` — predicate filter
  - `SelectColumns(columns: list[str])` — column projection
  - `RenameColumn(mapping: dict[str, str])` — rename
  - `DeriveColumn(name: str, expression: str)` — `with_columns`
  - `Aggregate(by: list[str], agg: dict[str, str])` — `group_by + agg`
- [x] **1.4.3** Write unit tests: `tests/test_python_runtime/test_transforms/test_pipeline.py`

### 1.5 — Analytics Handler (DuckDB)

**Dependencies:** 1.2 (Dataset), 1.3 (validation)

- [x] **1.5.1** Implement `python_runtime/handlers/analytics_handler.py`:
  - `AnalyticsHandler` implementing `JobHandler` protocol
  - Registers Dataset as DuckDB in-memory view
  - Executes SQL query with parameter binding
  - Returns result as new `Dataset`
  - Handles DuckDB errors as `ComputeError(code="ANALYTICS_ERROR")`
- [x] **1.5.2** Register `AnalyticsHandler` in dispatcher for pipeline="analytics"
- [x] **1.5.3** Write integration tests: `tests/test_python_runtime/test_handlers/test_analytics_handler.py`
  - Test SQL aggregations on imported Dataset
  - Test parameter binding
  - Test error: invalid SQL → structured error

### 1.6 — Export Pipeline (JSON + CSV)

**Dependencies:** 1.2 (Dataset)

- [x] **1.6.1** Implement `python_runtime/exporters/protocol.py`:
  - `Artifact` model (id, job_id, format, size_bytes, created_at, storage_path, content_type)
  - `Exporter` protocol (`format` property, `export(dataset, artifact) -> Artifact`)
- [x] **1.6.2** Implement `python_runtime/exporters/json_exporter.py`:
  - `JSONExporter` — writes Dataset as JSON array of objects
  - `content_type = "application/json"`
  - `format = "json"`
- [x] **1.6.3** Implement `python_runtime/exporters/csv_exporter.py`:
  - `CSVExporter` — writes Dataset as CSV with header row
  - `content_type = "text/csv"`
  - `format = "csv"`
- [x] **1.6.4** Write unit tests: `tests/test_python_runtime/test_exporters/test_exporters.py`
  - Test JSON export produces valid JSON
  - Test CSV export produces valid CSV
  - Test round-trip: export → re-import → same Dataset

### 1.7 — Cache Integration

**Dependencies:** 1.1 (cache), 1.5 (handler), 1.6 (export)

- [x] **1.7.1** Add cache-check step to `Dispatcher` before handler dispatch:
  - Compute cache key from Dataset hash + pipeline version + params hash
  - On cache HIT: skip pipeline, return cached Artifact directly
  - On cache MISS: run pipeline, store result in cache
- [x] **1.7.2** Add cache telemetry to `JobTelemetry` (`cache_hit` field)
- [x] **1.7.3** Write tests: `tests/test_python_runtime/test_cache.py`
  - Test identical inputs produce cache HIT
  - Test different inputs produce cache MISS
  - Test cache invalidation
  - Test <1ms response on cache HIT

### 1.8 — API Endpoints

**Dependencies:** 1.1–1.7 (all runtime components)

- [x] **1.8.1** Add new schemas to `apps/api/schemas.py`:
  - `JobSubmitRequest` (pipeline, source_type, source_uri, params, tenant_id)
  - `JobSubmitResponse` (job_id, status, created_at, poll_url, result_url)
  - `JobStatusResponse` (job_id, status, error, artifact_id, duration_ms)
  - `JobErrorResponse` (code, message, details)
- [x] **1.8.2** Add new routes to `apps/api/routes.py`:
  - `POST /api/v1/jobs/submit` — accepts `JobSubmitRequest`, dispatches job, returns `JobSubmitResponse`
  - `GET /api/v1/jobs/{job_id}/status` — returns current `JobStatusResponse`
  - `GET /api/v1/jobs/{job_id}/result` — returns the artifact content (or redirect to artifact URL)
  - `GET /api/v1/artifacts/{artifact_id}` — serves stored artifact with correct Content-Type
  - `POST /api/v1/jobs/{job_id}/cancel` — attempts job cancellation
- [x] **1.8.3** Add route tests: `tests/test_python_runtime/test_api.py` (using `httpx.AsyncClient`)
  - Test job submission → 202 with job_id
  - Test status polling → QUEUED → RUNNING → SUCCESS/FAILED
  - Test artifact retrieval with different Accept headers
  - Test error: invalid job_id → 404
  - Test error: invalid request → 422 with Pydantic error

### 1.9 — Port Existing Route: CSV Import

**Dependencies:** 1.8 (API endpoints)

- [x] **1.9.1** Add new code path to `POST /api/v1/import/csv` that delegates to Compute Runtime:
  - Submits a job with `pipeline="transform"` and the CSV file content
  - Returns both `job_id` and `result` (sync mode for backward compat)
- [x] **1.9.2** Add deprecation warning to old inline CSV import path
- [x] **1.9.3** Verify all existing tests still pass unchanged

### 1.10 — End-to-End Integration Test

**Dependencies:** 1.1–1.9

- [x] **1.10.1** Write golden-path E2E test:
  - Start FastAPI test client
  - Submit job: CSV source → DuckDB analytics → JSON export
  - Poll until SUCCESS
  - Verify artifact content matches expected result
  - Re-submit same job → verify cache HIT returns <1ms
- [x] **1.10.2** Write error-path E2E tests:
  - Invalid CSV → `VALIDATION_ERROR`
  - Invalid SQL → `ANALYTICS_ERROR`
  - Missing file → `IMPORT_ERROR`
- [x] **1.10.3** Verify all 83 existing tests still pass: `python -m pytest`

---

## Phase 2 — ML & Sandbox (3 weeks)

### 2.1 — Predictor Protocol

**Dependencies:** Phase 1 complete

- [ ] **2.1.1** Implement `python_runtime/predictors/protocol.py`:
  - `PredictionResult` model (predictions, confidence, model_name, model_version, features_used)
  - `Predictor` protocol with `predict(dataset) -> PredictionResult` and `load(model_path)`
- [ ] **2.1.2** Implement `python_runtime/predictors/sklearn_predictor.py`:
  - Loads `.pkl` via `joblib`
  - Runs `predict()` and `predict_proba()`
  - Returns typed `PredictionResult`
- [ ] **2.1.3** Implement `python_runtime/predictors/xgboost_predictor.py`:
  - Loads `.json` XGBoost model
  - Runs predict with feature validation
- [ ] **2.1.4** Create a new handler `python_runtime/handlers/prediction_handler.py`:
  - Accepts `model_ref` in job params
  - Loads predictor, runs prediction, exports result
- [ ] **2.1.5** Write tests with a small trained model fixture

### 2.2 — Safe Python Sandbox

**Dependencies:** Phase 1 complete

- [ ] **2.2.1** Implement `python_runtime/sandbox/restrictions.py`:
  - Define module blocklist: `socket`, `subprocess`, `os.system`, `os.popen`, `shutil`, `ctypes`, `signal`
  - Define builtin blocklist: `__import__`, `eval`, `exec`, `compile`, `open`, `input`
  - `SandboxRestrictions` data class with `allowed_modules`, `blocked_builtins`, `max_memory_mb`, `timeout_seconds`
- [ ] **2.2.2** Implement `python_runtime/sandbox/models.py`:
  - `SandboxInput` (code, entry_point, input_data, timeout_seconds, max_memory_mb)
  - `SandboxOutput` (result, stdout, stderr, error, duration_ms)
- [ ] **2.2.3** Implement `python_runtime/sandbox/executor.py`:
  - `SandboxExecutor` with `run(input: SandboxInput) -> SandboxOutput`
  - Phase 1: subprocess with `setrlimit(RLIMIT_AS)`, `signal.alarm(timeout)`, restricted globals
  - Serializes input/output as JSON over stdin/stdout pipe
  - Captures stdout/stderr separately
  - Converts sandbox crashes to `ComputeError(code="SANDBOX_ERROR")`
- [ ] **2.2.4** Create a new handler `python_runtime/handlers/custom_handler.py`:
  - Accepts Python code string in job params
  - Passes dataset through sandbox, collects result
  - Exports via standard export pipeline
- [ ] **2.2.5** Write security tests: `tests/test_python_runtime/test_sandbox/test_executor.py`
  - Test: sandbox rejects `socket.connect()`
  - Test: sandbox rejects `subprocess.run()`
  - Test: sandbox rejects `os.system()`
  - Test: sandbox times out on infinite loop
  - Test: sandbox enforces memory limit
  - Test: sandbox returns correct result for valid code

### 2.3 — Additional Exporters

**Dependencies:** Phase 1 (export protocol)

- [ ] **2.3.1** Implement `python_runtime/exporters/parquet_exporter.py`:
  - Writes Dataset as `.parquet` via `pl.write_parquet()`
  - Optional dependency `pyarrow`
- [ ] **2.3.2** Implement `python_runtime/exporters/excel_exporter.py`:
  - Writes Dataset as `.xlsx` via `pl.write_excel()` or openpyxl
  - Optional dependency `openpyxl`
- [ ] **2.3.3** Implement `python_runtime/exporters/chart_data_exporter.py`:
  - Column-oriented dict format: `{columns: [...], rows: [[...]], row_count: N}`
  - Designed for frontend chart components (replaces ad-hoc `variance_data` serialization)

---

## Phase 3 — Production (3 weeks)

### 3.1 — Async Job Queue

**Dependencies:** Phase 1 complete

- [ ] **3.1.1** Integrate `arq` (Redis-backed async job queue):
  - Add `arq>=0.26,<1.0` to `[project.optional-dependencies] compute`
  - Define `arq.Worker` settings in `python_runtime/deploy/worker.py`
  - Implement `arq.WorkerFunc` that wraps handler dispatch
- [ ] **3.1.2** Replace in-process `ThreadPoolExecutor` with `arq` in `Dispatcher`:
  - `submit()` enqueues to Redis
  - `get_status()` reads from DB (not in-memory)
  - `get_result()` reads from artifact store
- [ ] **3.1.3** Add Redis connection config to `shared/config/config.py`:
  - Reuse existing `redis_url` setting (already defined for caching)
- [ ] **3.1.4** Write `docker-compose` worker service definition:
  ```yaml
  services:
    compute-worker:
      build:
        context: .
        dockerfile: Dockerfile.compute-worker
      command: ["arq", "python_runtime.deploy.worker.WorkerSettings"]
      depends_on: [redis, postgres]
  ```

### 3.2 — WebSocket Status Feed

**Dependencies:** 3.1 (Redis queue)

- [ ] **3.2.1** Add WebSocket endpoint to `apps/api/websocket.py`:
  - `WS /ws/jobs/{job_id}` streams status change events
  - Events: `status_change {QUEUED|RUNNING|SUCCESS|FAILED}`, `progress {pct}`, `error {code}`
- [ ] **3.2.2** Publish status changes from dispatcher to Redis pub/sub
- [ ] **3.2.3** Subscribe WebSocket handler to Redis channel per job_id

### 3.3 — Evaluation Integration

**Dependencies:** Phase 1 complete

- [ ] **3.3.1** Add `evaluation` pipeline to Compute Runtime:
  - Accepts golden dataset ID in job params
  - Runs the dataset through the cognitive harness (via `finance/cognition/harness.py`)
  - Returns evaluation metrics as artifact
- [ ] **3.3.2** Connect `finance/evaluation/runner.py` to compute runtime:
  - `runner.run_all()` submits evaluation jobs instead of calling inline
  - Collects job telemetry as part of evaluation metrics
- [ ] **3.3.3** Verify all 22 golden datasets pass regression when run through the runtime

### 3.4 — Port All Inline Endpoints

**Dependencies:** Phase 1 + 3.1

- [ ] **3.4.1** Port `POST /api/v1/pipeline/execute` to use Compute Runtime
- [ ] **3.4.2** Port `GET /api/v1/commentary/{period}` to use Compute Runtime
- [ ] **3.4.3** Port `GET /api/v1/variances/{period}` to use Compute Runtime
- [ ] **3.4.4** Port `GET /api/v1/bridge/{period}/{account_id}` to use Compute Runtime
- [ ] **3.4.5** Port `GET /api/v1/data-quality/{period}` to use Compute Runtime
- [ ] **3.4.6** Port `GET /api/v1/policy/{period}` to use Compute Runtime
- [ ] **3.4.7** Remove old inline `_run_full_pipeline()` function after all ports are verified
- [ ] **3.4.8** Run full regression: `python -m pytest` (verify all 83+ existing tests pass)

### 3.5 — Monitoring & Dashboards

**Dependencies:** 3.1 (Redis queue)

- [ ] **3.5.1** Add Prometheus metrics to compute runtime:
  - `compute_jobs_submitted_total` (counter, labels: pipeline, status)
  - `compute_job_duration_seconds` (histogram, labels: pipeline)
  - `compute_cache_hit_ratio` (gauge)
  - `compute_queue_depth` (gauge)
- [ ] **3.5.2** Add structured logging fields to all runtime components
- [ ] **3.5.3** Document runtime observability in `/docs/observability.md`

### 3.6 — Documentation

**Dependencies:** Phase 3 complete

- [ ] **3.6.1** Write `python_runtime/README.md`:
  - Architecture overview (ASCII diagram from `design.md`)
  - How to add a new Importer
  - How to add a new Handler
  - How to add a new Exporter
  - How to run locally
  - Sandbox security model
- [ ] **3.6.2** Update `CONTRIBUTING.md`:
  - Document new package dependency rules (if any)
  - Add compute runtime testing checklist
- [ ] **3.6.3** Archive this change proposal:
  - `openspec archive add-compute-runtime --yes`
  - Create capability specs for the compute runtime
