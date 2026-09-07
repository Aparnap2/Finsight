# Design: FinSight v2 — Reconciliation

## Context

FinSight v2 adds an autonomous payment-reconciliation loop on top of the existing FP&A cognitive runtime. The system must reconcile Stripe-side payment intents against QuickBooks-side ledger entries, classify breaks, and either close deterministically or escalate ambiguous cases through an evidence-gated, policy-enforced, human-approved path.

**Platform constraints (non-negotiable):**

- **Python-first, Go later on benchmark:** All v2 reconciliation logic ships in the Python Compute Runtime (FastAPI + LangGraph + Pydantic v2). Go is deferred until a Python-vs-Go benchmark proves a latency/cost need. No Go service, no Go adapter, no dual implementation in v2 scope.
- **Postgres real, MiniStack only AWS primitives:** Persistence is real Postgres. Local/test AWS emulation uses MiniStack **only for AWS primitives** (SQS/SNS/S3-equivalent webhook ingress and object artifacts). No MiniStack Postgres, no MiniStack Redis, no shadow stores.
- **Existing reuse (must reuse, not reinvent):**
  - `finance/` — variance engine, materiality thresholds, assertion pipeline.
  - `shared/` — claim-validator (hallucination guard), policy engine, `ToolResult` envelope, `MoneyDecimal` (`Decimal`-only money; `float` banned at the Pydantic boundary).
  - `agents/` — LangGraph orchestration, checkpointing, read-only tool pattern.
  - `apps/api/schemas.py` — `MoneyDecimal` type alias as the single money boundary.

Current state: variance/materiality/assertion/claim-validator/policy/`ToolResult`/`MoneyDecimal` exist and are tested. Reconciliation, break classification, resolution proposals, HITL approval, sandboxed execution, and post-execution verification do not exist and are the subject of this change.

## Goals / Non-Goals

### Goals

1. Deterministic reconciliation of `PaymentRecord` pairs (Stripe intent ↔ QB entry) with tenant-injected tolerance.
2. Machine-testable break taxonomy (I1–I10 invariants).
3. Deterministic fast path: exact/tolerance matches auto-close with assertion + evidence, no LLM in the loop.
4. Ambiguous-path safety: read-only investigation → evidence → assertion → proposal → policy → HITL → sandbox execute → post-verify → close.
5. Full auditability: every state transition, money computation, policy decision, approval, execution, and verification is traced and replayable.
6. Idempotent webhook ingress with dedup; safe retries without double-close or double-execute.

### Non-Goals

1. No Go service in v2 (deferred behind benchmark gate).
2. No vector/semantic retrieval for reconciliation (Qdrant explicitly removed from this change).
3. No Temporal adoption in v2 (deferred to LangGraph checkpoint).
4. No autonomous money movement without HITL approval + sandbox + post-verification.
5. No LLM-owned arithmetic, reconciliation, policy enforcement, state transitions, execution authorization, idempotency, or post-execution verification (deterministic code owns all of these).
6. No new money type, no `float` money, no adapter before P0.2/P0.3 freeze.

## Architecture Flow

```text
Webhook/Event
      ↓
Deduplication
      ↓
Normalization
      ↓
Deterministic Reconciliation
      ↓
Exception Classification
      │
      ├── Resolved deterministically → Close
      │
      └── Ambiguous → Investigation
                         ↓
                    Read-only tools
                         ↓
                  Evidence bundle
                         ↓
                 Assertion validation
                         ↓
                      Proposal
                         ↓
                    Policy gate
                         ↓
                       HITL
                         ↓
                 Sandbox execution
                         ↓
                   Post-verify
                         ↓
                       Close
```

**Stage responsibilities:**

