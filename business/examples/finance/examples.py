"""Loader for all finance-domain CSV example sets.

Each CSV file under ``business/examples/finance/`` is parsed into an
:class:`~business.examples.models.ExampleSet` with descriptive metadata.
"""

from __future__ import annotations

from pathlib import Path

from business.examples.models import ExampleSet

HERE = Path(__file__).parent.resolve()

FINANCE_EXAMPLE_SETS: list[ExampleSet] = []
"""Globally registered finance example sets, populated at module import."""


def _build_invoice_good() -> ExampleSet:
    """Return 10 valid, approved/paid invoices across departments."""
    return ExampleSet.from_csv(
        example_id="invoice_good",
        name="Good Invoices",
        description="10 valid invoices with complete fields across multiple "
        "departments — the happy path for invoice processing.",
        domain="invoices",
        csv_path=HERE / "invoice_good.csv",
        tags=["valid", "complete", "happy-path"],
    )


def _build_invoice_duplicate() -> ExampleSet:
    """Return 5 invoices where 2 are exact duplicates (same vendor, amount, date)."""
    return ExampleSet.from_csv(
        example_id="invoice_duplicate",
        name="Duplicate Invoices",
        description="5 invoices including 2 exact duplicates (same vendor, "
        "amount, date, department) to test deduplication logic.",
        domain="invoices",
        csv_path=HERE / "invoice_duplicate.csv",
        tags=["edge-case", "duplicate", "dedup"],
    )


def _build_invoice_missing_vendor() -> ExampleSet:
    """Return 5 invoices where 2 have blank vendor_name."""
    return ExampleSet.from_csv(
        example_id="invoice_missing_vendor",
        name="Invoices Missing Vendor",
        description="5 invoices with 2 missing vendor_name fields — tests "
        "null-handling and required-field validation.",
        domain="invoices",
        csv_path=HERE / "invoice_missing_vendor.csv",
        tags=["edge-case", "missing-data", "null-handling"],
    )


def _build_invoice_negative_amount() -> ExampleSet:
    """Return 5 invoices where 2 have negative amounts (credit memos)."""
    return ExampleSet.from_csv(
        example_id="invoice_negative_amount",
        name="Invoices with Negative Amounts",
        description="5 invoices including 2 with negative amounts to test "
        "sign validation and credit memo handling.",
        domain="invoices",
        csv_path=HERE / "invoice_negative_amount.csv",
        tags=["edge-case", "negative-amount", "credit-memo"],
    )


def _build_trial_balance_unbalanced() -> ExampleSet:
    """Return 10 trial balance rows where total debits != total credits."""
    return ExampleSet.from_csv(
        example_id="trial_balance_unbalanced",
        name="Unbalanced Trial Balance",
        description="10 trial balance rows where debits (975,000) do not "
        "equal credits (905,000), resulting in a 70,000 imbalance.",
        domain="trial_balance",
        csv_path=HERE / "trial_balance_unbalanced.csv",
        tags=["edge-case", "imbalance", "validation"],
    )


def _build_trial_balance_balanced() -> ExampleSet:
    """Return 10 trial balance rows where total debits = total credits."""
    return ExampleSet.from_csv(
        example_id="trial_balance_balanced",
        name="Balanced Trial Balance",
        description="11 trial balance rows where total debits (1,155,000) "
        "equal total credits (1,155,000) — the happy path including equity.",
        domain="trial_balance",
        csv_path=HERE / "trial_balance_balanced.csv",
        tags=["valid", "balanced", "happy-path"],
    )


def _build_budget_variance_high() -> ExampleSet:
    """Return 10 budget-vs-actual pairs with >50% variance."""
    return ExampleSet.from_csv(
        example_id="budget_variance_high",
        name="High Budget Variance",
        description="10 budget vs actual pairs where every variance exceeds "
        "50%, testing materiality flagging and alerting thresholds.",
        domain="variance",
        csv_path=HERE / "budget_variance_high.csv",
        tags=["edge-case", "high-variance", "materiality"],
    )


def _build_budget_variance_normal() -> ExampleSet:
    """Return 10 budget-vs-actual pairs with <10% variance."""
    return ExampleSet.from_csv(
        example_id="budget_variance_normal",
        name="Normal Budget Variance",
        description="10 budget vs actual pairs where every variance is under "
        "10%, representing routine operational fluctuations.",
        domain="variance",
        csv_path=HERE / "budget_variance_normal.csv",
        tags=["valid", "normal-variance", "happy-path"],
    )


def _build_headcount_data() -> ExampleSet:
    """Return 10 headcount records by department and period."""
    return ExampleSet.from_csv(
        example_id="headcount_data",
        name="Headcount Data",
        description="10 headcount records across Engineering, Sales, Marketing, "
        "Operations, and HR for two periods with compensation totals.",
        domain="headcount",
        csv_path=HERE / "headcount_data.csv",
        tags=["valid", "headcount", "workforce"],
    )


def _build_forecast_vs_actual() -> ExampleSet:
    """Return 10 forecast vs actual comparison records across versions."""
    return ExampleSet.from_csv(
        example_id="forecast_vs_actual",
        name="Forecast vs Actual",
        description="10 forecast vs actual comparison records including "
        "version tracking (v1 for Jan, v2 for Feb).",
        domain="forecast",
        csv_path=HERE / "forecast_vs_actual.csv",
        tags=["valid", "forecast", "accuracy"],
    )


_BUILDERS: list[tuple[str, ExampleSet]] = [
    ("invoice_good", _build_invoice_good()),
    ("invoice_duplicate", _build_invoice_duplicate()),
    ("invoice_missing_vendor", _build_invoice_missing_vendor()),
    ("invoice_negative_amount", _build_invoice_negative_amount()),
    ("trial_balance_unbalanced", _build_trial_balance_unbalanced()),
    ("trial_balance_balanced", _build_trial_balance_balanced()),
    ("budget_variance_high", _build_budget_variance_high()),
    ("budget_variance_normal", _build_budget_variance_normal()),
    ("headcount_data", _build_headcount_data()),
    ("forecast_vs_actual", _build_forecast_vs_actual()),
]


def load_all() -> list[ExampleSet]:
    """Discover and register all finance example sets from CSV files.

    Returns:
        The full list of ExampleSet objects for the finance domain.
    """
    global FINANCE_EXAMPLE_SETS
    FINANCE_EXAMPLE_SETS = [ex for _, ex in _BUILDERS]
    return FINANCE_EXAMPLE_SETS


# Populate the module-level list at import time.
FINANCE_EXAMPLE_SETS = [ex for _, ex in _BUILDERS]
