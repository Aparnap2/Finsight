# FinSight State Machines Specification

**Version:** 1.0 (Frozen — requires explicit approval to change)
**Status:** Draft for review
**Canonical source:** `docs/specs/DOMAIN_MODEL.md`, `docs/PRODUCT.md` §4

---

## 1. Principles

- No free-form status strings. All states are explicit enums.
- Transitions are validated by a single transition function per entity.
- Every transition produces an `AuditEvent`.
- Terminal states cannot be exited except via explicit reopen (where defined).
- Forbidden transitions raise `INVALID_STATE_TRANSITION` error.
- State changes never happen silently.

---

## 2. ImportSession State Machine

### States

`CREATED` → `UPLOADING` → `VALIDATING` → `READY`
                                    ↓
                                `REJECTED`

### Transition Table

| From | To | Trigger | Preconditions | Authorization | Audit Event |
|---|---|---|---|---|---|
| CREATED | UPLOADING | First file upload | Session exists | Actor owns tenant | `session_upload_started` |
| UPLOADING | VALIDATING | All required files uploaded | At least one file per source type | Actor owns tenant | `session_validation_started` |
| VALIDATING | READY | All files valid | No INVALID rows | Actor owns tenant | `session_ready` |
| VALIDATING | REJECTED | Validation failures | At least one INVALID row | Actor owns tenant | `session_rejected` |
| READY | UPLOADING | Re-upload (new file) | — | Actor owns tenant | `session_reopened_for_upload` |
| REJECTED | UPLOADING | Re-upload (corrected file) | — | Actor owns tenant | `session_reopened_for_upload` |

### Terminal States

None (sessions can be reopened for re-upload).

### Forbidden Transitions

- `READY → VALIDATING` (must re-upload first)
- `REJECTED → VALIDATING` (must re-upload first)
- Any transition from a non-existent state

---

## 3. ReconciliationRun State Machine

### States

`QUEUED` → `VALIDATING` → `PROCESSING` → `SUCCEEDED`
                                       ↓
                                    `FAILED`
                                       ↓
                                 `CANCELLED`

### Transition Table

| From | To | Trigger | Preconditions | Authorization | Audit Event |
|---|---|---|---|---|---|
| QUEUED | VALIDATING | Start processing | Run exists, session is READY | Actor owns tenant | `run_validation_started` |
| VALIDATING | PROCESSING | Validation passed | All source files valid | Actor owns tenant | `run_processing_started` |
| VALIDATING | FAILED | Validation failed | At least one INVALID row | Actor owns tenant | `run_failed` (error_code=VALIDATION_FAILED) |
| PROCESSING | SUCCEEDED | Engine completed | All matches/allocations/exceptions persisted | Actor owns tenant | `run_succeeded` |
| PROCESSING | FAILED | Engine error or persistence failure | — | Actor owns tenant | `run_failed` (error_code=RECONCILIATION_FAILED or PERSISTENCE_UNAVAILABLE) |
| QUEUED | CANCELLED | User cancels | Run not started | Actor owns tenant | `run_cancelled` |
| VALIDATING | CANCELLED | User cancels | — | Actor owns tenant | `run_cancelled` |
| PROCESSING | CANCELLED | User cancels | — | Actor owns tenant | `run_cancelled` |

### Terminal States

`SUCCEEDED`, `FAILED`, `CANCELLED`

Terminal states cannot be exited. A new run must be created for re-processing.

### Retryability

- `FAILED` (PERSISTENCE_UNAVAILABLE): retryable (transient)
- `FAILED` (RECONCILIATION_FAILED): not retryable (permanent)
- `CANCELLED`: not retryable (user-initiated)

### Forbidden Transitions

- `SUCCEEDED → *` (terminal)
- `FAILED → *` (terminal, except via new run)
- `CANCELLED → *` (terminal)
- `QUEUED → PROCESSING` (must validate first)
- `QUEUED → SUCCEEDED` (must process first)

---

## 4. ReconciliationException State Machine

### States

`OPEN` → `INVESTIGATING` → `UNDER_REVIEW` → `RESOLVED`
   ↑                                              ↓
   └──────────────── `REOPENED` ←─────────────────┘

### Transition Table

