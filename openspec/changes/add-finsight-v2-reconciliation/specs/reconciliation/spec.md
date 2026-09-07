## ADDED Requirements

### Requirement: Spec Conformance Keywords
The whole FinSight v2 spec SHALL use RFC 2119 conformance keywords with the following legend:

- **MUST / MUST NOT**: absolute requirement. A non-conformant implementation is in violation of the spec.
- **SHOULD / SHOULD NOT**: strong recommendation. Valid only with documented justification and compensating control when not followed.
- **MAY**: optional permission. Implementations MAY choose to include or omit the behavior without violating conformance.

#### Scenario: Unambiguous conformance interpretation
- **WHEN** a requirement uses MUST, SHOULD, or MAY
- **THEN** conformance is evaluated per the legend above and no runtime code is implied by the wording alone

### Requirement: Authority Matrix — Decision Rights and Execution Boundaries
The system MUST enforce the following authority matrix. No actor SHALL exceed its listed rights. The LLM synthesizes proposals but MUST never have authority over state transitions, approvals, or execution.

| Actor | Read | Classify | Propose | Approve | Execute |
|---|---|---|---|---|---|
| Deterministic core | Yes | Yes | Rule-based | No | Guarded |
| LLM investigator | Evidence only | Recommend | Yes | No | No |
| Human | Yes | Override where policy allows | Request changes | Yes | Yes indirectly |
| Executor | Required context only | No | No | Approval already required | Sandbox only |

#### Scenario: LLM direct-execute rejected
- **WHEN** the LLM investigator attempts a direct state transition, approval grant, or Executor invocation without a recorded human approval
- **THEN** the system MUST reject the action, MUST NOT change state, and MUST record an `authority_denied` event with actor, attempted action, and reason

#### Scenario: Human override allowed per policy
- **WHEN** a human with override permission overrides a deterministic or LLM-recommended classification where policy allows overrides
- **THEN** the system MUST accept the override, MUST record prior value, new value, actor identity, policy basis, and rationale, and MUST require re-validation before downstream approval

#### Scenario: Human override blocked per policy
- **WHEN** a human attempts an override in a policy domain that forbids overrides (e.g., locked close period, segregation-of-duties violation)
- **THEN** the system MUST block the override, MUST NOT change classification or state, and MUST return a policy-denial with the controlling rule identifier

### Requirement: PaymentRecord
The system SHALL normalize every provider payment event into a `PaymentRecord` with `payment_id`, `provider`, `provider_event_id`, `idempotency_key`, `gross`, `fee`, `refund`, `net`, `currency`, `status`, `occurred_at`, `tenant_id`, and `source_reference`.

- The system MUST type `gross`, `fee`, `refund`, and `net` as `MoneyDecimal` (Decimal-only) and MUST reject `float` input at the validation boundary.
- The system MUST require a non-empty `idempotency_key` and MUST enforce `net == gross - fee - refund` in Decimal arithmetic; violations SHALL be rejected.
- The system MUST validate `currency` as ISO 4217 and `status` against the enum.
- The system MUST require `occurred_at` to be tz-aware, and SHOULD normalize it to UTC on ingest.
- The system MUST require `tenant_id`, `payment_id`, `provider`, and `provider_event_id` to be non-empty strings.
- The system MAY accept an opaque `source_reference`; when absent the system SHALL store null without failing validation.

#### Scenario: Valid normalize
- **WHEN** a provider event arrives with Decimal amounts `gross="100.00"`, `fee="2.50"`, `refund="0.00"`, `net="97.50"`, currency `USD`, and a present `idempotency_key`
- **THEN** the system accepts the record, normalizes `occurred_at` to UTC, and preserves Decimal precision on all money fields

#### Scenario: Float rejected
- **WHEN** a provider event arrives with any money field supplied as a JSON float
- **THEN** the system rejects the record with a Decimal-only validation error and creates no `PaymentRecord`

### Requirement: ReconciliationResult
The system SHALL compute a `ReconciliationResult` from an expected leg and an observed `PaymentRecord` leg with `outcome`, `expected`, `observed`, `difference`, `variance`, `tolerance_applied`, `exception_code`, `fingerprint`, and `materiality_verdict`.

