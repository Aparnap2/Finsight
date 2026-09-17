# Business Context — Meridian Commerce Pvt Ltd (Frozen)

## Company Dossier

| Attribute | Detail |
|-----------|--------|
| **Company** | **Meridian Commerce Pvt Ltd** — B2B commerce platform |
| **Scale** | 250 employees, ~1,500 merchants, ~20,000 payments/day |
| **Finance** | 8 finance team members, 3 payment-ops, Finance Manager + Director |
| **Base currency** | INR (`CompanyConfiguration.base_currency`) |
| **Fiscal calendar** | April–March (configured in `Company.fiscal_year_start`) |

### Systems of Record (Frozen Environment Diagram)

```
                    Meridian Commerce Pvt Ltd
                              │
   ┌──────────────┬───────────┼───────────┬──────────────┬──────────────┐
   │              │           │           │              │              │
Razorpay      QuickBooks   COBOL Legacy  Google Sheets  Gmail          Slack
(Payments)    (Accounting) (Settlement   (Expected       (Context)      (Approval)
              [Authority]   Ledger)      Settlement)                    Human HITL
- payouts       - Journal     - Fixed-width  - Business    - search_     - Approve/Reject
- fees 7,500      entries       batch file     expectation    finance_      pinned to
- refunds 2,500    debits==      NO HTTP         10,00,000      email         proposal hash
- adjustments     credits       via S3          per day       (read-only)
  10,000        - Period        transport
                open/closed
     ▲              ▲              ▲
     │              │              │
     └──────────────┼──────────────┘
                    ▼
           FinSight Core
   Reconciliation (Decimal) — net_settlement, debits==credits
   Evidence (hash-chain)   — EvidenceItem immutability
   Business Rules (Meridian) — refund tiers, legacy, closed period
                    │
           AI Investigator (bounded, cognitive tools only)
                    │
           FinancialSituation (central object)
```

**Constraint:** COBOL legacy has no HTTP. FinSight writes `CORRECTION_YYYYMMDD_XXX.DAT` (fixed-width, 500 records, control total + hash) to S3 bucket `finsight-legacy-outbound`; legacy polls S3, processes, writes result file to `finsight-legacy-result`; FinSight ingests result, re-reconciles, closes. PostgreSQL remains financial/idempotency authority; S3 is transport only (same as `add-ministack-s3-contract`).

### Who FinSight Serves

- **Primary:** Finance analyst (owns FinancialSituation queue; needs one-screen evidence packs, one-click safe actions, audit trail)
- **Secondary:** Payment-ops (settlement breaks), Finance Manager/Director (approvers per MeridianBusinessRules), Auditor (replay FS-231 from frozen inputs + goldens)

## Engagement Scope — Meridian Finance Resolution Agent

FinSight's frozen job is **detect/investigate/explain/propose/execute-under-authorization/verify** financial discrepancy resolution — not variance packs, not forecasting, not generic CFO work.

It operates on **FinancialSituation** (not transaction) — the reasoning state Meridian owns:

```
FinancialSituation FS-2026-0916-00231
  expected: 10,00,000 (Sheets authority)
  razorpay_net: 9,72,500 (Razorpay authority: gross - fee - refund - adjustment)
  quickbooks: 9,82,500 (QuickBooks authority)
  legacy: 9,82,500 (COBOL authority)
  variance: 10,000 (FinSight correlates, deterministic maths)
  status: INVESTIGATING → ... → CLOSED (verified)
```

FinSight owns: `FinancialSituation`, `Investigation`, `Evidence` (hash-verified, provenance), `Hypothesis`, `ResolutionProposal`, `PolicyDecision`, `Approval`, `Execution`, `Verification`, `Audit`.

Existing systems own facts (provider state, accounting, legacy, expected, context, approval signal). FinSight never invents a fact; it correlates authoritative facts into a provable resolution.

## Architecture Freeze (Post Phase 3 + Meridian Bound)

- **Deterministic engines:** `net_settlement`, `debits==credits`, `accounting_period_open`, `duplicate_action`, `refund_threshold` are code. No LLM math.
- **LLM:** What is unusual, what to investigate, which hypothesis, is evidence enough — bounded, typed candidates only.
- **Data model:** `Company`/`CompanyConfiguration`/`MeridianBusinessRules`/`AccountMappings`/`FinancialOntology`/`IntegrationRegistry` — static, not SaaS knobs. `Tenant`/`Plugin`/`WorkflowBuilder`/`CustomSchema` removed.
- **Success measured by:** cases detected/resolved, exposure ₹, false-positive rate, LLM cost (see `docs/00-executive-summary/Success Metrics.md`).

---
*This document replaces the generic FP&A cycle narrative. Meridian's problem is settlement reconciliation across 6 systems, not close-cycle packaging.*