1. **Webhook:** FastAPI ingress, HMAC verification, idempotency-key required. Emits immutable intake event. No business logic.
2. **Dedup:** Idempotency-key + provider-event-id dedup in Postgres with explicit locking. Duplicates return prior result; never re-enter Reconcile.
3. **Normalize:** Provider payloads → `PaymentRecord` contract. `MoneyDecimal` enforcement, currency/precision validation, Pandera + Pydantic checks. Failures → `FAILED` (terminal, no auto-close).
4. **Reconcile:** Pure deterministic matcher (exact → tolerance → fuzzy-candidate). Owns all money arithmetic. No LLM calls. Outputs `ReconciliationResult` + break code (I1–I10).
5. **Classify:** Break taxonomy router. Exact/tolerance match → deterministic-close (assertion + evidence, state `CLOSED`). Anything else → ambiguous path.
6. **Ambiguous path (agent-assisted, deterministically gated):** read-only tools → evidence → assertion → proposal → policy → HITL → sandbox execute → post-verify → close.

**Ambiguity boundary:**

The agent may synthesize an investigation path and propose an action, but deterministic code owns money arithmetic, reconciliation, policy enforcement, state transitions, execution authorization, idempotency, and post-execution verification.

## Decisions

### D1 — Five contracts (Pydantic v2 strict)

1. `PaymentRecord`: normalized provider-agnostic payment (id, provider, provider_event_id, idempotency_key, amount `MoneyDecimal`, currency, timestamps, tenant_id, raw_ref).
2. `ReconciliationResult`: deterministic outcome (matched | tolerance_matched | break with I-code, variance `MoneyDecimal`, materiality verdict, evidence refs). Produced only by `finance/` pure code.
3. `Evidence`: immutable bundle (tool call trace, snapshots, assertion results, provenance). Required for any non-deterministic-close.
4. `ResolutionProposal` (!= Execution): agent-synthesized candidate fix. A proposal authorizes nothing; it is data awaiting policy + HITL.
5. `Execution`: sandbox-run record (approved proposal ref, sandbox guard verdict, provider write receipts, post-verify result). Only created post-HITL via deterministic executor.

`ResolutionProposal` and `Execution` are distinct types by design: confusing them is a review-blocking defect.

### D2 — I1–I10 machine-testable invariants

Break taxonomy is ten enumerated, unit-testable invariants (exact match, tolerance match, fee drift, FX/precision, timing window, duplicate ingest, missing counterpart, amount mismatch over tolerance, currency mismatch, stale/superseded). Each I-code has: predicate, fixture, threshold source, and expected terminal/gated outcome. No free-text break reasons in storage; free text lives only in commentary.

### D3 — State machine with banned transitions

States: `RECEIVED → NORMALIZED → RECONCILING → MATCHED → CLOSED` and happy path `RECEIVED → NORMALIZED → RECONCILING → EXCEPTION → INVESTIGATING → EVIDENCE_READY → EVIDENCE_VERIFIED → PROPOSED → AWAITING_APPROVAL → APPROVED → EXECUTING → POST_VERIFYING → EXECUTION_VERIFIED → CLOSED` (with `REJECTED → CLOSED`, `FAILED → ESCALATED` recovery). `EVIDENCE_VERIFIED` is pre-proposal (evidence bundle asserted); `EXECUTION_VERIFIED` is post-execution (post-verify re-reconciled). Transition ownership is deterministic code only; the agent may request but never apply a transition.

Illegal transitions (enforced in code + tests):

- `INVESTIGATING -> EXECUTING` banned (must pass through evidence → proposal → policy → HITL → approval).
- `PROPOSED -> EXECUTING` banned (requires policy pass + HITL `APPROVED`).
- `FAILED -> CLOSED` banned (`FAILED` is terminal; requires explicit re-ingest as a new idempotency scope, never silent close).

### D4 — Tolerance is tenant-injected

No hardcoded tolerance. Tolerance (absolute `MoneyDecimal` and/or bps, timing window) is injected per tenant from config/policy. Reconcile receives it as an argument; tests parametrize it. Default-deny on missing tolerance config for tolerance-path closes.

### D5 — Thin direct SDKs behind LLMProvider, swappable (Resolved)