- The system MUST be pure and deterministic with no LLM involvement; identical inputs SHALL always produce identical outputs.
- The system MUST inject `tolerance_applied` per tenant at call time and MUST never hardcode tolerance values.
- The system MUST type `difference`, `variance`, and `tolerance_applied` as `MoneyDecimal`, with `difference == observed.net - expected.net` in Decimal arithmetic.
- The system SHALL set `outcome` to exactly one of `MATCHED | TOLERANCE_MATCHED | EXCEPTION | PENDING_EVIDENCE`.
- The system SHALL set `exception_code` to an `I-code` whenever `outcome` is `EXCEPTION`, and null otherwise.
- The system SHALL set `fingerprint` to the sha256 hash of the canonical expected-plus-observed pair.
- The system SHOULD derive `materiality_verdict` from tenant materiality thresholds.

#### Scenario: Exact match close
- **WHEN** expected and observed legs agree exactly (`difference == 0`, same currency, tolerance injected)
- **THEN** the system returns `outcome MATCHED` with zero `difference`, null `exception_code`, and a stable sha256 `fingerprint`

#### Scenario: Tolerance-boundary
- **WHEN** `abs(difference)` equals the injected tenant tolerance and a second case exceeds it
- **THEN** the boundary case returns `TOLERANCE_MATCHED` with no exception and the excess case returns `EXCEPTION` with an amount-mismatch I-code

### Requirement: Evidence Bundle Is Immutable Append-Only With Normalized References
The system MUST create an immutable, append-only Evidence bundle per retrieval with `evidence_id`, `exception_fingerprint`, `source_type`, `source_id`, `retrieved_at`, `content_hash`, `tool_result_fingerprint`, `data`, `row_count`, `coverage`, `quality`, `required_filters_present`, and `insufficient_data`.

- The system MUST store normalized references and MUST NOT embed inline blobs.
- The system MUST coerce monetary values in `data` to string form and MUST preserve `row_count`, `coverage`, and `quality`.
- The system MUST set `required_filters_present` and `insufficient_data` explicitly.
- The system SHOULD enforce a quality floor from tenant config without mutating stored bundles.
- The system MAY attach additional diagnostic metadata provided it does not alter identity fields.

#### Scenario: Append-only verified evidence
- **WHEN** a tool result is ingested for an `exception_fingerprint`
- **THEN** the system appends a new Evidence bundle with a fresh `evidence_id` and computed hashes and never updates or deletes a prior bundle

#### Scenario: Insufficient evidence flagged
- **WHEN** required filters are absent or coverage is below threshold
- **THEN** the system marks the bundle `required_filters_present False` and `insufficient_data True`

### Requirement: ResolutionProposal Authorizes Nothing and Is Distinct From Execution
The system MUST model `ResolutionProposal` as distinct from Execution with `proposal_id`, `exception_fingerprint`, `version`, `action`, `amount` as `MoneyDecimal`, `rationale`, `evidence_ids[]`, `proposed_by`, `proposed_at`, `expires_at`, and `requires_hitl True`.

- The system MUST recompute `amount` deterministically and MUST never accept `amount` from LLM output.
- The system MUST require all `evidence_ids[]` to resolve to `EVIDENCE_VERIFIED` Evidence before policy evaluation.
- The system MUST treat a proposal as authorizing nothing: policy plus HITL approval MUST precede any Execution.
- The system SHOULD expire proposals at `expires_at`; an expired proposal MUST NOT become executable without a new `version`.

#### Scenario: Proposal draft requires policy and HITL
- **WHEN** a proposal draft with all-`EVIDENCE_VERIFIED` evidence and deterministically recomputed `amount` is submitted
- **THEN** the system holds it as non-authorizing pending policy decision and HITL approval, and no Execution is created

#### Scenario: LLM-supplied amount rejected
- **WHEN** a proposal draft carries an `amount` sourced from LLM text rather than deterministic recomputation
- **THEN** the system rejects the draft as invalid and requires deterministic recomputation

