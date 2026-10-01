## ADDED Requirements

### Requirement: Legacy Isolation as a Separate Trust Zone

The legacy financial system SHALL be treated as a separate trust and integration zone behind a controlled file/batch boundary. It SHALL NOT be accessed via HTTP or internet-facing APIs. The modern system SHALL communicate with it only through files/batches; any direct REST-style call to the legacy system MUST be rejected by design and by test.

#### Scenario: Legacy access is file/batch only

- **WHEN** the modern system needs to action a legacy-accounted break
- **THEN** the interaction is represented as a fixed-width batch file governed by batch_id, sequence, and control total, not as an HTTP request

### Requirement: Fixed-Width Batch Protocol

The system SHALL define a minimal fixed-width batch protocol with `batch_id`, sequence number, per-record legacy account code, per-record amount (Decimal-as-string), `record_count`, and `control_total` (sum of record amounts). Duplicate `batch_id` MUST be detected and rejected upon resubmission; a stale or replayed result file MUST be detected via `batch_id` + sequence.

#### Scenario: Duplicate batch is detected

- **WHEN** the same `batch_id` batch file is submitted twice
- **THEN** the second submission is rejected as a duplicate and causes no additional legacy action, with an audit record

#### Scenario: Control total mismatch is rejected

- **WHEN** a batch `control_total` does not equal the sum of its record amounts
- **THEN** the batch is rejected prior to processing and no record is applied

### Requirement: Batch Result Lifecycle

The system SHALL model the legacy result lifecycle as `accepted` vs `rejected` per record, with batch-level outcomes `partial batch` (mixed accepted/rejected), `sequence mismatch`, `late result`, `ambiguous processing state`, and `malformed record`. `partial batch` MUST expose accepted vs rejected sets explicitly; malformed records MUST be per-record `REJECTED`, not batch-fail; late or replayed results MUST be detected before idempotent application.

#### Scenario: Partial batch is represented correctly

- **WHEN** a batch contains records that partially pass legacy validation
- **THEN** the result distinguishes accepted records from rejected records, and only the accepted set is eligible for downstream verification

### Requirement: Legacy Result Verification Before Closure

The system SHALL require legacy result verification before closure for any legacy-routed execution. Verification MUST re-read the authoritative legacy result (result file or computed expected), re-reconcile expected vs actual, and only then gate `CLOSED`; mismatch or ambiguous state MUST map to `FAILED`/`ESCALATED` or `UNKNOWN` awaiting reconciliation, never silent `CLOSED`.

#### Scenario: Unverified legacy result cannot close

- **WHEN** a legacy execution completes and its result file has not passed deterministic verification (accepted-status, sequence, control-total, expected-vs-actual)
- **THEN** the aggregate is not marked CLOSED and the verification failure is audited
