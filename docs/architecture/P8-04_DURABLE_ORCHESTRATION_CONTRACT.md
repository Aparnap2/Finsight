# P8-04 Durable Orchestration Boundary Contract

**Status:** Gate 1 RED (design + tests only; NO implementation)
**Base SHA:** `9fad082`
**Branch:** `feat/finsight-p8-04-durable-orchestration-boundary`
**Type:** DOC-ONLY
**Scope:** `docs/architecture/P8-04_*.md` + `tests/contract/test_p8_04_*.py` ONLY

## 1. Purpose and non-goals

P8-04 coordinates the frozen layers without redefining them: P8-01 boundary
(`agents/p8_runtime/contract.py`: `RunIdentity`, `Budget`, `FailureKind`,
`FailureClass`, `RetryPolicy`, `ProviderAdapter`, `Provenance`,
`EvaluationObservation`), P8-02 execution (`agents/p8_runtime/execution.py`:
`ExecutionState`, `AttemptIdentity`, `RunRecord`, `AttemptRecord`,
`TerminalOutcome`, `execute_run`, `replay_run`, `observe_run`), and P8-03
durability (`agents/p8_runtime/durability.py`: `DurableRunState`,
`PERSISTED_FIELDS`, `RECOVERY_ORDER`, `seal_domain`, `recover_run`,
`resume_run`, `replay_durable`, `resubmit`, `history`). P8-04 names the
workflow/scheduling seam ABOVE runs: what is scheduled when, how multi-run
workflows suspend/resume/retry/cancel, and where a future engine may plug in.
It implements nothing, schedules nothing, and stores nothing.

Non-goals (hard exclusions): Temporal, Redis, RabbitMQ/Kafka/Redpanda,
cloud workflows, database implementation, provider SDKs, LangGraph,
vector/graph infrastructure, financial execution, P6/P7 authority changes,
actual orchestration implementation.

### I1 — Orchestration surrounds, never redefines

P8-04 MUST reuse `RunIdentity`, `AttemptIdentity`, `RunRecord`,
`AttemptRecord`, `TerminalOutcome`, `Provenance`, `DurableRunState`, and
`ExecutionState` by name with frozen meanings. It MUST NOT redefine `Budget`,
`BudgetUsage`, `check_budget`, `FailureKind`, `FailureClass`,
`classify_failure`, `is_retryable`, `RetryPolicy`, `call_with_retry`,
`ExecutionState` transitions, `execute_run` ordering, `replay_run` semantics,
durable allowlist (`PERSISTED_FIELDS`), recovery order (`RECOVERY_ORDER`),
seal semantics (`seal_domain`), or quarantine semantics.

### I2 — No backend, framework, or authority coupling

P8-04 MUST NOT introduce Temporal, Redis, queues/streams, databases, cloud
services, provider SDKs, LangGraph, vector/graph stores, financial
execution, or authority minting. Orchestration semantics MUST be
backend-free; any future engine plugs in BEHIND the scheduling seam (see
I22), never inside execution or authority.

### I3 — DOC-ONLY Gate 1

Gate 1 MUST NOT add or modify implementation. Only this contract doc and
the RED suite exist. P6, P7, P8-01, P8-02, and P8-03 stay frozen and
untouched.

## 2. Workflow/run lifecycle: three distinct layers

### I4 — Minimal closed workflow-state set

The workflow layer SHALL define exactly six states and no others:
`PENDING` (accepted, unscheduled), `RUNNING` (at least one run admitted to
the schedule), `SUSPENDED` (paused at a recorded suspension point, see I13),
`COMPLETED` (sealed terminal success outcome recorded), `FAILED` (sealed
terminal failure outcome recorded), `CANCELLED` (cooperatively cancelled and
recorded, see I15). Minimality justification: `PENDING`/`RUNNING` cover
admission; `SUSPENDED` is required so resume-from-point (I13) is
distinguishable from fresh start; `COMPLETED`/`FAILED` mirror sealed run
outcomes at workflow scope; `CANCELLED` is required so cooperative stop is
auditable and distinct from failure. No `RETRYING`, `PAUSED-UNKNOWN`, or
quarantine states SHALL exist at workflow scope.

### I5 — Three layers, no merging

Workflow states (I4) vs P8-02 `ExecutionState`
(`CREATED`/`RUNNING`/`SUCCEEDED`/`FAILED`/`EXHAUSTED` per
`agents/p8_runtime/execution.py`) vs P8-03 durability markers (`UNKNOWN`
in-flight mark, `QUARANTINED` marker per
`agents/p8_runtime/durability.py`) are three distinct layers and MUST NEVER
merge: a workflow state MUST NOT appear as an `ExecutionState` member, an
`ExecutionState` MUST NOT appear as a workflow state, and durability markers
(`UNKNOWN`, `QUARANTINED`) MUST NOT appear in either lifecycle set.

