"""Scenario-based validation tests for core FP&A domain logic.

Tests cover:
- Variance calculation formula and sign conventions.
- Materiality threshold logic (>$50K AND >10%).
- Trial balance balancing (debits == credits).
- Invoice status state-machine transitions (draft → approved → paid).
- Period format validation (YYYY-MM).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from business.examples.models import ExampleSet

# ---------------------------------------------------------------------------
# Variance calculation
# ---------------------------------------------------------------------------

FIFTY_K = Decimal("50000.00")
TEN_PCT = Decimal("10.00")


def compute_variance(
    actual: Decimal, budget: Decimal
) -> tuple[Decimal, Decimal | None]:
    """Compute variance amount and percentage.

    Formula:
        variance = actual - budget
        variance_pct = (actual - budget) / abs(budget) * 100
        Returns None for variance_pct when budget is zero.
    """
    variance = actual - budget
    if budget == Decimal("0.00"):
        return variance, None
    variance_pct = (variance / abs(budget)) * Decimal("100.00")
    return variance, variance_pct


class TestVarianceFormula:
    """Tests for the variance = actual - budget formula."""

    def test_variance_calculation(self, variance_data: list[dict[str, Any]]) -> None:
        """Variance amount should equal actual - budget."""
        for case in variance_data:
            actual: Decimal = case["actual_amount"]
            budget: Decimal = case["budget_amount"]
            expected: Decimal = case["expected_variance"]
            result, _ = compute_variance(actual, budget)
            assert result == expected, (
                f"Variance({actual}, {budget}) = {result}, "
                f"expected {expected}"
            )

    def test_variance_percentage(self, variance_data: list[dict[str, Any]]) -> None:
        """Variance % should follow (actual - budget) / abs(budget) * 100."""
        for case in variance_data:
            actual: Decimal = case["actual_amount"]
            budget: Decimal = case["budget_amount"]
            expected_pct: Decimal | None = case.get("expected_variance_pct")
            _, result_pct = compute_variance(actual, budget)
            if expected_pct is None:
                assert result_pct is None, (
                    f"Expected None for division by zero, got {result_pct}"
                )
            else:
                assert result_pct is not None, (
                    f"Expected {expected_pct}, got None for "
                    f"actual={actual} budget={budget}"
                )
                assert result_pct == expected_pct, (
                    f"Variance%({actual}, {budget}) = {result_pct}, "
                    f"expected {expected_pct}"
                )

    def test_variance_sign_convention(self) -> None:
        """Verify sign convention: positive = unfavorable (actual exceeded budget)."""
        # Expense account: actual > budget → unfavorable → positive variance
        actual, budget = Decimal("120000.00"), Decimal("100000.00")
        variance, _ = compute_variance(actual, budget)
        assert variance > Decimal("0.00"), (
            f"Expense variance should be positive (unfavorable), "
            f"got {variance}"
        )

        # Expense account: actual < budget → favorable → negative variance
        actual2, budget2 = Decimal("80000.00"), Decimal("100000.00")
        variance2, _ = compute_variance(actual2, budget2)
        assert variance2 < Decimal("0.00"), (
            f"Expense variance should be negative (favorable), "
            f"got {variance2}"
        )

    def test_zero_variance(self) -> None:
        """When actual equals budget, variance should be zero."""
        variance, pct = compute_variance(Decimal("100000.00"), Decimal("100000.00"))
        assert variance == Decimal("0.00"), (
            f"Expected zero variance when actual equals budget, got {variance}"
        )
        assert pct == Decimal("0.00"), (
            f"Expected zero pct when actual equals budget, got {pct}"
        )

    def test_negative_budget_variance_sign(self) -> None:
        """Negative budgets should still follow variance = actual - budget."""
        actual, budget = Decimal("-30000.00"), Decimal("-50000.00")
        variance, pct = compute_variance(actual, budget)
        # actual > budget (less negative) → unfavorable for expense
        assert variance > Decimal("0.00"), (
            f"With negative budget, actual > budget should give positive "
            f"variance, got {variance}"
        )
        assert pct is not None and pct > Decimal("0.00"), (
            f"Expected positive variance % for this case, got {pct}"
        )


class TestMaterialityThreshold:
    """Tests for materiality: variance > $50K AND > 10%."""

    @staticmethod
    def is_material(
        variance_amount: Decimal, variance_pct: Decimal | None
    ) -> bool:
        """Determine whether a variance is material.

        Materiality requires BOTH:
        1. |variance_amount| > $50,000
        2. |variance_pct| > 10%
        """
        if variance_pct is None:
            return abs(variance_amount) > FIFTY_K
        return abs(variance_amount) > FIFTY_K and abs(variance_pct) > TEN_PCT

    def test_large_amount_large_pct_is_material(self) -> None:
        """$100K variance at 50% should be material."""
        assert self.is_material(
            Decimal("100000.00"), Decimal("50.00")
        ), "$100K at 50% should be material"

    def test_large_amount_small_pct_not_material(self) -> None:
        """$100K variance at 2% should NOT be material."""
        assert not self.is_material(
            Decimal("100000.00"), Decimal("2.00")
        ), "$100K at 2% should not be material"

    def test_small_amount_large_pct_not_material(self) -> None:
        """$10K variance at 50% should NOT be material."""
        assert not self.is_material(
            Decimal("10000.00"), Decimal("50.00")
        ), "$10K at 50% should not be material"

    def test_amount_at_threshold(self) -> None:
        """Exactly $50K at exactly 10% should NOT be material (not strictly >)."""
        assert not self.is_material(
            FIFTY_K, TEN_PCT
        ), "$50K at 10% should not be material (not strictly greater)"

    def test_just_above_threshold_is_material(self) -> None:
        """$50,001 at 10.01% should be material."""
        assert self.is_material(
            Decimal("50001.00"), Decimal("10.01")
        ), "$50,001 at 10.01% should be material"

    def test_negative_variance_materiality(self) -> None:
        """Negative variances should use absolute values for threshold check."""
        assert self.is_material(
            Decimal("-100000.00"), Decimal("-50.00")
        ), "-$100K at -50% should be material (absolute check)"

    def test_zero_budget_variance_materiality(self) -> None:
        """When budget is zero (pct is None), only amount threshold applies."""
        assert self.is_material(
            Decimal("75000.00"), None
        ), "$75K with zero budget should be material"
        assert not self.is_material(
            Decimal("30000.00"), None
        ), "$30K with zero budget should not be material"


class TestTrialBalanceBalancing:
    """Tests for trial balance debits == credits validation."""

    @staticmethod
    def total_debits(data: list[dict[str, Any]]) -> Decimal:
        """Sum all debit values from trial balance rows."""
        total = Decimal("0.00")
        for row in data:
            d: Decimal | None = row.get("debit")  
            if d is not None:
                total += d
        return total

    @staticmethod
    def total_credits(data: list[dict[str, Any]]) -> Decimal:
        """Sum all credit values from trial balance rows."""
        total = Decimal("0.00")
        for row in data:
            c: Decimal | None = row.get("credit")  
            if c is not None:
                total += c
        return total

    def test_balanced_tb(self, balanced_tb: ExampleSet) -> None:
        """A balanced trial balance must have equal debits and credits."""
        total_debits = self.total_debits(balanced_tb.data)
        total_credits = self.total_credits(balanced_tb.data)
        assert total_debits == total_credits, (
            f"Balanced TB failed: debits={total_debits} != credits={total_credits}"
        )

    def test_unbalanced_tb(self, unbalanced_tb: ExampleSet) -> None:
        """An unbalanced trial balance must have differing totals."""
        total_debits = self.total_debits(unbalanced_tb.data)
        total_credits = self.total_credits(unbalanced_tb.data)
        assert total_debits != total_credits, (
            f"Unbalanced TB unexpectedly equal: debits={total_debits} == credits={total_credits}"
        )

    def test_imbalance_amount(self, unbalanced_tb: ExampleSet) -> None:
        """The imbalance amount should be identifiable."""
        total_debits = self.total_debits(unbalanced_tb.data)
        total_credits = self.total_credits(unbalanced_tb.data)
        imbalance = abs(total_debits - total_credits)
        assert imbalance > Decimal("0.00"), (
            f"Expected non-zero imbalance, got {imbalance}"
        )
        assert imbalance % Decimal("0.01") == Decimal("0.00"), (
            f"Imbalance {imbalance} should be precise to 2 decimal places"
        )

    def test_tb_contains_only_numeric_debit_credit(
        self, balanced_tb: ExampleSet
    ) -> None:
        """Debit and credit values should all be Decimal types."""
        for i, row in enumerate(balanced_tb.data):
            debit = row.get("debit")
            credit = row.get("credit")
            assert isinstance(debit, Decimal), (
                f"Row {i}: debit {debit!r} is {type(debit).__name__}"
            )
            assert isinstance(credit, Decimal), (
                f"Row {i}: credit {credit!r} is {type(credit).__name__}"
            )


class TestInvoiceStatusMachine:
    """Tests for invoice status state machine transitions.

    Valid transitions: draft → approved → paid
    Invalid: draft → paid (skip approved), approved → draft (backwards)
    """

    VALID_TRANSITIONS: dict[str, list[str]] = {
        "draft": ["approved"],
        "approved": ["paid", "draft"],  # allow rejection back to draft
        "paid": [],
    }

    @staticmethod
    def can_transition(current: str, target: str) -> bool:
        """Check whether a status transition is allowed."""
        allowed = TestInvoiceStatusMachine.VALID_TRANSITIONS.get(current, [])
        return target in allowed

    def test_valid_draft_to_approved(self) -> None:
        """draft → approved is a valid transition."""
        assert self.can_transition("draft", "approved"), (
            "draft → approved should be valid"
        )

    def test_valid_approved_to_paid(self) -> None:
        """approved → paid is a valid transition."""
        assert self.can_transition("approved", "paid"), (
            "approved → paid should be valid"
        )

    def test_invalid_draft_to_paid(self) -> None:
        """draft → paid is invalid (skips approval)."""
        assert not self.can_transition("draft", "paid"), (
            "draft → paid should be invalid"
        )

    def test_invalid_paid_to_approved(self) -> None:
        """paid → approved is invalid (cannot un-pay)."""
        assert not self.can_transition("paid", "approved"), (
            "paid → approved should be invalid"
        )

    def test_good_invoice_statuses(self, good_invoices: ExampleSet) -> None:
        """All good invoices should have valid statuses (approved or paid)."""
        for i, row in enumerate(good_invoices.data):
            status = row.get("status")
            assert status in ("approved", "paid"), (
                f"Row {i}: unexpected status '{status}'"
            )

    def test_unknown_status_rejected(self) -> None:
        """An empty or unknown status string should not match any transition."""
        assert not self.can_transition("", "approved"), (
            "Empty status should not allow transitions"
        )
        assert not self.can_transition("cancelled", "approved"), (
            "'cancelled' is not a valid starting status"
        )


class TestPeriodFormat:
    """Tests for YYYY-MM period format validation."""

    @staticmethod
    def is_valid_period(period: str) -> bool:
        """Validate that a period string matches YYYY-MM."""
        parts = period.split("-")
        if len(parts) != 2:
            return False
        year_str, month_str = parts
        if len(year_str) != 4 or len(month_str) != 2:
            return False
        if not year_str.isdigit() or not month_str.isdigit():
            return False
        month = int(month_str)
        return 1 <= month <= 12

    def test_valid_periods(self) -> None:
        """2026-01 through 2026-12 should all be valid."""
        for m in range(1, 13):
            period = f"2026-{m:02d}"
            assert self.is_valid_period(period), (
                f"Period '{period}' should be valid"
            )

    def test_invalid_month(self) -> None:
        """Months outside 01-12 should be invalid."""
        assert not self.is_valid_period("2026-13"), (
            "Month 13 should be invalid"
        )
        assert not self.is_valid_period("2026-00"), (
            "Month 00 should be invalid"
        )

    def test_invalid_format(self) -> None:
        """Malformed period strings should be rejected."""
        assert not self.is_valid_period("2026"), "Missing month should be invalid"
        assert not self.is_valid_period("26-01"), "Short year should be invalid"
        assert not self.is_valid_period("2026-1"), "Single-digit month should be invalid"
        assert not self.is_valid_period(""), "Empty string should be invalid"
        assert not self.is_valid_period("2026-AB"), "Non-numeric month should be invalid"

    def test_all_example_periods_valid(self, example_library: Any) -> None:
        """All periods found in finance examples should pass validation."""
        checked = 0
        for ex_set in example_library.examples.values():
            for row in ex_set.data:
                period = row.get("period")
                if period is not None and period != "":
                    period_str = str(period)
                    assert self.is_valid_period(period_str), (
                        f"Invalid period '{period_str}' in {ex_set.example_id}"
                    )
                    checked += 1
        assert checked > 0, "No periods were checked across example sets"
