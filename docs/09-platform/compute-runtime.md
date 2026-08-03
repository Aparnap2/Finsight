# Python Compute Runtime — Execution Engine

**Layer classification:** Foundation execution — general-purpose compute that powers all Python-native workloads  
**Layer position:** Below DevSecOps — the substrate on which every operational layer runs  
**Codebase path:** `python-runtime/` (proposed)  
**Status:** Greenfield — architecture and design specification

---

## Purpose

The Python Compute Runtime is the general-purpose execution engine for all Python-native workloads in the Finance Operations OS. It is **not** an "ML container," a "data pipeline runner," or an "AI inference server" — ML inference, data validation, financial analytics, and safe sandboxed execution are all equally important handler types that the runtime dispatches, monitors, and governs.

The runtime exists because the Node.js backend (Next.js) orchestrates but never manipulates dataframes. Python computes. The backend sends a typed request; the runtime executes it, validates the output, and returns a structured result. Every transformation — from spreadsheet ingestion to XGBoost inference to LLM-generated Python execution — passes through the same request lifecycle, shares the same observability substrate, and fails with the same classified error model.

```
                    Finance Operations OS

                 ┌──────────────────────────┐
                 │       AgentOps           │
                 ├──────────────────────────┤
                 │        LLMOps            │
                 ├──────────────────────────┤
                 │        MLOps             │
                 ├──────────────────────────┤
                 │       DataOps            │
                 ├──────────────────────────┤
                 │       DevSecOps          │
                 ├──────────────────────────┤
                 │   Python Compute Runtime  │
                 └──────────────────────────┘
```

### What the runtime owns

| Responsibility | Detail |
|---------------|--------|
| **Request lifecycle** | Every compute job follows the same 11-stage pipeline from authentication to telemetry |
| **Dispatcher** | Routes job types to handlers — analytics, ML inference, validation, sandboxed execution |
| **Import abstraction** | Typed `Importer` Protocol for all data sources (Google Sheets, CSV, Excel, Postgres, future ERP) |
| **Dataset validation** | Pandera schema enforcement on every imported dataset before computation |
| **Sandboxed execution** | Safe Python execution environment for LLM-generated code — no internet, no shell, no data leaks |
| **Export pipeline** | Structured output serialization — Pydantic models to JSON, CSV, Parquet, Excel, chart data |
| **Observability** | Every job emits logs, metrics, traces, and artifacts — unified across all handler types |
| **Caching** | Deterministic cache-key computation for idempotent jobs — skip recomputation on identical inputs |
| **Error classification** | Typed error model with stage, recoverability, and retryability — never raw tracebacks |
| **State machine** | QUEUED → RUNNING → VALIDATING → EXECUTING → EXPORTING → SUCCESS (or FAILED → RETRYING → FAILED) |

### What the runtime does NOT own

- **Agent orchestration** — belongs to AgentOps (LangGraph state machines, routing, HITL checkpoints)
- **LLM prompt management** — belongs to LLMOps (prompt versioning, LiteLLM routing, Langfuse tracing)
- **Model lifecycle** — belongs to MLOps (training, feature engineering, model registry, drift monitoring)
- **Data governance** — belongs to DataOps (domain models, evidence chains, fiscal calendar, lineage)
- **Infrastructure** — belongs to DevSecOps (containers, secrets, CI/CD, database connections)

---

## Architecture

```
                    Finance Operations OS

               ┌──────────────────────────┐
               │      Next.js Backend      │
               │  (orchestrates, never     │
               │   manipulates dataframes) │
               └─────────────┬────────────┘
                             │
                   HTTP / gRPC / Queue
                             │
               ┌─────────────▼────────────┐
               │   Python Compute Runtime │
               │   ┌───────────────────┐  │
               │   │    Dispatcher     │  │
               │   │   routes by type  │  │
               │   └───┬───┬───┬───┬──┘  │
               │       │   │   │   │     │
               └───────┼───┼───┼───┼─────┘
                       │   │   │   │
      ┌────────────────┼───┼───┼───┼────────────────┐
      ▼                ▼   ▼   ▼   ▼                ▼
 Validation      Analytics  ML Inference  Safe Python  Export
 Pandera         DuckDB     sklearn       Sandboxed    JSON, CSV,
 Pydantic        Polars     XGBoost       Execution    Parquet, Excel
```

### Communication pattern

The Next.js backend never imports `pandas`, `polars`, `sklearn`, or any Python data library. It sends typed, serializable requests to the Python Runtime via one of three transport mechanisms:

| Transport | Use case | Latency |
|-----------|----------|---------|
| **HTTP (FastAPI)** | Synchronous queries — validation checks, simple lookups | < 5s |
| **gRPC** | Streaming results — large dataset exports, progress polling | Variable |
| **Message queue (RedPanda)** | Async batch jobs — forecast runs, bulk analytics | Minutes |

**Design rule:** Every request is a Pydantic model on arrival. The backend constructs it; the runtime validates it. Rejected requests never consume compute resources beyond deserialization.

---

## Request Lifecycle

Every job — no matter how simple or complex — passes through the same 11-stage pipeline. This uniformity is the core architectural guarantee: a one-row validation check and a 10-million-row forecast run share the same observability, error handling, and export machinery.

```
Request
   │
   ▼
┌──────────────────────────────────────────────────────────────────┐
│  1. Authenticate          Verify token, tenant_id, permissions   │
├──────────────────────────────────────────────────────────────────┤
│  2. Validate Input        Reject malformed Pydantic model        │
├──────────────────────────────────────────────────────────────────┤
│  3. Acquire Dataset       Importer.read() → Dataset              │
├──────────────────────────────────────────────────────────────────┤
│  4. Validate Dataset      Pandera schema enforcement             │
├──────────────────────────────────────────────────────────────────┤
│  5. Normalize             Currency, dates, booleans, vendor IDs  │
├──────────────────────────────────────────────────────────────────┤
│  6. Execute Task          Dispatcher routes to handler           │
├──────────────────────────────────────────────────────────────────┤
│  7. Verify Output         Pydantic model construction on result  │
├──────────────────────────────────────────────────────────────────┤
│  8. Export Result         Serialize → cache → return             │
├──────────────────────────────────────────────────────────────────┤
│  9. Cleanup               Temp files, connections, memory        │
├──────────────────────────────────────────────────────────────────┤
│ 10. Telemetry             Logs, metrics, traces, artifacts       │
└──────────────────────────────────────────────────────────────────┘
```

### State machine

Every job transitions through a tracked state machine. The backend can poll or subscribe to state changes via WebSocket.

```
      ┌──────────┐
      │  QUEUED  │
      └────┬─────┘
           │
      ┌────▼──────┐
      │  RUNNING  │
      └────┬──────┘
           │
      ┌────▼─────────┐
      │  VALIDATING  │
      └────┬─────────┘
           │
      ┌────▼─────────┐
      │  EXECUTING   │
      └────┬─────────┘
           │
      ┌────▼─────────┐
      │  EXPORTING   │
      └────┬─────────┘
           │
      ┌────▼──────┐     ┌──────────┐     ┌──────────┐
      │  SUCCESS  │     │  FAILED  │────▶│ RETRYING │
      └───────────┘     └────┬─────┘     └────┬─────┘
                            │                 │
                            │           ┌─────▼──────┐
                            └──────────▶│ FAILED      │
                                        │ (exhausted) │
                                        └─────────────┘
```

**States:**

| State | Meaning | Transitions to |
|-------|---------|---------------|
| `QUEUED` | Job accepted, waiting for worker capacity | `RUNNING` |
| `RUNNING` | Worker acquired, pipeline started | `VALIDATING`, `FAILED` |
| `VALIDATING` | Dataset validation in progress | `EXECUTING`, `FAILED` |
| `EXECUTING` | Task handler running | `EXPORTING`, `FAILED` |
| `EXPORTING` | Serializing and persisting result | `SUCCESS`, `FAILED` |
| `SUCCESS` | Completed successfully, result available | — |
| `FAILED` | Terminal failure (unrecoverable or retries exhausted) | `RETRYING` (if retryable) |
| `RETRYING` | Exponential backoff before retry | `RUNNING`, `FAILED` (exhausted) |
| `CANCELLED` | User-initiated cancellation | — |

---

## 1. Validate Request

The first computational step in the pipeline. No dataset is acquired, no import is attempted, no compute is consumed — until the request itself is structurally valid.

Every incoming request is deserialized into a `RuntimeRequest` Pydantic model. The FastAPI endpoint (or gRPC handler) does not pass raw dictionaries into the dispatcher; it passes a validated model.

```python
# python-runtime/api/models.py (proposed)

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from datetime import datetime

from pydantic import BaseModel, Field


class JobType(str, Enum):
    ANALYTICS = "analytics"               # DuckDB SQL query
    FORECAST = "forecast"                 # ML time-series predictor
    RISK = "risk"                         # ML risk scorer
    DUPLICATE_DETECTION = "duplicate"     # Similarity-based dedup
    AGGREGATION = "aggregation"           # Polars groupby/aggregate
    VALIDATION = "validation"             # Pandera schema check only
    CUSTOM_PYTHON = "custom_python"       # Sandboxed arbitrary Python
    EXPORT = "export"                     # Format conversion (no compute)


class SourceType(str, Enum):
    GOOGLE_SHEETS = "google_sheets"
    CSV = "csv"
    EXCEL = "excel"
    JSON = "json"
    POSTGRES = "postgres"


class RuntimeRequest(BaseModel):
    """Every compute job request. Validated immediately on arrival."""

    job_id: str
    job_type: JobType
    tenant_id: str
    requested_by: str

    # Data source
    source_type: SourceType
    source_config: dict  # provider-specific: sheet_id, file_path, query, etc.

    # Parameters for the handler
    params: dict = Field(default_factory=dict)

    # Export preferences
    export_format: str = "json"  # json | csv | parquet | excel
    export_options: dict = Field(default_factory=dict)

    # Execution constraints
    timeout_seconds: int = 120
    max_rows: int | None = None

    # Cache control
    bypass_cache: bool = False
```

**Validation rules enforced at construction:**

