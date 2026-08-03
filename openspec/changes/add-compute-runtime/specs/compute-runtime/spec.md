## ADDED Requirements

### Requirement: Async Job Lifecycle

The system SHALL provide an asynchronous job lifecycle for all compute workloads, with a state machine that transitions through `QUEUED → RUNNING → SUCCESS | FAILED`.

#### Scenario: Submit job and poll to completion
- **WHEN** a client submits a valid job request via `POST /api/v1/jobs/submit`
- **THEN** the system returns HTTP 202 with a `job_id` and initial status `QUEUED`
- **AND** the system processes the job asynchronously
- **WHEN** the client polls `GET /api/v1/jobs/{job_id}/status`
- **THEN** the system returns the current status (`RUNNING`, `SUCCESS`, or `FAILED`)
- **AND** on `SUCCESS` the response includes a reference to the result artifact

#### Scenario: Job failure returns structured error
- **WHEN** a compute job encounters a recoverable error
- **THEN** the job status transitions to `FAILED`
- **AND** the status response contains a `ComputeError` with a structured error code and message
- **AND** no raw exception traceback is included in the API response

### Requirement: Protocol-Based Importers

The system SHALL provide a pluggable `Importer` protocol that reads from data sources and produces typed `Dataset` containers backed by Polars DataFrames.

#### Scenario: CSV import produces typed Dataset
- **WHEN** a CSV file is provided as a data source
- **THEN** the `CSVImporter` reads the file via `pl.read_csv()`
- **AND** returns a `Dataset` with a Polars DataFrame, schema, row count, and content hash
- **AND** the content hash is deterministic (same CSV produces same hash)

#### Scenario: Importer wraps existing SpreadsheetProvider
- **WHEN** a Google Sheets URI is provided as a data source
- **THEN** the `GoogleSheetsImporter` delegates to the existing `GoogleSheetsProvider` from `finance/integration/`
- **AND** converts the `list[list[str]]` response to a Polars DataFrame
- **AND** returns a typed `Dataset`

### Requirement: Dual Validation (Pydantic + Pandera)

The system SHALL validate compute requests and datasets using two layers: Pydantic for API request models and Pandera for DataFrame schemas.

#### Scenario: Pydantic rejects malformed request
- **WHEN** a client submits a job request with missing required fields
- **THEN** the system returns HTTP 422 with Pydantic validation errors
- **AND** no job is created

#### Scenario: Pandera rejects invalid dataset
- **WHEN** an imported dataset violates its declared Pandera schema (e.g., null values in non-nullable column)
- **THEN** the job transitions to `FAILED`
- **AND** the error code is `VALIDATION_ERROR`
- **AND** the error details include the column name, check name, and failure count

### Requirement: Transform Pipeline

The system SHALL provide a composable `Transform` pipeline of pure functions operating on Polars DataFrames, supporting filtering, column selection, renaming, derived columns, joins, and aggregation.

#### Scenario: Multi-step transform produces correct output
- **WHEN** a transform pipeline with steps `FilterRows → DeriveColumn → Aggregate` is applied to a dataset
- **THEN** each step executes in order
- **AND** the final output matches the expected result of the composed operations

### Requirement: Analytics Handler (DuckDB)

The system SHALL execute analytical SQL queries against imported datasets using DuckDB, with results returned as new Datasets.

#### Scenario: DuckDB aggregation query executes
- **WHEN** an analytics job specifies a SQL query against an imported dataset
- **THEN** the system registers the dataset as a DuckDB in-memory view
- **AND** executes the SQL query with parameter binding
- **AND** returns the result as a new `Dataset`

#### Scenario: Invalid SQL returns structured error
- **WHEN** the SQL query contains a syntax or semantic error
- **THEN** the job transitions to `FAILED`
- **AND** the error code is `ANALYTICS_ERROR`
- **AND** the error message includes the DuckDB error detail

### Requirement: ML Predictors

