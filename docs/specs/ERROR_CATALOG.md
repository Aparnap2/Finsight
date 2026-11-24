# FinSight Error Catalog Specification

**Version:** 1.0 (Frozen — requires explicit approval to change)
**Status:** Draft for review
**Canonical source:** `docs/specs/API_CONTRACT.md`, `docs/specs/STATE_MACHINES.md`

---

## 0. Error-Management Invariant (Normative)

Errors are inevitable; **uncontrolled** errors are a design failure. Every
failure in FinSight must be handled at the correct boundary so that it is
graceful, tracked, measured, observed, and recoverable. A failure that is
contained but invisible is still a defect.

### 0.1 The five properties

| Property | Required behaviour |
|---|---|
| **Graceful** | Fail without corrupting data, leaking tenant information, or leaving partial state. Return a meaningful, user-safe error. |
| **Tracked** | Record a stable error `code`, `request_id`, `correlation_id`, tenant context, operation, and relevant entity IDs. |
| **Measured** | Aggregate failure rate, frequency, duration, retries, and recovery outcome. |
| **Observed** | Expose structured logs, metrics, traces, health signals, and actionable alerts. |
| **Recoverable** | State explicitly whether the caller should retry, resume, compensate, escalate, or seek human intervention. |

### 0.2 The five prohibitions

1. **No silent failures.** A caught exception that is neither surfaced to the
   caller nor logged with its trace is a defect.
2. **No partial financial state.** A failed operation must roll back entirely.
   The system must never report success when persistence failed.
3. **No unclassified errors.** Every emitted error carries a code from §2.
   An uncatalogued code is a spec change, not an implementation detail.
4. **No unmeasured critical operations.** Reconciliation, ingestion, exception
   decisions, and exports must be measurable. Absence of a metric is a known
   gap recorded in §6, never assumed to be acceptable.
5. **No unsafe retries.** Financial writes are retried only through the
   database-backed idempotency contract, never by blind client or blanket
   middleware retry.

### 0.3 Invariant statement

> Every failure is handled at the right boundary, preserves system integrity,
> produces actionable evidence, and remains observable from detection through
> resolution.

Graceful failure does **not** mean hidden failure. It means containing the
blast radius while making the failure impossible to overlook.

---

## 1. Error Response Envelope

All errors return a consistent JSON envelope:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message (user-safe, no secrets)",
    "details": {},
    "retryable": false
  },
  "request_id": "uuid",
  "correlation_id": "uuid"
}
```

- `code`: Stable error code from the taxonomy below.
- `message`: User-safe. Never contains stack traces, SQL, file paths, or secrets.
- `details`: Structured context (field names, expected formats). Never contains PII or raw financial data.
- `retryable`: Whether the caller may retry the identical request. Client
  behaviour must be driven by this field, not by status code guesses.
- `request_id`: Unique per HTTP request.
- `correlation_id`: Propagated from client or generated; links request → run → trace.

> **Versioning note.** `retryable` was added in v1.1 at the owner's request so
> that recovery semantics are machine-readable rather than inferred from the
> table. It is additive: existing clients that ignore it continue to work.

### 1.1 Single source of truth and Stage 1 compatibility

The classification facts in this document are executed, not merely described.
`shared/errors/catalog.py` holds the registry — stable code, category, default
HTTP status, severity, retryability, recovery guidance, and owner — and the API
boundary derives every response body from it (`apps/api/errors.py`). A handler
never invents a code; if a route needs a new one, the registry gains it first
and this document is updated in the same change. Drift in the
registry→document direction is a defect; a test asserts that every registered
code is documented here.

**Stage 1 is additive, not breaking.** The pre-existing FastAPI body shape

```json
{ "detail": <string or list, unchanged> }
```

is preserved **verbatim** for every response that already emitted it. The
`error` object, `request_id`, and `correlation_id` are added alongside it. No
status code changes. Therefore:

| Consumer reads | Before | After |
|---|---|---|
| `detail` only | works | works, byte-identical text |
| `error.code` / `error.retryable` | absent | present |
| Status code | unchanged | unchanged |

`detail` remains the human string or structured field list; `error.message`
carries the user-safe text and may be more general than `detail` (for example,
`detail="Unknown role: ceo"` with `error.message="Insufficient permissions for
this action."`). Middleware rejections (missing tenant context, unknown role)
emit the same envelope, so a denial is traceable to a correlation ID rather
than being an anonymous 401.