| Rule | Enforcement | Error code |
|------|-------------|------------|
| `job_id` is non-empty | Pydantic `min_length=1` | `VALIDATION_MISSING_FIELD` |
| `job_type` is a known enum member | Pydantic enum validation | `VALIDATION_INVALID_JOB_TYPE` |
| `tenant_id` is non-empty | Pydantic `min_length=1` | `VALIDATION_MISSING_TENANT` |
| `source_type` is a known enum member | Pydantic enum validation | `VALIDATION_INVALID_SOURCE` |
| `source_config` has required keys for `source_type` | Custom model validator | `VALIDATION_INVALID_CONFIG` |
| `timeout_seconds` is in allowed range (1–600) | Pydantic `Field(ge=1, le=600)` | `VALIDATION_TIMEOUT_RANGE` |
| `export_format` is a supported format | Pydantic validator | `VALIDATION_UNSUPPORTED_FORMAT` |

**What does NOT pass validation:**

```python
# Rejected — invalid job type
request = RuntimeRequest(
    job_id="",                          # VALIDATION_MISSING_FIELD
    job_type="deep_learning",           # VALIDATION_INVALID_JOB_TYPE — not in enum
    tenant_id="tnt_001",
    requested_by="user@co.com",
    source_type="google_sheets",
    source_config={"sheet_id": "abc123"},
    export_format="pdf",                # VALIDATION_UNSUPPORTED_FORMAT
)
```

**Pattern reference:** This mirrors the `ToolResult` pattern in `shared/utils/tools/tool_result.py` — a frozen, validated model that describes scope and provenance of a unit of work. The `RuntimeRequest` is the input-side equivalent.

---

## 2. Import (Importer Abstraction)

Once the request is validated, the runtime acquires a dataset. Every data source conforms to the `Importer` Protocol — the same duck-typed contract pattern used by `SpreadsheetProvider` in `finance/integration/protocol.py`.

### Protocol definition

```python
# python-runtime/importers/protocol.py (proposed)

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel


class Dataset(BaseModel):
    """Typed abstraction returned by every Importer.

    This is the universal data container that downstream stages
    (validation, normalization, execution) consume. No stage
    ever accesses raw CSV rows, Google Sheets API responses, or
    database result sets directly.
    """

    rows: list[dict[str, Any]]
    column_names: list[str]
    row_count: int
    source_type: str          # "csv", "google_sheets", "postgres", etc.
    source_fingerprint: str   # deterministic hash of provenance metadata
    imported_at: str          # ISO8601 timestamp
    metadata: dict[str, Any]  # source-specific: sheet_name, query, file_hash
    errors: list[str]         # non-fatal warnings during import (parse warnings, etc.)


@runtime_checkable
class Importer(Protocol):
    """Protocol that every data importer must satisfy.

    This is the same pattern as ``SpreadsheetProvider`` in
    ``finance/integration/protocol.py`` — a structural contract
    that enables the runtime to acquire data from any source
    without knowing the source type.
    """

    source_type: str

    def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Validate source-specific configuration.

        Returns the validated config dict, or raises ImportError
        with structured error details.
        """
        ...

    def read(self, config: dict[str, Any]) -> Dataset:
        """Read data from the source and return a typed Dataset.

        Args:
            config: Source configuration (sheet_id, file_path, query, etc.)
                that has passed through validate_config().
        Returns:
            Dataset with rows, column_names, and source provenance.
        Raises:
            ImportError: Source unreachable, credentials invalid, format corrupt.
        """
        ...
```

### Concrete implementations

| Importer | Source | File (proposed) |
|----------|--------|-----------------|
| `GoogleSheetsImporter` | Google Sheets API v4 | `python-runtime/importers/google_sheets.py` |
| `CSVImporter` | Local CSV files | `python-runtime/importers/csv_importer.py` |
| `ExcelImporter` | .xlsx workbooks | `python-runtime/importers/excel_importer.py` |
| `JSONImporter` | JSON documents | `python-runtime/importers/json_importer.py` |
| `PostgresImporter` | SQL queries | `python-runtime/importers/postgres_importer.py` |

### Usage pattern

```python
# python-runtime/importers/factory.py (proposed)

from python_runtime.importers.protocol import Importer


class ImporterFactory:
    """Factory for creating Importers by source type string.

    Mirrors the ``ProviderFactory`` pattern in
    ``finance/integration/factory.py``.
    """

    _IMPORTERS: dict[str, type[Importer]] = {}

    @classmethod
    def register(cls, source_type: str, importer_cls: type[Importer]) -> None:
        cls._IMPORTERS[source_type] = importer_cls

    @classmethod
    def create(cls, source_type: str) -> Importer:
        if source_type not in cls._IMPORTERS:
            raise KeyError(f"No importer registered for source type: {source_type}")
        return cls._IMPORTERS[source_type]()

    @classmethod
    def list_sources(cls) -> list[str]:
        return list(cls._IMPORTERS.keys())
```

```python
# Application code — the runtime never branches on source_type

importer = ImporterFactory.create(request.source_type.value)
validated_config = importer.validate_config(request.source_config)
dataset: Dataset = importer.read(validated_config)
# dataset.rows, dataset.column_names, dataset.row_count are now available
# downstream stages never access the original source
```

### Design rules

1. **Every importer returns a `Dataset`.** No importer returns raw file handles, database cursors, or streaming objects to the pipeline. The `Dataset` is the universal currency.
2. **`source_fingerprint` is deterministic.** It is computed from source identity + version + timestamp in a way that enables caching downstream. Same fingerprint → same data.
3. **Non-fatal errors are in `errors: list[str]`.** Parse warnings, column truncation, encoding fallbacks — these are surfaced but do not block import. Fatal errors (file not found, auth failure) raise `ImportError`.
4. **Importers are stateless.** Configuration is passed in; state is returned out. No importer holds connections or file handles between calls.

---

## 3. Dataset Validation (Pandera)

After import, every dataset passes through Pandera schema validation before any computation engine touches it. This is not optional — the pipeline blocks execution if the dataset fails schema constraints.

### Schema registry

Each job type registers the Pandera schema it expects:

```python
# python-runtime/validators/schemas.py (proposed)

import pandera as pa
from pandera.typing import Series


class BudgetLineSchema(pa.DataFrameModel):
    """Expected schema for budget analytics jobs."""

    account_id: Series[str] = pa.Field(nullable=False)
    account_name: Series[str] = pa.Field(nullable=False)
    department: Series[str] = pa.Field(nullable=False)
    fiscal_period: Series[str] = pa.Field(nullable=False)
    budget_amount: Series[float] = pa.Field(nullable=False, ge=0.0)
    currency: Series[str] = pa.Field(nullable=False, isin=["USD", "EUR", "GBP", "INR", "JPY"])
    cost_center: Series[str] = pa.Field(nullable=True)


class VendorRiskSchema(pa.DataFrameModel):
    """Expected schema for vendor risk scoring jobs."""

    vendor_id: Series[str] = pa.Field(nullable=False, unique=True)
    vendor_name: Series[str] = pa.Field(nullable=False)
    category: Series[str] = pa.Field(nullable=False)
    tenure_years: Series[float] = pa.Field(nullable=True, ge=0.0)
    total_paid: Series[float] = pa.Field(nullable=False, ge=0.0)
    payment_history_months: Series[int] = pa.Field(nullable=True, ge=1)
```

### Validation execution

```python
# python-runtime/validators/pipeline.py (proposed)

from pandera.typing import DataFrame

from python_runtime.validators.schemas import BudgetLineSchema
from python_runtime.shared.errors import ValidationError, ValidationErrorInfo


def validate_dataset(
    dataset: Dataset,
    schema: type[pa.DataFrameModel],
) -> list[ValidationErrorInfo]:
    """Validate dataset columns against a Pandera schema.

    Args:
        dataset: Imported Dataset with rows and column_names.
        schema: Pandera DataFrameModel subclass.

    Returns:
        Empty list if valid. List of ValidationErrorInfo if violations found.
        Never raises — validation errors are structured, not exceptional.
    """
    try:
        # Convert Dataset rows to Pandera DataFrame
        df = DataFrame[BudgetLineSchema](dataset.rows)
        # If we reach here, validation passed
        return []
    except pa.errors.SchemaError as exc:
        errors = []
        for failure in exc.args[0] if isinstance(exc.args, tuple) else exc.failures:
            errors.append(
                ValidationErrorInfo(
                    code="DATASET_SCHEMA_VIOLATION",
                    message=failure.message,
                    column=failure.column or "unknown",
                    check=failure.check or "unknown",
                    value=str(failure.value) if failure.value is not None else None,
                )
            )
        return errors
```

### Structured validation errors — never Python exceptions

Validation failures are **data**, not exceptions:

```python
# python-runtime/shared/errors.py (proposed)

from pydantic import BaseModel


class ValidationErrorInfo(BaseModel):
    """A single schema violation.

    This is a structured object, not an exception. The pipeline
    collects these into a list and returns them as part of the
    job result.
    """

    code: str           # DATASET_SCHEMA_VIOLATION, DATASET_MISSING_COLUMN,
                        # DATASET_NULL_VIOLATION, DATASET_TYPE_MISMATCH
    message: str        # Human-readable description
    column: str         # Column name where violation occurred
    row: int | None     # Row index (optional for column-level violations)
    value: str | None   # Offending value (serialized as string)
    constraint: str     # The constraint that was violated: "nullable=False",
                        # "isin=['USD', 'EUR']", "ge=0.0"
```

### What validation catches

| Check | Example violation | Error code |
|-------|-------------------|------------|
| Required column | `region` column missing | `DATASET_MISSING_COLUMN` |
| Data type | `budget_amount` is string, not float | `DATASET_TYPE_MISMATCH` |
| Null constraint | `vendor_id` has null values | `DATASET_NULL_VIOLATION` |
| Enum range | `currency` contains "BTC" | `DATASET_ENUM_VIOLATION` |
| Uniqueness | `vendor_id` has duplicates | `DATASET_UNIQUE_VIOLATION` |
| Numeric bounds | `tenure_years` is -5 | `DATASET_BOUND_VIOLATION` |

---

## 4. Normalization

