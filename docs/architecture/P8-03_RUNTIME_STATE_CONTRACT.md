# P8-03 Runtime State Persistence & Replay Contract

**Status:** FROZEN (merged via PR #66 as `9fad082`; was Gate 1 RED at design time)
**Base SHA:** `84c708e`
**Branch:** `feat/finsight-p8-03-runtime-state-persistence-replay`
**Type:** Contract + RED + GREEN (frozen)
**Scope:** `docs/architecture/P8-03_*.md` + `tests/contract/test_p8_03_*.py` ONLY

## 1. Purpose and non-goals

P8-03 defines durable-state semantics AROUND the frozen P8-01 boundary
(`agents/p8_runtime/contract.py`: `RunIdentity`, budgets, failure taxonomy)
and the frozen P8-02 execution surface (`agents/p8_runtime/execution.py`:
`ExecutionState`, `AttemptIdentity`, `RunRecord`, `execute_run`, `replay`).
P8-03 describes what MUST survive a crash, how recovery reconciles, and how
replay stays read-only. It implements nothing and stores nothing.

Non-goals (hard exclusions): Temporal, Redis, queues/streams, databases,
cloud services, provider SDKs, LangGraph, vector/graph storage, financial
execution, P6/P7 changes, actual persistence implementation.

### I1 — Durability surrounds, never redefines

P8-03 MUST reuse `RunIdentity`, `AttemptIdentity`, `RunRecord`, and
`Provenance` by name with frozen meanings. It MUST NOT redefine `Budget`,
`FailureKind`, `FailureClass`, `RetryPolicy`, `ExecutionState`, lifecycle
transitions, or `replay_run` semantics.

### I2 — No backend, framework, or authority coupling

P8-03 MUST NOT introduce Temporal, Redis, queues/streams, databases, cloud
services, provider SDKs, LangGraph, vector/graph stores, financial
execution, or authority minting. Durability semantics MUST be backend-free.

### I3 — DOC-ONLY Gate 1

Gate 1 MUST NOT add or modify implementation. Only this contract doc and
the RED suite exist. P6, P7, P8-01, and P8-02 stay frozen and untouched.

## 2. Durable run state: persisted allowlist vs forbidden fields

Durable state is the minimal subset of execution state that MUST survive a
crash so recovery can reconcile or seal the run without re-asking the
provider for recorded outcomes.

### I4 — Closed persisted-field allowlist

Durable state SHALL contain ONLY: (a) `RunIdentity` (`run_id`,
`input_fingerprint`); (b) tenant + situation scope fixed at intake (the
durable key, see I19); (c) ordered attempt list with per-attempt
`AttemptIdentity`, `Provenance`, timing (`latency_ms`), `BudgetUsage`
counters, `FailureKind`/`FailureClass` where applicable, and validated
`StructuredModelOutput` summaries where applicable; (d) terminal state
where durably recorded (`SUCCEEDED`/`FAILED`/`EXHAUSTED`); (e) cumulative
budget consumption; (f) integrity seal (see I21); (g) append-only recovery
events (see I24). No other field SHALL be treated as durable.

### I5 — Forbidden persisted fields

Durable state MUST NEVER contain credentials, raw PII bodies, provider
secrets, API keys, live handles (adapters, sockets, cursors), raw prompt
bodies beyond fingerprints, or authority fields (authorization, approval,
execution, settlement, verdict, gate-result). Logging of durable state
MUST scrub secrets and PII.

### I6 — Durable record is observer metadata

The durable record MUST be the persisted projection of the frozen P8-02
`RunRecord` (metadata, never financial fact). It MUST NOT subclass, coerce
to, or mint `AuthoritativeFact`, journal entries, settlements, or P7 result
types.

## 3. State transitions under failure

A crash may strike only non-terminal execution state. Recovery MUST treat
interrupted work as unknown until reconciled against durable state, and
MUST NEVER rewrite a durably recorded terminal outcome.

### I7 — Crash during RUNNING reconciles, never assumes success

A run interrupted in `RUNNING` (or `CREATED` before first durable write)
MUST load as UNKNOWN-then-reconciled: recovery SHALL mark each in-flight
attempt UNKNOWN, verify against durable history and budget, then resume via
the normal P8-02 TRANSIENT path or seal terminal. Recovery MUST NEVER
assume SUCCEEDED, synthesize a validated output, or silently complete.

### I8 — Terminal states immutable once durably recorded

`SUCCEEDED`, `FAILED`, and `EXHAUSTED` MUST have no outgoing transitions
once durably recorded. Recovery MUST NOT rewrite, delete, or re-derive a
recorded terminal state or its recorded outcome.

### I9 — Non-terminal state resumable, never silently completable

Non-terminal durable state MUST be resumable through `execute_run` ordering
(intake fixed scope, per-attempt `check_budget`, provider call, validate,
classify, bounded retry) and MUST NEVER transition directly to a terminal
state without executing (or replaying) the governing path.

## 4. Exactly-once vs at-least-once

Provider invocations and financial effects obey different guarantees, and
P8-03 MUST NOT conflate them.

### I10 — Provider calls are at-least-once across crashes

A provider invocation interrupted by a crash MAY have executed unseen.
Recovery MUST assume the call may have happened and MUST reconcile via
durable attempt history and fresh budget accounting — never by assuming
the call did or did not occur.

### I11 — Financial effects stay exactly-once; recorded attempts never re-invoke

Only P6 executes financial effects; P8 never does, so P8 recovery has no
financial effect to duplicate. Replay after recovery MUST NOT re-invoke
the provider (`ProviderAdapter.complete`) for attempts with recorded
outcomes; it MUST return recorded outcomes with zero new invocations, zero
new attempts, and zero budget consumption.

## 5. Idempotency on RunIdentity

Resubmission after a crash MUST converge on the recorded truth for the
submitted identity, never on a forked duplicate.

### I12 — Recorded identity returns recorded outcome; incomplete resumes

Re-submission of the same `RunIdentity` after a crash MUST return the
recorded outcome when a terminal outcome is durably recorded, or resume
the run from durable state when unrecorded/incomplete. It MUST NEVER fork
a duplicate run under the same identity.

### I13 — Duplicate-run creation under one identity forbidden

Two live executions MUST NEVER exist under one `RunIdentity`. Distinct
`run_id` values MUST never alias; a same-`run_id`/different-fingerprint
identity MUST NOT replay another fingerprint's outcome (frozen P8-02 I19
key rule extends to durable state).

