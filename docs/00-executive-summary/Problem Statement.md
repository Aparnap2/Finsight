# Problem Statement — Meridian Settlement Reconciliation

## What We Set Out to Solve (Meridian-Specific)

Meridian's finance team reconciles **settlement vs accounting vs expectation** daily across 6 systems. The business problem is not a missing ERP. It is **no continuous reasoning across systems** — a gap FinSight now fills as the Meridian Finance Resolution Agent.

### The Manual 13-Step Flow (Observed)

```
1. Razorpay payout received (gross)
2. Fees extracted (7,500)
3. Refunds extracted (2,500)
4. Adjustments extracted (10,000)
5. Net = gross - fees - refunds - adjustments (9,72,500) — manual Decimal
6. Expected looked up in Sheets (10,00,000)
7. QuickBooks entries checked (9,82,500)
8. Legacy batch checked (9,82,500)
9. Variance computed (10,000)
10. Gmail searched for context (fee notice? refund request? rejection?)
11. Legacy rejections inspected (499/500 accepted, 1 INVALID_ACCOUNT_CODE 4812)
12. Case history checked (prior FS for same merchant/batch)
13. Proposal drafted → Slack approval → Correction file → S3 → COBOL → result → re-reconcile → close
```

Steps 1-10 are mechanical but require domain judgment; steps 11-13 require human accountability. Today steps 1-12 are **manual**, error-prone, and scale linearly with merchant count.

### The Core Tension

| Current Approach | Why It Fails at 1,500 Merchants / 20k Payments Day |
|------------------|-----------------------------------------------------|
| **More analysts** | Linear cost, does not fix reasoning gap |
| **Spreadsheet automation** | Macros drift, no audit trail for variance math |
| **BI dashboards** | Show variance, not why; no hypothesis or evidence chain |
| **LLM copilot** | Generates plausible text but cannot guarantee INR arithmetic; hallucinates figures |
| **Generic ERP/reconciliation SaaS** | Assumes multi-tenant pluggability; Meridian needs COBOL fixed-width + S3 transport boundary, not a plugin platform |

### Existing Systems Own Facts — FinSight Was Missing

| Fact | Authority | FinSight Before |
|------|-----------|-----------------|
| Provider net 9,72,500 | Razorpay | Analyst reconciles by hand |
| Accounting 9,82,500 | QuickBooks (debits==credits, period open) | Analyst reconciles by hand |
| Legacy 9,82,500 (plus 499/1 rejection) | COBOL | Analyst inspects batch file by hand |
| Expected 10,00,000 | Sheets | Analyst looks up by hand |
| Context | Gmail | Analyst searches by hand |
| Approval | Slack → Human | Analyst chases by DM |

**Gap:** No system owned the **reasoning state** that ties these facts into a resolution: `FinancialSituation` → `Investigation` → `Evidence` → `Hypothesis` → `ResolutionProposal` → `PolicyDecision` → `Approval` → `Execution` → `Verification` → `Audit`. FinSight now owns exactly that — and nothing else.

### What a Solution Must Guarantee (Meridian-Specific)

1. **100% reconciliation accuracy.** `net_settlement`, `debits==credits`, variance are deterministic `Decimal`. Zero tolerance.
2. **Audit-grade traceability.** Every claim traces to an authoritative source via hash-verified `EvidenceItem`. Claims without evidence remain `HYPOTHESIS`.
3. **Hallucination-proof boundary.** LLM is restricted to: what is unusual, what to investigate, which hypothesis, is evidence enough. It never computes money, never approves, never executes.
4. **Company-specific policy enforced in code.** Refund <₹5k auto (if complete) / ₹5k-50k Manager / >₹50k Director; legacy always approval + valid code + balanced batch; closed period never modify — `MeridianBusinessRules`, not SaaS knobs.
5. **Legacy truth without HTTP.** Fixed-width batch via S3; control total + checksum; accepted/rejected/partial/duplicate semantics proven before close.
6. **Measurable resolution.** Cases detected/resolved, exposure ₹, false-positive rate, 100% verification, bounded LLM cost.

---

## Problem Statement (One Sentence — Frozen)

> Meridian's 8-person finance team spends 60-80% of settlement close time manually correlating Razorpay/QuickBooks/COBOL/Sheets/Gmail/Slack across 13 steps because no system owns continuous reasoning that can **detect a FinancialSituation (e.g. 10,00,000 vs 9,72,500 vs 9,82,500 variance 10,000) → investigate with evidence → propose a policy-gated resolution → execute via S3 batch → post-verify → close** with audit-grade proof, while existing systems remain the sole authorities for their facts.

## Success Criteria (Meridian)

| Criterion | Measure |
|-----------|---------|
| **Reconciliation accuracy** | 0% error on net_settlement / debits==credits / period checks |
| **Audit readiness** | Every INR claim traceable via `EvidenceItem` hash+provenance |
| **Hallucination rate** | 0% — LLM never produces unverified financial facts |
| **Resolution loop** | 13 manual steps → `Detect→...→Close` autonomous where policy allows |
| **Closed-period safety** | 100% — closed period modification blocked (deterministic gate) |
| **Legacy handling** | Partial (499/1) + duplicate correctly as one effect; control total mismatch fails closed |
| **Correctness measurement** | Golden FS-231 + P5 dimensions (grounding, investigation, security, control, financial, reliability) |

---
*Business Context details the Meridian dossier and environment diagram; Success Metrics defines the six measurement dimensions.*