Real-world financial data arrives in inconsistent formats — currency strings with ₹ symbols, dates in "2026/01/05" and "05-Jan-2026" and "20260105" all in the same column, vendor names spelled differently across source systems.

The normalization stage transforms the `Dataset` rows in-place before execution:

```python
# python-runtime/transforms/normalizer.py (proposed)

from typing import Any
from datetime import datetime
from decimal import Decimal
import re


class Normalizer:
    """Applies a sequence of normalization rules to a Dataset.

    Rules are composable and idempotent — applying them twice
    produces the same result as applying them once.
    """

    def __init__(self, rules: list[NormalizationRule]):
        self._rules = rules

    def apply(self, dataset: Dataset) -> Dataset:
        for rule in self._rules:
            for row in dataset.rows:
                rule.apply(row)
        return dataset


class NormalizationRule:
    """A single normalization transformation."""

    column: str

    def apply(self, row: dict[str, Any]) -> None:
        raise NotImplementedError


class CurrencyNormalizer(NormalizationRule):
    """Strip currency symbols and parse to Decimal.

    Handles: ₹10,000 → 10000, $1,234.56 → 1234.56, EUR 500 → 500
    """

    column: str = "amount"

    _CURRENCY_PATTERN = re.compile(r"^[\$€£¥₹]\s*|[\s\$€£¥₹]$|,\s*")

    def apply(self, row: dict[str, Any]) -> None:
        raw = row.get(self.column)
        if isinstance(raw, str):
            cleaned = self._CURRENCY_PATTERN.sub("", raw).strip()
            try:
                row[self.column] = Decimal(cleaned)
            except Exception:
                pass  # leave as-is; validation will catch it


class DateNormalizer(NormalizationRule):
    """Parse multiple date formats to ISO8601.

    Handles: "2026/01/05", "05-Jan-2026", "20260105", "01/05/2026"
    """

    column: str = "date"

    _FORMATS = [
        "%Y/%m/%d",
        "%d-%b-%Y",
        "%Y%m%d",
        "%m/%d/%Y",
        "%Y-%m-%d",
    ]

    def apply(self, row: dict[str, Any]) -> None:
        raw = row.get(self.column)
        if isinstance(raw, str):
            for fmt in self._FORMATS:
                try:
                    row[self.column] = datetime.strptime(raw, fmt).isoformat()
                    return
                except ValueError:
                    continue


class BooleanCoercer(NormalizationRule):
    """Coerce boolean-like strings to Python bool.

    TRUE / true / Yes / 1 → True
    FALSE / false / No / 0 → False
    """

    column: str = "is_active"

    _TRUE_VALUES = {"TRUE", "true", "Yes", "YES", "1", "y", "Y"}
    _FALSE_VALUES = {"FALSE", "false", "No", "NO", "0", "n", "N"}

    def apply(self, row: dict[str, Any]) -> None:
        raw = row.get(self.column)
        if isinstance(raw, str):
            if raw in self._TRUE_VALUES:
                row[self.column] = True
            elif raw in self._FALSE_VALUES:
                row[self.column] = False


class VendorIDCanonicalizer(NormalizationRule):
    """Map vendor name variants to canonical IDs using a lookup table."""

    column: str = "vendor_name"

    def __init__(self, lookup: dict[str, str]):
        self._lookup = lookup
        super().__init__()

    def apply(self, row: dict[str, Any]) -> None:
        raw = row.get(self.column)
        if isinstance(raw, str) and raw in self._lookup:
            row["vendor_id"] = self._lookup[raw]
```

**Design note:** Normalization runs **before** execution but **after** validation. This ordering is intentional — validation checks the raw imported data so schema drift at the source is detected and reported, while normalization handles the messy reality of multi-source formatting.

---

## 5. Execution (Dispatcher)

The dispatcher is the switchboard. It receives a validated, normalized `Dataset` and routes the job to the appropriate handler based on `job_type`.

```python
# python-runtime/dispatcher/router.py (proposed)

from __future__ import annotations

from typing import Any

from python_runtime.api.models import RuntimeRequest
from python_runtime.importers.protocol import Dataset
from python_runtime.shared.errors import RuntimeErrorInfo


class HandlerResult(BaseModel):
    """Typed result from any job handler.

    Structured output — never a raw dictionary.
    """

    data: list[dict[str, Any]] | dict[str, Any]
    row_count: int
    metrics: dict[str, Any] = Field(default_factory=dict)
    # handler-specific: execution_time_ms, prediction_scores, etc.
    warnings: list[str] = Field(default_factory=list)


class JobHandler(Protocol):
    """Protocol for job type handlers."""

    async def execute(
        self,
        request: RuntimeRequest,
        dataset: Dataset,
    ) -> HandlerResult:
        ...


class Dispatcher:
    """Routes job types to registered handlers."""

    def __init__(self):
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        self._handlers[job_type] = handler

    async def dispatch(
        self,
        request: RuntimeRequest,
        dataset: Dataset,
    ) -> HandlerResult:
        handler = self._handlers.get(request.job_type.value)
        if handler is None:
            raise KeyError(f"No handler registered for job type: {request.job_type}")
        return await handler.execute(request, dataset)
```

### Handler matrix

| Job type | Handler | Engine | Location (proposed) |
|----------|---------|--------|---------------------|
| `analytics` | `AnalyticsHandler` | DuckDB SQL, Polars lazy expressions | `python-runtime/analytics/handler.py` |
| `forecast` | `ForecastHandler` | ML Predictor (via `RiskProvider` protocol) | `python-runtime/predictors/forecast.py` |
| `risk` | `RiskHandler` | ML Predictor (via `RiskProvider` protocol) | `python-runtime/predictors/risk.py` |
| `duplicate` | `DuplicateHandler` | Similarity scoring + Isolation Forest | `python-runtime/predictors/duplicate.py` |
| `aggregation` | `AggregationHandler` | Polars groupby/aggregate | `python-runtime/analytics/aggregation.py` |
| `validation` | `ValidationOnlyHandler` | Pandera (no further compute) | `python-runtime/validators/pipeline.py` |
| `custom_python` | `SandboxHandler` | Safe sandboxed execution | `python-runtime/sandbox/handler.py` |
| `export` | `ExportHandler` | Format conversion only | `python-runtime/exporters/handler.py` |

### Handler sketch — Analytics

```python
# python-runtime/analytics/handler.py (proposed)

import duckdb

from python_runtime.dispatcher.router import JobHandler, HandlerResult


class AnalyticsHandler(JobHandler):
    """Executes DuckDB SQL analytics queries against a Dataset."""

    async def execute(
        self,
        request: RuntimeRequest,
        dataset: Dataset,
    ) -> HandlerResult:
        # Register the dataset as a DuckDB view
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE OR REPLACE VIEW input_data AS SELECT * FROM dataset.rows"
        )

        # Execute the analytics query from request params
        sql = request.params.get("query")
        result = con.execute(sql).fetchall()
        columns = [desc[0] for desc in con.description]

        # Structured output — list of dicts with column names
        data = [dict(zip(columns, row)) for row in result]
        con.close()

        return HandlerResult(
            data=data,
            row_count=len(result),
            metrics={"execution_time_ms": ...},
        )
```

### Handler sketch — ML Predictor

```python
# python-runtime/predictors/risk.py (proposed)

from python_runtime.dispatcher.router import JobHandler, HandlerResult


class RiskHandler(JobHandler):
    """Scores risk using a registered ML RiskProvider."""

    def __init__(self, model_name: str):
        # Loaded from InferenceRegistry (same pattern as finance/ml/registry.py)
        self._provider = InferenceRegistry().get(model_name)

    async def execute(
        self,
        request: RuntimeRequest,
        dataset: Dataset,
    ) -> HandlerResult:
        results = []
        for row in dataset.rows:
            evaluation = self._provider.evaluate(row)
            results.append({
                "entity_id": row.get("vendor_id") or row.get("invoice_id"),
                "score": evaluation.score,
                "confidence": evaluation.confidence,
                "tier": "high" if evaluation.score > 0.7 else "low",
            })

        return HandlerResult(
            data=results,
            row_count=len(results),
            metrics={"inferences": len(results)},
        )
```

**Key point:** ML inference is one handler among many. The `RiskHandler` does not know or care whether the `RiskProvider` is a rule set, an XGBoost model, or a LightGBM classifier — it calls the same protocol. The runtime treats it as a generic compute unit.

---

## 6. Async Execution

The Python Runtime never blocks the API. Every compute job runs asynchronously:

1. **Backend sends** `POST /api/runtime/jobs` with a `RuntimeRequest`
2. **Runtime responds immediately** with `{"job_id": "job_abc123", "status": "QUEUED"}`
3. **Job executes** in a background worker (asyncio task, Celery-style worker, or Temporal activity)
4. **Backend polls** `GET /api/runtime/jobs/{job_id}` or subscribes via WebSocket
5. **Runtime emits state transitions** — the backend updates UI in real-time

### State machine transitions

```python
# python-runtime/api/state.py (proposed)

from enum import Enum
from datetime import datetime
from pydantic import BaseModel


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    VALIDATING = "validating"
    EXECUTING = "executing"
    EXPORTING = "exporting"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class JobState(BaseModel):
    """Describes the current state of a compute job."""

    job_id: str
    status: JobStatus
    progress_pct: float  # 0.0 to 100.0
    message: str         # Human-readable status description
    started_at: datetime | None
    completed_at: datetime | None
    next_retry_at: datetime | None  # Only set when status == RETRYING
    retry_count: int = 0
    max_retries: int = 3

    # Result populated at SUCCESS
    result: dict | None = None

    # Error populated at FAILED
    error: RuntimeErrorInfo | None = None
```

### Polling contract

```python
# GET /api/runtime/jobs/{job_id}
# Response:
{
  "job_id": "job_abc123",
  "status": "executing",
  "progress_pct": 67.2,
  "message": "Processing batch 5 of 8",
  "started_at": "2026-07-29T08:15:00Z",
  "completed_at": null,
  "result": null,
  "error": null
}
```

### WebSocket subscription

For real-time UI updates, the backend subscribes to a job channel:

