# P8-02 Runtime Execution Contract

**Status:** Gate 1 RED (design + tests only)
**Base SHA:** `7fede69`
**Branch:** `feat/finsight-p8-02-runtime-execution-semantics`
**Type:** DOC-ONLY
**Scope:** `docs/architecture/P8-02_*.md` + `tests/contract/test_p8_02_*.py` ONLY

## 1. Purpose and non-goals

P8-02 defines bounded execution semantics over the frozen P8-01 surface
(`agents/p8_runtime/contract.py`). P8-01 owns types, budgets, taxonomy, and
policy; P8-02 owns lifecycle, attempt orchestration, records, and replay
semantics. P8-02 orchestrates P8-01 primitives; it reimplements none of them.

Non-goals: Temporal, Redis, RabbitMQ/Kafka/Redpanda, Qdrant/Neo4j, AWS/GCP,
provider SDKs, LangGraph, DB persistence, financial execution, P6 authority,
new P7 authority.

### I1 — Execution orchestrates, never reimplements

Execution MUST invoke only frozen P8-01 primitives (`ProviderAdapter.complete`,
`validate_raw_output`, `classify_failure`, `is_retryable`, `check_budget`,
`compute_input_fingerprint`, `replay_run`). It MUST NOT redefine `Budget`,
`FailureKind`, `FailureClass`, `RetryPolicy`, or `RunIdentity` semantics.

### I2 — No authority, persistence, or orchestration coupling

Execution MUST NOT mint authorization, approval, execution, verification,
settlement, verdict, evidence, or gate-result authority. Only P6 owns
authority. Execution MUST NOT introduce queues, workflows, graph/vector
stores, cloud vendors, database writes, provider SDK coupling, or
agent-framework control flow.

### I3 — DOC-ONLY Gate 1

Gate 1 MUST NOT add or modify implementation. Only the contract doc and the
RED suite exist on this branch. P6, P7, and P8-01 stay frozen and untouched.

## 2. Execution lifecycle

Minimal state machine: `CREATED -> RUNNING -> SUCCEEDED | FAILED | EXHAUSTED`.
`CREATED` is intake only; `RUNNING` is the sole active state; the three
terminal states are mutually exclusive outcomes. No suspended, paused,
cancelled, queued, or delegated states exist — each would imply a queue,
workflow engine, or authority seam excluded by I2.

### I4 — Minimal closed state set

A run SHALL exist in exactly one of `CREATED`, `RUNNING`, `SUCCEEDED`,
`FAILED`, `EXHAUSTED`. No other states SHALL exist on the execution surface,
and no hidden or implicit states SHALL be reachable.

### I5 — Exactly one terminal state per run

Every run MUST terminate in exactly one of `SUCCEEDED`, `FAILED`, or
`EXHAUSTED`. Transitions SHALL be only `CREATED -> RUNNING`,
`RUNNING -> SUCCEEDED`, `RUNNING -> FAILED`, `RUNNING -> EXHAUSTED`. Terminal
states MUST have no outgoing transitions.

## 3. What one bounded execution does, in order

One bounded execution performs, in fixed order: request intake, invocation
via P8-01 `ProviderAdapter.complete`, response capture, P8-01
`validate_raw_output`, P8-01 `classify_failure` on failure, bounded retry per
P8-01 `RetryPolicy`, then a typed result or a terminal failure. Each step
delegates to the named P8-01 primitive.

### I6 — Fixed ordered orchestration of P8-01 primitives

Execution SHALL follow intake -> `complete` -> capture -> `validate_raw_output`
-> `classify_failure` -> bounded retry -> typed result or terminal failure.
No step SHALL be skipped, reordered, or merged, and no step SHALL reimplement
the P8-01 primitive it orchestrates.

### I7 — Typed result or typed terminal failure only

A run MUST end with either a validated `StructuredModelOutput` (`SUCCEEDED`)
or a typed terminal failure (`FAILED` on terminal `FailureKind`,
`EXHAUSTED` on budget exhaustion or retry-cap consumption). Untyped,
coerced, or authority-bearing outcomes are forbidden.

## 4. Mid-run budget exhaustion

P8-01 `Budget` is checked via `check_budget` before EACH attempt and before
each model call within an attempt. Exhaustion ends the run as `EXHAUSTED`
with `BudgetExhaustedError` semantics. Partial attempts are recorded as
attempts; nothing is half-applied.

### I8 — Budget checked before every attempt and call

Execution MUST call P8-01 `check_budget` before each attempt and before each
model call. Any `BudgetExhaustedError` MUST terminate the run as `EXHAUSTED`.
No further provider invocation SHALL occur after exhaustion.

### I9 — Partial attempts recorded, never half-applied

A budget-interrupted attempt MUST appear in the record with its observed
usage, failure kind `budget_exhausted`, and no validated output. Execution
MUST NOT emit a partial typed result, partial authority, or partial
financial effect.

## 5. Attempt identity

