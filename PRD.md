# FinSight PRD v3 — Meridian Finance Resolution Agent (Frozen)

**Version:** 3.0 | **Status:** Frozen — single-company internal system | **Company:** Meridian Commerce Pvt Ltd | **Branch:** `feat/meridian-resolution-agent`
**Principle:** Existing systems own facts; FinSight owns reasoning state. Deterministic systems establish financial truth. The agent enters only at evidence ambiguity. It proposes; policy, HITL, sandbox/S3, idempotency, and deterministic post-verification retain control over money.

---

## 1. Company Dossier — Meridian Commerce Pvt Ltd

| Field | Value |
|-------|-------|
| **Industry** | B2B commerce platform |
| **Scale** | ~250 employees, ~1,500 merchants, ~20,000 payments/day via Razorpay |
| **Finance** | 8 finance, 3 payment-ops, Finance Manager (approver ₹5k–50k), Director (>₹50k) |
| **Environment** | Razorpay (provider state) + QuickBooks (accounting) + Google Sheets (expected settlement) + Gmail (context) + Slack (approval) + COBOL legacy settlement ledger (fixed-width batch file, **no HTTP**, S3 transport) |

**Environment is frozen.** No plugin platform, no connector builder.

```
Razorpay ←settlement→ QuickBooks ←batch→ COBOL (fixed-width, 500 recs, via S3) 
     ↕                    ↕                    ↕
 Sheets (expected 10,00,000)  Gmail (context)  Slack (Approve/Reject)
```

## 2. Problem — Manual Settlement Reconciliation (13 Steps)

Meridian does not lack an ERP. It lacks **continuous reasoning across systems**.

Daily flow is manual:

1. Razorpay payout lands (gross)
2. Fees/refunds/adjustments extracted
3. Expected looked up in Sheets
4. QuickBooks entries checked
5. COBOL batch checked
6. Variance = Expected − (QB + Legacy correlated) computed
7. Gmail searched for context (refund request, fee notice)
8. Hypotheses formed (fee mismatch? refund lag? legacy rejection?)
9. Legacy rejections inspected (`get_legacy_rejections`)
10. Case history checked (`get_case_history`)
11. Proposal drafted
12. Approval chased on Slack
13. Correction file built → S3 → COBOL → result polled → re-reconciled → closed

Finance spends 60-80% of time on steps 1-10; strategic analysis starved; month-end errors spike.

## 3. FinSight Job — Meridian Finance Resolution Agent

> **Detect / Investigate / Explain / Propose / Execute-under-authorization / Verify** financial discrepancy resolution.

FinSight is **not** AI analyst, chatbot, BI tool, ERP, generic CFO, or workflow builder. It is the **resolution agent** that takes a detected discrepancy to `CLOSED` with audit-grade proof.

**Authority split (frozen):**

| Owner | Owns (facts) | Never owns |
|-------|--------------|------------|
| Razorpay | Provider state (capture, fee, refund, adjustment) | Accounting truth |
| QuickBooks | Accounting truth (journal, debits==credits, period open/closed) | Provider state |
| COBOL Legacy | Legacy settlement truth (accepted/rejected per batch, fixed-width) | HTTP API |
| Sheets | Expected settlement (business expectation) | Execution |
| Gmail / Slack | Context / Approval signal | Authority |
| **FinSight** | **Reasoning state only:** `FinancialSituation`, `Investigation`, `Evidence`, `Hypothesis`, `ResolutionProposal`, `PolicyDecision`, `Approval`, `Execution`, `Verification`, `Audit` | **Facts** — it correlates, never invents |

**Central object:** `FinancialSituation` (not transaction). Example:

```
FinancialSituation FS-2026-0916-00231
  status: INVESTIGATING
  expected: 10,00,000 (Sheets)
  razorpay_net: 9,72,500  [10,00,000 - 7,500 fee - 2,500 refund - 10,000 adjustment - 7,500 pending]
  quickbooks: 9,82,500
  legacy: 9,82,500
  variance: 10,000
```

Variance is deterministic; FinSight reasons about **why**.

## 4. Scope — Meridian Only

**In (frozen):**

- Settlement vs expected vs QuickBooks vs Legacy reconciliation (Decimal, tolerance `100` minor)
- FinancialSituation lifecycle: `DETECTED → INVESTIGATING → EVIDENCE_READY → PROPOSED → POLICY_GATED → AWAITING_APPROVAL → APPROVED → EXECUTING → POST_VERIFYING → VERIFIED → CLOSED`
- MeridianBusinessRules: refund <₹5k auto (if evidence complete), ₹5k–50k Manager, >₹50k Director; legacy correction always approval + valid account code + balanced batch; closed period → hard block
- Agent tools read-only + cognitive (allowlisted)
- Slack HITL, S3 fixed-width batch transport, deterministic post-verify
- FS-231 flagship (see §6)

**Explicit non-goals (frozen):** Multi-tenant SaaS, Tenant/Plugin/WorkflowBuilder/CustomSchema UIs, Qdrant, Redpanda/Kafka, Temporal, K8s (until proven), real ERP close/packs/forecasts, Go services (P8 benchmark), arbitrary `execute_sql`/`call_any_api`/`send_any_http`, new AWS services (S3 stays transport only).

## 5. Flagship Workflow — 11-Stage Cognitive Loop

```
Detect → Triage → Investigate → Correlate → Explain → Propose → Policy → Auto/HITL → Execute → Verify → Close
```