```python
# WebSocket: ws://runtime/jobs/{job_id}/subscribe

# Stream of state transitions:
{"event": "state_change", "job_id": "job_abc123", "status": "validating", "timestamp": "..."}
{"event": "state_change", "job_id": "job_abc123", "status": "executing", "progress_pct": 33.3, "timestamp": "..."}
{"event": "state_change", "job_id": "job_abc123", "status": "success", "timestamp": "..."}
{"event": "result", "job_id": "job_abc123", "result": {"rows": 142, "columns": ["a", "b"]}, "timestamp": "..."}
```

---

## 7. Cancellation

A user may cancel a long-running job. The cancellation protocol ensures the runtime stops cleanly — no half-written exports, no orphaned temp files, no leaked connections.

### Protocol

1. **Backend sends** `POST /api/runtime/jobs/{job_id}/cancel`
2. **Runtime sets status to** `CANCELLED` immediately (prevents new progress)
3. **Runtime signals the running handler** with a cancellation event
4. **Handler cleans up:** temp files, database connections, partial exports
5. **Runtime finalizes** the job record with `completed_at` and `status=CANCELLED`

```python
# python-runtime/api/cancel.py (proposed)

import asyncio
from datetime import datetime


class CancellationToken:
    """Propagated to running handlers. Check periodically."""

    def __init__(self):
        self._cancelled = False
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._cancelled = True
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    async def wait_for_cancel(self) -> None:
        await self._event.wait()


async def cancel_job(job_id: str, state_store: dict[str, JobState]) -> None:
    token = cancellation_tokens.get(job_id)
    if token:
        token.cancel()
    state_store[job_id].status = JobStatus.CANCELLED
    state_store[job_id].completed_at = datetime.utcnow()
    state_store[job_id].message = "Cancelled by user"
```

### Handler contract for cancellation

Every handler must check the cancellation token at yield points:

```python
# Example: analytics handler with cancellation support

async def execute(self, request: RuntimeRequest, dataset: Dataset) -> HandlerResult:
    token: CancellationToken = request._cancellation_token  # injected by runtime

    for batch_nr, batch in enumerate(batches(dataset.rows, size=1000)):
        if token.is_cancelled:
            # Clean up partial work
            cleanup_temp_files()
            raise JobCancelledError("Job cancelled during batch execution")

        result = process_batch(batch)

    return HandlerResult(data=result, ...)
```

**Design rule:** No cancellation logic in handlers is the default. If a handler does not support cancellation, the runtime still sets status to `CANCELLED` and abandons the running task — but cleanup is the handler's responsibility. Handlers that own resources (temp files, DB connections) **must** implement cancellation support.

---

## 8. Timeouts

Every job type has a maximum execution time. If the handler exceeds its budget, the runtime kills the process, cleans up temporary resources, and marks the job as `FAILED` with a timeout error.

### Per-task timeouts

| Job type | Timeout | Rationale |
|----------|---------|-----------|
| `validation` | 30s | Schema checks on imported data — should complete in milliseconds |
| `analytics` | 2 min | DuckDB SQL queries on up to 10M rows |
| `forecast` | 3 min | ML inference on up to 500K entities |
| `risk` | 3 min | Same — batch scoring is compute-bound |
| `duplicate` | 5 min | Pairwise similarity is O(n²) at worst |
| `custom_python` | 60s | Sandboxed execution — prevent runaway code |
| `export` | 2 min | Format conversion (Parquet, Excel) on large datasets |

### Timeout enforcement

```python
# python-runtime/api/timeout.py (proposed)

import asyncio


async def execute_with_timeout(
    handler: JobHandler,
    request: RuntimeRequest,
    dataset: Dataset,
    timeout_seconds: int,
) -> HandlerResult:
    """Execute a handler with a hard timeout.

    If the handler exceeds timeout_seconds, it is cancelled and
    cleanup is triggered.
    """
    try:
        result = await asyncio.wait_for(
            handler.execute(request, dataset),
            timeout=timeout_seconds,
        )
        return result
    except asyncio.TimeoutError:
        # Kill process, clean up temp files, mark timeout
        cleanup_job_resources(request.job_id)
        raise JobTimeoutError(
            job_id=request.job_id,
            timeout_seconds=timeout_seconds,
            job_type=request.job_type,
        )
```

**What happens on timeout:**

1. `asyncio.TimeoutError` is caught
2. `cleanup_job_resources()` removes temp files, closes connections, releases memory
3. Job state is set to `FAILED` with:
   ```json
   {
     "code": "EXECUTION_TIMEOUT",
     "message": "Job exceeded maximum execution time of 120 seconds",
     "stage": "executing",
     "recoverable": false,
     "retryable": false,
     "details": {
       "job_type": "analytics",
       "timeout_seconds": 120,
       "elapsed_seconds": 121.3
     }
   }
   ```
4. The error propagates to the backend, which displays it to the user

---

## 9. Export Pipeline

Every job result goes through the export pipeline before it reaches the backend. The pipeline enforces that every result is a validated Pydantic model, not a raw dictionary — structural consistency is a non-negotiable guarantee.

### Pipeline

```
HandlerResult (Pydantic Model)
       │
       ▼
Validate Output — construct Pydantic model, raise ExportError on failure
       │
       ▼
Serialize — JSON, CSV, Parquet, Excel, Chart Data, SQL Result
       │
       ▼
Cache (if cacheable)
       │
       ▼
Return to Backend
```

### Serializer registry

```python
# python-runtime/exporters/registry.py (proposed)

from pydantic import BaseModel


class Serializer(Protocol):
    format: str

    def serialize(
        self,
        result: HandlerResult,
        options: dict[str, Any],
    ) -> ExportArtifact:
        ...


class ExportArtifact(BaseModel):
    """A serialized export artifact ready for delivery.

    The artifact is either an inline payload (for small results)
    or a reference to a stored file (for large results).
    """

    format: str
    payload: str | None    # Inline serialized content (JSON, CSV text)
    file_path: str | None  # Reference to stored artifact (Parquet, Excel)
    byte_count: int
    row_count: int
    column_names: list[str]
    content_type: str       # "application/json", "text/csv", etc.
```

| Format | Serializer | Content type | Typical use |
|--------|-----------|-------------|-------------|
| `json` | `JSONSerializer` | `application/json` | API response to Next.js |
| `csv` | `CSVSerializer` | `text/csv` | Analyst download |
| `parquet` | `ParquetSerializer` | `application/parquet` | Large dataset handoff |
| `excel` | `ExcelSerializer` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | Board-ready export |
| `chart_data` | `ChartDataSerializer` | `application/json` | Frontend chart rendering |
| `sql_result` | `SQLResultSerializer` | `application/json` | Database query result |

### Future formats

| Format | Status | When needed |
|--------|--------|-------------|
| PowerPoint (.pptx) | Planned | Board report export |
| PDF | Planned | Audit report generation |
| HTML | Backlog | Email-ready summary |
| Audit Report (JSON) | Planned | Structured compliance export |

### Export guarantees

1. **Every result passes through a Pydantic model.** No raw dictionaries cross the export boundary.
2. **Monetary values are `Decimal` until serialization.** The `DecimalEncoder` pattern from `shared/utils/encoders.py` serializes `Decimal` as strings in JSON output — no float precision loss.
3. **Large exports go to file.** If the payload exceeds 10 MB, the serializer writes to a temp file and returns a `file_path` reference instead of an inline payload.

---

## 10. Error Handling

The Python Runtime never returns raw Python tracebacks to the backend. Every error is a classified, structured object with a code, message, stage, and remediation hints.

### Error classification

```python
# python-runtime/shared/errors.py (proposed)

from pydantic import BaseModel
from enum import Enum


class ErrorCategory(str, Enum):
    VALIDATION = "validation"           # Input or schema violation
    IMPORT = "import"                   # Source unreachable, auth failure
    TRANSFORMATION = "transformation"   # Normalization or conversion failure
    ANALYTICS = "analytics"             # SQL error, aggregation failure
    PREDICTION = "prediction"           # ML inference failure
    EXPORT = "export"                   # Serialization failure
    INFRASTRUCTURE = "infrastructure"   # Network, disk, memory, timeout
    SANDBOX = "sandbox"                 # Sandboxed execution violation


class RuntimeErrorInfo(BaseModel):
    """Structured error from any stage of the runtime pipeline.

    Never a traceback. Always classified, with context for
    both operators and downstream automation.
    """

    code: str                        # e.g., "IMPORT_SOURCE_UNREACHABLE"
    message: str                     # Human-readable summary
    category: ErrorCategory
    stage: str                       # "import", "validate", "execute", "export"
    recoverable: bool                # Can the job proceed with degraded output?
    retryable: bool                  # Should the job be retried with backoff?
    details: dict[str, Any] = {}     # Stage-specific: column name, row index, HTTP status

    # Optional: suggestion for automated remediation
    remediation_hint: str | None = None
```

### Error catalog

| Code | Category | Stage | Recoverable? | Retryable? | Typical cause |
|------|----------|-------|-------------|------------|---------------|
| `VALIDATION_MISSING_FIELD` | `validation` | input | No | No | Request missing required field |
| `VALIDATION_INVALID_JOB_TYPE` | `validation` | input | No | No | Unknown job type enum |
| `VALIDATION_UNSUPPORTED_FORMAT` | `validation` | input | No | No | Export format not registered |
| `IMPORT_SOURCE_UNREACHABLE` | `import` | import | No | Yes | Google API timeout, network reset |
| `IMPORT_AUTH_FAILURE` | `import` | import | No | No | Expired OAuth token, bad credentials |
| `IMPORT_FORMAT_CORRUPT` | `import` | import | No | No | Malformed CSV, corrupt Excel |
| `IMPORT_EMPTY_RESULT` | `import` | import | Yes | No | Source returned zero rows |
| `DATASET_SCHEMA_VIOLATION` | `validation` | validate | No | No | Column missing, wrong data type |
| `DATASET_NULL_VIOLATION` | `validation` | validate | Yes | No | Null in non-nullable column |
| `TRANSFORMATION_FAILURE` | `transformation` | normalize | Yes | No | Unparseable date format |
| `ANALYTICS_SQL_ERROR` | `analytics` | execute | No | No | Invalid SQL query |
| `ANALYTICS_OUT_OF_MEMORY` | `analytics` | execute | No | No | Dataset exceeds memory budget |
| `PREDICTION_MODEL_NOT_FOUND` | `prediction` | execute | No | No | Requested model not in registry |
| `PREDICTION_FEATURE_MISMATCH` | `prediction` | execute | No | No | Feature schema changed |
| `EXPORT_SERIALIZATION_FAILED` | `export` | export | No | No | Unsupported data type in result |
| `EXPORT_FILE_TOO_LARGE` | `export` | export | Yes | No | Dataset exceeds export row limit |
| `INFRASTRUCTURE_DISK_FULL` | `infrastructure` | any | No | No | Temp write failed |
| `INFRASTRUCTURE_TIMEOUT` | `infrastructure` | execute | No | Some | Job exceeded per-task timeout |
| `SANDBOX_VIOLATION` | `sandbox` | execute | No | No | Code tried syscall, internet, shell |
| `SANDBOX_EXECUTION_ERROR` | `sandbox` | execute | No | No | Python code in sandbox raised |

