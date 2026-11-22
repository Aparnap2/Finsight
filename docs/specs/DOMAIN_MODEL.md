# FinSight Domain Model Specification

**Version:** 1.0 (Frozen — requires explicit approval to change)
**Status:** Draft for review
**Canonical source:** `docs/PRODUCT.md` §3–§5, `finance/reconciliation/models.py`, `finance/reconciliation/bank.py`, `finance/reconciliation/allocation.py`, `finance/reconciliation/statement_workflow.py`

---

## 1. Core Principle

Deterministic financial code owns financial outcomes. Every number in FinSight originates from the reconciliation engine (`finance/reconciliation/`) operating on typed, immutable records. AI, UI, and API layers read and display; they never compute or alter financial facts.

Money is `decimal.Decimal`. Float is rejected at every boundary. Currency is explicit ISO 4217. Tenant scoping is mandatory on every business record.

---

## 2. Entities

### 2.1 Tenant

| Attribute | Type | Constraints |
|---|---|---|
| `tenant_id` | UUID | PK |
| `name` | str | non-empty, unique |
| `created_at` | datetime (tz-aware, UTC) | not null |
| `status` | TenantStatus enum | ACTIVE, SUSPENDED |

**TenantStatus**: `ACTIVE`, `SUSPENDED`

No business record exists without a tenant. Tenant is the root of all data ownership.

### 2.2 ImportSession

Groups the three source imports for one reconciliation period.

| Attribute | Type | Constraints |
|---|---|---|
| `session_id` | UUID | PK |
| `tenant_id` | UUID | FK → Tenant, not null, indexed |
| `actor_id` | UUID | not null (who created) |
| `period_start` | date | not null |
| `period_end` | date | not null, ≥ period_start |
| `status` | ImportSessionStatus enum | see §4 |
| `created_at` | datetime (tz-aware, UTC) | not null |
| `updated_at` | datetime (tz-aware, UTC) | not null |

**ImportSessionStatus**: `CREATED`, `UPLOADING`, `VALIDATING`, `READY`, `REJECTED`

### 2.3 SourceFile

One uploaded CSV file belonging to an import session.

| Attribute | Type | Constraints |
|---|---|---|
| `file_id` | UUID | PK |
| `session_id` | UUID | FK → ImportSession, not null |
| `tenant_id` | UUID | FK → Tenant, not null (denormalized for RLS) |
| `source_type` | SourceType enum | INVOICE, STRIPE, BANK |
| `filename` | str | non-empty, max 255 chars |
| `content_hash` | str | sha256 hex digest (64 chars), unique per (tenant, source_type, period) |
| `file_size_bytes` | int | > 0, ≤ configured max (default 10 MB) |
| `row_count` | int | ≥ 0 |
| `storage_ref` | str | S3 key or local path; non-empty |
| `uploaded_at` | datetime (tz-aware, UTC) | not null |
| `uploaded_by` | UUID | not null |

**SourceType**: `INVOICE`, `STRIPE`, `BANK`

**Constraints:**
- One SourceFile per (session_id, source_type) — a session has at most one file per source type.
- Re-uploading the same file (same content_hash) for the same tenant/period is idempotent (returns existing record).

### 2.4 ImportRow

One normalized source record from an uploaded file.

| Attribute | Type | Constraints |
|---|---|---|
| `row_id` | UUID | PK |
| `file_id` | UUID | FK → SourceFile, not null |
| `session_id` | UUID | FK → ImportSession, not null (denormalized for RLS) |
| `tenant_id` | UUID | FK → Tenant, not null (denormalized for RLS) |
| `source_type` | SourceType enum | not null |
| `line_number` | int | ≥ 1 (1-based row in source file) |
| `raw_data` | JSON | original row as key-value (for audit) |
| `normalized` | JSON | normalized record (PaymentRecord or BankDepositRecord fields) |
| `validation_status` | ValidationStatus enum | VALID, INVALID |
| `reject_reason` | str | nullable; set when INVALID |
| `created_at` | datetime (tz-aware, UTC) | not null |