### I6 — Workflow transitions; terminal seal rule

Allowed workflow transitions SHALL be exactly: `PENDING`→`RUNNING`,
`PENDING`→`CANCELLED`, `RUNNING`→`SUSPENDED`, `RUNNING`→`COMPLETED`,
`RUNNING`→`FAILED`, `RUNNING`→`CANCELLED`, `SUSPENDED`→`RUNNING`
(resume, see I12–I13), `SUSPENDED`→`CANCELLED`. `COMPLETED`, `FAILED`, and
`CANCELLED` are terminal with no outgoing transitions; a recorded terminal
workflow outcome MUST NOT be rewritten, deleted, or re-derived (extends
frozen P8-03 I8 upward to workflow scope).

## 3. Durable workflow identity

### I7 — `workflow_id` distinct from `run_id`

Every workflow SHALL carry a `workflow_id` distinct in name and value-space
from P8-01 `run_id`: `workflow_id` names the multi-step orchestration;
`run_id` (inside `RunIdentity` with `input_fingerprint`) names one bounded
execution governed by P8-02/P8-03. A `workflow_id` MUST NEVER alias a
`run_id`, and run dedup beneath it stays governed by P8-03 identity
(`resubmit`, `replay_durable`, fingerprint key rule per P8-03 I12–I13).

### I8 — Parent/child linkage for multi-run workflows

A workflow MAY own an ordered child-run list of `RunIdentity` values plus an
optional `parent_workflow_id` link for nested workflows. Child linkage is
metadata only: it records which runs belong to which workflow and in what
order; it MUST NOT change any run's `RunIdentity`, scope, budget, or
terminal outcome, and MUST NOT let one workflow mutate another workflow's
runs.

### I9 — Identity stable across crashes; tenant+situation in the key

`workflow_id` MUST be stable across crashes: post-crash reconstruction (see
I21) MUST recover the same `workflow_id`, child-run list, and suspension
point from durable P8-03 records, never mint a replacement id. The workflow
key SHALL include tenant + situation scope fixed at intake (inheriting the
P8-03 I19 durable key); scope MUST NOT widen on schedule, retry, replay,
recovery, or resume.

## 4. Scheduling vs execution separation

### I10 — Scheduling decides WHAT runs WHEN

Scheduling SHALL decide only ordering, priority, and trigger conditions:
which admitted run (by `RunIdentity`) is eligible next, in what order, under
what trigger (prior run sealed, suspension released, workflow resumed).
Scheduling reads sealed run outcomes and workflow state; it MUST NOT decide
HOW a run executes (that is frozen `execute_run` ordering per P8-02) and
MUST NOT decide what survives a crash (that is the P8-03 durable allowlist
and recovery order).

### I11 — Scheduler prohibitions

The scheduler MUST NEVER invoke `ProviderAdapter.complete`, interpret
`StructuredModelOutput` contents, re-validate raw output, reclassify
`FailureKind`, mint authority (authorization, approval, execution,
settlement, verdict, gate-result), or widen scope. Violation of this
invariant is a contract breach even if behaviorally silent.

## 5. Resume/recovery semantics

### I12 — Resume replays durable state and re-enters the schedule

Workflow resume SHALL replay durable P8-03 state (`recover_run` order
`RECOVERY_ORDER`, `reconcile_unknown` history+budget) and re-enter the
schedule at the recorded point; it MUST NEVER re-execute a run whose
terminal outcome (`SUCCEEDED`/`FAILED`/`EXHAUSTED` with `TerminalOutcome`)
is durably recorded — recorded runs return via `replay_durable` /
`replay_run` with zero new invocations (frozen P8-03 I11, P8-02 replay).

### I13 — Suspended workflows resume from the recorded suspension point

Suspension SHALL record an explicit suspension point (workflow state +
next-eligible child `RunIdentity` + ordering cursor). Resume from
`SUSPENDED` MUST continue from that recorded point, not from workflow
start and not from an inferred point; skipping reconcile (`skipped_reconcile`)
is forbidden (extends P8-03 `ResumeMarker` semantics upward).

## 6. Timeout/cancellation

### I14 — Per-workflow and per-run deadlines

A workflow MAY carry a workflow deadline and each child run keeps its frozen
P8-01 `Budget.deadline_seconds`. The per-run deadline is enforced inside
`execute_run` via `check_budget`; the workflow deadline is enforced only at
the scheduling seam (admit/no-admit, suspend-on-expiry). A workflow deadline
MUST NOT shorten, extend, or reinterpret any run's `Budget`.

### I15 — Cooperative cancellation; timeout is classification input