### Requirement: Execution Is Sandbox-Only, Idempotent, and Pinned to an Approved Proposal Version
The system MUST model Execution with `execution_id`, `idempotency_key` unique per (`proposal_id`, `version`), pinned `proposal_id` plus pinned `version`, `adapter`, `result` of `SUCCEEDED` / `FAILED` / `REJECTED`, `external_reference`, and `post_verify_status`.

- The system MUST operate Execution sandbox-only and MUST be idempotent on `idempotency_key`.
- The system MUST require prior approval for the pinned (`proposal_id`, `version`) before Execution MAY start.
- The system MUST assign `post_verify_status` by an independent verifier, never by the executing adapter.
- The system MAY record `REJECTED` for denied attempts provided no side effect occurred.

#### Scenario: Idempotent retry
- **WHEN** an Execution with an `idempotency_key` for (`proposal_id`, `version`) is retried with the same key
- **THEN** the system returns the original `execution_id` and `result` with no second side effect

#### Scenario: Verifier-owned post-verification
- **WHEN** an adapter reports completion with an `external_reference`
- **THEN** the system leaves `post_verify_status` unset until the independent verifier sets it

### Requirement: LLM Authority Boundary — Planner and Investigator Only
The system MUST confine the LLM to planner and investigator roles. The agent may synthesize an investigation path and propose an action, but deterministic code MUST own money arithmetic, reconciliation, policy enforcement, state transitions, execution authorization, idempotency, and post-execution verification.

- The system MUST confine the LLM to planner / investigator roles: reads Evidence only, recommends classification, synthesizes proposal drafts.
- The system MUST never allow LLM money arithmetic, reconciliation, policy decisions, state transitions, approvals, execution, idempotency handling, or post-verification.
- The system MUST compute all of the above in deterministic domain code outside the LLM.
- The system SHOULD log any LLM forbidden-operation attempt as a boundary violation without acting on it.

#### Scenario: LLM draft stays advisory
- **WHEN** the LLM recommends a classification and synthesizes a proposal draft from `EVIDENCE_VERIFIED` Evidence
- **THEN** the system treats the output as advisory only, recomputes `amount` deterministically, and routes the draft through policy and HITL before any Execution

#### Scenario: Forbidden LLM operation blocked
- **WHEN** LLM output attempts a forbidden operation
- **THEN** the system rejects the operation, preserves invariants, and records a boundary violation

### Requirement: I1 — Decimal-Only Monetary Values
The system MUST represent, compute, and persist all monetary values as `decimal.Decimal`. The system MUST reject `float` monetary inputs at every trust boundary.

#### Scenario: Decimal monetary path accepted
- **WHEN** a monetary amount enters as `Decimal` or `Decimal`-parseable string
- **THEN** the system normalizes it to `Decimal` and processes it without loss

#### Scenario: Float monetary input rejected
- **WHEN** a monetary amount arrives as `float`
- **THEN** the system REJECTS the payload with a validation error, performs no state transition, and emits an audit event

### Requirement: I2 — Deterministic Reconciliation
The reconciliation engine MUST be a pure deterministic function: the same normalized inputs MUST always produce the same result. Reconciliation MUST NOT call LLMs, network, databases, clocks, or randomness.

#### Scenario: Same inputs yield identical outputs
- **WHEN** reconciliation runs twice on byte-identical normalized inputs in separate processes
- **THEN** both runs return byte-identical outputs including match decisions, variances, and hashes

#### Scenario: Side-effecting reconciliation rejected
- **WHEN** a reconciliation path attempts an LLM call, network fetch, DB query, wall-clock read, or randomness
- **THEN** the run is REJECTED, no verdict is emitted, and an audit event records the violation

### Requirement: I3 — Raw Evidence Immutable
The system MUST treat ingested raw evidence as immutable and MUST NOT support update, overwrite, or delete of raw evidence.

#### Scenario: Raw evidence preserved with hash lineage
- **WHEN** raw evidence is ingested
- **THEN** the system stores immutable bytes, assigns a content hash and immutable evidence ID, and references that ID/hash downstream

