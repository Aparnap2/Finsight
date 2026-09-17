# Meridian Process Model — P6-01 Domain Contract (Frozen)

**Status:** Frozen domain contract for Meridian Commerce Pvt Ltd.
**Scope:** Single-company internal system (`company_id = meridian`).
**Currency:** INR everywhere. Money is Decimal-concept. Floats forbidden.
**Boundary:** Product boundary frozen. See `company.md`, PRD v3, project.md.

`tenant_id` wherever it appears in older code or docs means
`company_id = meridian` plus `environment` (dev / staging / prod).
There is no multi-tenant product and no tenant switcher.

---

## 1. Canonical Entities

FinSight owns reasoning state. Existing systems own facts.
All money fields below are Decimal-concept with 2 decimal places.

### 1.1 Merchant

Merchant onboarded on the Meridian B2B commerce platform (~1500 total).

| Field | Type | Notes |
|-------|------|-------|
| `merchant_id` | `str` | Stable Meridian merchant key |
| `company_id` | `str` | Always `meridian` |
| `name` | `str` | Legal / trading name |
| `status` | `str` | `ACTIVE`, `SUSPENDED`, `CLOSED` |
| `onboarded_on` | `date` | First settlement eligibility date |

### 1.2 Payment

One Razorpay capture settled toward a merchant (~20k / day).

| Field | Type | Notes |
|-------|------|-------|
| `payment_id` | `str` | Razorpay payment id (provider truth) |
| `company_id` | `str` | Always `meridian` |
| `merchant_id` | `str` | Payee merchant |
| `gross_amount` | `Decimal` | Gross captured, INR |
| `fee_amount` | `Decimal` | Razorpay fee slice, INR |
| `net_amount` | `Decimal` | Gross minus fee, deterministic |
| `captured_at` | `datetime` | Provider timestamp |
| `status` | `str` | `CAPTURED`, `REFUNDED`, `ADJUSTED` |

### 1.3 Refund

Refund issued against a captured payment (provider truth).

| Field | Type | Notes |
|-------|------|-------|
| `refund_id` | `str` | Razorpay refund id |
| `company_id` | `str` | Always `meridian` |
| `payment_id` | `str` | Parent payment |
| `amount` | `Decimal` | Refund amount, INR |
| `issued_at` | `datetime` | Provider timestamp |
| `reason` | `str` | Reason code / note |

### 1.4 SettlementBatch

One expected-settlement window reconciled against provider
state, accounting truth, and legacy truth.

| Field | Type | Notes |
|-------|------|-------|
| `batch_id` | `str` | `LEGACY-YYYYMMDD-NNNN` for legacy leg |
| `company_id` | `str` | Always `meridian` |
| `environment` | `str` | dev / staging / prod |
| `expected_total` | `Decimal` | Sheets expected settlement, INR |
| `razorpay_net` | `Decimal` | Provider net, deterministic |
| `quickbooks_total` | `Decimal` | Accounting total, INR |
| `legacy_total` | `Decimal` | Legacy accepted total, INR |
| `control_total` | `Decimal` | Sum of record amounts, 2 dp |
| `status` | `str` | `OPEN`, `PARTIAL`, `ACCEPTED`, `REJECTED` |

### 1.5 LedgerEntry

One double-entry line in QuickBooks or one fixed-width
record in the COBOL legacy ledger.

| Field | Type | Notes |
|-------|------|-------|
| `entry_id` | `str` | QB entry id or `batch_id:sequence` |
| `company_id` | `str` | Always `meridian` |
| `source` | `str` | `quickbooks` or `cobol_legacy` |
| `account_code` | `str` | Static AccountMappings code |
| `debit` | `Decimal` | Debit leg, INR |
| `credit` | `Decimal` | Credit leg, INR |
| `period` | `str` | Accounting period (closed blocks) |

Debits must equal credits per batch. Closed periods never mutate.

### 1.6 FinancialSituation

Central object of FinSight. One detected discrepancy, one case.

| Field | Type | Notes |
|-------|------|-------|
| `id` | `str` | `FS-YYYYMMDD-NNNNN`, e.g. FS-231 |
| `company_id` | `str` | Always `meridian` |
| `variance` | `Decimal` | Expected minus correlated, INR |
| `expected` | `Decimal` | Sheets figure, INR |
| `razorpay_net` | `Decimal` | Provider net, INR |
| `quickbooks` | `Decimal` | Accounting figure, INR |
| `legacy` | `Decimal` | Legacy figure, INR |
| `status` | `str` | Lifecycle state (§2) |
| `evidence_ids` | `list[str]` | Immutable hash-chained evidence |
| `hypothesis_ids` | `list[str]` | Ranked hypotheses |
| `proposal_id` | `str \| None` | At most one active proposal |
| `approval` | `Approval \| None` | Slack HITL, hash-pinned |
| `execution` | `ExecutionRecord \| None` | S3 batch execution |
| `verification` | `VerificationReport \| None` | Re-reconcile verdict |

### 1.7 ResolutionProposal

What FinSight suggests. A proposal is never an execution.