Cancellation SHALL be cooperative and recorded: a cancel request marks the
workflow `CANCELLED` (terminal + auditable, with an append-only audit entry
per P8-03 I24 style); in-flight runs reconcile via the P8-03 protocol and
are never force-completed or force-sealed. A run timeout MUST surface only
as `FailureKind.TIMEOUT` classification input to frozen
`classify_failure`/`is_retryable` (P8-01), never as a new failure authority
or a new terminal state.

## 7. Retry ownership: three counters, three owners

### I16 — Workflow runs vs P8-02 calls vs P8-03 recovery

Exactly three retry counters with three owners SHALL exist: (a) workflow
retry policy — how many RUNS (child `RunIdentity` admissions) the workflow
may schedule, owned by P8-04; (b) P8-02 attempt retry — how many CALLS
(`AttemptIdentity` tries via `call_with_retry` up to
`min(budget, policy)+1`) inside one run, owned by frozen P8-01/P8-02;
(c) P8-03 recovery — UNKNOWN-reconcile gated retry (TRANSIENT + cap +
budget via `retry_unknown`), owned by frozen P8-03, with no blind retry
(P8-03 I18). P8-04 MUST NOT re-cap, reset, or double-count the P8-02 or
P8-03 counters.

### I17 — Precedence; no unbounded cross-layer loop

Precedence SHALL be: P8-03 recovery gates first (resume-or-seal per
`RECOVERY_ORDER`), then P8-02 attempt cap + `check_budget` inside the run,
then the P8-04 workflow run budget across runs. No retry loop MAY span
layers unboundedly: each layer's bound applies independently, and exhaustion
at any layer seals upward (run `EXHAUSTED` → workflow `FAILED` unless the
workflow policy admits a distinct new `RunIdentity`; never a silent
re-execution under the same identity).

## 8. Workflow-level idempotency

### I18 — Same `workflow_id` resubmission resumes or returns; never forks

Resubmission of the same `workflow_id` MUST return the recorded workflow
outcome when terminal (`COMPLETED`/`FAILED`/`CANCELLED`), or resume the
workflow from durable state when non-terminal. It MUST NEVER fork a
duplicate workflow under the same id; run dedup beneath it stays governed
by P8-03 `resubmit`/`replay_durable` (one identity, one live run; same
`run_id`/different-fingerprint never aliases).

## 9. Concurrent workflows

### I19 — Distinct workflows fully isolated

Distinct `workflow_id` values SHALL be fully isolated: no shared mutable
state, no shared budget accounting visibility (workflow run-counters are
per-workflow; per-run `BudgetUsage` stays per-`RunIdentity`), and provenance
entries MUST attribute to exactly one workflow + one run. One workflow's
schedule, suspend, cancel, or quarantine MUST NOT alter another's.

### I20 — Same `workflow_id` serializes

Concurrent submissions under one `workflow_id` MUST serialize: a second
caller SHALL observe the recorded outcome (terminal) or observe/wait for
the in-progress workflow (non-terminal) — never start a duplicate
workflow or a duplicate child run under an already-live `RunIdentity`
(extends P8-03 I19 upward).

## 10. Crash/restart and the future-engine plug point

### I21 — Scheduler state reconstructible; no scheduler store assumed

Scheduler state (workflow registry, ordering cursors, suspension points,
workflow retry counters) MUST be reconstructible from durable P8-03 records
(`DurableRunState` projections, ordered attempt histories, append-only
audit) plus the submitted workflow descriptors. P8-04 MUST NOT assume a
separate scheduler store, write-ahead log, or clock beyond what P8-03
durability already provides.

### I22 — In-flight runs reconcile via P8-03; engine plugs in BEHIND the seam

After a crash, in-flight runs SHALL reconcile exclusively via the P8-03
protocol (`recover_run` load→verify→reconcile→resume/seal; UNKNOWN marking;
gated retry only). Exactly one future-engine plug point is allowed: a
Temporal-style durable executor, unnamed and unimported, MAY implement the
scheduling seam from behind (admission, ordering, timers, resume triggers).
It MUST NEVER sit inside `execute_run`, `ProviderAdapter.complete`,
validation, classification, authority, or P6/P7 modules, and MUST NOT import
P7 result, authority, integration, or verification modules.

## 11. P7/P6 handoff

### I23 — Completion emits P7-consumable typed results via frozen seams only

Workflow completion SHALL hand off only frozen-seam shapes: per-run
`StructuredModelOutput` on `SUCCEEDED` or typed terminal failure otherwise
(`TerminalOutcome`/`RunRecord` projection), aggregated without
reinterpretation. The handoff MUST NOT import P7 result, authority,
integration, or verification modules (extends P8-03 I26 upward), and MUST
NOT touch P6 execution paths.

