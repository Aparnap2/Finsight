# FinSight v2 — Agentic Payment Reconciliation & Exception Resolution

> FinSight closes reconciliation exceptions, not dashboards. Deterministic engines own every number; agents only gather evidence and draft proposals. No autonomous writes. Every close is evidence-backed, policy-gated, human-approved, sandbox-executed, and post-verified.

FinSight is **not** an AI analyst, chatbot, BI tool, or ERP. It does one job: take a detected payment/accounting break to `CLOSED` with audit-grade proof.

## Architecture

```text
Webhook/Event → Dedup → Normalize → Deterministic Reconcile → Classify
      ├── MATCHED → CLOSED (auto, no LLM)
      └── EXCEPTION → INVESTIGATING → EVIDENCE_READY → EVIDENCE_VERIFIED
          → PROPOSED → AWAITING_APPROVAL → APPROVED → EXECUTING
          → POST_VERIFYING → EXECUTION_VERIFIED → CLOSED
              (REJECTED → CLOSED, FAILED → ESCALATED)
```

Ambiguity boundary: the agent may synthesize an investigation path and propose an action, but deterministic code owns money arithmetic, reconciliation, policy, transitions, execution authorization, idempotency, and post-verification. `ResolutionProposal ≠ Execution`.

## 80/20 scope

Deterministic (~80%): ingest, dedup, normalize, Decimal reconcile, tolerance/materiality, classification, policy, HITL queue, sandbox guard, idempotency, post-verify, audit. LLM (~20%): ambiguous classification assist, tool selection, evidence synthesis, hypothesis drafting, explanation. LLM never computes money, never approves, never executes.

Out for MVP: ERP close/packs/forecasts, Qdrant, Redpanda/Kafka, Temporal, K8s, real QB/Gmail (Mockoon + fixtures only), Go services (P8 benchmark decides).

## Flagship demo (60 seconds)

Stripe payout ₹50k, refund ₹15k → expected ₹35k; ledger still ₹50k → diff ₹15k `PARTIAL_REFUND_ACCOUNTING_LAG` → evidence (payout, refund, ledger line) → proposal (refund adjustment, policy-gated) → human approves → sandbox applies → post-verify `35k == 35k` → `CLOSED`, unsafe-actions = 0. Deterministic path uses zero LLM calls; P4 only upgrades ambiguous-evidence synthesis.

| Work | Deterministic | Agent/LLM |
|------|---------------|-----------|
| Reconcile, diffs | Owns, Decimal-only | Never touches numbers |
| Materiality/classify | Owns, tiered rules | None |
| Evidence gathering | Tool contracts own shape | Selects read-only tools |
| Narrative | Confidence formula owns score | Drafts hypotheses only |
| Proposal + close | Policy + HITL + sandbox + post-verify | Suggests template only |

## Safety invariants

I1 Decimal-only, float rejected. I2 Pure deterministic reconcile. I3 Evidence immutable. I4 LLM no writes. I5 Proposal needs `EVIDENCE_VERIFIED`. I6 Approval pinned to proposal hash, single-decision. I7 Idempotent execution. I8 Sandbox-only. I9 Post-verify mandatory. I10 No close without terminal verification. Banned: `INVESTIGATING → EXECUTING`, `PROPOSED → EXECUTING`, `FAILED → CLOSED`.

## Repo map

```text
finance/reconciliation/ → pure core: models, normalizer, matcher, tolerances, fingerprints, classifier, reconciler
shared/safety/ + shared/quality/ → execution_guard, idempotency, approval_gate; assertion/evidence validators, confidence
finance/policy/ → refund / correcting-entry / void / fee rules
agents/ → read-only evidence + proposal drafters (no writes)
apps/api/ → ingest, evidence, approvals, close routes
tests/fixtures/reconciliation/ + tests/golden/reconciliation/ → 50k/15k/35k + fee + duplicate goldens
```

Flow: `shared` ← `finance` ← `agents` ← `apps`. No reverse imports.

## Quickstart (P1-only, no Docker / no LLM)

```bash
uv sync
uv run python -m pytest tests/unit/reconciliation -x -q
uv run ruff check finance/reconciliation tests/unit/reconciliation
uv run mypy finance/reconciliation
```

## Phases + gates

P0 frozen specs. P1 pure core. P2 Stripe ingest. P3 QB mock + HITL + verify. P4 agent (thin direct SDKs: Groq/OpenRouter/Local). P5 `make e2e` flagship. P6 chaos (duplicate/out-of-order/crash-after-execute/double-approve/lost-response). P7 promptfoo evals offline. P8 Go benchmark (criteria only). P9 hardening: ruff, mypy strict, full pytest, secret scan, dependency audit, migration check, idempotency + degraded-mode proofs, unsafe = 0.