### JSON error example

```json
{
  "code": "IMPORT_SOURCE_UNREACHABLE",
  "message": "Google Sheets API returned 503 after 3 retries",
  "category": "import",
  "stage": "import",
  "recoverable": false,
  "retryable": true,
  "details": {
    "source_type": "google_sheets",
    "sheet_id": "1a2b3c4d5e",
    "http_status": 503,
    "retry_count": 3,
    "elapsed_ms": 45200
  },
  "remediation_hint": "Check Google API quota and service status. The job will be retried automatically with exponential backoff."
}
```

### Error propagation

Errors propagate upward through the pipeline stages, each stage adding its own context:

```
ImportError
  → wrapped as RuntimeErrorInfo(category="import", stage="import", retryable=True)
  → returned in JobState.error
  → backend receives classified error
  → UI shows "Import failed: Google Sheets API unavailable. Retrying in 30s..."
```

### What never happens

```python
# NEVER — raw traceback returned to backend or user
{
  "error": "Traceback (most recent call last):\n  File \"...\", line 42, in execute\n    raise ValueError('something broke')\nValueError: something broke"
}
```

Instead, the raw traceback is written to the runtime's local log at `ERROR` level for operator debugging. The structured error goes to the backend.

---

## 11. Retry Policy

Not all errors should be retried. The retry policy distinguishes between transient infrastructure failures and permanent logical failures.

### Good retry candidates (transient)

| Situation | Why | Backoff |
|-----------|-----|---------|
| Google Sheets API returns 503 / timeout | Service temporarily overloaded | Exponential, 10s → 30s → 90s |
| Network reset during import | Transient connectivity issue | Exponential, 5s → 15s → 45s |
| Temporary PostgreSQL connection failure | Connection pool drained | Exponential, 5s → 15s → 45s |
| DuckDB out of memory (transient) | Concurrent workload spike | Exponential, 30s → 60s → 120s |
| Export file locked (Windows Excel) | User has file open | Linear, 10s intervals, max 3 |

### Bad retry candidates (permanent)

| Situation | Why not | Correct action |
|-----------|---------|---------------|
| Column `region` missing from dataset | Schema drift — will fail again | Report error, notify DataOps |
| `budget_amount` is string, not float | Upstream format changed | Report validation error, block pipeline |
| Wrong spreadsheet ID in request | User error | Return VALIDATION_MISSING_FIELD, don't retry |
| Unrecognized job type | Programming error | Return VALIDATION_INVALID_JOB_TYPE |
| OAuth token expired | Credential issue | Return IMPORT_AUTH_FAILURE, trigger credential rotation |
| Dataset schema mismatch | Source schema changed | Flag for human review, do not retry |

### Retry configuration

```python
# python-runtime/api/retry.py (proposed)

from dataclasses import dataclass
import asyncio
import random


@dataclass
class RetryPolicy:
    """Retry schedule for transient errors.

    Default: exponential backoff with jitter.
    """

    max_retries: int = 3
    base_delay_seconds: float = 5.0
    max_delay_seconds: float = 120.0
    backoff_factor: float = 2.0
    jitter: bool = True

    def next_delay(self, attempt: int) -> float:
        delay = min(
            self.base_delay_seconds * (self.backoff_factor ** attempt),
            self.max_delay_seconds,
        )
        if self.jitter:
            delay *= 1 + random.random() * 0.5  # 50% jitter
        return delay


RETRY_POLICIES: dict[ErrorCategory, RetryPolicy] = {
    ErrorCategory.IMPORT: RetryPolicy(max_retries=3, base_delay_seconds=10.0),
    ErrorCategory.INFRASTRUCTURE: RetryPolicy(max_retries=2, base_delay_seconds=5.0),
    # VALIDATION, TRANSFORMATION, ANALYTICS, PREDICTION, EXPORT: not retried
}
```

### Retry flow

```
Job fails with RuntimeErrorInfo(retryable=True)
     │
     ▼
Increment retry_count
     │
     ▼
retry_count >= max_retries?  ──Yes──→  Mark FAILED (exhausted)
     │
     No
     │
     ▼
Compute next_delay(attempt=retry_count)
     │
     ▼
Set status = RETRYING
Set next_retry_at = now + delay
     │
     ▼
Wait delay seconds
     │
     ▼
Set status = RUNNING (re-enter pipeline at stage where it failed)
```

---

## 12. Safe Python Execution

LLMs generate Python code dynamically. The runtime must execute that code safely — no access to the host filesystem, no network, no shell, no dangerous imports, and strict limits on CPU, memory, and execution time.

This capability powers the finance agents when they need to compute something that is not covered by a registered handler — custom transformations, one-off calculations, user-defined formulae.

### Architecture

```
LLM generates Python code
     │
     ▼
AST parse → reject dangerous constructs (compile-time)
     │
     ▼
Sandboxed execution environment (runtime isolation)
     │
     ▼
CPU / memory / filesystem limits enforced
     │
     ▼
Execution timeout (60s hard limit)
     │
     ▼
Validate output → Pydantic model
     │
     ▼
Return HandlerResult
```

### Compile-time restrictions (AST analysis)

Before execution, the code is parsed and checked for dangerous constructs:

```python
# python-runtime/sandbox/ast_checker.py (proposed)

import ast
from typing import Any


class SandboxViolation(Exception):
    """Raised when code contains disallowed constructs."""

    def __init__(self, reason: str, node: ast.AST):
        self.reason = reason
        self.lineno = getattr(node, "lineno", "unknown")
        super().__init__(f"Sandbox violation at line {self.lineno}: {reason}")


# Disallowed module imports (infinite blocklist — expanded as needed)
_FORBIDDEN_MODULES = {
    "os", "subprocess", "sys", "shutil", "socket", "multiprocessing",
    "threading", "ctypes", "signal", "importlib", "builtins.__import__",
    "pickle", "marshal", "shelve", "webbrowser", "antigravity",
}

_FORBIDDEN_FUNCTIONS = {
    "eval", "exec", "compile", "open", "__import__", "input",
    "breakpoint", "exit", "quit",
}


def check_ast_safety(code: str) -> None:
    """Parse code and reject dangerous constructs.

    Raises SandboxViolation on first violation.
    """
    tree = ast.parse(code)

    for node in ast.walk(tree):
        # Block imports of dangerous modules
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                module_name = alias.name.split(".")[0]
                if module_name in _FORBIDDEN_MODULES:
                    raise SandboxViolation(f"Import of forbidden module: {module_name}", node)

        # Block dangerous function calls
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _FORBIDDEN_FUNCTIONS:
                raise SandboxViolation(f"Call to forbidden function: {func.id}", node)

        # Block attribute access on dangerous builtins
        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "os":
                raise SandboxViolation("Access to os.* is forbidden", node)
            if isinstance(node.value, ast.Name) and node.value.id == "subprocess":
                raise SandboxViolation("Access to subprocess.* is forbidden", node)
```

### Runtime isolation (Modal Sandbox or local Docker)

Two deployment options for the sandbox:

| Option | When to use | Implementation |
|--------|-------------|----------------|
| **Modal Sandbox** | Production / serverless | `modal.Sandbox.create()` — auto-enforced isolation |
| **Local Docker** | Development / single-tenant | Docker container per execution with resource limits |

```python
# python-runtime/sandbox/runner.py (proposed)

import resource
import threading
from typing import Any


class SandboxConfig(BaseModel):
    """Resource limits for sandboxed execution."""

    max_cpu_seconds: int = 30
    max_memory_mb: int = 512
    max_file_size_mb: int = 10
    execution_timeout_seconds: int = 60
    allowed_modules: list[str] = ["math", "json", "decimal", "datetime",
                                   "statistics", "re", "itertools", "collections",
                                   "typing", "functools"]
    temp_directory: str = "/tmp/sandbox"
    disable_network: bool = True


def execute_sandboxed(
    code: str,
    input_data: dict[str, Any],
    config: SandboxConfig,
) -> dict[str, Any]:
    """Execute user-provided Python code in a restricted environment.

    Steps:
    1. AST parse check (compile-time)
    2. Resource limit enforcement (runtime)
    3. Execution timeout (hard limit)
    4. Output validation
    """
    # Step 1: AST safety check
    check_ast_safety(code)

    # Step 2: Prepare restricted globals
    restricted_globals = {
        "__builtins__": {
            "abs": abs, "all": all, "any": any, "bool": bool,
            "dict": dict, "enumerate": enumerate, "filter": filter,
            "float": float, "int": int, "isinstance": isinstance,
            "len": len, "list": list, "map": map, "max": max,
            "min": min, "print": lambda *_: None,  # stdout suppressed
            "range": range, "round": round, "sorted": sorted,
            "str": str, "sum": sum, "tuple": tuple, "type": type,
            "zip": zip, "True": True, "False": False, "None": None,
            "ValueError": ValueError, "TypeError": TypeError,
            "KeyError": KeyError, "IndexError": IndexError,
            "Exception": Exception,
        },
        "input_data": input_data,
    }

    # Step 3: Set resource limits
    resource.setrlimit(resource.RLIMIT_CPU, (config.max_cpu_seconds, config.max_cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (config.max_memory_mb * 1024 * 1024, -1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (config.max_file_size_mb * 1024 * 1024, -1))

    # Step 4: Execute with timeout
    result = {}
    exception = None

    def run():
        nonlocal result, exception
        try:
            exec(code, restricted_globals, result)
        except Exception as e:
            exception = e

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=config.execution_timeout_seconds)

    if thread.is_alive():
        raise SandboxTimeoutError("Execution exceeded timeout")

    if exception:
        raise SandboxExecutionError(str(exception)) from exception

    # Step 5: Validate output — must be JSON-serializable
    output = result.get("output", {})
    # Pydantic validation on output happens in the caller
    return output
```

