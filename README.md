# FinSight — Meridian Finance Resolution Agent

> **Frozen boundary:** Single-company internal system for **Meridian Commerce Pvt Ltd** (B2B commerce, ~1,500 merchants, 20k daily payments). FinSight is NOT generic SaaS, not multi-tenant product, not workflow builder, not plugin platform, not generic CFO. It does one job: **detect → investigate → explain → propose → execute (under authorization) → verify** financial discrepancy resolution for Meridian.

FinSight closes **FinancialSituations**, not transactions. Deterministic engines own every number; agents only gather evidence and draft proposals. No autonomous writes. Every close is evidence-backed, policy-gated, human-approved when required, and post-verified.

## Product Scope Decision — 2026-10-15 (Governing)

**COBOL is not a mandatory FinSight dependency.** The flagship workflow is Razorpay Test Mode + accounting records (QuickBooks or a clearly identified fixture/mock) + settlement reconciliation. COBOL-style fixed-width settlement processing and its S3 batch adapter are optional extensions, retained as reusable code pending a value assessment. Do not add COBOL-specific features or make the core workflow depend on a legacy ledger unless a concrete business scenario demonstrates material value and a testable resolution path.

FinSight's product value is the controlled financial-resolution loop: **detect → reconcile deterministically → investigate with traceable evidence → propose a typed resolution → enforce policy and required human approval → execute through an idempotent boundary → independently reread authoritative state → close only after verification**.

This scope decision does not relax safety invariants: deterministic money calculations, explicit authorization, proposal-bound approval, idempotency, immutable/auditable evidence, fail-closed behavior, and independent post-action verification remain mandatory. Existing COBOL/S3 code is not being deleted by this decision; it is simply not a required part of the flagship path.

## 1. Meridian Commerce Dossier — Frozen

| Attribute | Value |
|-----------|-------|
| **Company** | Meridian Commerce Pvt Ltd — B2B commerce platform |
| **Scale** | ~250 employees, ~1,500 active merchants, ~20,000 payments/day |
| **Finance team** | 8 finance, 3 payment-ops, Finance Manager + Director |
| **Systems of record** | **Razorpay** (provider/payment state), **QuickBooks** (accounting), **Google Sheets** (expected settlement where used), **Gmail** (context), **Slack** (human coordination/approval). COBOL/S3 is an optional legacy extension, not a core dependency. |

### Environment Diagram (core path; legacy adapter optional)

```
Razorpay Test Mode ──────┐
                         ├─> Deterministic reconciliation ─> FinancialSituation
Accounting records ──────┘                                  │
                                                            ▼
                                                Evidence-backed investigation
                                                            ▼
                                                Typed proposal + policy/HITL
                                                            ▼
                                                Idempotent test action
                                                            ▼
                                                Independent verification → Close

Optional extensions: expected-settlement records, context/approval connectors,
and the retained COBOL-style fixed-width/S3 adapter.
```

**Optional legacy adapter:** Existing fixed-width batch/S3 code can model accepted/rejected records, but it is outside the required flagship path. Keep it reusable; do not expand it without a demonstrated business need. FinSight owns reasoning state; **authoritative systems own facts**.

## 2. Business Problem — Not Missing ERP

Meridian does not lack an ERP. It lacks **continuous reasoning across 6 systems**. The flagship demonstration uses a bounded resolution loop: (1) ingest Razorpay Test Mode payment/settlement evidence, (2) compare it with accounting records and expected amounts, (3) create a durable discrepancy case, (4) investigate competing explanations against traceable evidence, (5) produce a typed resolution proposal, (6) apply deterministic policy and human approval where required, and (7) execute in the permitted test boundary, independently reread authoritative state, and close only after verification. Legacy batch inspection is an optional extension, not a prerequisite.

Mechanically 60-80% of 8-person finance team time; analytically starved; error-prone under month-end load.

## 3. FinSight Job — Meridian Finance Resolution Agent

> **Detect / Investigate / Explain / Propose / Execute-under-authorization / Verify** financial discrepancy resolution.

| What FinSight owns (reasoning state) | What FinSight NEVER owns (facts) |
|--------------------------------------|----------------------------------|
| `FinancialSituation` (e.g. FS-2026-0916-00231, variance ₹10,000, INVESTIGATING) | Razorpay provider state, QuickBooks accounting truth, expected records when used, contextual sources when used; optional COBOL ledger only when explicitly enabled |
| `Investigation`, `Evidence` (hash-verified), `Hypothesis`, `ResolutionProposal`, `PolicyDecision`, `Approval`, `Execution`, `Verification`, `Audit` | Slack is approval channel, not authority; Policy engine is authority |

