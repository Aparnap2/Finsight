"""Programmatic edge-case example sets for FP&A domain logic.

Each edge case is constructed as an ExampleSet with explicit row data rather
than loaded from CSV, allowing precise control over boundary conditions such
as zero budgets, negative amounts, and future periods.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from business.examples.models import ExampleSet


def _build_zero_budget_variance() -> ExampleSet:
    """Variance rows where budget is zero, causing division-by-zero in variance %.

    Actual amounts are positive, so variance = actual - 0 = actual, and
    variance % should be undefined / infinite.
    """
    data: list[dict[str, Any]] = [
        {
            "entity_id": "ent-001",
            "period": "2026-01",
            "account_id": "acc-9000",
            "department": "R&D",
            "budget_amount": Decimal("0.00"),
            "actual_amount": Decimal("50000.00"),
            "variance_amount": Decimal("50000.00"),
            "variance_pct": None,
        },
        {
            "entity_id": "ent-001",
            "period": "2026-01",
            "account_id": "acc-9001",
            "department": "R&D",
            "budget_amount": Decimal("0.00"),
            "actual_amount": Decimal("12500.00"),
            "variance_amount": Decimal("12500.00"),
            "variance_pct": None,
        },
    ]
    return ExampleSet(
        example_id="zero_budget_variance",
        name="Zero Budget Variance",
        description="Two variance rows where budget is 0 but actual is "
        "positive — tests division-by-zero protection in variance % formulas.",
        domain="variance",
        data=data,
        tags=["edge-case", "zero-budget", "division-by-zero"],
        source="programmatic",
    )


def _build_negative_budget() -> ExampleSet:
    """Budget lines with negative amounts (restructuring / unusual scenarios).

    Negative budgets are unusual but can appear for items like restructuring
    reserves or contra-revenue accounts.
    """
    data: list[dict[str, Any]] = [
        {
            "entity_id": "ent-001",
            "period": "2026-01",
            "account_id": "acc-9100",
            "department": "Operations",
            "budget_amount": Decimal("-50000.00"),
            "actual_amount": Decimal("-48000.00"),
            "variance_amount": Decimal("2000.00"),
            "variance_pct": Decimal("4.00"),
        },
        {
            "entity_id": "ent-001",
            "period": "2026-01",
            "account_id": "acc-9101",
            "department": "Operations",
            "budget_amount": Decimal("-75000.00"),
            "actual_amount": Decimal("-80000.00"),
            "variance_amount": Decimal("-5000.00"),
            "variance_pct": Decimal("-6.67"),
        },
    ]
    return ExampleSet(
        example_id="negative_budget",
        name="Negative Budget Lines",
        description="Two budget lines with negative budget amounts for "
        "restructuring reserves — tests sign handling in variance formulas.",
        domain="variance",
        data=data,
        tags=["edge-case", "negative-budget", "restructuring"],
        source="programmatic",
    )


def _build_missing_department_codes() -> ExampleSet:
    """Records where department is blank or None, testing null handling."""
    data: list[dict[str, Any]] = [
        {
            "entity_id": "ent-001",
            "period": "2026-01",
            "account_id": "acc-9200",
            "department": None,
            "budget_amount": Decimal("100000.00"),
            "actual_amount": Decimal("95000.00"),
        },
        {
            "entity_id": "ent-001",
            "period": "2026-01",
            "account_id": "acc-9201",
            "department": "",
            "budget_amount": Decimal("50000.00"),
            "actual_amount": Decimal("52000.00"),
        },
        {
            "entity_id": "ent-001",
            "period": "2026-01",
            "account_id": "acc-9202",
            "department": "Unassigned",
            "budget_amount": Decimal("25000.00"),
            "actual_amount": Decimal("24800.00"),
        },
    ]
    return ExampleSet(
        example_id="missing_department_codes",
        name="Missing Department Codes",
        description="Variance records with None, empty, or 'Unassigned' "
        "department codes — tests null-safety in grouping and aggregation.",
        domain="variance",
        data=data,
        tags=["edge-case", "missing-data", "null-handling"],
        source="programmatic",
    )


def _build_cross_currency_invoices() -> ExampleSet:
    """Invoices in multiple currencies (USD + EUR) without exchange rates.

    Tests that the system flags cross-currency scenarios when no FX rate
    is available for conversion.
    """
    data: list[dict[str, Any]] = [
        {
            "entity_id": "ent-001",
            "vendor_name": "EuroParts GmbH",
            "account_id": "acc-4010",
            "amount": Decimal("45000.00"),
            "currency": "EUR",
            "invoice_date": "2026-03-15",
            "category": "Parts",
            "department": "Operations",
        },
        {
            "entity_id": "ent-001",
            "vendor_name": "UK Services Ltd",
            "account_id": "acc-4020",
            "amount": Decimal("22000.00"),
            "currency": "GBP",
            "invoice_date": "2026-03-20",
            "category": "Consulting",
            "department": "Engineering",
        },
        {
            "entity_id": "ent-001",
            "vendor_name": "Domestic Supply Co",
            "account_id": "acc-4010",
            "amount": Decimal("15000.00"),
            "currency": "USD",
            "invoice_date": "2026-03-25",
            "category": "Supplies",
            "department": "Finance",
        },
    ]
    return ExampleSet(
        example_id="cross_currency_invoices",
        name="Cross-Currency Invoices",
        description="Three invoices in EUR, GBP, and USD without exchange "
        "rate data — tests FX-awareness and conversion-gap detection.",
        domain="invoices",
        data=data,
        tags=["edge-case", "cross-currency", "fx", "missing-rate"],
        source="programmatic",
    )


def _build_future_dated_invoices() -> ExampleSet:
    """Invoices with dates in the future relative to the analysis period.

    Tests that the system correctly handles or flags future-dated
    transactions in historical analysis.
    """
    data: list[dict[str, Any]] = [
        {
            "entity_id": "ent-001",
            "vendor_name": "FutureTech Inc",
            "account_id": "acc-4030",
            "amount": Decimal("75000.00"),
            "currency": "USD",
            "invoice_date": "2026-12-01",
            "category": "Software",
            "department": "Engineering",
            "period": "2026-01",
        },
        {
            "entity_id": "ent-001",
            "vendor_name": "Prepaid Services Co",
            "account_id": "acc-4040",
            "amount": Decimal("120000.00"),
            "currency": "USD",
            "invoice_date": "2027-01-15",
            "category": "Prepaid",
            "department": "Finance",
            "period": "2026-01",
        },
    ]
    return ExampleSet(
        example_id="future_dated_invoices",
        name="Future-Dated Invoices",
        description="Two invoices dated in the future (Dec 2026, Jan 2027) "
        "but posted to a current period — tests temporal validation.",
        domain="invoices",
        data=data,
        tags=["edge-case", "future-date", "temporal"],
        source="programmatic",
    )


def _build_multi_period_budget_revisions() -> ExampleSet:
    """Budget lines revised across multiple versions for the same account.

    Tests that multi-version budget tracking correctly sequences and
    compares versions of the same budget line.
    """
    data: list[dict[str, Any]] = [
        {
            "entity_id": "ent-001",
            "period": "2026-01",
            "account_id": "acc-7010",
            "department": "Sales",
            "budget_version": 1,
            "amount": Decimal("100000.00"),
        },
        {
            "entity_id": "ent-001",
            "period": "2026-01",
            "account_id": "acc-7010",
            "department": "Sales",
            "budget_version": 2,
            "amount": Decimal("110000.00"),
        },
        {
            "entity_id": "ent-001",
            "period": "2026-01",
            "account_id": "acc-7010",
            "department": "Sales",
            "budget_version": 3,
            "amount": Decimal("105000.00"),
        },
        {
            "entity_id": "ent-001",
            "period": "2026-02",
            "account_id": "acc-7010",
            "department": "Sales",
            "budget_version": 1,
            "amount": Decimal("115000.00"),
        },
    ]
    return ExampleSet(
        example_id="multi_period_budget_revisions",
        name="Multi-Period Budget Revisions",
        description="Four budget lines showing three revisions to the same "
        "account in January and a fresh February version — tests version tracking.",
        domain="budget",
        data=data,
        tags=["edge-case", "budget-revision", "versioning", "multi-period"],
        source="programmatic",
    )


def _build_period_with_no_actuals() -> ExampleSet:
    """A period that has budget data but all-zero or missing actuals.

    Tests that the system correctly detects inactive periods and avoids
    false anomalies when no business activity occurred.
    """
    data: list[dict[str, Any]] = [
        {
            "entity_id": "ent-001",
            "period": "2026-06",
            "account_id": "acc-7010",
            "department": "Sales",
            "budget_amount": Decimal("100000.00"),
            "actual_amount": Decimal("0.00"),
        },
        {
            "entity_id": "ent-001",
            "period": "2026-06",
            "account_id": "acc-7020",
            "department": "Marketing",
            "budget_amount": Decimal("50000.00"),
            "actual_amount": Decimal("0.00"),
        },
        {
            "entity_id": "ent-001",
            "period": "2026-06",
            "account_id": "acc-7030",
            "department": "Engineering",
            "budget_amount": Decimal("200000.00"),
            "actual_amount": Decimal("0.00"),
        },
    ]
    return ExampleSet(
        example_id="period_with_no_actuals",
        name="Period with No Actuals",
        description="A full period (2026-06) where all accounts have budget "
        "but zero actuals — tests handling of dormant periods.",
        domain="variance",
        data=data,
        tags=["edge-case", "zero-actuals", "dormant-period"],
        source="programmatic",
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EDGE_CASE_SETS: list[ExampleSet] = [
    _build_zero_budget_variance(),
    _build_negative_budget(),
    _build_missing_department_codes(),
    _build_cross_currency_invoices(),
    _build_future_dated_invoices(),
    _build_multi_period_budget_revisions(),
    _build_period_with_no_actuals(),
]


def get_edge_case_examples() -> list[ExampleSet]:
    """Return all programmatic edge-case example sets.

    Returns:
        The full list of programmatically defined edge-case ExampleSets.
    """
    return list(EDGE_CASE_SETS)
