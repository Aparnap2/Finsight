# FinSight API Contract Specification

**Version:** 1.0 (Frozen — requires explicit approval to change)
**Status:** Draft for review
**Base URL:** `/api/v1`
**Canonical source:** `docs/specs/DOMAIN_MODEL.md`, `docs/PRODUCT.md` §3

---

## 1. Conventions

### Authentication

All endpoints (except health) require authentication. Current implementation uses demo headers (`X-Tenant-ID`, `X-User-ID`, `X-Role`) for development. Production must use JWT or session-based auth.

### Tenant scoping

Every request is scoped to the authenticated tenant. Cross-tenant access returns `403 Forbidden`.

### Error response envelope

Every error response carries a structured `error` object plus request
identifiers:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "category": "validation",
    "message": "Human-readable message",
    "details": {},
    "retryable": false
  },
  "request_id": "uuid",
  "correlation_id": "uuid",
  "detail": "<legacy field, preserved verbatim>"
}
```

* `error.code` is a stable code from `docs/specs/ERROR_CATALOG.md`. The
  executable registry is `shared/errors/catalog.py`; the response is derived
  from it, never the reverse.
* `error.retryable` states whether the identical request may be retried. Clients
  must drive retry behaviour from this field, not from status-code guesses.
* `request_id` / `correlation_id` are also echoed as the `X-Request-ID` and
  `X-Correlation-ID` response headers.
* `detail` is the **pre-envelope** body. It is preserved byte-for-byte so
  existing clients keep working.

**Contract change notice (additive, Stage 1).** This is a deliberate,
documented extension of the frozen contract, not a silent one. The `error`
object, `retryable`, `request_id`, and `correlation_id` are additions; no
status code changes and no existing field is removed or renamed. Middleware
rejections (401 missing tenant context, 403 unknown role) emit the same
envelope so a denial is traceable to a correlation ID. Removing the legacy
`detail` key later is a breaking change and requires separate authorization.
See `ERROR_CATALOG.md` §1.1 for the compatibility matrix and
`tests/unit/api/test_error_contract.py` for the enforcing tests.

### Pagination

List endpoints support `?limit=50&offset=0`. Default limit: 50. Max limit: 200.

Response includes `total_count` and `has_more`.

### Idempotency

Mutating endpoints accept `Idempotency-Key` header. Duplicate keys return the original response.

---

## 2. Endpoints

### 2.1 Import Sessions

#### POST /api/v1/import-sessions

Create a new import session.

**Request:**
```json
{
  "period_start": "2026-01-01",
  "period_end": "2026-01-31"
}
```

**Response (201):**
```json
{
  "session_id": "uuid",
  "tenant_id": "uuid",
  "status": "CREATED",
  "period_start": "2026-01-01",
  "period_end": "2026-01-31",
  "created_at": "2026-01-15T10:00:00Z"
}
```

**Errors:** 400 (invalid period), 401 (unauthorized), 409 (duplicate session for period)

#### POST /api/v1/import-sessions/{session_id}/files/{source_type}

Upload a source file (CSV or any supported format).

**Path params:** `source_type` ∈ {INVOICE, STRIPE, BANK}

**Request:** `multipart/form-data` with file field.

**Response (201):**
```json
{
  "file_id": "uuid",
  "source_type": "INVOICE",
  "filename": "invoices_jan.csv",
  "row_count": 42,
  "content_hash": "sha256...",
  "uploaded_at": "2026-01-15T10:05:00Z"
}
```

**Errors:** 400 (invalid file, wrong type), 401, 403 (wrong tenant), 404 (session not found), 409 (duplicate file), 413 (file too large)

#### POST /api/v1/import-sessions/{session_id}/validate

Validate all uploaded files.

**Response (200):**
```json
{
  "session_id": "uuid",
  "status": "READY",
  "files": [
    {
      "file_id": "uuid",
      "source_type": "INVOICE",
      "valid_rows": 40,
      "invalid_rows": 2,
      "errors": [
        {"line_number": 5, "field": "amount", "reason": "INVALID_AMOUNT", "detail": "Not a valid decimal"}
      ]
    }
  ]
}
```

**Errors:** 400 (no files uploaded), 401, 403, 404, 409 (already validated)

#### GET /api/v1/import-sessions/{session_id}

**Response (200):** Full session detail with files and validation status.

---

### 2.2 Reconciliation Runs

#### POST /api/v1/runs

Start a reconciliation run.

**Request:**
```json
{
  "session_id": "uuid",
  "idempotency_key": "unique-key-123"
}
```

**Response (201):**
```json
{
  "run_id": "uuid",
  "session_id": "uuid",
  "status": "QUEUED",
  "created_at": "2026-01-15T10:10:00Z"
}
```

**Errors:** 400 (session not ready), 401, 403, 404 (session not found), 409 (idempotency conflict), 422 (validation failed)

#### GET /api/v1/runs/{run_id}

**Response (200):**
```json
{
  "run_id": "uuid",
  "session_id": "uuid",
  "status": "SUCCEEDED",
  "engine_version": "abc1234",
  "input_fingerprint": "sha256...",
  "started_at": "2026-01-15T10:10:01Z",
  "completed_at": "2026-01-15T10:10:02Z",
  "summary": {
    "matches": 5,
    "exceptions": 2,
    "pending_evidence": 1,
    "ambiguous": 1
  }
}
```

**Errors:** 401, 403, 404

#### GET /api/v1/runs/{run_id}/matches

**Response (200):**
```json
{
  "run_id": "uuid",
  "matches": [
    {
      "match_id": "uuid",
      "invoice_id": "INV-001",
      "charge_id": "ch_001",
      "outcome": "MATCHED",
      "expected_amount": "1000.00",
      "observed_amount": "971.00",
      "difference": "-29.00",
      "variance": "29.00",
      "tolerance_applied": "0.00",
      "currency": "USD",
      "exception_code": null,
      "materiality": "IMMATERIAL",
      "fingerprint": "sha256..."
    }
  ],
  "total_count": 5,
  "has_more": false
}
```

#### GET /api/v1/runs/{run_id}/allocations

**Response (200):**
```json
{
  "run_id": "uuid",
  "allocations": [
    {
      "allocation_id": "uuid",
      "deposit_id": "dep-001",
      "outcome": "MATCHED",
      "allocated_total": "971.00",
      "eligible_net_total": "971.00",
      "open_balance": "0.00",
      "unallocated_deposit": "0.00",
      "fee_total": "29.00",
      "refund_total": "0.00",
      "exception_code": null,
      "fingerprint": "sha256...",
      "legs": [
        {
          "payment_id": "ch_001",
          "gross": "1000.00",
          "fee": "29.00",
          "refund": "0.00",
          "net": "971.00",
          "allocated": "971.00",
          "fingerprint": "sha256..."
        }
      ]
    }
  ],
  "total_count": 1,
  "has_more": false
}
```

#### GET /api/v1/runs/{run_id}/exceptions

**Response (200):**
```json
{
  "run_id": "uuid",
  "exceptions": [
    {
      "exception_id": "uuid",
      "exception_code": "I-DUPLICATE",
      "severity": "HIGH",
      "status": "OPEN",
      "title": "Duplicate ledger entry",
      "description": "Deposit dep-001 appears twice in the statement",
      "evidence_refs": ["stmt:line-3", "stmt:line-7"],
      "created_at": "2026-01-15T10:10:02Z"
    }
  ],
  "total_count": 2,
  "has_more": false
}
```

---

### 2.3 Exceptions

#### GET /api/v1/exceptions/{exception_id}

**Response (200):** Full exception detail with evidence.

#### POST /api/v1/exceptions/{exception_id}/investigations

Start an AI investigation.

**Request:**
```json
{
  "actor_id": "uuid"
}
```

**Response (201):**
```json
{
  "investigation_id": "uuid",
  "exception_id": "uuid",
  "status": "PENDING",
  "created_at": "2026-01-15T10:15:00Z"
}
```

**Errors:** 400 (already investigating), 401, 403, 404

#### GET /api/v1/investigations/{investigation_id}

**Response (200):**
```json
{
  "investigation_id": "uuid",
  "exception_id": "uuid",
  "status": "COMPLETED",
  "provider": "groq",
  "model": "openai/gpt-oss-20b",
  "result_text": "The deposit discrepancy of 29.00 is explained by...",
  "evidence_refs": ["stmt:line-3", "ch_001"],
  "started_at": "2026-01-15T10:15:01Z",
  "completed_at": "2026-01-15T10:15:03Z"
}
```

#### POST /api/v1/exceptions/{exception_id}/decisions

Record a human decision.

**Request:**
```json
{
  "decision_type": "APPROVE",
  "reason": "Confirmed duplicate deposit; second entry is a bank re-posting",
  "evidence_refs": ["stmt:line-3", "stmt:line-7"]
}
```

**Response (201):**
```json
{
  "decision_id": "uuid",
  "exception_id": "uuid",
  "decision_type": "APPROVE",
  "previous_status": "OPEN",
  "new_status": "RESOLVED",
  "decided_at": "2026-01-15T10:20:00Z"
}
```

**Errors:** 400 (invalid transition), 401, 403 (unauthorized), 404, 409 (duplicate decision)

---

### 2.4 Exports

#### POST /api/v1/runs/{run_id}/exports

**Request:**
```json
{
  "format": "CSV"
}
```

**Response (201):**
```json
{
  "export_id": "uuid",
  "run_id": "uuid",
  "status": "PENDING",
  "format": "CSV",
  "created_at": "2026-01-15T10:25:00Z"
}
```

#### GET /api/v1/exports/{export_id}

**Response (200):**
```json
{
  "export_id": "uuid",
  "run_id": "uuid",
  "status": "COMPLETED",
  "format": "CSV",
  "storage_ref": "s3://bucket/exports/run-123.csv",
  "file_size_bytes": 4096,
  "completed_at": "2026-01-15T10:25:01Z"
}
```

---

### 2.5 Health

#### GET /health/live

**Response (200):** `{"status": "alive"}`

No dependency checks. Process is running.

#### GET /health/ready

**Response (200):** `{"status": "ready", "checks": {"database": "ok", "migrations": "current"}}`

**Response (503):** `{"status": "not_ready", "checks": {"database": "error", "migrations": "pending"}}`

Checks: PostgreSQL connectivity, migration currency (current == head).

---

## 3. Error Code Mapping

See `docs/specs/ERROR_CATALOG.md` for full taxonomy. Summary:

| Error Code | HTTP Status | Retryable |
|---|---|---|
| INVALID_FILE | 400 | No |
| INVALID_SCHEMA | 400 | No |
| VALIDATION_FAILED | 422 | No |
| DUPLICATE_IMPORT | 409 | No |
| IDEMPOTENCY_CONFLICT | 409 | No |
| RESOURCE_NOT_FOUND | 404 | No |
| UNAUTHORIZED | 401 | No |
| FORBIDDEN | 403 | No |
| TENANT_ACCESS_DENIED | 403 | No |
| TENANT_CONTEXT_MISSING | 401 | No |
| INVALID_STATE_TRANSITION | 409 | No |
| ILLEGAL_TRANSITION | 409 | No |
| DUPLICATE_DECISION | 409 | No |
| STATE_VERSION_CONFLICT | 409 | Yes (after re-read) |
| BAD_REQUEST | 400 | No |
| RECONCILIATION_FAILED | 500 | No |
| INTERNAL_ERROR | 500 | No |
| PERSISTENCE_UNAVAILABLE | 503 | Yes (transient) |
| SERVICE_UNAVAILABLE | 503 | Yes (transient) |
| GATEWAY_TIMEOUT | 504 | Yes (transient) |
| RATE_LIMITED | 429 | Yes (transient) |
| BUDGET_EXHAUSTED | 429 | Yes (transient) |
| PROVIDER_TIMEOUT | 504 | Yes (transient) |
| PROVIDER_UNAVAILABLE | 503 | Yes (transient) |
| EXPORT_FAILED | 500 | Yes (transient) |