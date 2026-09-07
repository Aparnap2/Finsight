# FinSight PRD v2 — Agentic Payment Reconciliation & Exception Resolution

**Version:** 2.0 | **Status:** Frozen for P1 | **Branch:** `feat/finsight-v2-exception-resolution`
**Principle:** Deterministic systems establish financial truth. The agent enters only at evidence ambiguity. It proposes; policy, HITL, sandbox, idempotency, and deterministic post-verification retain control over money.

---

## 1. Problem

A payment succeeds, but systems disagree:

```text
Stripe:      ₹50,000 captured, ₹15,000 refunded → net ₹35,000
QuickBooks:  ₹50,000 recorded (refund missing)
Spreadsheet: ₹50,000 expected
Gmail:       customer requested partial refund
```

Traditional reconciliation detects *amounts don't match*. A human must still determine *why*: partial refund, fee, duplicate entry, payout timing, missing invoice, wrong mapping, manual adjustment. FinSight automates that cognitive layer while keeping money math, policy, execution, and verification deterministic.

FinSight is **not** an AI analyst, chatbot, BI tool, or ERP. It is an **exception-resolution system**: reconcile money movement across systems, assemble evidence, safely execute approved corrections in sandbox, verify, close.

## 2. Users

- **Primary: Finance / operations analyst** — triages exception queue; needs auto-matched clears, one-screen evidence packs, one-click safe actions, audit trail. FinSight removes repetitive cognitive assembly, not the human.
- **Secondary:** payment-ops team, controller, bookkeeper (approve/review); auditor (replay any verdict from frozen inputs + goldens).

## 3. Scope: 3 exception types only

1. **PARTIAL_REFUND_ACCOUNTING_LAG (flagship):** Stripe net (50k − 15k = 35k) vs QB ledger 50k → diff ₹15,000. Evidence: Stripe refund + QB receipt + Gmail request. Action: QB correcting entry ₹15,000 → re-verify 35k == 35k → CLOSED.
2. **FEE_MISMATCH:** Stripe fee vs QB expense vs Sheets schedule; tolerance `max(₹1.00, 0.5%)` tenant-injected, never hardcoded. Auto-propose if < ₹500 else analyst review.
3. **DUPLICATE_LEDGER_ENTRY:** 2× QB rows same `payment_id`, 1× Stripe charge (fingerprint idempotency). Action: void duplicate → verify single-net.

**Explicit non-goals:** ERP close, management packs, forecasts; Qdrant/vector memory; Redpanda/Kafka, Temporal, K8s; real QuickBooks/Gmail (sandbox fixtures + Mockoon only in MVP); Go services (Python-first, extraction only on P8 benchmark evidence).

## 4. Flagship workflow (9 cinematic steps)

1. Money moves: customer pays ₹50,000 (Stripe webhook).
2. Partial refund: ₹15,000 refunded in Stripe → expected net ₹35,000.
3. Accounting lags: QuickBooks still shows ₹50,000.
4. FinSight detects (deterministic, 0 LLM calls): expected ₹35,000 vs observed ₹50,000 → diff ₹15,000 → `PARTIAL_REFUND_ACCOUNTING_LAG`, status EXCEPTION, fingerprint.
5. Evidence assembled: Stripe refund event + QB receipt + Gmail request (normalized refs, content hashes).
6. Proposal: correcting accounting entry ₹15,000, reason + 3 verified sources; `ResolutionProposal ≠ Execution`, authorizes nothing.
7. Human approves (HITL shows evidence, impact, rationale).
8. Sandbox executes (Mock QB adapter, idempotency key, dry-run-first).
9. Post-verification re-reconciles: expected ₹35,000 == ledger ₹35,000 → `EXECUTION_VERIFIED` → CLOSED, audit complete, unsafe-autonomous-actions = 0.

## 5. Deterministic-first + agent ROI

| Work | Deterministic | Agent/LLM | ROI logic |
|------|---------------|-----------|-----------|
| Reconcile amounts, diffs | Owns, Decimal-only | Never touches numbers | Zero hallucination |
| Materiality + classification | Owns, tiered rules | None | Instant, auditable |
| Evidence gathering | Tool contracts own shape | Selects read-only tools | Bounded, fingerprintable |
| Root-cause narrative | Confidence formula owns score | Drafts hypotheses only | Capped on thin evidence |
| Commentary | Claim validator owns gate | Renders validated assertions | Blocks on fail |
| Proposal + close | Policy + HITL + sandbox + post-verify | Suggests template only | No autonomous writes |

Deterministic MVP must be demonstrably complete before P4: webhook → verify → dedup → normalize → reconcile → classify → evidence → proposal → policy → HITL → sandbox → post-verify → close, all with zero LLM calls. P4 only upgrades the `exception → investigation → assertions → proposal` segment for ambiguous evidence.

## 6. Safety invariants I1–I10 (compact)

I1 Decimal-only money, float rejected. I2 Reconciliation pure deterministic (no LLM/net/DB). I3 Raw evidence immutable. I4 LLM cannot execute writes. I5 Every proposal cites ≥1 `EVIDENCE_VERIFIED` record. I6 Approval bound to immutable proposal version/hash, single-decision. I7 Idempotent execution (same key+payload returns prior; diff payload REJECTED). I8 Sandbox-only MVP, real targets disabled. I9 Mandatory post-execution re-verification (`EXECUTING → POST_VERIFYING → EXECUTION_VERIFIED → CLOSED`). I10 No close without valid terminal verification.

Authority: deterministic core (read/classify yes, approve no, execute guarded); LLM investigator (evidence-only read, recommend, propose yes, approve/execute no); human (approve yes, execute indirectly); executor (sandbox only, prior approval required). State split: `EVIDENCE_VERIFIED` (pre-proposal) vs `EXECUTION_VERIFIED` (post-execution). Banned: `INVESTIGATING → EXECUTING`, `PROPOSED → EXECUTING`, `FAILED → CLOSED`.

## 7. KPIs

Autonomous resolution rate (target >70% on goldens); unsafe-action count = 0 (release gate); median time-to-close (<2 min standard); replay fidelity 100%; evidence completeness 100%.

## 8. OpsCore contrast

FinSight (truth engine: verified verdict + evidence + receipt; LLM 20% words-only; fails closed) vs OpsCore (ops console: risk scores/queues; LLM often decides; fails open). Interview line: OpsCore helps you *look*; FinSight helps you *prove*.

## 9. Milestones + P1 gate

P0 frozen (contracts + I1–I10 + split states). P1 pure `finance/reconciliation/` (stdlib + Decimal only, no HTTP/DB/LLM). P2 Stripe sandbox ingest. P3 QB mock + HITL + sandbox verify. P4 agentic investigation (thin direct SDKs: Groq/OpenRouter/Local behind `LLMProvider`). P5 flagship E2E `make e2e`. P6 chaos. P7 evals (promptfoo, offline). P8 Go benchmark (criteria, no numeric gate yet). P9 hardening + final gates.

**P1 gate:** `pytest tests/unit/reconciliation -q` + `ruff check` + `mypy --strict` green; exact match, partial-refund 50k/15k→35k EXCEPTION, fee boundary, duplicate fingerprint, Decimal-only/float-rejected, tolerance boundary, order independence, tenant tolerance injection — zero infra, zero LLM.
