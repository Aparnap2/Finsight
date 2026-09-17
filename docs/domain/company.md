# Company — Meridian Commerce Pvt Ltd (Frozen Single-Company Boundary)

## Business Meaning

FinSight is **not** generic SaaS, not multi-tenant product. The product boundary is frozen to a **single-company internal system** for **Meridian Commerce Pvt Ltd** (`company_id = meridian`). All financial data, FinancialSituations, investigations, and approvals are scoped to this one company. There is no Tenant switcher, no Tenant onboarding UI.

`Company` is a static identity record, not a runtime SaaS knob. `CompanyConfiguration`, `MeridianBusinessRules`, `AccountMappings`, `FinancialOntology`, and `IntegrationRegistry` are code-level frozen configuration, not UI-managed knobs.

## Models (Frozen)

### Company

| Attribute | Type | Value (Meridian) |
|-----------|------|------------------|
| `id` | `str` | `"meridian"` (sole value; no other ids exist) |
| `name` | `str` | `"Meridian Commerce Pvt Ltd"` |
| `base_currency` | `str` | `"INR"` (immutable; stored via `MoneyDecimal` everywhere) |
| `fiscal_year_start` | `date` | April 1 (Meridian FY) |
| `employee_count` | `int` | ~250 |
| `merchant_count` | `int` | ~1,500 |
| `payments_per_day` | `int` | ~20,000 |

### CompanyConfiguration (Replaces `TenantConfiguration`)

```python
class CompanyConfiguration(BaseModel):
    company_id: str = "meridian"
    base_currency: str = "INR"
    tolerance_minor: MoneyDecimal = Decimal("100")          # minor variance threshold
    auto_approval_limit: MoneyDecimal = Decimal("500000")   # upper bound for auto
    legacy_correction_requires_approval: bool = True        # always true
    # No per-tenant overrides. Changes via Alembic migration + code review.
```

### MeridianBusinessRules (Replaces `CustomPolicy`)

```python
class MeridianBusinessRules:
    REFUND_AUTO = Decimal("5000")       # <5k auto if evidence complete
    REFUND_MANAGER = Decimal("50000")   # 5k-50k Finance Manager
    REFUND_DIRECTOR = Decimal("50000")  # >50k Director
    LEGACY_REQUIRES = ["approval", "valid_account_code", "balanced_batch"]
    CLOSED_PERIOD = "NEVER_MODIFY"      # hard deterministic block
    # None of the above were CustomWorkflow/CustomPolicy/Plugin before.
```

### AccountMappings (Replaces generic ConnectorRegistry mappings)

Static table Razorpay ↔ QuickBooks ↔ COBOL GL codes. No runtime `ConnectorRegistry` mutation.

### FinancialOntology

Canonical variance types for Meridian: fee mismatch, refund lag, legacy rejection, timing difference, duplicate, adjustment — not a generic CFO ontology.

### IntegrationRegistry (Static, Not Plugin Platform)

```python
INTEGRATIONS = ["razorpay", "quickbooks", "sheets", "gmail", "slack", "cobol_legacy_s3"]
# Razorpay: provider state authority
# QuickBooks: accounting authority
# COBOL: fixed-width batch via S3 (no HTTP)
# No WorkflowBuilder, no Plugin, no ConnectorRegistry emergence.
```

## FinancialSituation — Central Object (Not Transaction)

```
FinancialSituation
  id: FS-2026-0916-00231
  company_id: meridian
  variance: 10,000 (Decimal)
  expected: 10,00,000 (Sheets)
  razorpay_net: 9,72,500 (Razorpay)
  quickbooks: 9,82,500
  legacy: 9,82,500
  status: INVESTIGATING | ... | CLOSED
  evidence_ids: [ ... hash-verified ... ]
  hypothesis_ids: [ ... ]
  proposal_id: ResolutionProposal | None
  policy_decision: PolicyDecision | None
  approval: Approval | None (Slack, pinned to proposal hash)
  execution: Execution | None (S3 CORRECTION_*.DAT)
  verification: Verification | None (re-reconcile pass/fail)
```

FinSight owns reasoning state; existing systems own facts.

## Relationships

```
Company (meridian) — single row
├── has one CompanyConfiguration (INR, 100, 500000, legacy-approval true)
├── has one MeridianBusinessRules (refund tiers, legacy, closed period)
├── has one FinancialOntology (variance catalog)
├── has one AccountMappings (static)
├── has one IntegrationRegistry (6 fixed integrations)
├── has many FinancialSituations (FS-*)
│     ├── has one Investigation
│     ├── has many Evidence (immutable, hash)
│     ├── has many Hypotheses
│     ├── has at most one ResolutionProposal
│     ├── has one PolicyDecision
│     ├── has at most one Approval (Slack HITL)
│     ├── has at most one Execution (S3 batch)
│     └── has at most one Verification (post-execution re-reconcile)
└── has one FiscalCalendar / ChartOfAccounts
```

## Rules

### Base Currency Immutable

`INR` at Meridian creation; cannot change (same rationale as before, now single-company).

### Company/Environment Boundary Isolation (Replaces Tenant Isolation)

Every row that previously carried `tenant_id` now carries `company_id` + `environment` (where useful). Enforcement is identical: RLS `app.company_id = 'meridian'`, API `company_id` from authenticated context (never client-supplied), S3 prefix `{company_id}/{case_id}/...`, `CompanyIsolationError` (fka `TenantIsolationError`) on cross-scope attempt, audit `company_id` on every event. Not SaaS tenancy — it is **company vs external world + environment isolation** (dev/staging/prod) where useful.

### No SaaS Knobs

`CustomWorkflow`, `CustomPolicy`, `Plugin`, `ConnectorRegistry` mutation, `WorkflowBuilder`, `CustomSchema` do not exist. Changing a threshold is a code change + migration + review, not a UI toggle.

## Edge Cases

### Multi-Entity Narrative Removed

There is exactly one company. Consolidation across legal entities is out of scope and was the former multi-tenant narrative — deleted.

### Fiscal Year / Deactivation

Same as before but single-company: deactivation preserves audit; fiscal-year shift creates stub period. No multi-company branching.

## Migration Note

Existing `shared/models/database.py` tables with `tenant_id` are migrated to `company_id` (default `meridian`) + `environment` where applicable. Code references to `Tenant`/`TenantConfiguration` become `Company`/`CompanyConfiguration`. `TenantIsolationError` aliased to `CompanyIsolationError` (preserve tests).