**ValidationStatus**: `VALID`, `INVALID`

### 2.5 ReconciliationRun

A durable execution of the reconciliation engine on a specific import session.

| Attribute | Type | Constraints |
|---|---|---|
| `run_id` | UUID | PK |
| `session_id` | UUID | FK → ImportSession, not null |
| `tenant_id` | UUID | FK → Tenant, not null (denormalized for RLS) |
| `actor_id` | UUID | not null (who started) |
| `idempotency_key` | str | unique per (tenant_id, idempotency_key); non-empty |
| `status` | RunStatus enum | see §4 |
| `engine_version` | str | non-empty (git SHA or version tag) |
| `input_fingerprint` | str | sha256 hex (64 chars) — fingerprint of canonical input |
| `input_snapshot_ref` | str | reference to immutable input snapshot |
| `started_at` | datetime (tz-aware, UTC) | nullable (set on transition to PROCESSING) |
| `completed_at` | datetime (tz-aware, UTC) | nullable (set on terminal state) |
| `created_at` | datetime (tz-aware, UTC) | not null |
| `updated_at` | datetime (tz-aware, UTC) | not null |
| `error_code` | ErrorCode enum | nullable; set on FAILED |
| `error_detail` | str | nullable; user-safe message |

**RunStatus**: `QUEUED`, `VALIDATING`, `PROCESSING`, `SUCCEEDED`, `FAILED`, `CANCELLED`

**Constraints:**
- Same (tenant_id, idempotency_key) → returns existing run (idempotent).
- A run cannot transition to SUCCEEDED while any required processing is incomplete.
- `completed_at` is set only on terminal states (SUCCEEDED, FAILED, CANCELLED).

### 2.6 ReconciliationMatch

Deterministic match between an invoice and a charge (or charge-to-deposit allocation).

| Attribute | Type | Constraints |
|---|---|---|
| `match_id` | UUID | PK |
| `run_id` | UUID | FK → ReconciliationRun, not null |
| `tenant_id` | UUID | FK → Tenant, not null (denormalized for RLS) |
| `invoice_id` | str | non-empty (source invoice identifier) |
| `charge_id` | str | non-empty (source charge identifier) |
| `outcome` | ReconciliationOutcome enum | MATCHED, TOLERANCE_MATCHED, EXCEPTION, PENDING_EVIDENCE |
| `expected_amount` | Decimal | ≥ 0, 2 decimal places (currency minor unit) |
| `observed_amount` | Decimal | ≥ 0, 2 decimal places |
| `difference` | Decimal | observed - expected |
| `variance` | Decimal | abs(difference) |
| `tolerance_applied` | Decimal | ≥ 0 |
| `currency` | str | ISO 4217 (3 uppercase) |
| `exception_code` | str | nullable; I-code when outcome is EXCEPTION |
| `materiality` | MaterialityVerdict enum | MATERIAL, IMMATERIAL |
| `fingerprint` | str | sha256 hex (64 chars) |
| `created_at` | datetime (tz-aware, UTC) | not null |

**ReconciliationOutcome**: `MATCHED`, `TOLERANCE_MATCHED`, `EXCEPTION`, `PENDING_EVIDENCE`

**MaterialityVerdict**: `MATERIAL`, `IMMATERIAL`

### 2.7 PayoutAllocation

Allocation of a bank deposit to one or more charges.