`AttemptIdentity` names one try within a run: `run_id` plus a deterministic
`attempt_number` plus the run `input_fingerprint`. The same logical retry
chain shares one `run_id`; distinct `run_id` values never merge.

### I10 — Attempt identity shape and deterministic counting

`AttemptIdentity` MUST carry `run_id`, `attempt_number` (zero-based,
sequential, gap-free within the run), and `input_fingerprint` (the frozen
P8-01 `compute_input_fingerprint` value for the run input). Counting MUST be
deterministic: identical retry chains yield identical sequences.

### I11 — Retry chains never merge or fork identities

All attempts of one bounded execution MUST share the run `run_id`. Attempts
with distinct `run_id` values MUST never be merged, compared as one chain,
or renumbered into another run.

## 6. Retry semantics

Only P8-01 `TRANSIENT` failures retry. Terminal failures never retry. The
attempt cap derives from `Budget.max_retries` and `RetryPolicy.max_retries`
(whichever binds first). Termination by construction: no infinite loops.
Each retry repeats the same neutral call with no authority change.

### I12 — Only TRANSIENT retries, capped by construction

Execution MUST retry exactly when P8-01 `is_retryable` returns true, and
MUST raise immediately otherwise. Total attempts MUST NOT exceed
`min(Budget.max_retries, RetryPolicy.max_retries) + 1`. Uncapped retry loops
are forbidden.

### I13 — Retry repeats the neutral call with no authority change

A retry MUST repeat the same neutral `ModelRequest` through
`ProviderAdapter.complete` with unchanged task semantics. Retries MUST NOT
add authority, capability, approval, or task-redefinition fields to the
request, response, or retry types.

## 7. Fallback

Provider or model fallback is observational infrastructure. It may change
where inference came from; it MUST never change what authority the result
has or what the task means. Every fallback try is a recorded attempt with
provenance.

### I14 — Fallback changes provenance only, never authority or task

Fallback MUST NOT introduce new response, gate, or authority types, and MUST
NOT alter task semantics or confer authority. The validated output shape
after fallback MUST be identical to the non-fallback shape.

### I15 — Fallback attempts recorded with provenance

Each fallback try MUST be recorded as an attempt carrying P8-01 `Provenance`
(provider, model, version, runtime config, timestamps, `run_id`). Fallback
tries MUST count against the I12 attempt cap and budget.

## 8. Execution record

One `ExecutionRecord` exists per run: run identity, ordered attempt list,
per-attempt provenance (provider/model/version), timing, usage, failure
info, and terminal state. The record is evidence-grade metadata for
observers; it is NOT a financial fact and NOT evidence authority.

### I16 — Record shape is metadata, complete per run

`ExecutionRecord` MUST carry `RunIdentity`, the ordered `AttemptIdentity`
list with per-attempt `Provenance`, timing, `BudgetUsage`, `FailureKind` /
`FailureClass` where applicable, and the single terminal state. Records MUST
NOT carry authorization, approval, execution, settlement, verdict, or
gate-result fields.

### I17 — Record is not a financial fact or evidence authority

`ExecutionRecord` MUST NOT subclass, coerce to, or mint `AuthoritativeFact`,
journal entries, settlements, or P7 result types (`DiscoveryResult`,
`ReasoningResult`, `HumanResolutionBrief`, `GateResult`). Agent output is
never financial truth.

## 9. Replay and idempotency

Replay of a recorded run returns the recorded outcome without re-invoking
the provider. Replay creates no new attempts, consumes no budget, and has no
financial effect. Idempotency is keyed on P8-01 `RunIdentity`.

### I18 — Replay returns the recorded outcome without re-invocation

Replay MUST NOT call `ProviderAdapter.complete`, MUST NOT create attempts,
and MUST NOT mint financial actions, journal entries, or settlements. Replay
of an unrecorded identity MUST return `None` (P8-01 `replay_run` semantics).

### I19 — Idempotency keyed on RunIdentity

Repeated replay of the same `RunIdentity` MUST return the identical recorded
outcome. Distinct `run_id` values MUST never alias to one another.

## 10. Security

Model and provider output is untrusted throughout execution. Injection text
stays data across attempts. Secrets and PII are scrubbed at every boundary.
Tenant and situation scope is fixed at intake and never widened by model
text. Retry, fallback, and replay MUST NOT escalate capability.

### I20 — Injection stays data across attempts

Provider or prompt text claiming capabilities, approvals, or execution
rights MUST NOT expand capability fields, mint authority, or register
evidence. Suspicious content MUST fail `validate_raw_output` or remain inert
string data in the record.

### I21 — Secrets scrubbed and scope fixed at intake

Secret material MUST NOT appear on requests, responses, provenance, records,
or boundary logs; logging MUST scrub secrets and PII. Tenant and situation
scope fixed at intake MUST NOT be widened by model text, retry, fallback,
or replay.

### I22 — No capability escalation via execution mechanics

Retry, fallback, and replay MUST NOT add capability, grant, permission, or
authority fields, and MUST NOT widen scope. The future implementation seam
MUST NOT import P7 result or authority modules.