## 6. Attempt history & replay

Full history is durable; replay is a pure read over it.

### I14 — Full attempt history is durable in order

Durable state MUST retain the complete ordered attempt list: gap-free
`attempt_number` per `AttemptIdentity`, per-attempt `Provenance`
(provider, model, version, runtime config, timestamps, `run_id`), timing,
usage, `FailureKind`/`FailureClass`, and validated output where present.

### I15 — Replay reads history only

Replay MUST read durable history only: it SHALL write nothing, invoke
nothing, consume no budget, and mint no financial actions. Replay of an
unrecorded identity MUST return `None` (frozen `replay_run` semantics).

## 7. Recovery protocol (ordered, recorded as provenance)

Recovery is a fixed ordered procedure, itself observable but never counted
as an execution attempt.

### I16 — Ordered recovery steps

Recovery SHALL execute in fixed order: (1) load durable state for the
`RunIdentity`; (2) verify the integrity seal (see I21–I23); (3) reconcile
in-flight attempts — mark UNKNOWN, then retry ONLY via the normal P8-02
TRANSIENT path (`is_retryable`, attempt-cap and `check_budget` accounting
applied to fresh usage); never auto-retry blindly, never retry TERMINAL
kinds; (4) resume execution or seal the terminal state.

### I17 — Recovery is provenance, not an attempt

Recovery events (load, seal-verdict, UNKNOWN markings, resume/seal
decision) MUST be recorded as append-only provenance/audit entries, NOT as
attempts: they SHALL NOT consume `attempt_number` slots, count against the
retry cap, or carry provider `Provenance`.

### I18 — Blind auto-retry forbidden

Recovery MUST NOT re-invoke the provider for an UNKNOWN attempt without
passing the P8-02 gates (TRANSIENT classification, cap remaining, budget
remaining). Budget-interrupted or TERMINAL-kind attempts MUST seal, not
retry.

## 8. Concurrent and repeated invocation

One identity means one serial execution; parallelism MUST NOT duplicate
work or split state.

### I19 — One identity serializes; durable key fixed at intake

Concurrent executions sharing one `RunIdentity` MUST serialize: a second
caller SHALL observe the recorded outcome (recorded) or wait for / observe
the in-progress run (unrecorded) — never start a duplicate. Distinct
identities MUST NEVER share durable state. Tenant + situation scope fixed
at intake is part of the durable key and MUST NOT widen on retry,
fallback, replay, or recovery.

### I20 — Quarantined runs are non-executable

A quarantined run (see I22) MUST refuse `execute_run`, resume, replay-as-
success, and provider invocation until human review clears it. Concurrency
control MUST apply equally to quarantined identities (no duplicate
recovery races).

## 9. State integrity and tamper detection

Durable records carry a backend-free integrity seal; failure quarantines
the run for humans instead of healing it silently.

### I21 — Integrity seal over canonical fields, no new crypto

Each durable record MUST carry an integrity seal: a hash over the
canonical projection of the I4 allowlist fields, computed with a
domain-separated fingerprint in the style of frozen
`compute_input_fingerprint` (canonical JSON, sorted keys, SHA-256 with a
`p8-03-seal` domain separator). The seal MUST introduce NO new crypto
infra, NO key management, and MUST contain NO secrets.

### I22 — Seal mismatch quarantines, never auto-heals

