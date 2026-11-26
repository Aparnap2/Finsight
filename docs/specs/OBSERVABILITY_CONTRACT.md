# FinSight Observability Contract Specification

**Version:** 1.0 (Frozen — requires explicit approval to change)
**Status:** Draft for review
**Canonical source:** `docs/PRODUCT.md` §6, `docs/specs/ERROR_CATALOG.md`

---

## 1. Structured Log Schema

All application logs are structured JSON. One JSON object per line.

```json
{
  "timestamp": "2026-01-15T10:10:02.123Z",
  "severity": "INFO",
  "service": "finsight-api",
  "environment": "staging",
  "build_id": "abc1234",
  "request_id": "uuid",
  "correlation_id": "uuid",
  "tenant_id_hash": "sha256(tenant_id)[:16]",
  "run_id": "uuid",
  "operation": "reconciliation.run",
  "outcome": "success",
  "duration_ms": 1234.5,
  "message": "Reconciliation run completed",
  "error_code": null,
  "error_category": null
}
```

### Field Definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `timestamp` | ISO 8601 UTC | Yes | Event time with millisecond precision |
| `severity` | enum | Yes | DEBUG, INFO, WARNING, ERROR, CRITICAL |
| `service` | str | Yes | Service name (e.g., "finsight-api") |
| `environment` | str | Yes | development, staging, production |
| `build_id` | str | Yes | Git commit SHA (short) |
| `request_id` | UUID | Yes | Unique per HTTP request |
| `correlation_id` | UUID | No | Propagated from client or generated |
| `tenant_id_hash` | str (16 hex) | No | SHA-256 of tenant_id, truncated. Never raw tenant ID. |
| `run_id` | UUID | No | Reconciliation run ID if applicable |
| `operation` | str | No | Operation name (e.g., "reconciliation.run") |
| `outcome` | str | No | success, failure, partial |
| `duration_ms` | float | No | Operation duration in milliseconds |
| `message` | str | Yes | Human-readable message |
| `error_code` | str | No | Error code from ERROR_CATALOG |
| `error_category` | str | No | validation, authorization, processing, infrastructure, provider |

### Redaction Rules

**Never log:**
- Secrets, API keys, passwords, tokens
- Full uploaded file contents
- Raw financial amounts in error messages (amounts may appear in audit events)
- PII beyond tenant/actor IDs (no email, phone, SSN)
- Database connection strings
- Stack traces in user-facing output (server-side logs only)

**Safe to log:**
- Tenant ID hash (truncated SHA-256)
- Actor ID (UUID)
- Run ID, exception ID, decision ID
- Error codes and categories
- File metadata (name, size, row count) — not contents
- Metric values

---

## 2. Correlation Model

```
request_id → trace_id → tenant_id (hashed) → run_id → operation
```

- `request_id`: Generated per HTTP request (UUID v4). Returned in response headers (`X-Request-ID`).
- `trace_id`: OpenTelemetry trace ID. Propagated via `traceparent` header.
- `tenant_id`: Hashed for logs. Used for RLS and authorization.
- `run_id`: Reconciliation run ID. Links all operations for a run.
- `operation`: Logical operation name (e.g., "reconciliation.run", "import.upload", "exception.decision").

**Propagation:**
- HTTP requests: `request_id` and `correlation_id` in response headers (`X-Request-ID`, `X-Correlation-ID`). Both are accepted on the inbound request; an unsafe inbound value is replaced rather than echoed.
- Database queries: `run_id` in query comments (for slow query analysis).
- AI investigations: `run_id` and `exception_id` in provider call metadata.
- Logs: all fields above included in every log line for the request.

---

## 3. Metrics

### 3.1 HTTP Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `finsight_http_requests_total` | Counter | method, path_template, status_code | Total HTTP requests |
| `finsight_http_request_duration_seconds` | Histogram | method, path_template | Request latency |
| `finsight_http_active_requests` | Gauge | — | Currently processing requests |

**Label cardinality**: `path_template` uses route templates (e.g., `/api/v1/runs/{run_id}`), not actual paths. Max ~20 unique values.

### 3.2 Upload Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `finsight_uploads_total` | Counter | source_type, status | Total file uploads |
| `finsight_upload_bytes_total` | Counter | source_type | Total bytes uploaded |
| `finsight_upload_validation_failures_total` | Counter | reason | Validation failures by reason |
| `finsight_upload_duration_seconds` | Histogram | source_type | Upload processing time |