1. **Detect** — deterministic `net_settlement`, `debits==credits`, `accounting_period_open`, `duplicate_action` → create `FinancialSituation` FS-231 INVESTIGATING (variance 10k)
2. **Triage** — severity Medium
3. **Investigate** — agent selects `get_settlement`, `get_quickbooks_entries`, `get_expected_settlement`, `search_finance_email`, `get_legacy_batch`, `get_legacy_rejections`, `get_case_history` (read-only)
4. **Correlate** — `compare_financial_states` (10,00,000 vs 9,72,500 vs 9,82,500)
5. **Explain** — `create_hypothesis` 1-3 hypotheses, `record_evidence` (hash-chain)
6. **Propose** — `propose_resolution` → ResolutionProposal (reprocess 10k, corrected account 4812) — `ResolutionProposal ≠ Execution`
7. **Policy** — MeridianBusinessRules: legacy → HITL required
8. **Auto/HITL** — Slack Approve (pinned to proposal hash, single-decision)
9. **Execute** — idempotent, sandbox/S3: `CORRECTION_20260916_231.DAT` via `finsight-legacy-outbound` bucket
10. **Verify** — deterministic re-reconcile: 9,92,500 + pending 7,500 = 10,00,000 → EXECUTION_VERIFIED
11. **Close** — CLOSED + immutable audit

**Deterministic-first ROI:**

| Work | Deterministic | LLM |
|------|---------------|-----|
| Reconcile, diffs, net_settlement | Owns (Decimal) | Never touches numbers |
| Materiality / classify | Owns | None |
| Evidence gathering | Tool contracts own shape | Selects read-only tools |
| Narrative | Confidence formula | Drafts hypotheses only |
| Proposal + close | Policy + HITL + S3 + post-verify | Suggests template only |

Deterministic MVP must be demonstrably complete before P4: webhook→verify→dedup→normalize→reconcile→classify→evidence→proposal→policy→HITL→S3→post-verify→close, zero LLM calls for §6 fee-type cases. P4 upgrades ambiguous-evidence synthesis only.

## 6. Safety Invariants I1–I10 (compact, preserved)

I1 Decimal-only. I2 Pure deterministic reconcile. I3 Evidence immutable. I4 LLM no writes. I5 Proposal needs `EVIDENCE_VERIFIED`. I6 Approval bound to immutable proposal hash, single-decision. I7 Idempotent execution. I8 Sandbox/S3-only, real targets disabled (legacy via S3 is the sandbox boundary). I9 Mandatory post-execution re-verification. I10 No close without terminal verification.

**Company/environment boundary isolation** (reinterprets former tenant isolation): every path carries `company_id=meridian` + `environment` scope; store prefixes `{company_id}/{case_id}/...`; RLS `app.company_id`. Cross-company attempts fail closed `CompanyIsolationError` (formerly `TenantIsolationError`).

Banned transitions: `INVESTIGATING → EXECUTING`, `PROPOSED → EXECUTING`, `FAILED → CLOSED`.

## 7. KPIs — Meridian-Specific (Measure Phase)

| Metric | Target | Source |
|--------|--------|--------|
| Cases detected / resolved | Trend up | FinancialSituation count |
| Exposure ₹ (sum variance) | Trend down | variance aggregation |
| False-positive rate | <5% | verifier vs human override |
| LLM cost per case | Bounded (≤3 calls) | `shared/llm` budget |
| Verification rate | 100% (no close without verify) | verifier invariant |
| Replay fidelity | 100% | golden datasets |

OpsCore contrast preserved: truth engine (verified verdict + evidence + receipt; LLM 20% words-only; fails closed) vs ops console (risk scores/queues).

## 8. Milestones + P1 Gate

P0 frozen (contracts + I1–I10 + FS model). P1 pure `finance/reconciliation/` (stdlib + Decimal). P2 Razorpay sandbox ingest. P3 QB mock + HITL + verify. P4 agentic investigation (thin SDKs Groq/OpenRouter/Local via `LLMProvider`). P5 flagship E2E `make e2e` FS-231. P6 chaos (duplicate/out-of-order/crash-after-execute/double-approve/lost-response/legacy partial). P7 promptfoo evals offline. P8 Go benchmark (criteria). P9 hardening.

**P1 gate:** `pytest tests/unit/reconciliation -q` + `ruff check` + `mypy --strict` green; exact match, FS-231 net 10,00,000→9,72,500→9,82,500 variance 10k, fee boundary, duplicate fingerprint, Decimal-only, tolerance boundary, order independence, company tolerance injection (`CompanyConfiguration`) — zero infra, zero LLM.

## 9. Data Model Simplification (frozen)

```
REMOVED: Tenant, TenantConfiguration, CustomWorkflow, CustomPolicy, Plugin,
         ConnectorRegistry, WorkflowBuilder, CustomSchema
ADDED:   Company (single Meridian row)
         CompanyConfiguration { base_currency: INR, tolerance_minor: 100,
                                auto_approval: 500000, legacy_correction_requires_approval: true }
         MeridianBusinessRules (refund tiers, legacy, closed period)
         AccountMappings (Razorpay ↔ QB ↔ COBOL static)
         FinancialOntology (variance types)
         IntegrationRegistry (Razorpay, QuickBooks, Sheets, Gmail, Slack, COBOL/S3 — static)
         FinancialSituation (central object)
```

No SaaS knobs. Config is code + Alembic migration, not UI.

## 10. Risks (Meridian-specific)

| Risk | Mitigation |
|------|------------|
| Sheets expected is business-owned (human error) | Cross-check vs Razorpay gross; evidence hash |
| COBOL batch is half-unknown until result file | Protocol `LEGACY_BATCH_PROTOCOL.md` + control total + checksum |
| Gmail/Sheets free text prompt injection | Conext builder treats as DATA, never instruction (corpus) |
| Slack approval phishing | Approval pinned to proposal hash; no Gmail-passed approvals |

---

*FinSight is Meridian's resolution agent. It does not own facts — it proves resolution of FinancialSituations with evidence, policy, and verification.*
