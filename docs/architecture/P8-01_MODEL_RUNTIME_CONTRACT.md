# P8-01 Model Runtime Contract

**Status:** Gate 1 RED (design + tests only)
**Base SHA:** `dbe84d4a84df209690a5b070d6286f021f9a2a44`
**Branch:** `feat/finsight-p8-01-model-runtime-contract`
**Type:** DOC-ONLY
**Scope:** `docs/architecture/P8-01_*.md` + `tests/contract/test_p8_01_*.py` ONLY

## 1. Purpose and non-goals

P8-01 defines the sole provider-neutral seam for model invocation. It carries
untrusted model text to explicit validation, bounded execution, and
observational evaluation. It confers no authority.

Non-goals: Temporal, Redis, RabbitMQ, Kafka, Redpanda, Qdrant, Neo4j, AWS/GCP,
DB persistence, LLM provider SDK coupling, LangGraph.

### I1 — Runtime is a boundary, not an authority

The runtime MUST NOT mint authorization, approval, execution, verification, or
evidence authority. Only P6 owns authority.

### I2 — No persistence or orchestration coupling

The runtime MUST NOT introduce queues, workflows, graph/vector stores, cloud
vendors, database writes, or agent-framework control flow.

### I3 — DOC-ONLY Gate 1

Gate 1 MUST NOT add or modify implementation. Only the contract doc and the RED
suite exist on this branch.

## 2. Provider-neutral surface (Gate A, Gate G)

The sole provider seam is `ProviderAdapter.complete`. Request, response,
configuration, and provenance types MUST be provider-neutral.

### I4 — Neutral request and response

`ModelRequest`, `ModelResponse`, `RuntimeConfig`, and `Provenance` MUST NOT
carry provider-specific, deployment-specific, or secret fields. Annotations
MUST NOT reference provider SDK types.

### I5 — Single adapter seam

`ProviderAdapter` SHALL be an explicit protocol exposing `complete`. No other
provider entry point SHALL exist on the public surface.

### I6 — Provenance is metadata, not authority

Every `ModelResponse` MUST carry `Provenance` and `run_id`. Provenance fields
(prompt context, evidence ids, model label, provider label, version, runtime
config, timestamps, run id) are observational metadata. They MUST NOT include
authority, approval, execution, or verdict semantics.

## 3. Structured output seam (Gate B)

Raw model text is untrusted. Structure requires an explicit rejecting validator.

### I7 — Raw output is distinct and untrusted

`RawModelOutput` MUST be distinct from `DiscoveryResult`, `ReasoningResult`,
and `HumanResolutionBrief`. It MUST NOT subclass, coerce to, or expose
converters into those types. Hostile text MUST remain data.

### I8 — Explicit validation gate

`validate_raw_output` is the only path from `RawModelOutput` to
`StructuredModelOutput`. It MUST reject malformed content by raising
`InvalidStructuredOutputError`. No implicit coercion SHALL exist.

## 4. Budgets (Gate C)

Bounds are required, finite, and enforced before further work.

### I9 — All dimensions required and finite

`Budget` MUST require `max_model_calls`, `max_tokens`, `max_tool_calls`,
`deadline_seconds`, and `max_retries`. Each MUST be finite. Absent or infinite
bounds MUST be rejected at construction.

### I10 — Enforcement is typed refusal

`check_budget` MUST raise `BudgetExhaustedError` when any `BudgetUsage`
dimension exceeds its `Budget` bound. In-budget usage MUST pass without side
effects.

## 5. Failure taxonomy (Gate E)

Failures are enumerated once and classified deterministically.

### I11 — Enumerated kinds and classes

`FailureKind` MUST cover timeout, provider_unavailable, rate_limited,
malformed_response, invalid_structured_output, budget_exhausted,
policy_refusal, and safety_injection_rejection. `FailureClass` MUST be exactly
transient and terminal.

### I12 — Fixed transient and terminal split

`classify_failure` MUST be deterministic. TRANSIENT is exactly timeout,
provider_unavailable, and rate_limited. TERMINAL is malformed_response,
invalid_structured_output, budget_exhausted, policy_refusal, and
safety_injection_rejection. Budget, policy, and safety failures MUST be
terminal.

## 6. Retry and fallback (Gate F)

Retries are bounded. Fallback MUST NOT change authority semantics.

### I13 — Bounded retry policy

`RetryPolicy` MUST require finite `max_retries`. Absent or infinite values MUST
be rejected. Retry loops MUST be capped; uncapped retries are forbidden.

### I14 — Eligibility follows classification with no authority change

`is_retryable` MUST return true exactly when `classify_failure` returns
TRANSIENT. Fallback MUST NOT introduce new response, gate, or authority types,
nor add authority or capability fields to request, response, or retry types.

## 7. Determinism (Gate D)

Runs are identifiable and replayable without re-executing financial effects.

### I15 — Stable input fingerprint