### What the sandbox blocks

| Access type | Blocked at | Error code |
|-------------|-----------|------------|
| Import `os`, `subprocess`, `sys` | AST parse | `SANDBOX_FORBIDDEN_IMPORT` |
| Call `eval()`, `exec()`, `compile()` | AST parse | `SANDBOX_FORBIDDEN_CALL` |
| `open()` files outside `/tmp/sandbox` | Runtime | `SANDBOX_FILE_ACCESS` |
| Network sockets | Runtime | `SANDBOX_NETWORK_BLOCKED` |
| CPU > 30 seconds | Resource limit | `SANDBOX_CPU_EXCEEDED` |
| Memory > 512 MB | Resource limit | `SANDBOX_MEMORY_EXCEEDED` |
| Write > 10 MB | Resource limit | `SANDBOX_DISK_EXCEEDED` |
| Execution > 60 seconds | Timeout | `SANDBOX_TIMEOUT` |

---

## 13. Observability

Every job in the runtime emits a standard set of observability signals. No job is invisible. The observability model follows the same patterns established in DevSecOps — structured logging, OpenTelemetry traces, and typed metrics.

### Logs

Every stage transition produces a structured log entry:

```json
{
  "timestamp": "2026-07-29T08:15:01.234Z",
  "level": "INFO",
  "event": "job.stage.transition",
  "job_id": "job_abc123",
  "tenant_id": "tnt_001",
  "job_type": "analytics",
  "from_status": "validating",
  "to_status": "executing",
  "elapsed_ms": 3420,
  "source_fingerprint": "a1b2c3d4e5..."
}
```

| Level | When | Example |
|-------|------|---------|
| `ERROR` | Pipeline failure, unrecoverable error | `IMPORT_SOURCE_UNREACHABLE` |
| `WARNING` | Non-fatal issue, retry, degraded mode | `Retry attempt 2/3 for job_abc123` |
| `INFO` | State transition, stage completion | `Job job_abc123 completed: SUCCESS` |
| `DEBUG` | Per-row details, internal timing | `Processing batch 7/12` |

### Metrics

Every job emits counters, histograms, and gauges:

```python
# python-runtime/telemetry/metrics.py (proposed)

from prometheus_client import Counter, Histogram, Gauge

# Counters
jobs_started = Counter("runtime_jobs_started_total", "Jobs started", ["job_type"])
jobs_completed = Counter("runtime_jobs_completed_total", "Jobs completed", ["job_type", "status"])
jobs_retried = Counter("runtime_jobs_retried_total", "Jobs retried", ["job_type"])
validation_failures = Counter("runtime_validation_failures_total", "Validation failures", ["error_code"])

# Histograms
execution_duration = Histogram(
    "runtime_execution_duration_seconds",
    "Job execution duration",
    ["job_type"],
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 120, 300],
)
import_duration = Histogram("runtime_import_duration_seconds", "Import duration", ["source_type"])
rows_processed = Histogram("runtime_rows_processed", "Rows processed per job", ["job_type"])
prediction_latency = Histogram(
    "runtime_prediction_latency_ms",
    "ML inference latency per prediction",
    ["model_name"],
)

# Gauges
active_jobs = Gauge("runtime_active_jobs", "Currently active jobs", ["job_type"])
memory_usage_mb = Gauge("runtime_memory_usage_mb", "Runtime process memory")
cache_hits = Counter("runtime_cache_hits_total", "Cache hits", ["job_type"])
cache_misses = Counter("runtime_cache_misses_total", "Cache misses", ["job_type"])
```

| Metric | Type | When recorded |
|--------|------|---------------|
| `runtime_jobs_started_total` | Counter | Job transitions from QUEUED → RUNNING |
| `runtime_jobs_completed_total` | Counter | Job reaches SUCCESS or terminal FAILED |
| `runtime_execution_duration_seconds` | Histogram | Job completes (by job_type) |
| `runtime_import_duration_seconds` | Histogram | Importer.read() returns |
| `runtime_validation_failures_total` | Counter | Pandera validation returns violations |
| `runtime_rows_processed` | Histogram | After export, total row count |
| `runtime_prediction_latency_ms` | Histogram | Per ML inference call |
| `runtime_active_jobs` | Gauge | Updated on every state transition |
| `runtime_memory_usage_mb` | Gauge | Sampled every 30s |
| `runtime_cache_hits_total` | Counter | On cache hit |
| `runtime_cache_misses_total` | Counter | On cache miss that results in execution |

### Traces

Every job produces an OpenTelemetry trace that follows the request lifecycle:

```
Trace: job_abc123
  ├── Span: authenticate          (2ms)
  ├── Span: validate_input        (1ms)
  ├── Span: import                (4,200ms)
  │   ├── Span: google_sheets.read_range  (4,150ms)
  │   └── Span: build_dataset      (50ms)
  ├── Span: validate_dataset      (310ms)
  ├── Span: normalize             (85ms)
  ├── Span: execute               (12,400ms)
  │   ├── Span: duckdb_query       (12,300ms)
  │   └── Span: post_process       (100ms)
  ├── Span: export                (220ms)
  │   ├── Span: serialize_json     (180ms)
  │   └── Span: cache_store        (40ms)
  └── Span: telemetry             (5ms)
```

Traces are exported via OTLP to Jaeger (development) or a production trace backend.

### Artifacts

Certain job types produce artifacts that are stored alongside the job result:

| Artifact | Job type | Storage | Retention |
|----------|----------|---------|-----------|
| Imported CSV snapshot | All | Temp file, TTL 24h | 24 hours |
| Normalized dataset | All | Temp file, TTL 24h | 24 hours |
| Model prediction SHAP values | `risk`, `forecast` | JSON per entity | 7 days |
| Sandbox execution script | `custom_python` | `.reasoning_traces/` | 30 days |
| Export artifact | All | Configurable (S3, volume) | Per tenant policy |

---

## 14. Caching

Identical jobs produce identical results — this is the core guarantee of deterministic computation in FinSight (see NFR-02 in the PRD). Caching exploits this guarantee: if the same sheet version, job type, and parameters produce a previously computed result, return it immediately.

### Cache key computation

```python
# python-runtime/cache/key.py (proposed)

import hashlib
import json


def compute_cache_key(
    source_fingerprint: str,
    job_type: str,
    params: dict,
    tenant_id: str,
) -> str:
    """Deterministic cache key.

    Components:
    - source_fingerprint: hash of source identity + version (from Dataset)
    - job_type: analytics, forecast, risk, etc.
    - params: sorted, serialized job parameters
    - tenant_id: isolate cache between tenants

    Same key → same input → same output.
    """
    raw = json.dumps({
        "source_fingerprint": source_fingerprint,
        "job_type": job_type,
        "params": dict(sorted(params.items())),
        "tenant_id": tenant_id,
    }, sort_keys=True, default=str)

    return hashlib.sha256(raw.encode()).hexdigest()
```

### Cache hit/miss flow

```
RuntimeRequest
     │
     ▼
Compute cache_key
     │
     ▼
Is key in cache? ──Yes──→ Return cached HandlerResult (skips import → execute → export)
     │
     No
     │
     ▼
Run full pipeline (import → validate → normalize → execute → export)
     │
     ▼
Store result in cache with TTL
     │
     ▼
Return HandlerResult
```

### Cache TTL by job type

| Job type | TTL | Rationale |
|----------|-----|-----------|
| `analytics` | 1 hour | DuckDB results may change with new data |
| `forecast` | 24 hours | ML predictions valid until next training cycle |
| `risk` | 24 hours | Same — batch scoring is stable intra-cycle |
| `duplicate` | 1 hour | New invoices arrive continuously |
| `aggregation` | 1 hour | Depends on underlying data freshness |
| `validation` | 5 minutes | Schema checks should be near-real-time |
| `custom_python` | None | Non-deterministic (LLM-generated code varies) |
| `export` | None | Format conversion is trivial to recompute |

### Cache invalidation

Explicit invalidation happens when:

1. **Source data changes** → new `source_fingerprint` → automatic cache miss
2. **Tenant clears cache** → `DELETE /api/runtime/cache/{tenant_id}`
3. **Admin force-clear** → `DELETE /api/runtime/cache` (platform-wide, rarely used)
4. **TTL expires** → Redis eviction handles automatic expiry

### Cache backend

```python
# python-runtime/cache/backend.py (proposed)

import redis.asyncio as redis
from python_runtime.shared.config import get_settings


class CacheBackend:
    """Async Redis-based cache for runtime job results."""

    def __init__(self):
        self._client = redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
        )

    async def get(self, key: str) -> HandlerResult | None:
        cached = await self._client.get(f"runtime:cache:{key}")
        if cached:
            return HandlerResult.model_validate_json(cached)
        return None

    async def set(
        self,
        key: str,
        result: HandlerResult,
        ttl_seconds: int,
    ) -> None:
        await self._client.setex(
            f"runtime:cache:{key}",
            ttl_seconds,
            result.model_dump_json(),
        )

    async def invalidate_tenant(self, tenant_id: str) -> int:
        cursor = 0
        deleted = 0
        while True:
            cursor, keys = await self._client.scan(
                cursor, match=f"runtime:cache:*", count=100
            )
            for key in keys:
                # Cache keys are not tenant-tagged at the key level;
                # this scans and filters. Production would use
                # tenant-scoped namespaces.
                deleted += 1
                await self._client.delete(key)
            if cursor == 0:
                break
        return deleted
```

---

## Proposed Directory Structure