### 3.3 Reconciliation Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `finsight_reconciliation_runs_total` | Counter | status | Runs by terminal status |
| `finsight_reconciliation_run_duration_seconds` | Histogram | — | Run processing time |
| `finsight_reconciliation_failures_total` | Counter | reason | Failures by reason |
| `finsight_reconciliation_matches_total` | Counter | outcome | Matches by outcome |
| `finsight_reconciliation_exceptions_total` | Counter | severity, code | Exceptions by severity and code |

### 3.4 Exception Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `finsight_open_exceptions` | Gauge | severity | Currently open exceptions |
| `finsight_exception_age_seconds` | Histogram | severity | Age of open exceptions |
| `finsight_exception_decisions_total` | Counter | decision_type | Decisions by type |

### 3.5 AI Investigation Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `finsight_ai_investigations_total` | Counter | status | Investigations by status |
| `finsight_ai_investigation_duration_seconds` | Histogram | — | Investigation processing time |
| `finsight_ai_provider_errors_total` | Counter | reason | Provider errors by reason |
| `finsight_ai_provider_latency_seconds` | Histogram | provider | Provider call latency |

### 3.6 Infrastructure Metrics

| Metric | Type | Labels | Description |
|---|---|---|---|
| `finsight_database_errors_total` | Counter | operation | DB errors by operation |
| `finsight_database_query_duration_seconds` | Histogram | operation | DB query latency |
| `finsight_export_total` | Counter | format, status | Exports by format and status |
| `finsight_export_failures_total` | Counter | reason | Export failures |
| `finsight_retries_total` | Counter | operation | Retry attempts |
| `finsight_retries_exhausted_total` | Counter | operation | Exhausted retries |

### 3.7 Label Cardinality Rules

- **Never** use tenant IDs, run IDs, request IDs, or actor IDs as metric labels.
- **Never** use arbitrary strings (file names, error messages) as labels.
- All labels must have a bounded, known set of values.
- Maximum 10 unique values per label.
- If a value is unbounded, use a log field, not a metric label.

---

## 4. Health Endpoints

> **Implementation note (v1.1).** The endpoints below are specified at
> `/health/live` and `/health/ready`. The application currently registers
> `/live` and `/ready` (see `apps/api/observability.py::create_readiness_router`).
> Both spellings are exempt from tenant authentication so an unauthenticated
> probe works either way. The divergence is recorded in `ERROR_CATALOG.md` §6
> and is not silently "fixed" by renaming the contract.
>
> Readiness currently performs the database check only. Migration-currency and
> required-table checks are specified but **not implemented**; a ready process
> therefore proves connectivity, not migration correctness.

### GET /health/live

- **Purpose**: Process is alive.
- **Checks**: None (returns 200 if the process responds).
- **Dependencies**: None.
- **Response**: `{"status": "alive"}`
- **Must not** depend on PostgreSQL or any external service.

### GET /health/ready

- **Purpose**: Application is ready to serve traffic.
- **Checks**:
  1. PostgreSQL connectivity (SELECT 1)
  2. Migration currency (current revision == head)
  3. Required tables exist
- **Response (200)**: `{"status": "ready", "checks": {"database": "ok", "migrations": "current"}}`
- **Response (503)**: `{"status": "not_ready", "checks": {"database": "error", "migrations": "pending"}}`
- **Must not** check external providers (LLM, S3) — those are optional.

---

## 5. Tracing

- **Protocol**: OpenTelemetry (OTLP export).
- **Instrumentation**: FastAPI, SQLAlchemy, httpx (LLM calls).
- **Propagation**: `traceparent` header (W3C Trace Context).
- **Spans**: One span per HTTP request, one child span per DB query, one child span per LLM call, one child span per reconciliation stage.
- **Attributes**: `tenant_id_hash`, `run_id`, `operation`, `outcome`. Never raw tenant ID or financial data.
- **Export**: OTLP to collector (Jaeger/Tempo) or stdout (development).

---

## 6. Operator Diagnosis Procedure

Given a failed reconciliation run (run_id):

1. **Find the run**: `GET /api/v1/runs/{run_id}` → status, error_code, error_detail.
2. **Find the request**: Search logs by `run_id` → `request_id`, `correlation_id`.
3. **Find the trace**: Search traces by `correlation_id` → span tree with timing.
4. **Find the exception**: `GET /api/v1/runs/{run_id}/exceptions` → exception codes and evidence.
5. **Find the audit trail**: Query `audit_events` by `entity_id = run_id` → state transitions.
6. **Find the investigation**: `GET /api/v1/investigations/{id}` → AI result (if any).
7. **Determine recovery**: Check run status (FAILED → retryable? cancelled? terminal?).

All of this must be possible without accessing the database directly or reading application source code.