**Central object:** `FinancialSituation` ≠ transaction. Example:

```
FS-2026-0916-00231
  expected: 10,00,000 (Sheet)
  razorpay: 9,72,500  (gross 10,00,000 - fee 7,500 - refund 2,500 - adjustment 10,000 - pending 7,500)
  quickbooks: 9,82,500
  optional legacy example: 9,82,500
  variance: 10,000  STATUS=INVESTIGATING
```

## 4. Cognitive Loop (frozen)

```
Detect → Triage → Investigate → Correlate → Explain → Propose → Policy → Auto/HITL → Execute → Verify → Close
   │        │          │            │           │         │        │          │          │       │
   └─net_settlement  tools: get_*  compare_  create_  propose_  refund <5k  Slack    S3 batch  re-reconcile
     debits==credits         + Gmail/Legacy financial_states hypothesis resolution auto?          file
     period_open                          record_evidence          5k-50k Mgr
     duplicate_action                                                  >50k Dir        → optional legacy adapter
                                                                       optional legacy adapter: approval + valid
                                                                       account code + balanced batch
                                                                       closed period: NEVER modify
```

**Deterministic vs LLM split (P3/P4 invariants preserved):**

| Deterministic (code, no LLM) | LLM (language only) |
|------------------------------|---------------------|
| `net_settlement = gross - fees - refunds - adjustments` | What is unusual about variance pattern? |
| `debits == credits` | Which hypothesis to test next? |
| `accounting_period_open(period_id)` | What to investigate? |
| `duplicate_action(action_hash)` | Is evidence sufficient? |
| `refund_threshold(amount)` → auto/manager/director | Narrative explanation for proposal |

LLM never computes money, never approves, never executes.

## 5. Company-Specific Rules (MeridianBusinessRules)

```python
# finance/business_rules/meridian.py (frozen, not SaaS knob)
REFUND_AUTO_THRESHOLD   = Decimal("5000")   # <5k auto if evidence complete
REFUND_MANAGER_THRESHOLD = Decimal("50000")  # 5k-50k Finance Manager
REFUND_DIRECTOR_THRESHOLD = Decimal("50000") # >50k Director
LEGACY_CORRECTION_REQUIRES = ["approval", "valid_account_code", "balanced_batch"]
CLOSED_PERIOD_RULE = "NEVER_MODIFY"
BASE_CURRENCY = "INR"
TOLERANCE_MINOR = Decimal("100")
AUTO_APPROVAL_LIMIT = Decimal("500000")
```

If the optional legacy adapter is enabled, legacy correction requires approval + valid account code + balanced batch. Closed period → hard block (`INVESTIGATING → EXECUTING` banned).

## 6. Agent Tools — Allowlists Only

**Read-only evidence tools (allowlisted):**
`get_settlement`, `get_payment`, `get_quickbooks_entries`, `get_expected_settlement`, `search_finance_email`, `get_legacy_batch`, `get_legacy_rejections`, `get_case_history`

**Cognitive tools:**
`create_hypothesis`, `record_evidence`, `compare_financial_states`, `propose_resolution`

**Banned (no `execute_sql`, `call_any_api`, `send_any_http`):**
Raw SQL, arbitrary HTTP, unsanctioned tools. Enforcement: `CapabilityExecutor` closed allowlist + `tenant_id`/`case` scope re-check.

## 7. Historical Legacy-Enabled Example FS-231 — Optional Extension