## 11. P7 compatibility and observability

Execution emits one P8-01 `EvaluationObservation` per attempt as an observer.
The final validated result is consumable by the frozen P7 contracts without
redefining them. Observation never authorizes.

### I23 — Per-attempt observation only, never authorization

Execution MUST emit `EvaluationObservation` (`run_id`, `failure_kind`,
latency, token usage) per attempt with no authority or capability fields.
Observations MUST expose no authorize, approve, settle, verify, or execution
behavior, and MUST NOT gate task semantics.

### I24 — Final result consumable by frozen P7 without redefinition

The `SUCCEEDED` typed result MUST be consumable by frozen P7 contracts
(`DiscoveryResult`, `ReasoningResult`, `HumanResolutionBrief`, `GateResult`)
without redefining those types. No evaluation-derived authorization SHALL
exist: observations MUST NOT produce approvals, verdicts, or gate results.

## 12. P8-01 vs P8-02 seam

Anything ambiguous belongs to frozen P8-01. P8-02 adds only execution
semantics over those primitives.

| Concept | Owner | Note |
|---------|-------|------|
| `ProviderAdapter`, `ModelRequest` | P8-01 | Neutral seam; P8-02 only calls it |
| `ModelResponse` | P8-01 | Neutral seam; P8-02 only calls it |
| `RawModelOutput`, `validate_raw_output` | P8-01 | Gate; P8-02 only orchestrates it |
| `StructuredModelOutput` | P8-01 | Gate output; orchestrated only |
| `Budget`, `BudgetUsage`, `check_budget` | P8-01 | Bounds; P8-02 checks per attempt |
| `BudgetExhaustedError` | P8-01 | Typed refusal; ends run as EXHAUSTED |
| `FailureKind`, `FailureClass` | P8-01 | Taxonomy; P8-02 gates retries on it |
| `classify_failure`, `is_retryable` | P8-01 | Pure classifiers; P8-02 applies them |
| `RetryPolicy`, `call_with_retry` | P8-01 | Policy; P8-02 caps attempts by it |
| `RetryExhaustedError` | P8-01 | Cap signal; maps to EXHAUSTED/FAILED |
| `RunIdentity`, `compute_input_fingerprint` | P8-01 | Identity; P8-02 keys replay on it |
| `replay_run` | P8-01 | Observational replay; P8-02 extends it |
| `Provenance`, `RuntimeConfig` | P8-01 | Metadata; P8-02 records per attempt |
| `EvaluationObservation` | P8-01 | Observation; P8-02 emits per attempt |
| Lifecycle states, transitions, terminal-state rule | P8-02 | New: minimal machine (I4, I5) |
| `AttemptIdentity`, attempt counting, chain rule | P8-02 | New: per-try identity (I10, I11) |
| Ordered orchestration, per-attempt budget checks | P8-02 | New: execution order (I6, I8, I9) |
| Retry cap composition, fallback-as-attempt rule | P8-02 | New: policy execution (I12-I15) |
| `ExecutionRecord` (metadata, not authority) | P8-02 | New: per-run record (I16, I17) |
| Recorded-outcome replay, idempotency on `RunIdentity` | P8-02 | New: replay semantics (I18, I19) |

### I25 — Ambiguity resolves to frozen P8-01

Any concept ambiguous between boundary types and execution semantics MUST
remain in frozen P8-01. P8-02 MUST define only lifecycle, attempts, records,
and orchestration of P8-01 primitives — never rival types, budgets,
taxonomy, or policy.

### I26 — No P7 imports in the execution seam

The future P8-02 implementation seam MUST NOT import P7 result, authority,
integration, or verification modules. P7 compatibility is by consumable
shape, not by import.

## 13. Gate 1 acceptance

### I27 — RED for intended reasons only

The RED suite (`tests/contract/test_p8_02_*.py`) MUST fail only because the
P8-02 execution surface (lifecycle, `AttemptIdentity`, `ExecutionRecord`,
orchestration, recorded replay) is absent — not because of P6, P7, or P8-01
regressions, which MUST stay green.

### I28 — No frozen-layer or implementation changes

Gate 1 MUST contain no `src/` (implementation) changes and MUST leave frozen
P6/P7 contracts and the frozen P8-01 module (`agents/p8_runtime/contract.py`)
untouched. Scope is this doc plus the RED suite only.

## Test classification

Gate 1 tests map to Gates A-J in
`tests/contract/test_p8_02_runtime_execution_contract_red.py`: A lifecycle,
B ordered orchestration, C budget exhaustion, D attempt identity, E retry
semantics, F fallback, G execution record, H replay and idempotency,
I security and P7 compatibility, J seam and acceptance (including
`adversarial_` cases).

## Gate 1 DoD

- Contract committed on the P8-02 branch.
- RED suite fails for intended reasons; frozen suites stay green.
- No implementation changes; frozen layers untouched.
- STOP: no GREEN implementation in Gate 1.