`compute_input_fingerprint` MUST be deterministic: identical payloads yield
identical non-empty strings, and distinct situations yield distinct values.
`RunIdentity` MUST carry `run_id` and `input_fingerprint` with no authority
fields.

### I16 — Replay is observational only

`replay_run` returns `ModelResponse | None`. Replay MUST NOT mint financial
actions, journal entries, settlements, or any new financial effect.

## 8. Evaluation hooks (Gate I)

Evaluation observes the runtime; it never authorizes through it.

### I17 — Observation only, never authorization

`EvaluationObservation` MUST carry run id, failure kind, latency, and token
usage, with no authority or capability fields. It MUST expose no authorize,
approve, settle, verify, or execution behavior. No public symbol SHALL contain
authority-granting verbs.

## 9. Security (Gate H, Gate J)

Injection stays data. Secrets are scrubbed at the boundary. Type confusion is
refused.

### I18 — Injection stays data

Provider or prompt text claiming capabilities, approvals, or execution rights
MUST NOT expand capability fields, mint `AuthoritativeFact`, or register
evidence. Suspicious content MUST fail validation or remain inert data.

### I19 — Secrets and PII redacted at the boundary

Secret material MUST NOT appear on `ModelRequest`, `ModelResponse`,
`Provenance`, `RawModelOutput`, or `RuntimeConfig`. Boundary logging MUST scrub
secrets and PII. Contracts MUST NOT carry raw bodies beyond the untrusted raw
envelope.

### I20 — Type separation and no authority leakage

`RawModelOutput` is not `DiscoveryResult`, `ReasoningResult`, or
`HumanResolutionBrief`. Agent output is never financial truth. The runtime
surface MUST NOT define or reference authorization, approval, execution,
verification, settlement, verdict, or gate-result types.

## 10. Existing infrastructure classification

One line per surveyed path. REUSE as-is, WRAP behind the neutral seam,
EXCLUDE from P8-01.

| Path | Class |
|------|-------|
| `shared/llm/provider.py` | REUSE — provider Protocol plus strict structured-output validation |
| `shared/llm/types.py` | REUSE — frozen prompt, health, metadata, and call-log types |
| `shared/llm/errors.py` | REUSE — credential-safe error hierarchy |
| `shared/llm/fake.py` | REUSE — fake provider for tests |
| `shared/llm/replay.py` | REUSE — replay provider for determinism |
| `shared/safety/secrets.py` | REUSE — standard redaction and scrubbing |
| `agents/trajectory/models.py` | REUSE — frozen trajectory and step types |
| `agents/evaluation/harness.py` | REUSE — Layer-1 evaluation pattern only |
| `shared/llm/config.py` | WRAP — environment-driven config with capped retries |
| `shared/llm/factory.py` | WRAP — provider construction entry point |
| `shared/llm/openai_compatible.py` | WRAP — wire adapter behind the neutral seam |
| `agents/trajectory/recorder.py` | WRAP — fixture save and load plus sequential replay |
| `shared/llm/groq.py` | EXCLUDE — legacy provider |
| `finance/llm/client.py` | EXCLUDE — unbounded loop |
| `finance/llm/model_router.py` | EXCLUDE — hardcoded provider table |
| `finance/llm/structured_generation.py` | EXCLUDE — uncapped backoff with direct transport coupling |
| `finance/llm/response_validator.py` | EXCLUDE — weak validator |
| `finance/llm/telemetry.py` | EXCLUDE — missing credential hygiene |
| `agents/trajectory/harness.py` | EXCLUDE — gated live mode |

### I21 — Reuse without reimplementation

REUSE paths SHALL be consumed as-is for protocol shape, frozen types, error
semantics, fakes, replay, redaction, trajectory, and evaluation pattern. P8-01
MUST NOT reimplement them.

### I22 — Wrap behind the neutral seam

WRAP paths SHALL be confined behind `ProviderAdapter.complete`, capped
configuration, and fixture replay. Direct transport or factory coupling MUST
NOT leak onto the typed surface.

### I23 — Exclude legacy and unsafe paths

EXCLUDE paths MUST NOT be imported, wrapped, or reintroduced by P8-01.

## 11. Gate 1 acceptance

### I24 — RED for intended reasons only

The RED suite MUST show 28 failures caused by the absent runtime boundary, not
by frozen P6 or P7 regressions.

### I25 — No frozen-layer or implementation changes

Gate 1 MUST contain no implementation changes and MUST leave frozen P7
contracts untouched.

## Test classification

Gate 1 tests map to Gates A–J in
`tests/contract/test_p8_01_model_runtime_contract_red.py`: A provider
neutrality, B raw-output boundary, C budgets, D identity and replay, E failure
taxonomy, F retry and fallback, G provenance, H security, I evaluation seam,
J no authority leakage.

## Gate 1 DoD

- Contract committed on the P8-01 branch.
- RED suite fails for intended reasons; frozen suites stay green.
- No implementation changes; frozen layers untouched.
- STOP: no GREEN implementation in Gate 1.