This compatibility layer is a **transition state**, not the final contract. A
later stage may drop the top-level `detail` once consumers are migrated; that
removal is a breaking change and requires its own explicit authorization.


---

## 2. Error Taxonomy

### 2.0 Classification model

Every error belongs to exactly one category. The category fixes the default
severity, retryability, owner, and recovery policy; a specific row may narrow
but must not contradict it.

| Category | Default HTTP | Severity | Retryable | Owner | Recovery policy |
|---|---|---|---|---|---|
| **Validation** | 4xx | WARNING | No | Caller | Correct input and resubmit. |
| **Business-rule** | 4xx | WARNING | No | Operator (human) | Resolve state or ambiguity, then resubmit a valid action. |
| **Authorization** | 4xx | WARNING | No | Caller | Authenticate or request access. |
| **Security** | 4xx | **ERROR** | No | Security owner | Deny, record a security event, investigate. |
| **Concurrency** | 409 | WARNING | **Yes (safe)** | Caller | Re-read current state, then retry with fresh preconditions. |
| **Resource** | 404 | INFO | No | Caller | Verify the identifier exists in tenant scope. |
| **Processing** | 5xx | ERROR | No | FinSight engineering | Investigate with the correlation ID; do not blind-retry. |
| **Infrastructure** | 5xx | ERROR | Yes (bounded) | Platform | Back off and retry; surface `Retry-After`. |
| **Provider (AI)** | 5xx | WARNING | Yes (bounded) | AI platform | Deterministic results stay available; retry investigation separately. |

Concurrency and business-rule failures are **not** validation failures. They
mean the request was well-formed but the system refused it for a state reason.
Collapsing them into `400` hides whether a safe retry is possible.

### 2.1 Validation Errors (4xx, not retryable)

| Code | HTTP | Meaning | User Message | Retryable | Metric |
|---|---|---|---|---|---|
| `INVALID_FILE` | 400 | File is empty, wrong format, or unsupported encoding | "The uploaded file could not be read. Check encoding and format." | No | `finsight_upload_validation_failures_total{reason="invalid_file"}` |
| `INVALID_SCHEMA` | 400 | CSV headers don't match expected schema | "Expected columns: {list}. Found: {list}." | No | `finsight_upload_validation_failures_total{reason="invalid_schema"}` |
| `VALIDATION_FAILED` | 422 | Row-level validation errors | "N rows failed validation. See details." | No | `finsight_upload_validation_failures_total{reason="validation_failed"}` |
| `DUPLICATE_IMPORT` | 409 | Same file content already imported for this period | "This file was already imported for this period." | No | `finsight_upload_validation_failures_total{reason="duplicate_import"}` |
| `INVALID_STATE_TRANSITION` | 409 | Requested state transition is not permitted | "Cannot transition from {from} to {to}." | No | `finsight_invalid_transitions_total` |
| `IDEMPOTENCY_CONFLICT` | 409 | Same idempotency key with different request body | "Idempotency key already used with different parameters." | No | `finsight_idempotency_conflicts_total` |
| `BAD_REQUEST` | 400 | Malformed request that no more specific code describes | "The request could not be understood." | No | — |
| `PAYLOAD_TOO_LARGE` | 413 | Request body exceeds the configured limit | "The upload is too large." | No | — |
| `METHOD_NOT_ALLOWED` | 405 | HTTP method not supported by this resource | "That method is not supported for this resource." | No | — |

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
| `INTERNAL_ERROR` | 500 | Unexpected failure with no more specific classification | "Internal server error." (never the exception text) | No | — |

`INTERNAL_ERROR` is the terminal fallback: an unhandled exception maps here and
the diagnostic detail stays in protected logs. It is never used where a precise
code exists.

### 2.5 Infrastructure Errors (5xx / 429, retryable)

