"""Business policy registry — 15+ declarative policies.

Populates the PolicyRegistry with business policies covering
materiality thresholds, approval gates, data classification,
retention periods, validation rules, and compliance requirements.
"""

from datetime import date

from business.policies.models import BusinessPolicy, PolicyRegistry
from finplatform.config.tenant_schema import TenantConfig

# ---------------------------------------------------------------------------
# Helper: common effective date
# ---------------------------------------------------------------------------

_EARLY = date(2024, 1, 1)
_FAR_FUTURE: date | None = None  # no expiry

# ---------------------------------------------------------------------------
# Policy registry — singleton
# ---------------------------------------------------------------------------

POLICY_REGISTRY = PolicyRegistry(
    policies={
        # ==================================================================
        # MATERIALITY POLICIES
        # ==================================================================
        "mat-001": BusinessPolicy(
            policy_id="mat-001",
            name="Variance Absolute Threshold",
            description=(
                "A variance exceeding the absolute dollar threshold is"
                " flagged as potentially material."
            ),
            scope="variance",
            condition="abs(variance_amount) > {amount_threshold}",
            action=(
                "Flag variance as exceeding absolute threshold;"
                " include in materiality review queue."
            ),
            severity="warning",
            owner="FP&A Team",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["materiality", "variance"],
        ),
        "mat-002": BusinessPolicy(
            policy_id="mat-002",
            name="Variance Percentage Threshold",
            description=(
                "A variance exceeding the percentage threshold is flagged as potentially material."
            ),
            scope="variance",
            condition="abs(variance_pct) > {pct_threshold}",
            action=(
                "Flag variance as exceeding percentage threshold;"
                " include in materiality review queue."
            ),
            severity="warning",
            owner="FP&A Team",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["materiality", "variance"],
        ),
        "mat-003": BusinessPolicy(
            policy_id="mat-003",
            name="Combined Materiality Threshold",
            description=(
                "A variance exceeding BOTH absolute AND percentage"
                " thresholds is classified as material."
            ),
            scope="variance",
            condition=(
                "abs(variance_amount) > {amount_threshold} and"
                " abs(variance_pct) > {pct_threshold}"
            ),
            action=(
                "Classify variance as material; escalate to commentary engine for explanation."
            ),
            severity="blocking",
            owner="FP&A Team",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["materiality", "variance", "escalation"],
        ),
        "mat-004": BusinessPolicy(
            policy_id="mat-004",
            name="Revenue Variance Lower Threshold",
            description=(
                "Revenue account variances have a lower materiality"
                " threshold due to board sensitivity."
            ),
            scope="variance",
            condition="account_type == 'revenue' and abs(variance_pct) > {pct_threshold}",
            action=(
                "Flag revenue variance as material at lower threshold;"
                " trigger board report inclusion."
            ),
            severity="warning",
            owner="FP&A Team",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["materiality", "revenue", "board_report"],
        ),
        "mat-005": BusinessPolicy(
            policy_id="mat-005",
            name="Trend Materiality",
            description=(
                "A small variance persisting for 3+ consecutive periods is trend-material."
            ),
            scope="variance",
            condition="consecutive_periods >= 3 and abs(variance_amount) > {amount_threshold}",
            action=("Flag as trend-material; include in trend analysis commentary."),
            severity="info",
            owner="FP&A Team",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["materiality", "trend"],
        ),
        # ==================================================================
        # APPROVAL POLICIES
        # ==================================================================
        "app-001": BusinessPolicy(
            policy_id="app-001",
            name="Restricted Data Human Review",
            description=(
                "Any operation involving RESTRICTED-classification data requires human review."
            ),
            scope="data_access",
            condition="data_classification == 'restricted'",
            action=("Route to human review queue; block automated processing."),
            severity="blocking",
            owner="Data Governance",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["approval", "classification", "human_review"],
        ),
        "app-002": BusinessPolicy(
            policy_id="app-002",
            name="SOX Dual Approval",
            description=(
                "SOX-relevant financial fields require dual-approval before modification."
            ),
            scope="sox_fields",
            condition="sox_relevant == True and operation in ('update', 'delete')",
            action=("Require second approver; log both approvals to audit trail."),
            severity="blocking",
            owner="Compliance",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["approval", "sox", "audit"],
        ),
        "app-003": BusinessPolicy(
            policy_id="app-003",
            name="Period Reopen Approval",
            description=("Reopening a closed fiscal period requires CFO-level authorisation."),
            scope="period",
            condition="operation == 'reopen' and current_status == 'closed'",
            action=("Require CFO approval; record approval reference in audit log."),
            severity="blocking",
            owner="Finance Operations",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["approval", "period", "cfo"],
        ),
        "app-004": BusinessPolicy(
            policy_id="app-004",
            name="Action Impact Manager Review",
            description=(
                "Proposed actions with estimated impact exceeding $100K require manager review."
            ),
            scope="action",
            condition="impact_estimate is not None and abs(impact_estimate) > 100000",
            action=("Route action for manager approval before proceeding."),
            severity="warning",
            owner="FP&A Team",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["approval", "action", "manager_review"],
        ),
        # ==================================================================
        # CLASSIFICATION POLICIES
        # ==================================================================
        "cls-001": BusinessPolicy(
            policy_id="cls-001",
            name="Employee Compensation is PII",
            description=(
                "Employee compensation data (salary, bonus, equity) is"
                " classified as PII and Restricted."
            ),
            scope="data_classification",
            condition="field_category == 'compensation'",
            action=(
                "Classify as 'restricted'; apply encryption-at-rest and"
                " need-to-know access controls."
            ),
            severity="blocking",
            owner="Data Governance",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["classification", "pii", "restricted"],
        ),
        "cls-002": BusinessPolicy(
            policy_id="cls-002",
            name="Vendor Bank Details are Restricted",
            description=("Vendor banking and payment information is classified as Restricted."),
            scope="data_classification",
            condition="field_category == 'vendor_bank'",
            action=("Classify as 'restricted'; mask in non-privileged views."),
            severity="blocking",
            owner="Data Governance",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["classification", "vendor", "restricted"],
        ),
        "cls-003": BusinessPolicy(
            policy_id="cls-003",
            name="Financial Actuals are Confidential",
            description=(
                "Actual financial amounts and budget details are classified as Confidential."
            ),
            scope="data_classification",
            condition=("field_type in ('actual_amount', 'budget_amount', 'forecast_amount')"),
            action=("Classify as 'confidential'; enforce role-based access controls."),
            severity="warning",
            owner="Data Governance",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["classification", "confidential", "financial"],
        ),
        # ==================================================================
        # RETENTION POLICIES
        # ==================================================================
        "ret-001": BusinessPolicy(
            policy_id="ret-001",
            name="Audit Log Retention",
            description=(
                "Audit log entries must be retained for a minimum of 7 years for compliance."
            ),
            scope="audit",
            condition="record_type == 'audit_log'",
            action=(
                "Retain for 7 years; archive to cold storage after year 7; purge after year 10."
            ),
            severity="blocking",
            owner="Compliance",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["retention", "audit", "compliance"],
        ),
        "ret-002": BusinessPolicy(
            policy_id="ret-002",
            name="Trial Balance Retention",
            description=(
                "Trial balance records must be retained for 10 years"
                " for statutory and tax purposes."
            ),
            scope="trial_balance",
            condition="record_type == 'trial_balance'",
            action=("Retain for 10 years from period end; archive to cold storage thereafter."),
            severity="blocking",
            owner="Compliance",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["retention", "trial_balance", "statutory"],
        ),
        "ret-003": BusinessPolicy(
            policy_id="ret-003",
            name="Invoice Record Retention",
            description=(
                "Vendor invoice records must be retained for 7 years"
                " per tax authority requirements."
            ),
            scope="invoice",
            condition="record_type == 'invoice'",
            action=(
                "Retain for 7 years from invoice date; purge after"
                " expiry with disposal certificate."
            ),
            severity="warning",
            owner="Accounts Payable",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["retention", "invoice", "tax"],
        ),
        # ==================================================================
        # VALIDATION POLICIES
        # ==================================================================
        "val-001": BusinessPolicy(
            policy_id="val-001",
            name="Trial Balance Must Balance",
            description=(
                "The trial balance must have equal total debits and total credits for every period."
            ),
            scope="trial_balance",
            condition="abs(sum_debits - sum_credits) > 0.01",
            action=("Block period close; flag trial balance discrepancy for investigation."),
            severity="blocking",
            owner="Finance Operations",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["validation", "trial_balance", "close"],
        ),
        "val-002": BusinessPolicy(
            policy_id="val-002",
            name="Budget Amounts Cannot Be Negative",
            description=("Budget line amounts must be non-negative across all budget versions."),
            scope="budget",
            condition="amount < 0",
            action=("Reject budget line; require positive amount or contra-account treatment."),
            severity="blocking",
            owner="FP&A Team",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["validation", "budget"],
        ),
        "val-003": BusinessPolicy(
            policy_id="val-003",
            name="Variance Amount Must Match Calculation",
            description=(
                "The variance amount must equal actual minus budget to within rounding tolerance."
            ),
            scope="variance",
            condition=("abs(variance_amount - (actual_amount - budget_amount)) > 0.01"),
            action=("Flag variance calculation mismatch; recalculate from source data."),
            severity="warning",
            owner="FP&A Team",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["validation", "variance", "consistency"],
        ),
        "val-004": BusinessPolicy(
            policy_id="val-004",
            name="Currency Code ISO Compliance",
            description=("All currency codes must be valid ISO 4217 three-letter uppercase codes."),
            scope="currency",
            condition=(
                "currency is not None and (len(currency) != 3 or currency != currency.upper())"
            ),
            action=("Reject record with invalid currency code; log validation error."),
            severity="blocking",
            owner="Data Governance",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["validation", "currency", "iso"],
        ),
        # ==================================================================
        # COMPLIANCE POLICIES
        # ==================================================================
        "cmp-001": BusinessPolicy(
            policy_id="cmp-001",
            name="SOX Audit Trail Required",
            description=("All SOX-relevant fields must have a complete audit trail of changes."),
            scope="sox_fields",
            condition="sox_relevant == True",
            action=(
                "Ensure every modification is recorded in the audit log with before/after values."
            ),
            severity="blocking",
            owner="Compliance",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["compliance", "sox", "audit_trail"],
        ),
        "cmp-002": BusinessPolicy(
            policy_id="cmp-002",
            name="Period Close Requires CFO Sign-Off",
            description=("Fiscal period close requires documented CFO sign-off before archiving."),
            scope="period",
            condition="operation == 'archive' and current_status == 'closed'",
            action=("Verify CFO sign-off is recorded; block archive if absent."),
            severity="blocking",
            owner="Finance Operations",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["compliance", "period", "cfo_signoff"],
        ),
        "cmp-003": BusinessPolicy(
            policy_id="cmp-003",
            name="Restricted Data Access Logging",
            description=(
                "All access to Restricted-classification data must be logged with user identity."
            ),
            scope="data_access",
            condition="data_classification == 'restricted'",
            action=(
                "Log access event with user_id, timestamp, data_ref, and access_type to audit log."
            ),
            severity="blocking",
            owner="Compliance",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["compliance", "restricted", "audit"],
        ),
        "cmp-004": BusinessPolicy(
            policy_id="cmp-004",
            name="Materiality Override Audit",
            description=(
                "Manual override of materiality classification must be logged and justified."
            ),
            scope="variance",
            condition="operation == 'override_materiality'",
            action=(
                "Log override with reason, approver identity, before/after values, and timestamp."
            ),
            severity="warning",
            owner="Compliance",
            version="1.0",
            effective_from=_EARLY,
            effective_until=_FAR_FUTURE,
            tags=["compliance", "materiality", "override", "audit"],
        ),
    },
)

# Convenience lookup by scope
POLICIES_BY_SCOPE: dict[str, list[BusinessPolicy]] = {}
for policy in POLICY_REGISTRY.policies.values():
    POLICIES_BY_SCOPE.setdefault(policy.scope, []).append(policy)


def resolve_policy_condition(policy: BusinessPolicy, tenant_config: TenantConfig) -> str:
    """Resolve a policy condition template with tenant materiality thresholds.

    Substitutes ``{amount_threshold}`` and ``{pct_threshold}`` placeholders
    with the tenant's materiality values formatted as plain Decimals.
    Conditions without placeholders are returned unchanged.
    """
    materiality = tenant_config.materiality
    return policy.condition.format(
        amount_threshold=materiality.amount,
        pct_threshold=materiality.pct,
    )