| Attribute | Type | Constraints |
|---|---|---|
| `allocation_id` | UUID | PK |
| `run_id` | UUID | FK → ReconciliationRun, not null |
| `tenant_id` | UUID | FK → Tenant, not null (denormalized for RLS) |
| `deposit_id` | str | non-empty (source deposit identifier) |
| `outcome` | PayoutOutcome enum | MATCHED, TOLERANCE_MATCHED, EXCEPTION, PENDING_EVIDENCE, REQUIRES_HUMAN |
| `allocated_total` | Decimal | ≥ 0 |
| `eligible_net_total` | Decimal | ≥ 0 |
| `open_balance` | Decimal | ≥ 0 (eligible_net - allocated) |
| `unallocated_deposit` | Decimal | ≥ 0 (deposit - allocated) |
| `fee_total` | Decimal | ≥ 0 |
| `refund_total` | Decimal | ≥ 0 |
| `exception_code` | str | nullable; I-code when outcome is EXCEPTION |
| `fingerprint` | str | sha256 hex (64 chars) |
| `created_at` | datetime (tz-aware, UTC) | not null |

**PayoutOutcome**: `MATCHED`, `TOLERANCE_MATCHED`, `EXCEPTION`, `PENDING_EVIDENCE`, `REQUIRES_HUMAN`

**AllocationLeg** (child of PayoutAllocation, 1:N):

| Attribute | Type | Constraints |
|---|---|---|
| `leg_id` | UUID | PK |
| `allocation_id` | UUID | FK → PayoutAllocation, not null |
| `payment_id` | str | non-empty (source charge identifier) |
| `gross` | Decimal | ≥ 0 |
| `fee` | Decimal | ≥ 0 |
| `refund` | Decimal | ≥ 0 |
| `net` | Decimal | gross - fee - refund |
| `allocated` | Decimal | > 0, ≤ net |
| `fingerprint` | str | sha256 hex (64 chars) |

**Invariants (enforced in `Allocation.__post_init__`):**
- `allocated_total + open_balance == eligible_net_total`
- `allocated_total + unallocated_deposit == deposit_amount`
- `allocated_total == sum(leg.allocated)`
- No charge appears in more than one leg per run
- `leg.allocated <= leg.net` (no over-allocation)
- `leg.net == leg.gross - leg.fee - leg.refund`

### 2.8 ReconciliationException

An unresolved discrepancy requiring human attention.

| Attribute | Type | Constraints |
|---|---|---|
| `exception_id` | UUID | PK |
| `run_id` | UUID | FK → ReconciliationRun, not null |
| `tenant_id` | UUID | FK → Tenant, not null (denormalized for RLS) |
| `exception_code` | str | non-empty I-code |
| `severity` | ExceptionSeverity enum | CRITICAL, HIGH, MEDIUM, LOW |
| `status` | ExceptionStatus enum | see §4 |
| `title` | str | non-empty |
| `description` | str | non-empty |
| `evidence_refs` | JSON (list of str) | source record identifiers |
| `assigned_to` | UUID | nullable |
| `created_at` | datetime (tz-aware, UTC) | not null |
| `updated_at` | datetime (tz-aware, UTC) | not null |

**ExceptionSeverity**: `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`

**ExceptionStatus**: `OPEN`, `INVESTIGATING`, `UNDER_REVIEW`, `RESOLVED`, `REOPENED`

### 2.9 ExceptionDecision

Append-only record of a human decision on an exception.

| Attribute | Type | Constraints |
|---|---|---|
| `decision_id` | UUID | PK |
| `exception_id` | UUID | FK → ReconciliationException, not null |
| `tenant_id` | UUID | FK → Tenant, not null (denormalized for RLS) |
| `actor_id` | UUID | not null |
| `decision_type` | DecisionType enum | APPROVE, REJECT, REOPEN, ASSIGN |
| `reason` | str | non-empty |
| `evidence_refs` | JSON (list of str) | nullable |
| `previous_status` | ExceptionStatus enum | not null |
| `new_status` | ExceptionStatus enum | not null |
| `decided_at` | datetime (tz-aware, UTC) | not null |

**DecisionType**: `APPROVE`, `REJECT`, `REOPEN`, `ASSIGN`

**Constraint**: Append-only. No UPDATE or DELETE permitted (enforced via DB trigger or application-level).

### 2.10 Investigation

AI investigation of an exception.