| Field | Type | Notes |
|-------|------|-------|
| `proposal_id` | `str` | Stable id per situation version |
| `company_id` | `str` | Always `meridian` |
| `situation_id` | `str` | Parent FinancialSituation |
| `action` | `str` | E.g. `REPROCESS_LEGACY_RECORD` |
| `amount` | `Decimal` | Correction amount, INR |
| `account_code` | `str` | Corrected code, e.g. `4812` |
| `proposal_hash` | `str` | Immutable hash; approval pins this |
| `status` | `str` | `DRAFT`, `PROPOSED`, `APPROVED`, `REJECTED` |

### 1.8 Approval

Human decision on Slack, bound to one immutable proposal hash.

| Field | Type | Notes |
|-------|------|-------|
| `approval_id` | `str` | Slack signal id |
| `company_id` | `str` | Always `meridian` |
| `proposal_hash` | `str` | Must match proposal exactly |
| `decider` | `str` | Manager (5k-50k) or Director (>50k) |
| `decision` | `str` | Single `APPROVE` or `REJECT` |
| `decided_at` | `datetime` | Slack timestamp |

One decision per proposal hash. Double-approve is rejected.

### 1.9 ExecutionRecord

Deterministic S3 transport of a fixed-width correction file.

| Field | Type | Notes |
|-------|------|-------|
| `execution_id` | `str` | Idempotency key (proposal hash) |
| `company_id` | `str` | Always `meridian` |
| `batch_id` | `str` | New or reused legacy batch id |
| `s3_key` | `str` | `{company_id}/{batch_id}/CORRECTION_*.DAT` |
| `control_total` | `Decimal` | Batch control total, INR |
| `result` | `str` | `ACCEPTED`, `PARTIAL`, `REJECTED` |

Idempotent on `(company_id, proposal_hash, batch_id)`.

### 1.10 VerificationReport

Deterministic post-execution re-reconcile. Required to close.

| Field | Type | Notes |
|-------|------|-------|
| `report_id` | `str` | Re-reconcile run id |
| `company_id` | `str` | Always `meridian` |
| `situation_id` | `str` | Parent FinancialSituation |
| `legacy_total_after` | `Decimal` | Legacy total after accept, INR |
| `variance_after` | `Decimal` | Residual variance, INR |
| `verdict` | `str` | `EXECUTION_VERIFIED` or `FAILED` |

No `CLOSED` without `EXECUTION_VERIFIED`.

---

## 2. FinancialSituation Lifecycle

Canonical forward chain:

```text
DETECTED -> TRIAGED -> INVESTIGATING -> CORRELATED -> EXPLAINED
  -> PROPOSED -> APPROVED -> EXECUTING -> VERIFYING -> CLOSED
```

Side states: `ESCALATED` (needs higher authority) and
`REJECTED` (terminal, proposal refused). Both can re-enter
the chain only via a new proposal version.

### 2.1 Allowed Transitions

| From | To | Gate |
|------|----|------|
| `DETECTED` | `TRIAGED` | Deterministic severity assigned |
| `TRIAGED` | `INVESTIGATING` | Investigation opened |
| `INVESTIGATING` | `CORRELATED` | States compared deterministically |
| `CORRELATED` | `EXPLAINED` | 1-3 hypotheses with evidence |
| `EXPLAINED` | `PROPOSED` | Proposal with `EVIDENCE_VERIFIED` |
| `PROPOSED` | `APPROVED` | Slack approve pinned to hash |
| `PROPOSED` | `REJECTED` | Slack reject (terminal for version) |
| `APPROVED` | `EXECUTING` | Idempotent S3 upload started |
| `EXECUTING` | `VERIFYING` | Legacy result file parsed |
| `VERIFYING` | `CLOSED` | `EXECUTION_VERIFIED`, residual ~0 |
| `VERIFYING` | `INVESTIGATING` | `FAILED` verdict, re-investigate |
| Any active | `ESCALATED` | Amount / risk exceeds decider |
| `ESCALATED` | `INVESTIGATING` | Higher decider takes ownership |
| `ESCALATED` | `PROPOSED` | Revised proposal under new decider |

### 2.2 Banned Transitions

- `INVESTIGATING -> EXECUTING` (no execution without proposal).
- `PROPOSED -> EXECUTING` (no execution without approval).
- `VERIFYING -> CLOSED` on `FAILED` verdict (re-investigate first).
- Any state `-> CLOSED` without terminal verification.
- Closed-period ledger mutation, at any state, is hard-blocked.

---

## 3. Discrepancy Taxonomy

All variances are Decimal-computed. The agent reasons about why.

| Code | Name | Meaning | Detection source |
|------|------|---------|------------------|
| `I-REFUND-LAG` | Refund lag | Refund in provider, missing in QB | `net_settlement` + QB diff |
| `I-FEE-DRIFT` | Fee drift | Fee slice differs from expectation | `net_settlement` + Sheets |
| `I-DUPLICATE` | Duplicate | Same action / fingerprint twice | `duplicate_action` check |
| `I-LEGACY-REJECT` | Legacy reject | COBOL record rejected (e.g. code) | `get_legacy_rejections` |
| `I-CONTROL-MISMATCH` | Control mismatch | Batch totals differ | Control total + checksum |
| `I-TIMING` | Timing difference | Period cut-off, not a real loss | `accounting_period_open` |
| `I-ADJUSTMENT` | Adjustment | Provider adjustment not in QB | `compare_financial_states` |

