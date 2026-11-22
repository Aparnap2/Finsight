# FinSight Error Catalog Specification

**Version:** 1.0 (Frozen — requires explicit approval to change)
**Status:** Draft for review
**Canonical source:** `docs/specs/API_CONTRACT.md`, `docs/specs/STATE_MACHINES.md`

---

## 1. Error Response Envelope

All errors return a consistent JSON envelope:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message (user-safe, no secrets)",
    "details": {}
  },
  "request_id": "uuid",
  "correlation_id": "uuid"
}
```

- `code`: Stable error code from the taxonomy below.
- `message`: User-safe. Never contains stack traces, SQL, file paths, or secrets.
- `details`: Structured context (field names, expected formats). Never contains PII or raw financial data.
- `request_id`: Unique per HTTP request.
- `correlation_id`: Propagated from client or generated; links request → run → trace.

---

## 2. Error Taxonomy

### 2.1 Validation Errors (4xx, not retryable)

| Code | HTTP | Meaning | User Message | Retryable | Metric |
|---|---|---|---|---|---|
| `INVALID_FILE` | 400 | File is empty, wrong format, or unsupported encoding | "The uploaded file could not be read. Check encoding and format." | No | `finsight_upload_validation_failures_total{reason="invalid_file"}` |
| `INVALID_SCHEMA` | 400 | CSV headers don't match expected schema | "Expected columns: {list}. Found: {list}." | No | `finsight_upload_validation_failures_total{reason="invalid_schema"}` |
| `VALIDATION_FAILED` | 422 | Row-level validation errors | "N rows failed validation. See details." | No | `finsight_upload_validation_failures_total{reason="validation_failed"}` |
| `DUPLICATE_IMPORT` | 409 | Same file content already imported for this period | "This file was already imported for this period." | No | `finsight_upload_validation_failures_total{reason="duplicate_import"}` |
| `INVALID_STATE_TRANSITION` | 409 | Requested state transition is not permitted | "Cannot transition from {from} to {to}." | No | `finsight_invalid_transitions_total` |
| `IDempotency_CONFLICT` | 409 | Same idempotency key with different request body | "Idempotency key already used with different parameters." | No | `finsight_idempotency_conflicts_total` |

### 2.2 Authorization Errors (4xx, not retryable)

| Code | HTTP | Meaning | User Message | Retryable | Metric |
|---|---|---|---|---|---|
| `TENANT_ACCESS_DENIED` | 403 | Cross-tenant access attempt | "Access denied." (no detail) | No | `finsight_authz_denials_total{reason="tenant"}` |
| `UNAUTHORIZED` | 401 | Missing or invalid authentication | "Authentication required." | No | `finsight_auth_failures_total` |
| `FORBIDDEN` | 403 | Insufficient role for action | "Insufficient permissions for this action." | No | `finsight_authz_denials_total{reason="role"}` |

### 2.3 Resource Errors (4xx, not retryable)

| Code | HTTP | Meaning | User Message | Retryable | Metric |
|---|---|---|---|---|---|
| `RESOURCE_NOT_FOUND` | 404 | Entity not found (or not in tenant scope) | "Resource not found." | No | `finsight_resource_not_found_total` |

### 2.4 Processing Errors (5xx, not retryable)

| Code | HTTP | Meaning | User Message | Retryable | Metric |
|---|---|---|---|---|---|
| `RECONCILIATION_FAILED` | 500 | Engine error during reconciliation | "Reconciliation failed. Contact support." | No | `finsight_reconciliation_failures_total{reason="engine"}` |
| `EXPORT_FAILED` | 500 | Export generation failed | "Export failed. Retry or contact support." | Yes (transient) | `finsight_export_failures_total` |

### 2.5 Infrastructure Errors (5xx, retryable)

| Code | HTTP | Meaning | User Message | Retryable | Metric |
|---|---|---|---|---|---|
| `PERSISTENCE_UNAVAILABLE` | 503 | Database unavailable | "Service temporarily unavailable. Retry." | Yes | `finsight_database_errors_total` |
| `PROVIDER_TIMEOUT` | 504 | AI provider timeout | "Investigation timed out. Retry." | Yes | `finsight_ai_provider_errors_total{reason="timeout"}` |
| `PROVIDER_UNAVAILABLE` | 503 | AI provider unavailable | "Investigation service unavailable. Retry later." | Yes | `finsight_ai_provider_errors_total{reason="unavailable"}` |
| `PROVIDER_AUTH` | 503 | AI provider authentication failure | "Investigation service misconfigured." | No | `finsight_ai_provider_errors_total{reason="auth"}` |
| `SCHEMA_VIOLATION` | 422 | AI response failed schema validation | "Investigation returned invalid result." | No | `finsight_ai_provider_errors_total{reason="schema"}` |

---

## 3. Error Handling Rules

1. **Never expose stack traces** to users. Log them server-side with correlation ID.
2. **Never expose SQL, file paths, or internal identifiers** in user-facing messages.
3. **Never expose raw financial data** in error details (amounts, account numbers).
4. **Retryable errors** return appropriate HTTP status (503/504) and include `Retry-After` header.
5. **Permanent errors** return 4xx and do not include retry guidance.
6. **All errors** are logged with: request_id, correlation_id, tenant_id (hashed), error_code, timestamp, stack trace (server-side only).
7. **All errors** increment the corresponding metric counter.
8. **AI provider errors** never corrupt or block access to deterministic reconciliation results. Financial data remains accessible even when AI is down.

---

## 4. Recovery Guidance

| Error Category | Recovery Action |
|---|---|
| Validation (4xx) | User corrects input and resubmits |
| Authorization (4xx) | User authenticates or requests access |
| Not Found (404) | User verifies resource exists |
| State Transition (409) | User checks current state and retries valid transition |
| Idempotency Conflict (409) | User uses a new idempotency key |
| Processing (5xx) | User retries; if persistent, contact support |
| Infrastructure (5xx) | System auto-retries (transient); user retries after backoff |
| Provider (5xx) | System retries (transient); user can retry investigation separately |

---

## 5. Internal Diagnostic Context

Server-side logs include (in addition to the error envelope):

```json
{
  "error_code": "RECONCILIATION_FAILED",
  "request_id": "uuid",
  "correlation_id": "uuid",
  "tenant_id_hash": "sha256(tenant_id)[:16]",
  "actor_id": "uuid",
  "entity_type": "ReconciliationRun",
  "entity_id": "uuid",
  "stack_trace": "...",
  "timestamp": "2026-01-15T10:10:02Z"
}
```

**Never log:** secrets, API keys, full uploaded file contents, PII beyond tenant/actor IDs, raw financial amounts in error details (amounts may appear in audit events, not error logs).