| Attribute | Type | Constraints |
|---|---|---|
| `investigation_id` | UUID | PK |
| `exception_id` | UUID | FK → ReconciliationException, not null |
| `tenant_id` | UUID | FK → Tenant, not null (denormalized for RLS) |
| `status` | InvestigationStatus enum | see §4 |
| `provider` | str | nullable (e.g., "groq", "openrouter") |
| `model` | str | nullable |
| `prompt_fingerprint` | str | sha256 hex (64 chars), nullable |
| `result_text` | str | nullable (AI-generated explanation) |
| `evidence_refs` | JSON (list of str) | source records cited |
| `error_code` | str | nullable (provider error) |
| `started_at` | datetime (tz-aware, UTC) | nullable |
| `completed_at` | datetime (tz-aware, UTC) | nullable |
| `created_at` | datetime (tz-aware, UTC) | not null |
| `created_by` | UUID | not null |

**InvestigationStatus**: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`

### 2.11 AuditEvent

Immutable record of state transitions and significant actions.

| Attribute | Type | Constraints |
|---|---|---|
| `event_id` | UUID | PK |
| `tenant_id` | UUID | FK → Tenant, not null |
| `entity_type` | str | non-empty (e.g., "ReconciliationRun", "Exception") |
| `entity_id` | UUID | not null |
| `action` | str | non-empty (e.g., "created", "status_changed", "decision_recorded") |
| `actor_id` | UUID | nullable (system actions have null) |
| `previous_state` | str | nullable |
| `new_state` | str | nullable |
| `metadata` | JSON | nullable (additional context, no PII) |
| `correlation_id` | UUID | nullable |
| `created_at` | datetime (tz-aware, UTC) | not null |

**Constraint**: Append-only. No UPDATE or DELETE.

### 2.12 ExportArtifact

Generated report from a reconciliation run.

| Attribute | Type | Constraints |
|---|---|---|
| `export_id` | UUID | PK |
| `run_id` | UUID | FK → ReconciliationRun, not null |
| `tenant_id` | UUID | FK → Tenant, not null (denormalized for RLS) |
| `status` | ExportStatus enum | see §4 |
| `format` | ExportFormat enum | CSV, JSON, MARKDOWN |
| `storage_ref` | str | nullable (S3 key or local path) |
| `file_size_bytes` | int | nullable |
| `created_at` | datetime (tz-aware, UTC) | not null |
| `completed_at` | datetime (tz-aware, UTC) | nullable |
| `created_by` | UUID | not null |
| `error_code` | str | nullable |

**ExportStatus**: `PENDING`, `GENERATING`, `COMPLETED`, `FAILED`

**ExportFormat**: `CSV`, `JSON`, `MARKDOWN`

---

## 3. Public Service Interfaces

### 3.0 Source Adapter Interface (NEW)

```python
class SourceAdapter(Protocol):
    \"\"\"Common interface for all source adapters (CSV, Google Sheets, etc.).

    Adapters parse raw source data into canonical records. They do NOT
    validate or persist — that is the ingestion service's responsibility.
    \"\"\"

    def parse(self, raw: bytes | str, *, encoding: str = "utf-8") -> list[dict[str, Any]]:
        \"\"\"Parse raw source data into a list of row dicts.\"\"\"

    def headers(self, raw: bytes | str, *, encoding: str = "utf-8") -> list[str]:
        \"\"\"Return the header row of the source.\"\"\"

    def source_type(self) -> SourceType:
        \"\"\"Return the source type this adapter handles.\"\"\"

    def supported_formats(self) -> list[str]:
        \"\"\"Return supported file extensions (e.g., ['.csv']).\"\"\"
```

### 3.1 Ingestion Service (source-independent)

```python
def create_import_session(
    tenant_id: UUID,
    actor_id: UUID,
    period_start: date,
    period_end: date,
) -> ImportSession:
    """Create a new import session for a reconciliation period."""