| Step | System | Value / Artifact |
|------|--------|------------------|
| Expected | Sheet | 10,00,000 |
| Razorpay | Provider | 9,72,500 (fee 7,500 + refund 2,500 + adjustment 10,000 = net 27,500) |
| QuickBooks | Accounting | 9,82,500 |
| Legacy | COBOL | 9,82,500 (mirrors QB) |
| Variance | FinSight | **10,000** → FinancialSituation FS-231 INVESTIGATING |
| Hypotheses | AI | H1 fee mismatch? H2 refund lag? H3 legacy rejection? (compare_financial_states) |
| Evidence | Batch | `LEGACY-20260916-0042` — 500 records, **499 accepted, 1 rejected `INVALID_ACCOUNT_CODE 4812`** (₹10,000) |
| Evidence chain | Recorded | `payment→settlement→qb→legacy→gmail→rejection→case_history` hashed + provenance |
| Proposal | ResolutionProposal | Reprocess ₹10,000, account code corrected, **severity Medium, HITL required** |
| Policy | MeridianBusinessRules | Legacy correction → approval needed → route to Slack |
| Approval | Slack | **Approved** (Manager) — pinned to proposal hash |
| Execution | S3 transport | `CORRECTION_20260916_231.DAT` (fixed-width, balanced, valid code) → optional legacy adapter |
| Result | Legacy | **ACCEPTED** (1/1) |
| Verification | Deterministic | Expected 10,00,000 vs (QB 9,82,500 + correction 10,000 + Razorpay pending 7,500) == 10,00,000? Recomputed net **9,92,500** ledger → **CLOSED** (verified) |

All amounts `Decimal`, all writes idempotent, post-verify mandatory. Unsafe-actions = 0.

## 8. Data Model — Simplification (frozen)

**Removed (SaaS-generic):** `Tenant`, `TenantConfiguration`, `CustomWorkflow`, `CustomPolicy`, `Plugin`, `ConnectorRegistry`, `WorkflowBuilder`, `CustomSchema`

**Replaced with (static, Meridian-specific):**

| Model | Purpose | File |
|-------|---------|------|
| `Company` | Single row: Meridian Commerce Pvt Ltd | `finance/domain/company.py` |
| `CompanyConfiguration` | `base_currency=INR`, `tolerance_minor=100`, `auto_approval=500000`, `legacy_correction_requires_approval=true` | `finance/domain/company.py` |
| `MeridianBusinessRules` | Refund tiers, legacy, closed-period invariants | `finance/business_rules/meridian.py` |
| `AccountMappings` | Razorpay ↔ QuickBooks ↔ COBOL codes (static) | `finance/domain/account_mappings.py` |
| `FinancialOntology` | Canonical variance/exceptions for Meridian | `finance/domain/ontology.py` |
| `IntegrationRegistry` | Fixed core: Razorpay + accounting records; contextual and legacy adapters are optional and not pluggable | `finance/integration/registry.py` |
| `FinancialSituation` | Central object (replaces generic transaction/investigation root) | `finance/domain/financial_situation.py` |

No per-tenant knobs at runtime. Config is code + migration, not UI.

## 9. Architecture — Core Payments/Accounting → FinSight (Legacy Optional)

```
Meridian Commerce (250 staff, 8 finance)
      │
      ├─ Payments: Razorpay (20k/day)
      ├─ Accounting: QuickBooks + Sheets (expected)
      └─ Optional: COBOL batch (fixed-width, S3; only if enabled)
                 │
                 ▼
         FinSight Core
     ┌─────────────────────┐
     │ Reconciliation (Decimal)  ── net_settlement, debits==credits, duplicate
     │ Evidence (hash-chain)     ── EvidenceItem immutability
     │ Business Rules (Meridian) ── refund tiers, legacy, closed period
     └──────────┬──────────┘
                │
         AI Investigator (LLM, bounded)
         create_hypothesis / compare_financial_states
                │
         Resolution Case (FinancialSituation FS-*)
                │
     ┌─────────┴─────────┐
   Policy Gate        HITL (Slack)
   Auto <5k           5k-50k Mgr, >50k Dir, legacy always
                │
          Action Engine (sandbox, idempotent)
                │
     External / Legacy (S3 fixed-width batch)
                │
            Verify (re-reconcile)
                │
             Close (Audit, immutable)
```

Dependency rule preserved: `shared ← finance ← agents ← apps`. No reverse imports.

## 10. FDE Story — How Meridian Gets Live

| Phase | What happens | Who |
|-------|--------------|-----|
| **Discovery (W1)** | Shadow 13-step manual flow, map 6 systems, freeze FS example, confirm optional adapter value | FDE + Finance + Payment Ops |
| **Solution Design (W2)** | FinancialSituation model, 11-stage loop, MeridianBusinessRules, IntegrationRegistry, controlled test boundary; assess optional adapter only if justified | Architect |
| **Build (W3-5)** | Deterministic engines → agent tools → Slack HITL → controlled test-boundary protocol → verifier → audit | Eng |
| **Deploy (W6)** | `API Gateway → FastAPI (apps/api) → durable state → bounded agent → test-mode action → independent verifier` (optional legacy adapter via S3 only when enabled) — healthchecks, RLS/company boundary isolation, secrets via env | DevSecOps |
| **Measure (W7+)** | Cases detected/resolved, exposure ₹, false-positive rate, LLM cost/call | FDE + Finance Lead |