| From | To | Trigger | Preconditions | Authorization | Audit Event |
|---|---|---|---|---|---|
| OPEN | INVESTIGATING | Start AI investigation | Exception exists, actor authorized | Actor owns tenant, role ≥ ANALYST | `exception_investigation_started` |
| OPEN | UNDER_REVIEW | Manual review started | — | Actor owns tenant, role ≥ ANALYST | `exception_review_started` |
| OPEN | RESOLVED | Direct resolution (no investigation) | — | Actor owns tenant, role ≥ MANAGER | `exception_resolved` |
| INVESTIGATING | UNDER_REVIEW | Investigation completed | Investigation status = COMPLETED | Actor owns tenant, role ≥ ANALYST | `exception_review_started` |
| INVESTIGATING | OPEN | Investigation failed/cancelled | — | Actor owns tenant, role ≥ ANALYST | `exception_investigation_failed` |
| UNDER_REVIEW | RESOLVED | Human decision recorded | Decision recorded | Actor owns tenant, role ≥ MANAGER | `exception_resolved` |
| UNDER_REVIEW | OPEN | Reopened for further investigation | — | Actor owns tenant, role ≥ MANAGER | `exception_reopened` |
| RESOLVED | REOPENED | Reopen (new evidence) | — | Actor owns tenant, role ≥ MANAGER | `exception_reopened` |
| REOPENED | INVESTIGATING | Re-investigate | — | Actor owns tenant, role ≥ ANALYST | `exception_investigation_started` |
| REOPENED | UNDER_REVIEW | Re-review | — | Actor owns tenant, role ≥ ANALYST | `exception_review_started` |

### Terminal States

None (exceptions can be reopened).

### Forbidden Transitions

- `RESOLVED → RESOLVED` (no-op, reject)
- `OPEN → RESOLVED` without UNDER_REVIEW (except direct resolution by MANAGER)
- `INVESTIGATING → RESOLVED` (must go through UNDER_REVIEW)
- Any transition by unauthorized actor

---

## 5. Investigation State Machine

### States

`PENDING` → `RUNNING` → `COMPLETED`
                      ↓
                   `FAILED`
                      ↓
                 `CANCELLED`

### Transition Table

| From | To | Trigger | Preconditions | Authorization | Audit Event |
|---|---|---|---|---|---|
| PENDING | RUNNING | Start investigation | Exception exists, provider available | Actor owns tenant | `investigation_started` |
| RUNNING | COMPLETED | Provider returned valid result | Structured output validated | System (provider callback) | `investigation_completed` |
| RUNNING | FAILED | Provider error, timeout, or schema violation | — | System | `investigation_failed` |
| PENDING | CANCELLED | User cancels before start | — | Actor owns tenant | `investigation_cancelled` |
| RUNNING | CANCELLED | User cancels during run | — | Actor owns tenant | `investigation_cancelled` |

### Terminal States

`COMPLETED`, `FAILED`, `CANCELLED`

### Retryability

- `FAILED` (PROVIDER_TIMEOUT, PROVIDER_UNAVAILABLE): retryable (transient)
- `FAILED` (PROVIDER_AUTH, SCHEMA_VIOLATION): not retryable (permanent)

### Forbidden Transitions

- `COMPLETED → *` (terminal)
- `FAILED → *` (terminal, except new investigation)
- `CANCELLED → *` (terminal)
- `PENDING → COMPLETED` (must run first)

---

## 6. ExportArtifact State Machine

### States

`PENDING` → `GENERATING` → `COMPLETED`
                        ↓
                     `FAILED`

### Transition Table

| From | To | Trigger | Preconditions | Authorization | Audit Event |
|---|---|---|---|---|---|
| PENDING | GENERATING | Start generation | Run exists and is SUCCEEDED | Actor owns tenant | `export_started` |
| GENERATING | COMPLETED | File written to storage | Storage ref set | System | `export_completed` |
| GENERATING | FAILED | Storage error or timeout | — | System | `export_failed` |

### Terminal States

`COMPLETED`, `FAILED`

### Forbidden Transitions

- `COMPLETED → *` (terminal)
- `FAILED → *` (terminal, except new export)
- `PENDING → COMPLETED` (must generate first)