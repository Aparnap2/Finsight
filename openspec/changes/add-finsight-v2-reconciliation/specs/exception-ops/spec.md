## ADDED Requirements

### Requirement: Spec Conformance Keywords
The whole FinSight v2 spec SHALL use RFC 2119 conformance keywords with the following legend:

- **MUST / MUST NOT**: absolute requirement. A non-conformant implementation is in violation of the spec.
- **SHOULD / SHOULD NOT**: strong recommendation. Valid only with documented justification and compensating control when not followed.
- **MAY**: optional permission. Implementations MAY choose to include or omit the behavior without violating conformance.

#### Scenario: Unambiguous conformance interpretation
- **WHEN** a requirement uses MUST, SHOULD, or MAY
- **THEN** conformance is evaluated per the legend above and no runtime code is implied by the wording alone

### Requirement: Exception Aggregate as Single Orchestration Boundary
The system MUST represent every actionable reconciliation break as one Exception Aggregate with exactly these fields: `exception_id`, `tenant_id`, `reconciliation_result_id`, `exception_type`, `severity`, `state`, `state_version`, `evidence_ids[]`, `proposal_id`, `approval_id`, `execution_id`, `created_at` / `updated_at`.

- The system MUST restrict `exception_type` to the 3 frozen codes. No ad-hoc fourth code.
- The system MUST restrict `state` to the SM-1 enum only, including `EVIDENCE_VERIFIED` (pre-proposal) and `EXECUTION_VERIFIED` (post-execution). No aggregate state outside SM-1.
- The system MUST treat the aggregate as the single orchestration boundary: all proposal, approval, and execution references for one break MUST hang off the aggregate's `proposal_id` / `approval_id` / `execution_id` slots. No orphan proposal, approval, or execution.
- The system MUST mutate `state` only via code-owned transitions that take an `expected_state_version` and advance `state_version` by exactly one on success. Direct field writes, out-of-band status edits, and UI-driven state patches MUST be rejected.
- The system SHOULD keep `evidence_ids[]` append-only after `EVIDENCE_VERIFIED`; it MAY allow `severity` re-derivation without a version bump only if severity is explicitly classified as non-state metadata.

#### Scenario: Aggregate created once per break and mutated only via transitions
- **WHEN** a reconciliation result yields an actionable break for a tenant
- **THEN** the system creates exactly one aggregate linking that `reconciliation_result_id`, with `state_version` initialized, `evidence_ids[]` populated from verified evidence, and empty `proposal_id` / `approval_id` / `execution_id` until each phase completes

#### Scenario: Bypass write rejected
- **WHEN** any caller attempts to set `state` directly without going through a code-owned transition with `expected_state_version`
- **THEN** the write is rejected, the aggregate is unmutated, and the rejection is audited with caller identity, attempted state, and timestamp

### Requirement: Optimistic Concurrency on Every Transition
Every state transition MUST take `expected_state_version`. The system MUST compare it against current `state_version` before any mutation.

- The system MUST reject a stale-version attempt: no mutation to `state`, `state_version`, `proposal_id`, `approval_id`, or `execution_id`, plus a mandatory audit record (actor, attempted transition, expected vs. actual version, timestamp).
- The system MUST guarantee `state_version` is a monotonic integer incremented only on successful transition — never on rejection, never decremented, never reset.
- The system SHOULD surface the current `state_version` on every read so callers can retry with a fresh version; it MAY expose a contention counter but MUST NOT auto-merge concurrent writes.

#### Scenario: Concurrent approve and reject — one wins, one rejected
- **WHEN** two reviewers concurrently submit approve and reject against the same `expected_state_version`
- **THEN** exactly one transition succeeds and bumps `state_version` by one, while the second is REJECTED with an audit record and zero mutation, even if its business logic was otherwise valid

#### Scenario: Double-approve fails stale
- **WHEN** a second approve arrives with the now-stale version after a first approve succeeded
- **THEN** the second approve is REJECTED + audited with no mutation

### Requirement: Single Terminal Approval Decision Per Proposal Version
The system MUST admit at most one terminal approval decision per immutable proposal version identified by `proposal_id + version + content_hash`. A second terminal decision on the same proposal version MUST be rejected, MUST create no Execution, and MUST emit an audit event. At most one Execution MUST ever be created from one approved proposal version.

#### Scenario: Second terminal decision on same version rejected
- **WHEN** a proposal version already has a recorded terminal decision and a second terminal decision is submitted for the same `proposal_id + version + content_hash`
- **THEN** the system REJECTS the second decision, retains the first decision unchanged, creates no Execution, and emits an audit event with proposal identity, both decisions, and reason

#### Scenario: Approved version executes at most once
- **WHEN** an approved proposal version has already produced an Execution
- **THEN** the system MUST NOT create a second Execution from the same approval and MUST route any repeat request to the existing Execution record

### Requirement: Approval Pinning to Proposal Version and Content Hash
Every approval MUST bind the triple (`proposal_id`, proposal `version`, proposal `content_hash`) at approval time. An approval without all three bound MUST be invalid.

- Proposal mutation MUST bump proposal `version`, recompute `content_hash`, and invalidate all prior approvals pinned to older versions. Invalidated approvals MUST NOT be resurrected — a new approval is required.
- The system MUST refuse execution when the presented approval's pinned triple does not exactly match the aggregate's current `proposal_id` / version / hash.
- The system SHOULD retain invalidated approvals as auditable history; it MAY notify the original approver on invalidation but MUST NOT auto-re-approve.

#### Scenario: Proposal edit invalidates prior approval
- **WHEN** an approved proposal is mutated (amount, account, memo, or any hashed field changes)
- **THEN** the proposal version bumps, the content hash changes, the prior approval is marked invalidated, and the aggregate remains unexecuted until a new approval pins the new triple