Notes:

- `I-LEGACY-REJECT` carries the COBOL reason string verbatim,
  e.g. `INVALID_ACCOUNT_CODE`, plus the offending account code.
- `I-CONTROL-MISMATCH` fails closed. No partial acceptance.
- `I-DUPLICATE` matches on idempotency fingerprint, never on
  amount equality alone.

---

## 4. Worked Example — FS-231 End to End

Situation `FS-2026-0916-00231`, Meridian, INR, Decimal only.

### 4.1 Detection

- Sheets expected settlement: `1000000`.
- Razorpay gross `1000000` decomposes deterministically:
  fee `7500` + refund `2500` + adjustment `10000` + pending
  `7500`, leaving provider net `972500`.
- QuickBooks total: `982500`.
- Legacy accepted total: `982500`.
- Provider → Books gap (actionable variance):
  `982500 - 972500 = 10000`.
- Expected → Books gap: `1000000 - 982500 = 17500`
  (`7500` timing item + `10000` unexplained discrepancy).
- State `DETECTED -> TRIAGED` (severity Medium).

### 4.2 Investigation and correlation

- Read-only tools: settlement, QB entries, expected
  settlement, finance email, legacy batch, legacy
  rejections, case history.
- `compare_financial_states`: `1000000` vs `972500`
  vs `982500` vs `982500`.
- Legacy batch `LEGACY-20260916-0042`: 500 records sent,
  499 accepted, 1 rejected.
- Rejected record reason: `INVALID_ACCOUNT_CODE`, code
  `4812` expected on the correction leg.

### 4.3 Explanation and proposal

- Hypothesis: legacy rejection of the `10000` correction
  leg under a wrong account code explains the residual.
- Evidence hash-chained: batch file, result file, QB
  entries, Sheets cell, email context.
- Proposal: reprocess `10000` under corrected account
  code `4812` via a `CORRECTION` batch. Proposal hashed.
- State `CORRELATED -> EXPLAINED -> PROPOSED`.

### 4.4 Approval and execution

- Policy: legacy correction always needs human approval
  plus valid account code plus balanced batch.
- Slack approval pinned to the immutable proposal hash.
  Single decision. State `PROPOSED -> APPROVED`.
- Execution uploads `CORRECTION_20260916_231.DAT` via S3
  key `{company_id}/{batch_id}/...` in bucket
  `finsight-legacy-outbound`. Idempotent on proposal hash.
- State `APPROVED -> EXECUTING`.

### 4.5 Verification and close

- COBOL result file polled from `finsight-legacy-result`.
  Correction record returns `ACCEPTED`.
- Deterministic re-reconcile: legacy total now `992500`;
  `992500 + 7500` pending equals `1000000` expected.
- Residual variance within tolerance `100`. Verdict
  `EXECUTION_VERIFIED`. State `VERIFYING -> CLOSED`.
- Immutable audit appended. No close without verification.

---

## 5. Integration Authorities

FinSight correlates. It never invents facts.

| System | Owns this truth | FinSight read | FinSight write |
|--------|-----------------|---------------|----------------|
| Razorpay | Provider state: capture, fee, refund, adjustment | Read-only SDK | Never writes |
| QuickBooks | Accounting truth: journals, balance, period | Read-only entries | Never writes |
| Google Sheets | Expected settlement (business view) | Read expected cell | Never writes |
| Gmail | Context only (refund request, fee note) | Search as DATA | Never sends |
| Slack | Approval signal (human decision) | Read decision | Posts proposal only |
| COBOL ledger | Legacy settlement truth per batch | Read result file | S3 `CORRECTION` file |

Rules:

- Gmail content is untrusted DATA, never instruction.
- Slack approval must pin the proposal hash; Gmail
  approvals are never accepted.
- COBOL has no HTTP. S3 file transport is the only path.
- S3 keys are prefixed `{company_id}/{case_id}/...` and
  isolated by `company_id = meridian` plus environment.

---

## 6. Explicit Non-Goals

- No generic SaaS product. No multi-tenant onboarding,
  no tenant switcher, no per-customer configuration UI.
- No multi-company consolidation. One company row:
  Meridian Commerce Pvt Ltd.
- No plugin platform, connector builder, workflow
  builder, custom schema, or custom policy UI. Config is
  code plus migration plus review.
- The LLM never computes money. All arithmetic is
  deterministic Decimal Python (`net_settlement`,
  control totals, variance, materiality).
- The LLM never approves, never executes, never mutates
  policy, scope, authority, or closed periods.
- No close without deterministic post-verification.
- No new queues, streams, or AWS services for this
  contract. S3 stays transport-only for legacy batches.
- No Qdrant, Redpanda / Kafka, Temporal, K8s, Go
  services, or arbitrary SQL / HTTP execution tools.

---

*P6-01 domain contract. Frozen with company.md, PRD v3, and
the legacy batch protocol. Code follows this document.*