def upload_source_file(
    session_id: UUID,
    source_type: SourceType,
    file: UploadedFile,
    idempotency_key: str,
) -> SourceFile:
    """Upload and store a source file (CSV or any supported format). Idempotent on content hash."""

def validate_import(session_id: UUID) -> ImportValidationResult:
    """Validate all uploaded files. Returns per-row errors."""

def get_import_session(session_id: UUID, tenant_id: UUID) -> ImportSessionDetail:
    """Retrieve session with file and validation status."""
```

### 3.2 Reconciliation Service

```python
def start_reconciliation(
    session_id: UUID,
    tenant_id: UUID,
    actor_id: UUID,
    idempotency_key: str,
) -> ReconciliationRun:
    """Start a reconciliation run. Idempotent on (tenant_id, idempotency_key)."""

def get_reconciliation_run(run_id: UUID, tenant_id: UUID) -> ReconciliationRunDetail:
    """Retrieve run status and summary."""

def get_matches(run_id: UUID, tenant_id: UUID) -> list[ReconciliationMatch]:
    """Retrieve all matches for a run."""

def get_allocations(run_id: UUID, tenant_id: UUID) -> list[PayoutAllocation]:
    """Retrieve all payout allocations for a run."""

def get_exceptions(run_id: UUID, tenant_id: UUID) -> list[ReconciliationException]:
    """Retrieve all exceptions for a run."""
```

### 3.3 Exception Service

```python
def get_exception(exception_id: UUID, tenant_id: UUID) -> ReconciliationException:
    """Retrieve exception detail."""

def start_investigation(exception_id: UUID, tenant_id: UUID, actor_id: UUID) -> Investigation:
    """Start an AI investigation. Returns existing if already running."""

def record_decision(
    exception_id: UUID,
    tenant_id: UUID,
    actor_id: UUID,
    decision_type: DecisionType,
    reason: str,
    evidence_refs: list[str] | None = None,
) -> ExceptionDecision:
    """Record a human decision. Validates state transition."""
```

### 3.4 Export Service

```python
def create_export(run_id: UUID, tenant_id: UUID, actor_id: UUID, format: ExportFormat) -> ExportArtifact:
    """Generate an export artifact."""

def get_export(export_id: UUID, tenant_id: UUID) -> ExportArtifact:
    """Retrieve export status and download reference."""
```

---

## 4. Financial Invariants (Non-Negotiable)

These are enforced by the reconciliation engine (`finance/reconciliation/`) and must never be violated by the application layer:

1. **Allocation conservation**: `allocated + open == eligible net`; `allocated + unallocated == deposit`
2. **No double allocation**: a charge appears in at most one leg per run
3. **Decimal-only money**: no float on any path or in any output
4. **No false settlement**: settled ⇒ zero residual + fully credited legs
5. **Determinism**: same inputs ⇒ same result + fingerprint
6. **Provenance**: every leg and evidence line resolves to an input record
7. **Currency isolation**: no cross-currency matching
8. **Tenant isolation**: no cross-tenant data access
9. **Refund conservation**: refunds reported separately, never increase settled value
10. **No autonomous postings**: FinSight never writes to a ledger or moves money

---

## 5. Data Types

### Money

All monetary values use `decimal.Decimal`. The `MoneyDecimal` type alias (`apps/api/schemas.py`) rejects floats at the Pydantic boundary. Database columns use `NUMERIC(19, 4)` or equivalent.

### Timestamps

All timestamps are tz-aware UTC (`datetime` with `tzinfo`). Naive datetimes are rejected.

### Identifiers

All entity identifiers are UUID v4. Source record identifiers (invoice_id, charge_id, deposit_id) are strings from the source system.

### Fingerprints

SHA-256 hex digest (64 lowercase hex characters). Used for run input fingerprinting and evidence provenance.

### Currency

ISO 4217 three-letter uppercase code (e.g., "USD", "EUR"). Validated by regex `[A-Z]{3}`.