#### Scenario: Stale pinned approval cannot execute
- **WHEN** execution is requested with an approval pinned to v1 / hash-A while the current proposal is v2 / hash-B
- **THEN** execution is rejected before any adapter call, the aggregate is unmutated, and the rejection is audited with both triples recorded

### Requirement: Execution Idempotency and Crash Replay Safety
Every execution MUST carry a caller-supplied idempotency key stored on the aggregate's execution slot. A repeated execution request with an already-seen key and byte-identical payload MUST NOT create a second correcting entry and MUST return the original execution outcome.

- The system MUST make Execution replay-safe after a crash where the sandbox write succeeded but the response was lost: a retry presenting the same `idempotency_key` with byte-identical payload for the same pinned (`proposal_id`, `version`) MUST return the prior Execution with its original `execution_id` and `result`, and MUST NOT perform a second financial action.
- A retry reusing a known `idempotency_key` with a differing payload MUST be REJECTED with an `IDEMPOTENCY_CONFLICT` error, MUST perform no write, and MUST emit an audit event.

#### Scenario: Retry after lost success response returns prior Execution
- **WHEN** the sandbox write succeeded, the response was lost due to crash, and the caller retries with the same `idempotency_key` and byte-identical payload
- **THEN** the system returns the prior Execution record with no additional side effect and records the retry as a replay in audit

#### Scenario: Differing payload on known key rejected
- **WHEN** a retry reuses a known `idempotency_key` with a differing payload
- **THEN** the system REJECTS the request, performs no write, and emits an audit event

### Requirement: Success-But-Unverified Never Closes
The system MUST NOT transition to `CLOSED` on an adapter success response alone. Adapter `result SUCCEEDED` MUST only advance `EXECUTING → POST_VERIFYING`, and `CLOSED` MUST require an independent verifier passing record (`POST_VERIFYING → EXECUTION_VERIFIED → CLOSED`). If post-verification still shows a mismatch after the sandbox write, the system MUST move to `FAILED` and then `ESCALATED`, never to `CLOSED`.

#### Scenario: Adapter success with post-verify mismatch escalates
- **WHEN** the sandbox adapter returns success yet independent post-verification re-reconciliation still shows a mismatch
- **THEN** the system transitions `POST_VERIFYING → FAILED → ESCALATED`, records the verification failure with expected versus observed evidence, and emits an audit event

#### Scenario: Direct close on adapter success rejected
- **WHEN** any caller attempts `EXECUTING → CLOSED` or treats adapter success as terminal verification without a passing independent verifier record
- **THEN** the system REJECTS the transition, retains the non-closed state, and emits an audit event

### Requirement: Atomic Compare-and-Swap Persistence for Transitions
The system MUST enforce `expected_state_version` atomically in persistence, not merely validated in Python before a repository update. Conceptually:

```sql
UPDATE exceptions SET state = :new_state, state_version = state_version + 1
WHERE id = :id AND state_version = :expected_version AND state = :expected_state;
```

If affected rows = 0, the system MUST return `CONCURRENCY_CONFLICT`: no mutation, plus an audit record. A read-then-check-then-write sequence without an atomic version guard MUST NOT satisfy this requirement.

#### Scenario: Concurrent writers — one CAS wins
- **WHEN** two writers race transitions from the same `expected_state_version`
- **THEN** exactly one `UPDATE` affects a row and advances the version; the other affects zero rows, receives `CONCURRENCY_CONFLICT`, mutates nothing, and emits an audit event

### Requirement: Mock QuickBooks AccountingAdapter Interface Contract — Sandbox Only
The system MUST expose sandbox financial actions only through the `AccountingAdapter` interface contract. P3 defines the contract only: no live QuickBooks implementation, no network calls, no real credentials in P3.

- The contract MUST declare three operations: create-correcting-entry, retrieve-entry, and void-entry, each accepting an idempotency key and a tenant-scoped context. Signatures, error taxonomy, and idempotency semantics are part of the contract; behavior is satisfied in P3 only by a mock/sandbox fake.
- The contract MUST define three failure modes with deterministic handling: validation failure (non-retryable, surfaces to proposal phase for correction), transient 5xx (retryable under bounded policy, never auto-close), and delayed visibility (read-after-write may miss the entry, so post-verify MUST re-read before verdict).
- All adapter use in P3 MUST be sandbox-only: the mock MUST be injectable, MUST NOT touch production books, and MUST log every call with idempotency key and outcome for audit replay.
- The system SHOULD require the mock to simulate all three failure modes on demand for tests; it MAY add latency injection but MUST keep P3 deterministic (seeded script, no randomness in verdicts).
- No LLM in P3: proposal drafting, approval decisions, and verify verdicts MUST be rule-based and replayable. This delta MUST NOT weaken I1–I10, MUST NOT add states to SM-1/SM-2/SM-3, and MUST NOT bypass `EVIDENCE_VERIFIED` before proposal or `EXECUTION_VERIFIED` before close.

#### Scenario: Validation failure blocks execution without state advance
- **WHEN** create-correcting-entry is invoked with an invalid account, unbalanced amount, or malformed payload
- **THEN** the adapter returns a validation-failure outcome, no entry is recorded, the aggregate does not advance toward `EXECUTION_VERIFIED`, and the failure is attached as evidence for proposal correction

#### Scenario: Transient 5xx then delayed visibility still requires post-verify
- **WHEN** the adapter first returns a transient 5xx and then success, but an immediate retrieve does not yet show the entry
- **THEN** the retry uses the same idempotency key without duplicating the entry, and the aggregate MUST NOT close until a subsequent re-read confirms the entry