**Measure gates:** `cases_detected`, `cases_resolved`, `exposure_value`, `false_positive_rate`, `llm_cost_per_case`, `verification_rate=100%`.

## 11. Safety Invariants (P3/P4 preserved, reinterpreted)

I1 Decimal-only. I2 Pure deterministic reconcile. I3 Evidence immutable. I4 LLM no writes. I5 Proposal needs `EVIDENCE_VERIFIED`. I6 Approval pinned to proposal hash, single-decision. I7 Idempotent execution. I8 Sandbox-only (test-mode boundary is mandatory; S3 transport is used only if optional legacy adapter is enabled). I9 Post-verify mandatory. I10 No close without terminal verification. **Boundary isolation = company/environment isolation** (not SaaS tenancy): every path carries `company_id=meridian` + `environment` scope.

## 12. Repo Map (updated)

```
finance/domain/          → Company, CompanyConfiguration, FinancialSituation, AccountMappings, FinancialOntology
finance/reconciliation/  → pure core: models, normalizer, matcher, tolerances, classifier, reconciler (Decimal)
finance/business_rules/  → meridian.py (refund tiers, legacy, closed period)
finance/integration/     → IntegrationRegistry (Razorpay/QB core; Sheets/Gmail/Slack/COBOL-S3 optional) static
finance/evidence/        → EvidenceItem (hash, provenance, immutability)
finance/accounting/     → sandbox provider boundary: adapter protocol + deterministic mock (no live provider)
finance/execution/       → guarded executor: intent row → write → post-verify (Decimal, CAS state machine)
finance/ingestion/       → webhook inbox + transactional outbox (at-least-once, claim/lease/fence)
finance/policy/          → deterministic execution policy gate (thresholds, approval binding)
finance/verification/    → single-pass verifier over recorded handoffs (readers, digest gate)
agents/investigation/    → allowlisted read-only + cognitive tools
agents/verification/     → 6-stage verifier (claim→evidence→tenant/company→provenance→supported→VERIFIED)
apps/api/                → ingest, evidence, approvals, close, execution, observation routes (FastAPI)
apps/workers/            → SQS transport worker (controlled execution)
python_runtime/          → Compute Runtime: dispatcher, handlers, exporters (duckdb/polars)
shared/safety/           → idempotency store, execution guard, durability, secrets scrubbing
tests/fixtures/reconciliation/ → FS-231 golden (10,00,000 / 9,72,500 / 9,82,500 / 10k)
tests/unit/property/      → property-based financial invariants (Hypothesis, test-only dep)
```

Flow: `shared` ← `finance` ← `agents` ← `apps`. No reverse imports.

## 13. Quickstart

```bash
uv sync --all-extras
uv run pytest tests/unit/reconciliation -x -q
uv run ruff check finance/reconciliation tests/unit/reconciliation
uv run mypy finance/reconciliation
# Deterministic golden-dataset gate (no provider calls):
uv run python -m finance.evaluation.runner \
  --dataset-id regression_forecast_naive \
  --dataset-id regression_anomaly_materiality \
  --dataset-id regression_duplicate_rows
```

`make test` mirrors the CI fast gate (`tests/unit` + `tests/contract`);
`make test-integration` runs the PG-gated tier; `make ci-local` runs the
whole fast gate locally. The FS-231 lifecycle golden lives at
`tests/unit/domain/test_fs231_lifecycle.py` — it is the optional
legacy-enabled example, not the flagship path.

## 14. Phases + Gates (frozen)

P0 frozen specs (this README/PRD). P1 pure `finance/reconciliation/` (stdlib + Decimal, no HTTP/DB/LLM). P2 Razorpay ingest. P3 QB mock + HITL + verify. P4 agent (thin SDKs: Groq/OpenRouter/Local via `LLMProvider`). P5 flagship E2E. P6 chaos (duplicate/out-of-order/crash-after-execute/double-approve/lost-response). P7 LLM evals offline (`finance/evaluation/` golden datasets; provider calls are manual-only). P8 runtime hardening (`python_runtime/`, `agents/p8_runtime/`). P9 hardening.

`S3` is artifact + legacy transport only; PostgreSQL is financial/idempotency authority. No new AWS service without queue gate.