On seal mismatch the run MUST enter quarantine: a distinct,
non-executable, observable state that is NOT `FAILED`, NOT `SUCCEEDED`,
and NOT a member of the frozen P8-02 `ExecutionState` lifecycle set (it is
a durability-layer marker only, so frozen P8-02 I4/I5 stay unviolated).
Quarantine MUST persist pending human review and MUST NEVER auto-heal,
auto-retry, or auto-seal terminal.

### I23 — Quarantine is observable and scoped

Quarantine MUST be observable (quarantine flag + seal-verdict in durable
state and audit) and MUST NOT widen scope, leak secrets, or alter other
runs' state.

## 10. Provenance and audit

Every durability decision leaves an uneditable trail with minimized
content.

### I24 — Per-attempt provenance plus recovery events, append-only

Durable state MUST carry P8-01 `Provenance` per attempt plus append-only
recovery events (load, seal-verdict, UNKNOWN markings, resume/seal). The
audit log MUST be append-only: recorded entries SHALL NOT be mutated,
reordered, or deleted by retry, recovery, replay, or quarantine.

### I25 — Retention and minimization

Persisted provenance MUST retain no raw prompt bodies beyond fingerprints
and no secrets, ever. Per-attempt `EvaluationObservation` emission stays
observer-only (no authority or capability fields).

## 11. P7 compatibility

P8-03 changes nothing observable above the frozen seams.

### I26 — Recovered output indistinguishable in shape; P7 sees no recovery

A recovered/resumed run's typed output MUST be indistinguishable in shape
from an uninterrupted run's (`StructuredModelOutput` on `SUCCEEDED`,
typed terminal failure otherwise) via the frozen seams. P7 MUST NEVER
observe recovery internals (UNKNOWN markings, seals, quarantine flags,
audit entries). The future durability seam MUST NOT import P7 result,
authority, integration, or verification modules.

## 12. Ownership seam table

### I27 — P8-01 owns boundary, P8-02 owns lifecycle, P8-03 owns durability

| Concept | Owner | Note |
|---------|-------|------|
| `RunIdentity`, `compute_input_fingerprint` | P8-01 | Identity; P8-03 keys durability on it |
| `Budget`, `BudgetUsage`, `check_budget` | P8-01 | Bounds; P8-03 accounts fresh on resume |
| `FailureKind`, `FailureClass`, `classify_failure`, `is_retryable` | P8-01 | Taxonomy; P8-03 gates resume-retry on it |
| `RetryPolicy`, `call_with_retry` | P8-01 | Policy; P8-03 never re-caps |
| `ProviderAdapter.complete`, `ModelRequest/Response` | P8-01 | Sole call seam; P8-03 never calls it |
| `validate_raw_output`, `StructuredModelOutput` | P8-01 | Gate; P8-03 never revalidates |
| `Provenance`, `RuntimeConfig`, `EvaluationObservation` | P8-01 | Metadata; P8-03 persists per attempt |
| `replay_run` (observational, `None` if unrecorded) | P8-01 | Semantics; P8-03 extends to durable read |
| `ExecutionState`, transitions, terminal-state rule | P8-02 | Lifecycle; P8-03 adds no lifecycle state |
| `AttemptIdentity`, counting, chain rule | P8-02 | Identity; P8-03 persists in order |
| `execute_run`, ordered orchestration, budget checks | P8-02 | Execution; P8-03 resumes through it |
| `RunRecord` (metadata, not authority) | P8-02 | Record; P8-03 persists its projection |
| Recorded-outcome replay, idempotency on `RunIdentity` | P8-02 | Replay; P8-03 keeps it read-only |
| Durable allowlist, UNKNOWN-reconcile, resume-or-seal | P8-03 | New: durability semantics only |
| Serialization on identity, seal + quarantine, audit | P8-03 | New: recovery/integrity only |

### I28 — Ambiguity resolves to the frozen layer

Any concept ambiguous between durability and boundary/execution MUST
remain in frozen P8-01/P8-02. P8-03 MUST define ONLY durability, recovery,
integrity, and audit semantics — never execution, transport, or storage
backend.

## 13. Gate 1 acceptance

### I29 — RED for intended reasons only

The RED suite (`tests/contract/test_p8_03_*.py`, Gates A–J plus
`adversarial_` cases in P8-02 RED style) MUST fail only because the P8-03
durability surface (durable projection, UNKNOWN-reconcile, resume-or-seal,
seal + quarantine, append-only audit) is absent — not because of P6, P7,
P8-01, or P8-02 regressions, which MUST stay green.

### I30 — No frozen-layer or implementation changes

Gate 1 MUST contain no `src/` (implementation) changes and MUST leave
frozen P6/P7 contracts, `agents/p8_runtime/contract.py`, and
`agents/p8_runtime/execution.py` untouched. Scope is this doc plus the RED
suite only. STOP: no GREEN implementation in Gate 1.