#### Scenario: Raw evidence mutation rejected
- **WHEN** any caller attempts to update, overwrite, or delete raw evidence
- **THEN** the system REJECTS the operation and emits an audit event

### Requirement: I4 — LLM Cannot Execute Writes
The LLM MUST be advisory-only. The LLM MUST NOT execute writes, invoke execution tools, transition case state, approve proposals, or bypass the control plane.

#### Scenario: LLM output treated as draft rationale only
- **WHEN** the LLM returns analysis or a recommended action
- **THEN** the system stores it as non-authoritative commentary and requires code-owned verification, proposal, approval, and execution steps before any effect

#### Scenario: LLM-initiated write rejected
- **WHEN** an LLM output attempts a write, state transition, approval, or execution
- **THEN** the system REJECTS the action, performs no mutation, and emits an audit event

### Requirement: I5 — Every Proposal Has Verified Evidence
The system MUST require every proposal to cite at least one evidence record in `EVIDENCE_VERIFIED` state.

#### Scenario: Proposal with verified evidence accepted for review
- **WHEN** a proposal is submitted citing currently-`EVIDENCE_VERIFIED` evidence with matching hash
- **THEN** the system admits it to `PROPOSED` and records the evidence-to-proposal linkage

#### Scenario: Proposal without verified evidence rejected
- **WHEN** a proposal cites zero, unverified, unknown, or hash-mismatched evidence
- **THEN** the system REJECTS the proposal and emits an audit event

### Requirement: I6 — Approval Bound to Immutable Proposal Version
Approval MUST bind to one immutable proposal version identified by content hash. Each proposal version MUST admit at most one terminal approval decision.

#### Scenario: Approval locks exact proposal hash once
- **WHEN** an approver approves the current frozen proposal version
- **THEN** the system records `APPROVED` bound to `proposal_id + version + content_hash` and rejects any second decision on that version

#### Scenario: Stale-hash or double-decision approval rejected
- **WHEN** an approval references a superseded hash or an already-decided version
- **THEN** the system REJECTS the approval and emits an audit event

### Requirement: I7 — Idempotent Execution
Execution MUST be idempotent on an explicit idempotency key. Same key with byte-identical payload MUST return the prior result without re-executing. Same key with differing payload MUST be REJECTED.

#### Scenario: Retry with identical payload returns prior result
- **WHEN** an execution request repeats a known idempotency key with byte-identical payload
- **THEN** the system returns the original execution record with no duplicate side effects

#### Scenario: Key reuse with differing payload rejected
- **WHEN** an execution request reuses a known idempotency key with a different payload
- **THEN** the system REJECTS the request with an `IDEMPOTENCY_CONFLICT` error and emits an audit event

### Requirement: I8 — Explicit Sandbox Boundary
Every execution request and record MUST carry an explicit environment label. For MVP the system MUST operate sandbox-only and MUST disable real execution targets.

#### Scenario: Sandbox execution explicitly labeled
- **WHEN** an approved proposal executes in MVP
- **THEN** the system requires `environment=sandbox`, records it, and routes only to sandbox adapters

#### Scenario: Real-target execution rejected
- **WHEN** a request specifies `environment=real`, omits environment, or targets a real ledger
- **THEN** the system REJECTS the execution and emits an audit event

### Requirement: I9 — Mandatory Post-Execution Re-Verification
Every executed action MUST pass post-execution re-verification. `EXECUTING` MUST transition only to `POST_VERIFYING` or `FAILED`. `CLOSED` MUST be reachable from the execution path only via `POST_VERIFYING → EXECUTION_VERIFIED → CLOSED`.

#### Scenario: Executed action completes via post-verification
- **WHEN** execution finishes
- **THEN** the system transitions `EXECUTING → POST_VERIFYING`, re-verifies, and only on success transitions to `EXECUTION_VERIFIED → CLOSED`

#### Scenario: Skip-post-verification close rejected
- **WHEN** any caller attempts `EXECUTING → CLOSED` or `POST_VERIFYING → CLOSED` without a passing record
- **THEN** the system REJECTS the transition and emits an audit event