The system SHALL provide a `Predictor` protocol for serialized ML models (scikit-learn, XGBoost) that return typed `PredictionResult` models.

#### Scenario: Sklearn model predicts on dataset
- **WHEN** a prediction job references a trained scikit-learn model file
- **THEN** the system loads the model via joblib
- **AND** runs `predict()` on the input dataset
- **AND** returns a `PredictionResult` with predictions, confidence, model metadata, and features used

### Requirement: Safe Python Sandbox

The system SHALL execute untrusted Python code in a sandboxed subprocess with restricted builtins, no internet access, no shell access, a configurable CPU timeout, and a configurable memory limit.

#### Scenario: Sandbox rejects network access
- **WHEN** sandboxed code calls `socket.connect()`
- **THEN** the sandbox raises a runtime error
- **AND** the job transitions to `FAILED` with error code `SANDBOX_ERROR`

#### Scenario: Sandbox enforces timeout
- **WHEN** sandboxed code contains an infinite loop
- **THEN** the sandbox terminates the subprocess after the configured timeout
- **AND** the job transitions to `FAILED` with error code `SANDBOX_TIMEOUT`

#### Scenario: Sandbox returns result for valid code
- **WHEN** sandboxed code executes a valid computation
- **THEN** the sandbox returns the result via JSON over stdin/stdout
- **AND** captures stdout and stderr separately
- **AND** the job completes with `SUCCESS`

### Requirement: Export Pipeline

The system SHALL provide a pluggable `Exporter` protocol with implementations for JSON, CSV, Parquet, Excel, and Chart Data formats.

#### Scenario: JSON export produces valid artifact
- **WHEN** a compute job completes and the export format is `json`
- **THEN** the system writes the result as a JSON array of objects
- **AND** stores it as an `Artifact` with content type `application/json`

#### Scenario: CSV export produces downloadable file
- **WHEN** a compute job completes and the export format is `csv`
- **THEN** the system writes the result as CSV with header row
- **AND** stores it as an `Artifact` with content type `text/csv`

### Requirement: Result Caching

The system SHALL cache compute results keyed on the content hash of the input dataset, pipeline version, and job parameters. Cache hits SHALL bypass all pipeline stages and return in under 1 millisecond.

#### Scenario: Identical inputs return cached result
- **WHEN** a client submits a job with identical input data, pipeline, and parameters as a previously completed job
- **THEN** the system returns the cached artifact directly
- **AND** the job transitions to `SUCCESS` in under 1ms
- **AND** the telemetry records `cache_hit: true`

#### Scenario: Cache invalidation on dataset change
- **WHEN** the input dataset content changes (different hash)
- **THEN** the system computes a new result
- **AND** stores the new result in the cache
- **AND** the old cache entry is preserved until TTL expiry

### Requirement: Per-Job Telemetry

The system SHALL record structured telemetry for every compute job, including duration, peak memory, input and output row counts, cache hit status, and pipeline version.

#### Scenario: Telemetry recorded on job completion
- **WHEN** a compute job transitions to `SUCCESS` or `FAILED`
- **THEN** the system writes a `JobTelemetry` record
- **AND** the record includes `duration_ms`, `input_rows`, `output_rows`, `cache_hit`, `pipeline_version`, and per-stage timing

### Requirement: Typed Error Hierarchy

The system SHALL define a `ComputeError` model with structured error codes (`IMPORT_ERROR`, `VALIDATION_ERROR`, `ANALYTICS_ERROR`, `SANDBOX_ERROR`, `SANDBOX_TIMEOUT`, `ENGINE_ERROR`, `EXPORT_ERROR`) that are serialized in API responses. No raw Python tracebacks SHALL leak to API consumers.

#### Scenario: Error code present in failed job response
- **WHEN** a job fails with any error
- **THEN** the status response includes an `error` object with `code` and `message` fields
- **AND** the `code` is one of the defined `ComputeError` codes
- **AND** no Python traceback is present in the response body