| Code | HTTP | Meaning | User Message | Retryable | Metric |
|---|---|---|---|---|---|
| `PERSISTENCE_UNAVAILABLE` | 503 | Database unavailable | "Service temporarily unavailable. Retry." | Yes | `finsight_database_errors_total` |
| `SERVICE_UNAVAILABLE` | 503 | A dependency other than the database is unavailable | "Service temporarily unavailable. Retry." | Yes | — |
| `GATEWAY_TIMEOUT` | 504 | Upstream dependency did not answer in time | "The request timed out. Retry." | Yes | — |
| `RATE_LIMITED` | 429 | Caller exceeded a configured rate limit | "Too many requests. Retry after the interval." | Yes | — |
| `BUDGET_EXHAUSTED` | 429 | An LLM/agent budget (calls, tokens, deadline) was exceeded | "The operation budget was exhausted." | Yes | — |
| `PROVIDER_TIMEOUT` | 504 | AI provider timeout | "Investigation timed out. Retry." | Yes | `finsight_ai_provider_errors_total{reason="timeout"}` |
| `PROVIDER_UNAVAILABLE` | 503 | AI provider unavailable | "Investigation service unavailable. Retry later." | Yes | `finsight_ai_provider_errors_total{reason="unavailable"}` |
| `PROVIDER_AUTH` | 503 | AI provider authentication failure | "Investigation service misconfigured." | No | `finsight_ai_provider_errors_total{reason="auth"}` |
| `SCHEMA_VIOLATION` | 422 | AI response failed schema validation | "Investigation returned invalid result." | No | `finsight_ai_provider_errors_total{reason="schema"}` |

### 2.6 Concurrency Errors (409, safely retryable after re-read)

| Code | HTTP | Meaning | User Message | Retryable | Metric |
|---|---|---|---|---|---|
| `STATE_VERSION_CONFLICT` | 409 | Resource changed since the caller read it (`expected_state_version` mismatch) | "This record changed. Reload and try again." | Yes (after re-read) | `finsight_concurrency_conflicts_total{reason="state_version"}` |
| `DUPLICATE_DECISION` | 409 | Decision already recorded for this exception/version | "A decision is already recorded for this version." | No (idempotent success) | `finsight_concurrency_conflicts_total{reason="duplicate_decision"}` |

A concurrency conflict is never a 5xx. It is an expected outcome of correct
concurrent operation and must be reported as a conflict, not a server error.

### 2.7 Business-Rule Errors (4xx, not retryable, human review)

| Code | HTTP | Meaning | User Message | Retryable | Metric |
|---|---|---|---|---|---|
| `ILLEGAL_TRANSITION` | 409¹ | Requested exception transition is forbidden by the state machine | "That transition is not allowed from the current state." | No | `finsight_invalid_transitions_total` |
| `AMBIGUOUS_ALLOCATION` | 422 | More than one legal allocation target; deterministic resolution refused | "The allocation is ambiguous and needs review." | No | `finsight_reconciliation_failures_total{reason="ambiguous"}` |
| `CONFLICT` | 409 | Generic state conflict with no more specific business-rule code | "The request conflicts with the current state." | No | — |

¹ `API_CONTRACT.md` §4 shows `OPEN → RESOLVED` via `APPROVE`, while
`finance/reconciliation/exception_lifecycle.ALLOWED_TRANSITIONS` forbids it.
The state machine is authoritative; the transition returns an error rather
than silently succeeding. See §6 for the recorded divergence.

### 2.8 Security Errors (4xx, ERROR severity, audited)

| Code | HTTP | Meaning | User Message | Retryable | Metric |
|---|---|---|---|---|---|
| `TENANT_ACCESS_DENIED` | 403 | Cross-tenant access attempt | "Access denied." (no detail) | No | `finsight_authz_denials_total{reason="tenant"}` |
| `TENANT_CONTEXT_MISSING` | 401 | Request reached a tenant-scoped route without a resolvable tenant | "Authentication required." | No | `finsight_authz_denials_total{reason="context"}` |

Security errors are distinguished from ordinary authorization errors by
**evidence obligation**: each must emit an audit or security event that
records the attempted resource and the decision, without recording the
protected payload. Denial without an auditable record is a defect.

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

---

## 6. Implementation Status (evidence-based)

This section exists so that no reader mistakes a specified behaviour for a
delivered one. Statuses are **Verified** (direct evidence), **Partial**
(some evidence, known gaps), or **Not implemented** (no evidence found).