All LLM calls go through `shared` `LLMProvider` protocol exposing `generate_structured` / `health_check` / `model_metadata`. Providers are thin direct SDK bindings: `GroqProvider` (default v2), `OpenRouterProvider`, `LocalProvider`. NOT LangChain / LiteLLM in the MVP domain path. Deterministic stages make zero LLM calls. Ambiguous-path investigation may call the LLM for path synthesis and summaries only; outputs must pass claim-validator + assertion before becoming `Evidence`/`ResolutionProposal`.

### D6 — Quality vs safety vs policy ownership

- `shared/quality/` owns deterministic content checks: `assertion_validator`, `evidence_validator`, `confidence` scoring. No execution authority.
- `shared/safety/` owns cross-cutting execution safety: `execution_guard.py` (global invariant: allowlist, dry-run-first, receipt capture), `idempotency`, `approval_gate`. No financial-domain rules.
- `finance/policy/` owns financial-domain rules: refund / correcting-entry / void / fee rules, tolerance sourcing, materiality. Expresses rules; never enforces the global execution invariant.

## Risks / Trade-offs

- **Go early = complexity** → Rejected for v2. Python-first; Go only if the benchmark gate trips.
- **Qdrant removed** → Reconciliation is exact/relational, not semantic. Postgres covers dedup, ledger, and event spine.
- **Temporal deferred to LangGraph checkpoint** → LangGraph checkpointing already provides resume, replay, and HITL suspension for v2 scale.
- **LLM drift into arithmetic/policy** → Hard boundary: LLM outputs are advisory text + tool-call plans; claim-validator + assertion pipeline reject ungrounded proposals.
- **Sandbox escape / partial execution (Resolved: `shared/safety/execution_guard.py` owns global invariant)** → `shared/safety/execution_guard.py` owns provider-write allowlist, dry-run-first, receipt capture; `finance/` expresses financial rules only. Post-verify must re-reconcile to `CLOSED`, else `FAILED` + incident.
- **Idempotency replay storms** → Dedup at ingress + executor idempotency keys + Postgres locks; duplicates short-circuit to stored result.

## Migration Plan

Strictly sequenced; no stage starts until prior exit gate passes. **No adapter before P0.2/P0.3.**

- **P0 — Freeze:** Lock `MoneyDecimal`, `ToolResult`, policy, claim-validator, assertion interfaces. Define the 5 contracts as stubs + I1–I10 enumeration + state machine with banned-transition tests (red).
- **P1 — Pure:** Implement Normalize → Reconcile → Classify + deterministic-close path in `finance/` with golden fixtures. No provider SDKs, no agent, no execution.
- **P2 — Stripe:** Add Stripe webhook ingress + Dedup + `PaymentRecord` normalization. Read-only; QB side stubbed with fixtures.
- **P3 — QB/HITL:** Add QB normalization, ambiguous-path evidence → assertion → proposal → policy → HITL queue (no execution).
- **P4 — Agent:** Enable read-only agent investigation + sandbox executor + post-verify → close. Full journey + chaos tests.

## Open Questions

- **RESOLVED — LLM binding (D5):** Thin direct provider SDKs behind `LLMProvider` (`GroqProvider` / `OpenRouterProvider` / `LocalProvider` with `generate_structured` / `health_check` / `model_metadata`). NOT LangChain / LiteLLM in MVP domain.
- **RESOLVED — Provenance placement:** Normalized references (already in `Evidence`); no inline blob duplication, no TimescaleDB hypertable refs in v2.
- **RESOLVED — Sandbox guard owner:** `shared/safety/execution_guard.py` owns global invariant; `finance/` expresses financial rules only.
- **RESOLVED — Golden 50k/15k/35k freeze:** Canonical fixtures at `tests/fixtures/reconciliation/<type>/` with expectations at `tests/golden/reconciliation/<type>.yaml`.
- **RESOLVED — Go gate metric (criteria, not numeric):** Python-first; Go only on benchmark-proven latency/cost need. No numeric gate fixed in v2 scope; any Go proposal must define its numeric criterion.