```
python-runtime/
├── __init__.py
│
├── api/                       # Request handlers (FastAPI)
│   ├── __init__.py
│   ├── app.py                 # FastAPI application, startup, shutdown
│   ├── models.py              # RuntimeRequest, JobState, JobStatus
│   ├── routes.py              # POST /jobs, GET /jobs/{id}, POST /cancel
│   ├── cancel.py              # CancellationToken, cancel_job()
│   ├── state.py               # JobState model, state transitions
│   └── timeout.py             # execute_with_timeout()
│
├── jobs/                      # Job definitions
│   ├── __init__.py
│   ├── manager.py             # JobManager — create, track, persist
│   └── worker.py              # Background worker that executes jobs
│
├── dispatcher/                # Job type routing
│   ├── __init__.py
│   ├── router.py              # Dispatcher, JobHandler protocol, HandlerResult
│   └── registry.py            # Handler registration by job type
│
├── importers/                 # Data acquisition
│   ├── __init__.py
│   ├── protocol.py            # Importer protocol, Dataset model
│   ├── factory.py             # ImporterFactory
│   ├── google_sheets.py       # Google Sheets Importer
│   ├── csv_importer.py        # CSV file Importer
│   ├── excel_importer.py      # Excel file Importer
│   ├── json_importer.py       # JSON document Importer
│   └── postgres_importer.py   # PostgreSQL query Importer
│
├── validators/                # Input validation
│   ├── __init__.py
│   ├── schemas.py             # Pandera DataFrameModel schemas
│   └── pipeline.py            # validate_dataset() — Pandera runner
│
├── transforms/                # Normalization and cleaning
│   ├── __init__.py
│   ├── normalizer.py          # Normalizer, NormalizationRule classes
│   ├── currency.py            # CurrencyNormalizer
│   ├── dates.py               # DateNormalizer
│   └── booleans.py            # BooleanCoercer
│
├── analytics/                 # Data computation
│   ├── __init__.py
│   ├── handler.py             # AnalyticsHandler (DuckDB SQL)
│   └── aggregation.py         # AggregationHandler (Polars)
│
├── predictors/                # ML inference
│   ├── __init__.py
│   ├── forecast.py            # ForecastHandler
│   ├── risk.py                # RiskHandler
│   └── duplicate.py           # DuplicateHandler
│
├── exporters/                 # Output serialization
│   ├── __init__.py
│   ├── registry.py            # Serializer protocol, ExportArtifact model
│   ├── json_serializer.py     # JSON serializer
│   ├── csv_serializer.py      # CSV serializer
│   ├── parquet_serializer.py  # Parquet serializer
│   ├── excel_serializer.py    # Excel serializer
│   └── chart_data.py          # Chart-optimized JSON serializer
│
├── sandbox/                   # Safe Python execution
│   ├── __init__.py
│   ├── handler.py             # SandboxHandler (registered with Dispatcher)
│   ├── ast_checker.py         # AST-based code safety analysis
│   ├── runner.py              # SandboxConfig, execute_sandboxed()
│   └── config.py              # Sandbox configuration
│
├── telemetry/                 # Observability
│   ├── __init__.py
│   ├── metrics.py             # Prometheus counters, histograms, gauges
│   ├── logging.py             # Structured logging configuration
│   ├── tracing.py             # OpenTelemetry span management
│   └── artifacts.py           # Artifact storage and retention
│
├── cache/                     # Result caching
│   ├── __init__.py
│   ├── key.py                 # compute_cache_key()
│   └── backend.py             # CacheBackend (Redis)
│
└── shared/                    # Common utilities
    ├── __init__.py
    ├── errors.py              # RuntimeErrorInfo, ErrorCategory, error catalog
    ├── retry.py               # RetryPolicy, retry schedules
    ├── config.py              # Runtime configuration (extends shared/config)
    └── utils.py               # JSON helpers, Decimal handling, type utilities
```

---

## Dependency Rules

The runtime follows the same layered architecture as the rest of the FinSight codebase:

```
python-runtime/
    │
    ├── api/           → depends on: jobs/, dispatcher/, cache/, shared/
    ├── jobs/          → depends on: dispatcher/, telemetry/, shared/
    ├── dispatcher/    → depends on: importers/, validators/, transforms/,
    │                     analytics/, predictors/, sandbox/, exporters/, shared/
    ├── importers/     → depends on: shared/
    ├── validators/    → depends on: shared/ (Pandera, Pydantic)
    ├── transforms/    → depends on: shared/
    ├── analytics/     → depends on: shared/ (DuckDB, Polars)
    ├── predictors/    → depends on: shared/, finance/ml/registry (if available)
    ├── exporters/     → depends on: shared/
    ├── sandbox/       → depends on: shared/
    ├── telemetry/     → depends on: shared/ (OpenTelemetry, Prometheus)
    ├── cache/         → depends on: shared/ (Redis)
    └── shared/        → depends on: nothing within runtime (may reference shared/ config)
```

**Cardinal rules:**

| Rule | Enforcement |
|------|-------------|
| `shared/` never imports from any other runtime module | Circular prevention |
| `importers/` never imports from `analytics/`, `predictors/`, `sandbox/` | Importers acquire data only |
| `analytics/`, `predictors/` never import from `exporters/` | Executors produce `HandlerResult` only |
| `predictors/` may import `RiskProvider` protocol from `finance/ml/` | But must not import concrete model implementations |
| `sandbox/` never accesses the network | Enforced by sandbox configuration |

---

## Interfaces

### Upward interfaces (what the runtime provides to the backend)

| Interface | Type | Consumer | Example |
|-----------|------|----------|---------|
| `RuntimeRequest` | Pydantic `BaseModel` | Backend POST body | `{"job_id": "...", "job_type": "analytics", ...}` |
| `JobState` | Pydantic `BaseModel` | Backend polling response | `{"status": "executing", "progress_pct": 67.2}` |
| `HandlerResult` | Pydantic `BaseModel` | Backend result consumption | `{"data": [...], "row_count": 142}` |
| `RuntimeErrorInfo` | Pydantic `BaseModel` | Backend error handling | `{"code": "IMPORT_SOURCE_UNREACHABLE", ...}` |
| `ExportArtifact` | Pydantic `BaseModel` | Backend download handler | `{"format": "csv", "file_path": "/tmp/..."}` |
| `Cache clear` | HTTP DELETE endpoint | Backend admin | `DELETE /api/runtime/cache/{tenant_id}` |

### Downward interfaces (what the runtime consumes)

| Interface | Provider | Notes |
|-----------|----------|-------|
| `Importer` Protocol | Implementation classes | Same pattern as `SpreadsheetProvider` in `finance/integration/protocol.py` |
| `RiskProvider` Protocol | `finance/ml/` registry | Same pattern as `InferenceRegistry` in `finance/ml/registry.py` |
| Redis | Cache backend | Via `python-runtime/cache/backend.py` |
| Pandera | Schema validation | `python-runtime/validators/schemas.py` |
| DuckDB / Polars | Analytics engines | `python-runtime/analytics/` |
| OpenTelemetry | Trace export | `python-runtime/telemetry/tracing.py` |
| Prometheus | Metrics export | `python-runtime/telemetry/metrics.py` |

### Design contract

All upward interfaces share four properties:

1. **Typed** — No dictionaries cross the boundary. Every return value is a Pydantic model.
2. **Validated at construction** — `RuntimeRequest` raises on invalid input before any compute runs.
3. **Self-documenting** — Every model field has a clear business meaning.
4. **Immutable where practical** — `RuntimeRequest` is frozen after construction; `JobState` is a snapshot, not a live reference.

---

## Operational Metrics

### Job Health

| Metric | Definition | Target | Source |
|--------|-----------|--------|--------|
| `runtime.jobs.success_rate` | Jobs completing SUCCESS / total started | > 98% | `runtime_jobs_completed_total{status="success"}` |
| `runtime.jobs.retry_rate` | Jobs retried / total started | < 5% | `runtime_jobs_retried_total` |
| `runtime.jobs.timeout_rate` | Jobs timed out / total started | < 1% | `runtime_jobs_completed_total{status="timeout"}` |
| `runtime.jobs.cancellation_rate` | Jobs cancelled / total started | < 2% | `runtime_jobs_completed_total{status="cancelled"}` |
| `runtime.jobs.p99_duration` | 99th percentile of execution duration | Analytics < 30s, ML < 60s | `runtime_execution_duration_seconds` |

### Import Health

| Metric | Definition | Target | Source |
|--------|-----------|--------|--------|
| `runtime.import.success_rate` | Imports completed / total attempted | > 99% | Per-importer success counter |
| `runtime.import.p99_duration` | 99th percentile import time | CSV < 5s, Sheets < 15s | `runtime_import_duration_seconds` |
| `runtime.import.validation_failure_rate` | Pandera violations / total imports | < 2% | `runtime_validation_failures_total` |

### ML Inference Health

| Metric | Definition | Target | Source |
|--------|-----------|--------|--------|
| `runtime.prediction.latency_p50` | Median prediction latency | < 50ms per entity | `runtime_prediction_latency_ms` |
| `runtime.prediction.latency_p99` | 99th percentile prediction latency | < 200ms per entity | `runtime_prediction_latency_ms` |
| `runtime.prediction.error_rate` | Predictions raising exceptions | < 0.1% | `runtime_jobs_completed_total{status="failed", job_type="risk"}` |

### Cache Health

| Metric | Definition | Target | Source |
|--------|-----------|--------|--------|
| `runtime.cache.hit_rate` | Cache hits / (hits + misses) | > 40% | `runtime_cache_hits_total / (hits + misses)` |
| `runtime.cache.avg_eviction_age` | Average TTL at eviction | > 50% of configured TTL | Redis `evicted_keys` metric |

### Sandbox Health

| Metric | Definition | Target | Source |
|--------|-----------|--------|--------|
| `runtime.sandbox.violation_rate` | AST violations / total sandbox submissions | < 5% | Sandbox violation counter |
| `runtime.sandbox.execution_time_p95` | 95th percentile sandbox execution time | < 10s | Sandbox execution duration histogram |

---

## Failure Modes

### F-1: Schema Drift (Upstream)

**What happens:** A connected Google Sheet changes a column name, adds a required field, or changes a data type. Pandera validation produces violations for every row.