| Requirement | Status | Evidence |
|---|---|---|
| No partial financial state | **Verified** | `tests/integration/test_reconciliation_http.py::TestPersistenceAtomicity` — injected failure at the final write leaves zero rows and the idempotency key reusable. |
| Unsafe-retry prevention | **Verified** | Savepoint idempotency + `FOR UPDATE` decisions (`finance/reconciliation/persistence.py`); `tests/integration/test_reconciliation_concurrency.py`. |
| Internal detail never leaked on 5xx | **Verified** | 15 × `detail="Internal server error."` + `logger.exception(...)` in `apps/api/reconciliation_routes.py`; `IngestionError → 400` for malformed CSV. |
| `request_id` propagation | **Verified** | `apps/api/observability.py::RequestIDMiddleware`; `tests/integration/test_observability.py`. |
| `correlation_id` propagation | **Verified** | Accepted/echoed as `X-Correlation-ID` and recorded in the access log; `tests/integration/test_observability.py::TestCorrelationId`. |
| Error `code` in responses | **Verified (additive, Stage 1)** | Registry `shared/errors/catalog.py`; handlers `apps/api/errors.py`; every `HTTPException` and unhandled exception now yields `error.code`. Tested by `tests/unit/api/test_error_contract.py`. |
| `retryable` in responses | **Verified (additive, Stage 1)** | Derived from the registry spec, not hard-coded per handler; `tests/unit/api/test_error_contract.py::TestRegistryInvariants::test_retryability_is_explicit`. |
| Registry↔document consistency | **Verified (one direction)** | `tests/unit/api/test_error_contract.py::TestSingleSourceOfTruth` asserts every registered code is documented. The reverse (documented but unregistered) is not yet machine-checked. |
| Legacy `detail` compatibility | **Verified** | `detail` echoed verbatim; existing `["detail"]` assertions in `tests/unit/test_platform/test_middleware.py` and `tests/integration/test_error_echo.py` still pass unchanged. |
| Metrics (§3 of observability contract) | **Not implemented** | No metrics backend in `pyproject.toml`; no `prometheus_client` import. |
| Tracing (OpenTelemetry) | **Not implemented** | No OpenTelemetry dependency or instrumentation. |
| Structured JSON log lines | **Not implemented** | Python `logging` with a text formatter; records are structured in memory but rendered as text. |
| Health endpoint paths | **Partial / divergent** | Implemented `/live` and `/ready`; `OBSERVABILITY_CONTRACT.md` §4 specifies `/health/live` and `/health/ready`. Recorded, not silently renamed. |
| Readiness dependency depth | **Partial** | `default_db_probe` runs `SELECT 1` only; the contract also specifies migration currency and required-table checks. |
| Per-category metric counters | **Not implemented** | Taxonomy lists metric names; none are emitted. |

### 6.1 Recorded contradictions (not silently resolved)

1. **`OPEN → RESOLVED` via `APPROVE`.** `API_CONTRACT.md` §4 shows this
   transition; `exception_lifecycle.ALLOWED_TRANSITIONS` forbids it. The state
   machine is authoritative: the API returns `400` with a generic message.
2. **Illegal transition status.** This catalog maps `INVALID_STATE_TRANSITION`
   to `409`; `apps/api/reconciliation_routes.py` returns `400` for the same
   condition. Both are recorded; neither is silently changed.
3. **Code casing.** `IDempotency_CONFLICT` was corrected to
   `IDEMPOTENCY_CONFLICT` in v1.1 to match `API_CONTRACT.md` and the audit
   event constraint `chk_audit_event_type`.

### 6.2 Consequences of the "no parallel architecture" rule

The gaps above are **not** addressed by adding a logging framework, a metrics
server, or a tracer. They are addressed by (a) fixing defects that already
corrupt reliability, and (b) marking unimplemented capabilities honestly.
Introducing an observability stack is a separate, separately-authorized
initiative.

### 6.3 Stage 1 scope: what was built and what was deliberately not

Stage 1 closed the **error contract** only. It is bounded as follows.

Built:

* A registry (`shared/errors/catalog.py`) that owns code, category, default
  status, severity, retryability, recovery, and owner.
* A centralised exception→response mapping (`apps/api/errors.py`) using
  FastAPI's native `add_exception_handler` — no custom middleware framework.
* The additive envelope described in §1.1, with `detail` preserved.
* Contract, regression, and compatibility tests (`tests/unit/api/test_error_contract.py`).

Deliberately **not** built (each needs its own authorization):

* A `/metrics` endpoint. Measurement is Stage 2, and a metric must first name
  the operational decision it supports, its cardinality, retention, and
  exposure. An endpoint without those definitions is not observability.
* OpenTelemetry tracing. Not authorized.
* JSON log rendering. Not authorized; logs remain structured in memory and
  rendered as text.
* Removal of the legacy `detail` key. Breaking; requires consumer migration.

The envelope is a **projection** of the registry, never a second source of
truth. If a response and the registry disagree, the registry is correct and the
response is the defect.