### I24 — Deterministic handoff; orchestration adds no interpretation

The handoff MUST be deterministic: the same durable history (same ordered
attempts, same terminal outcomes, same child-run list) SHALL yield the same
handoff payload. Orchestration MUST add no interpretation, no verdict, no
ranking, no summary rewriting, and no authority of any kind.

## 12. Observability/evaluation

### I25 — Workflow observations are observer-only

Workflow-level observations (workflow state transitions, scheduling
decisions, suspension/resume/cancel events) SHALL be observer metadata in
the style of P8-01 `EvaluationObservation`: they carry no authority, no
capability fields, and no secrets/PII beyond fingerprints.

### I26 — Per-run observations preserved; no eval-derived control

Per-run P8-01 observations (via `observe_run`, one per `AttemptRecord`) MUST
be preserved beneath workflow observations without alteration. No evaluation
output SHALL authorize work, mint capability, or drive scheduling priority;
scheduling reads only sealed outcomes and explicit triggers (I10), never
eval scores.

## 13. Ownership seam table

### I27 — Four-row seam: boundary / execution / durability / orchestration

| Concept | Owner | Note |
|---------|-------|------|
| `RunIdentity`, `compute_input_fingerprint`, `Budget`, `BudgetUsage`, `check_budget` | P8-01 | Bounds/identity; P8-04 keys workflow scope on them, never re-caps |
| `FailureKind`, `FailureClass`, `classify_failure`, `is_retryable`, `RetryPolicy`, `call_with_retry` | P8-01 | Taxonomy/policy; P8-04 treats timeout as input only |
| `ProviderAdapter.complete`, `ModelRequest/Response`, `validate_raw_output`, `StructuredModelOutput` | P8-01 | Sole call/validation seam; scheduler never touches it |
| `Provenance`, `RuntimeConfig`, `EvaluationObservation` | P8-01 | Metadata; P8-04 persists per workflow + per run |
| `replay_run` (observational, `None` if unrecorded) | P8-01 | Semantics; P8-04 extends to workflow outcome |
| `ExecutionState`, transitions, terminal-state rule | P8-02 | Run lifecycle; P8-04 adds no run state |
| `AttemptIdentity`, counting, chain rule | P8-02 | Attempts; P8-04 counts runs, not calls |
| `execute_run`, ordered orchestration, budget checks | P8-02 | HOW a run executes; P8-04 resumes through it |
| `RunRecord`, `AttemptRecord`, `TerminalOutcome` | P8-02 | Records; P8-04 aggregates, never mutates |
| Durable allowlist, UNKNOWN-reconcile, resume-or-seal, seal + quarantine, audit | P8-03 | What survives; P8-04 reconstructs the schedule from it |
| Serialization on identity, scope fixed at intake | P8-03 | Concurrency/key; P8-04 extends to `workflow_id` |
| Workflow states, `workflow_id`, parent/child linkage, suspension points | P8-04 | New: orchestration identity/lifecycle only |
| Scheduling (ordering, priority, triggers), workflow retry policy, deadlines, cancel | P8-04 | New: WHAT runs WHEN; never HOW, never authority |
| Workflow idempotency, isolation, reconstructible schedule, engine plug point | P8-04 | New: coordination only, behind-the-seam engine |
| Deterministic typed handoff, workflow observations | P8-04 | New: P7-consumable shapes, observer-only |

### I28 — Ambiguity resolves to the frozen layer

Any concept ambiguous between orchestration and boundary/execution/
durability MUST remain in frozen P8-01/P8-02/P8-03. P8-04 MUST define ONLY
workflow identity, workflow lifecycle, scheduling, workflow retry/cancel/
deadline policy, idempotency, isolation, reconstruction, and handoff shape —
never execution, transport, storage backend, or authority.

## 14. Gate 1 acceptance

### I29 — RED for intended reasons only

The RED suite (`tests/contract/test_p8_04_*.py`, Gates A–J plus
`adversarial_` cases in P8-03 RED style) MUST fail only because the P8-04
orchestration surface (workflow states, `workflow_id`, scheduling seam,
suspend/resume-from-point, workflow retry policy, idempotent resubmission,
isolation, reconstructible schedule, deterministic handoff) is absent — not
because of P6, P7, P8-01, P8-02, or P8-03 regressions, which MUST stay
green.

### I30 — No frozen-layer or implementation changes

Gate 1 MUST contain no `src/` (implementation) changes and MUST leave
frozen P6/P7 contracts, `agents/p8_runtime/contract.py`,
`agents/p8_runtime/execution.py`, and `agents/p8_runtime/durability.py`
untouched. Scope is this doc plus the RED suite only. STOP: no GREEN
implementation in Gate 1.
