"""pytest fixtures for the business domain test suite.

Provides ready-to-use ExampleSet fixtures for all finance data files
and programmatic edge cases.
"""

# mypy: disable-error-code="untyped-decorator"

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from business.examples.edge_cases import get_edge_case_examples
from business.examples.finance.examples import FINANCE_EXAMPLE_SETS
from business.examples.models import ExampleLibrary, ExampleSet


@pytest.fixture(scope="session")
def example_library() -> ExampleLibrary:
    """Return a fully populated ExampleLibrary with all finance datasets."""
    lib = ExampleLibrary()
    for ex in FINANCE_EXAMPLE_SETS:
        lib.register(ex)
    for ex in get_edge_case_examples():
        lib.register(ex)
    return lib


@pytest.fixture
def good_invoices() -> ExampleSet:
    """Return the ``invoice_good`` example set (10 valid invoices)."""
    for ex in FINANCE_EXAMPLE_SETS:
        if ex.example_id == "invoice_good":
            return ex
    msg = "invoice_good example set not found"
    raise ValueError(msg)


@pytest.fixture
def duplicate_invoices() -> ExampleSet:
    """Return the ``invoice_duplicate`` example set (5 invoices, 2 duplicates)."""
    for ex in FINANCE_EXAMPLE_SETS:
        if ex.example_id == "invoice_duplicate":
            return ex
    msg = "invoice_duplicate example set not found"
    raise ValueError(msg)


@pytest.fixture
def missing_vendor_invoices() -> ExampleSet:
    """Return the ``invoice_missing_vendor`` example set."""
    for ex in FINANCE_EXAMPLE_SETS:
        if ex.example_id == "invoice_missing_vendor":
            return ex
    msg = "invoice_missing_vendor example set not found"
    raise ValueError(msg)


@pytest.fixture
def negative_amount_invoices() -> ExampleSet:
    """Return the ``invoice_negative_amount`` example set."""
    for ex in FINANCE_EXAMPLE_SETS:
        if ex.example_id == "invoice_negative_amount":
            return ex
    msg = "invoice_negative_amount example set not found"
    raise ValueError(msg)


@pytest.fixture
def balanced_tb() -> ExampleSet:
    """Return the balanced trial balance (debits == credits)."""
    for ex in FINANCE_EXAMPLE_SETS:
        if ex.example_id == "trial_balance_balanced":
            return ex
    msg = "trial_balance_balanced example set not found"
    raise ValueError(msg)


@pytest.fixture
def unbalanced_tb() -> ExampleSet:
    """Return the unbalanced trial balance (debits != credits)."""
    for ex in FINANCE_EXAMPLE_SETS:
        if ex.example_id == "trial_balance_unbalanced":
            return ex
    msg = "trial_balance_unbalanced example set not found"
    raise ValueError(msg)


@pytest.fixture
def high_variance_data() -> ExampleSet:
    """Return budget variances that exceed 50%."""
    for ex in FINANCE_EXAMPLE_SETS:
        if ex.example_id == "budget_variance_high":
            return ex
    msg = "budget_variance_high example set not found"
    raise ValueError(msg)


@pytest.fixture
def normal_variance_data() -> ExampleSet:
    """Return budget variances that are under 10%."""
    for ex in FINANCE_EXAMPLE_SETS:
        if ex.example_id == "budget_variance_normal":
            return ex
    msg = "budget_variance_normal example set not found"
    raise ValueError(msg)


@pytest.fixture
def headcount_data() -> ExampleSet:
    """Return the headcount data example set."""
    for ex in FINANCE_EXAMPLE_SETS:
        if ex.example_id == "headcount_data":
            return ex
    msg = "headcount_data example set not found"
    raise ValueError(msg)


@pytest.fixture
def forecast_vs_actual_data() -> ExampleSet:
    """Return the forecast-vs-actual comparison data."""
    for ex in FINANCE_EXAMPLE_SETS:
        if ex.example_id == "forecast_vs_actual":
            return ex
    msg = "forecast_vs_actual example set not found"
    raise ValueError(msg)


@pytest.fixture
def variance_data() -> list[dict[str, Any]]:
    """Return known variance calculations for formula testing.

    Each dict contains budget_amount, actual_amount, and the expected
    variance_amount and variance_pct derived from:
        variance = actual - budget
        variance_pct = (actual - budget) / abs(budget) * 100
    """
    return [
        {
            "budget_amount": Decimal("100000.00"),
            "actual_amount": Decimal("110000.00"),
            "expected_variance": Decimal("10000.00"),
            "expected_variance_pct": Decimal("10.00"),
            "classification": "unfavorable",
        },
        {
            "budget_amount": Decimal("100000.00"),
            "actual_amount": Decimal("90000.00"),
            "expected_variance": Decimal("-10000.00"),
            "expected_variance_pct": Decimal("-10.00"),
            "classification": "favorable",
        },
        {
            "budget_amount": Decimal("50000.00"),
            "actual_amount": Decimal("75000.00"),
            "expected_variance": Decimal("25000.00"),
            "expected_variance_pct": Decimal("50.00"),
            "classification": "unfavorable",
        },
        {
            "budget_amount": Decimal("0.00"),
            "actual_amount": Decimal("10000.00"),
            "expected_variance": Decimal("10000.00"),
            "expected_variance_pct": None,  # division by zero → undefined
            "classification": "unfavorable",
        },
        {
            "budget_amount": Decimal("-50000.00"),
            "actual_amount": Decimal("-45000.00"),
            "expected_variance": Decimal("5000.00"),
            "expected_variance_pct": Decimal("10.00"),
            "classification": "unfavorable",
        },
    ]


@pytest.fixture
def edge_cases() -> list[ExampleSet]:
    """Return all programmatic edge-case example sets."""
    return get_edge_case_examples()