**Detection:** `runtime_validation_failures_total` spike. Validation stage returns 100% violation rate. Job enters `FAILED` with `DATASET_SCHEMA_VIOLATION`.

**Response:**
1. Identify the violating column and constraint from the `ValidationErrorInfo` list
2. Determine if this is an upstream schema change or a data quality issue
3. If schema change: update the Pandera schema in `python-runtime/validators/schemas.py` and re-deploy
4. If data quality: notify DataOps, add normalization rule if needed
5. Backfill: resubmit the job after schema update

**Prevention:**
- Pin schema version metadata in `source_fingerprint` — detect drift before validation
- Monitor `validation_failure_rate` trend per source type

### F-2: Source Unreachable

**What happens:** Google Sheets API returns 503, PostgreSQL connection times out, network is unreachable. `Importer.read()` raises `ImportError`.

**Detection:** Job enters `FAILED` with `IMPORT_SOURCE_UNREACHABLE`, `retryable=True`. Retry count increments.

**Response:**
1. Check retry policy — transient errors retry automatically with exponential backoff
2. If retries exhausted: the error is surfaced to the backend with `remediation_hint`
3. Check authentication credentials if the error is `IMPORT_AUTH_FAILURE` (403)
4. For Google Sheets: check API quota and service dashboard
5. For PostgreSQL: check connection pool and service health

**Prevention:**
- Implement circuit-breaker pattern for external API connectors
- Monitor credential expiry — rotate before they expire
- Configure health checks on all source connections

### F-3: Dataset Exceeds Capacity

**What happens:** A job submits a 100M-row dataset, exceeding memory limits. DuckDB runs out of memory. The handler raises `ANALYTICS_OUT_OF_MEMORY`.

**Detection:** `runtime_jobs_completed_total{status="failed"}` increments for analytics job type. Memory gauge spikes.

**Response:**
1. The error is not retryable — larger dataset will fail again
2. Surface error to user with row count and limit
3. Options: filter dataset, increase memory allocation, or switch to streaming execution mode
4. Log the dataset size in metrics for capacity planning

**Prevention:**
- Enforce `max_rows` from `RuntimeRequest` at the import stage
- Implement streaming/batched execution for large datasets
- Configure per-tenant memory quotas

### F-4: Sandbox Escape Attempt

**What happens:** A user or generated code attempts to import `os`, call `subprocess.run()`, or access the filesystem outside the sandbox. The AST checker or runtime isolation blocks it.

**Detection:** `SANDBOX_VIOLATION` error with details of the blocked call.

**Response:**
1. Log the full blocked code and violation details (for incident investigation)
2. Return structured error to the backend — never expose the blocked code in the error message
3. If repeated attempts from the same user: flag for security review
4. If the code was LLM-generated: add the violation pattern to the prompt guardrails

**Prevention:**
- Maintain and regularly update the forbidden-module blocklist
- Run sandbox tests in CI that verify all known escape vectors are blocked
- Use Modal Sandbox (production) which provides hardware-level isolation

### F-5: Cache Poisoning

**What happens:** The cache key does not adequately distinguish between two different inputs. A cached result from dataset A is returned for dataset B.

**Detection:** Customers report that job results are unchanging despite data updates. `cache_hit_rate` is suspiciously high (> 95%).

**Response:**
1. Flush the cache immediately: `DELETE /api/runtime/cache`
2. Investigate `compute_cache_key()` for missing parameters in the key
3. Check `source_fingerprint` computation — two different datasets should produce different fingerprints
4. Add integration test that verifies cache miss on different data

**Prevention:**
- `source_fingerprint` must include a content hash of the source data, not just metadata
- Every parameter in `params` must be included in the cache key (sorted, serialized)
- Cache key should include a version number for future iteration
- Test: two jobs with different data but same `source_type` must produce different keys

### F-6: Export Serialization Failure

**What happens:** The handler result contains a data type that the serializer cannot handle (e.g., a Pydantic model with a nested custom type, or a `Decimal` that is not JSON-serializable).

**Detection:** `EXPORT_SERIALIZATION_FAILED` error. Job completes execution but fails at export stage.

**Response:**
1. Check the `HandlerResult.data` structure for unsupported types
2. Add a serializer for the new type, or convert before inserting into `HandlerResult`
3. Verify that all `Decimal` values are handled — they must use `DecimalEncoder` pattern
4. Add validation in handler output: construct Pydantic model before inserting into `HandlerResult`

**Prevention:**
- All handler outputs must be JSON-serializable Pydantic models
- Use the `DecimalEncoder` from `shared/utils/encoders.py` for all monetary serialization
- Add export integration tests for every handler type

### F-7: Memory Leak Across Jobs

**What happens:** A handler does not release resources (database connections, file handles, large DataFrames) after completion. Over successive jobs, runtime memory grows until OOM.

**Detection:** `runtime_memory_usage_mb` shows monotonic growth across job completions. Container OOM kills the runtime.

**Response:**
1. Restart the runtime container (temporary fix)
2. Profile memory usage per handler — identify which handler is leaking
3. Common causes: DuckDB connections not closed, Pandas DataFrames in closure scope, unclosed file handles
4. Fix handler to release resources in `finally` block or context manager

**Prevention:**
- Every handler must release resources in `finally` or via `contextlib`
- Set `resource.setrlimit(RLIMIT_AS)` per job to cap per-job memory
- Run memory leak detection in CI (`pytest --memray` or similar)
- Implement per-worker memory limit at the process level

---

## Relationship to Other Platform Layers

| Layer | Runtime Provides | Runtime Requires |
|-------|-----------------|-----------------|
| **DevSecOps** | Compute process lifecycle, temp storage | Docker container, Redis cache, Prometheus endpoint, OTLP collector |
| **DataOps** | Dataset validation results, normalized data | Pandera schemas, domain model definitions, `MoneyDecimal` enforcement pattern |
| **MLOps** | ML inference execution environment | `RiskProvider` protocol, trained model artifacts, `InferenceRegistry` |
| **LLMOps** | Sandboxed Python execution for generated code | Prompt schemas, forbidden-pattern blocklist updates |
| **AgentOps** | Compute-as-a-service — agents dispatch work | Job type definitions, handler registration |

### Key architectural boundaries

```
                         AgentOps
                            │
                   dispatches compute jobs
                            │
                         ┌──▼──┐
                         │Runtime│
                         └──┬──┘
                    ┌───────┼───────┐
                    │       │       │
               ┌────▼──┐ ┌─▼──┐ ┌──▼────┐
               │DataOps│ │MLOps│ │LLMOps │
               └───────┘ └────┘ └───────┘
                    │       │       │
                    └───┬───┘───┬───┘
                        │       │
                   ┌────▼───────▼───┐
                   │   DevSecOps    │
                   └────────────────┘
```

**Critical rule:** The Runtime does not own domain logic. It does not compute variances, materiality, KPI values, or any finance-specific calculation. Those belong to the deterministic engines in `finance/`. The Runtime owns the execution infrastructure — acquisition, validation, dispatch, sandboxing, export, caching, observability, error classification.

**The Runtime is to compute what DevSecOps is to infrastructure — the universal substrate that makes everything else reliable, observable, and governable.**

---

## Migration Paths

### Phase 1 — Monolithic Runtime (Current target)

The entire runtime lives in a single Python process (FastAPI + background workers). All handlers are in-process. Suitable for single-tenant deployments and development:

```
docker-compose.yml addition:
  runtime:
    build:
      context: ./python-runtime
      dockerfile: Dockerfile.runtime
    ports:
      - "8010:8010"
    depends_on:
      - redis
      - postgres
    environment:
      - REDIS_URL=redis://redis:6380/0
      - RUNTIME_WORKERS=4
```

### Phase 2 — Worker Pool (Horizontal scaling)

When job volume outgrows the monolithic process, extract workers into a pool:

```
Runtime API (stateless) → RedPanda queue → Worker pool (N containers)
```

- API container handles request validation, returns `{job_id, status}`
- Workers pick up jobs from the queue, execute, store results
- API polls result store or uses Temporal for orchestration
- Workers scale horizontally based on queue depth

### Phase 3 — Serverless (Modal)

Individual handlers migrate to Modal when elasticity demands it:

```
Runtime API (stateless) → Modal Sandbox / Modal Function → Result store
```

- Heavy handlers (ML inference, large analytics) run on Modal
- Simple handlers (validation, small exports) remain in-process
- The `JobHandler` Protocol means zero code change per handler
- Migration is handler-by-handler, not all-or-nothing

**No code changes required for any migration path** — the `Dispatcher` + `JobHandler` Protocol abstracts the execution target. A handler does not know whether it runs in-process, in a worker pool, or on Modal.

---

## References

- **Protocol pattern:** `finance/integration/protocol.py` — the `SpreadsheetProvider` Protocol that inspired the `Importer` abstraction
- **Factory pattern:** `finance/integration/factory.py` — the `ProviderFactory` that inspired `ImporterFactory`
- **Structured results:** `shared/utils/tools/tool_result.py` — the `ToolResult` frozen model pattern informs `Dataset`, `HandlerResult`, and `RuntimeErrorInfo`
- **Structured errors:** The error classification model extends the `DegradedMode` pattern from `shared/models/degraded_mode.py`
- **Decimal serialization:** `shared/utils/encoders.py` — the `DecimalEncoder` that ensures monetary values serialize as strings
- **Async execution:** The `JobState` state machine mirrors the `PipelineState` pattern in `shared/models/state.py`
- **ML inference:** `finance/ml/protocol.py` — the `RiskProvider` protocol that `predictors/` handlers call
- **ML registry:** `finance/ml/registry.py` — the `InferenceRegistry` that provides model instances to the runtime
- **Sandbox execution:** Modal `Sandbox.create()` — the production sandbox isolation mechanism
- **Configuration:** `shared/config/config.py` — the `Settings` pattern that `python-runtime/shared/config.py` extends
- **PRD NFR-02:** "Deterministic computation — identical inputs produce identical outputs" — the guarantee that makes caching safe
- **ADR-008:** Hexagonal architecture — the Protocol-based port-adapter pattern that the runtime uses for Importers and Handlers