### Requirement: I10 — No Close Without Valid Terminal Verification
The system MUST allow `CLOSED` only with a valid, non-expired terminal verification record bound to the current version.

#### Scenario: Close with valid terminal verification
- **WHEN** a case presents a passing terminal verification bound to the current version
- **THEN** the system allows transition to `CLOSED` and records the verification ID/hash

#### Scenario: Close without valid verification rejected
- **WHEN** close is requested with missing, failed, expired, superseded, or version-mismatched verification
- **THEN** the system REJECTS the close and emits an audit event

### Requirement: SM-1 — Allowed State-Machine Transitions
The case lifecycle MUST follow only the transitions in the table below. Any transition not listed MUST be rejected.

| From | To | Meaning |
|---|---|---|
| `RECEIVED` | `NORMALIZED` | ingest normalized |
| `NORMALIZED` | `RECONCILING` | reconciliation started |
| `RECONCILING` | `MATCHED` | deterministic match |
| `MATCHED` | `CLOSED` | clean close, verification on file |
| `RECONCILING` | `EXCEPTION` | mismatch requiring investigation |
| `EXCEPTION` | `INVESTIGATING` | investigation opened |
| `INVESTIGATING` | `EVIDENCE_READY` | evidence gathered |
| `EVIDENCE_READY` | `EVIDENCE_VERIFIED` | evidence verified |
| `EVIDENCE_VERIFIED` | `PROPOSED` | proposal drafted |
| `PROPOSED` | `AWAITING_APPROVAL` | proposal submitted |
| `AWAITING_APPROVAL` | `APPROVED` | approval granted |
| `AWAITING_APPROVAL` | `REJECTED` | approval denied |
| `APPROVED` | `EXECUTING` | sandbox execution started |
| `EXECUTING` | `POST_VERIFYING` | re-verification required |
| `EXECUTING` | `FAILED` | execution failure |
| `POST_VERIFYING` | `EXECUTION_VERIFIED` | post-verification passed |
| `POST_VERIFYING` | `FAILED` | post-verification failed |
| `EXECUTION_VERIFIED` | `CLOSED` | verified close |
| `REJECTED` | `CLOSED` | terminal close after rejection |
| `FAILED` | `ESCALATED` | terminal escalation |

#### Scenario: Legal transition accepted and logged
- **WHEN** code requests a listed transition from the current state with all preconditions met
- **THEN** the system applies the transition once, persists prior/next state, and emits an audit event

#### Scenario: Unlisted transition rejected
- **WHEN** any caller requests a from/to pair not in the table
- **THEN** the system REJECTS the transition and emits an audit event

### Requirement: SM-2 — Banned Transitions Rejected With Audit
The system MUST reject `INVESTIGATING → EXECUTING`, `PROPOSED → EXECUTING`, and `FAILED → CLOSED` in all circumstances.

#### Scenario: Investigating to executing rejected
- **WHEN** a transition from `INVESTIGATING` directly to `EXECUTING` is requested
- **THEN** the system REJECTS it, retains `INVESTIGATING`, and emits an audit event

#### Scenario: Proposed to executing rejected
- **WHEN** a transition from `PROPOSED` directly to `EXECUTING` is requested
- **THEN** the system REJECTS it, retains `PROPOSED`, and emits an audit event

#### Scenario: Failed to closed rejected
- **WHEN** a transition from `FAILED` directly to `CLOSED` is requested
- **THEN** the system REJECTS it, retains `FAILED`, and emits an audit event

### Requirement: SM-3 — Code-Owned Transitions Only
Only versioned control-plane code MUST mutate case state. LLM outputs, human UI actions, and external API calls MUST request transitions through validated code handlers; direct state writes MUST be rejected.

#### Scenario: Validated code transition applied
- **WHEN** a validated code handler authorizes a table-allowed transition with satisfied guards
- **THEN** the system applies exactly one transition and records actor, code version, guards checked, and prior/next state

#### Scenario: Non-code direct state write rejected
- **WHEN** an LLM, human action, or external caller attempts to set state directly or skip guards
- **THEN** the system REJECTS the write and emits an audit event
