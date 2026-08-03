"""Tests for canonical example CSV loading and parsing.

Verifies that every CSV file in the finance domain:
- Can be parsed without errors.
- Has the expected row count.
- Contains valid Decimal monetary values.
- Has parseable date strings.
- Has no empty required fields (for "good" example sets).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from business.examples.models import ExampleSet


class TestInvoiceExamples:
    """Tests for invoice-related CSV example sets."""

    def test_good_invoices_parsed(self, good_invoices: ExampleSet) -> None:
        """Good invoices CSV should load exactly 10 rows."""
        assert good_invoices.row_count() == 10, (
            f"Expected 10 good invoices, got {good_invoices.row_count()}"
        )

    def test_good_invoices_all_fields_present(self, good_invoices: ExampleSet) -> None:
        """Every row should have non-null entity_id, vendor_name, amount, currency."""
        required = {"entity_id", "vendor_name", "amount", "currency", "invoice_date"}
        for i, row in enumerate(good_invoices.data):
            missing = required - set(row.keys())
            assert not missing, f"Row {i} is missing fields: {missing}"
            for field in required:
                assert row.get(field) is not None and row[field] != "", (
                    f"Row {i}: required field '{field}' is empty"
                )

    def test_good_invoices_amounts_are_decimal(self, good_invoices: ExampleSet) -> None:
        """All amount values must be parsed as Decimal, not str."""
        for i, row in enumerate(good_invoices.data):
            amount = row.get("amount")
            assert isinstance(amount, Decimal), (
                f"Row {i}: amount {amount!r} is {type(amount).__name__}, "
                f"expected Decimal"
            )

    def test_good_invoices_positive_amounts(self, good_invoices: ExampleSet) -> None:
        """All good invoice amounts must be positive."""
        for i, row in enumerate(good_invoices.data):
            amount: Decimal | None = row.get("amount")  
            assert amount is not None and amount > Decimal("0.00"), (
                f"Row {i}: amount {amount} must be positive for good invoices"
            )

    def test_good_invoices_date_format(self, good_invoices: ExampleSet) -> None:
        """All invoice_date values should be YYYY-MM-DD format."""
        for i, row in enumerate(good_invoices.data):
            date_val = str(row.get("invoice_date", ""))
            parts = date_val.split("-")
            assert len(parts) == 3, (
                f"Row {i}: invoice_date '{date_val}' is not YYYY-MM-DD"
            )
            assert len(parts[0]) == 4 and len(parts[1]) == 2 and len(parts[2]) == 2, (
                f"Row {i}: invoice_date '{date_val}' does not match YYYY-MM-DD"
            )

    def test_duplicate_invoices_count(self, duplicate_invoices: ExampleSet) -> None:
        """Duplicate invoice CSV should load exactly 5 rows."""
        assert duplicate_invoices.row_count() == 5, (
            f"Expected 5 rows, got {duplicate_invoices.row_count()}"
        )

    def test_duplicate_invoices_contains_duplicates(
        self, duplicate_invoices: ExampleSet
    ) -> None:
        """There should be at least one pair of identical rows."""
        seen: set[tuple[Any, ...]] = set()
        found_duplicates = False
        for row in duplicate_invoices.data:
            key = tuple(sorted(row.items()))
            if key in seen:
                found_duplicates = True
                break
            seen.add(key)
        assert found_duplicates, "Expected at least one duplicate row pair"

    def test_missing_vendor_has_nulls(self, missing_vendor_invoices: ExampleSet) -> None:
        """At least one row should have empty or None vendor_name."""
        null_found = False
        for row in missing_vendor_invoices.data:
            vendor = row.get("vendor_name")
            if vendor is None or vendor == "":
                null_found = True
                break
        assert null_found, "Expected at least one row with missing vendor_name"


class TestTrialBalanceExamples:
    """Tests for trial balance CSV example sets."""

    def test_balanced_tb_row_count(self, balanced_tb: ExampleSet) -> None:
        """Balanced trial balance should have exactly 11 rows (10 accounts + equity)."""
        assert balanced_tb.row_count() == 11, (
            f"Expected 11 rows, got {balanced_tb.row_count()}"
        )

    def test_balanced_tb_debits_equal_credits(self, balanced_tb: ExampleSet) -> None:
        """Total debits must equal total credits in a balanced trial balance."""
        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")
        for row in balanced_tb.data:
            debit: Decimal | None = row.get("debit")  
            credit: Decimal | None = row.get("credit")  
            if debit is not None:
                total_debit += debit
            if credit is not None:
                total_credit += credit
        assert total_debit == total_credit, (
            f"Balanced TB should have equal debits and credits, "
            f"got debits={total_debit} credits={total_credit}"
        )

    def test_unbalanced_tb_debits_not_equal_credits(
        self, unbalanced_tb: ExampleSet
    ) -> None:
        """Total debits must differ from total credits in an unbalanced TB."""
        total_debit = Decimal("0.00")
        total_credit = Decimal("0.00")
        for row in unbalanced_tb.data:
            debit: Decimal | None = row.get("debit")  
            credit: Decimal | None = row.get("credit")  
            if debit is not None:
                total_debit += debit
            if credit is not None:
                total_credit += credit
        assert total_debit != total_credit, (
            f"Unbalanced TB should have unequal debits and credits, "
            f"but got debits={total_debit} credits={total_credit}"
        )

    def test_unbalanced_tb_row_count(self, unbalanced_tb: ExampleSet) -> None:
        """Unbalanced trial balance should have exactly 10 rows."""
        assert unbalanced_tb.row_count() == 10, (
            f"Expected 10 rows, got {unbalanced_tb.row_count()}"
        )

    def test_tb_period_format(self, balanced_tb: ExampleSet) -> None:
        """All periods should be YYYY-MM format."""
        for i, row in enumerate(balanced_tb.data):
            period = str(row.get("period", ""))
            parts = period.split("-")
            assert len(parts) == 2 and len(parts[0]) == 4 and len(parts[1]) == 2, (
                f"Row {i}: period '{period}' does not match YYYY-MM"
            )


class TestBudgetVarianceExamples:
    """Tests for budget variance example sets."""

    def test_high_variance_row_count(self, high_variance_data: ExampleSet) -> None:
        """High variance CSV should have exactly 10 rows."""
        assert high_variance_data.row_count() == 10, (
            f"Expected 10 rows, got {high_variance_data.row_count()}"
        )

    def test_high_variance_all_exceed_50_percent(
        self, high_variance_data: ExampleSet
    ) -> None:
        """Every high-variance row must have >50% variance magnitude."""
        for i, row in enumerate(high_variance_data.data):
            budget: Decimal | None = row.get("budget_amount")  
            actual: Decimal | None = row.get("actual_amount")  
            assert budget is not None and actual is not None, (
                f"Row {i} missing budget_amount or actual_amount"
            )
            if budget == Decimal("0.00"):
                continue  # skip divide-by-zero
            variance_pct = abs((actual - budget) / budget) * Decimal("100.00")
            assert variance_pct > Decimal("50.00"), (
                f"Row {i}: variance {variance_pct:.2f}% is not > 50% "
                f"(budget={budget}, actual={actual})"
            )

    def test_normal_variance_row_count(self, normal_variance_data: ExampleSet) -> None:
        """Normal variance CSV should have exactly 10 rows."""
        assert normal_variance_data.row_count() == 10, (
            f"Expected 10 rows, got {normal_variance_data.row_count()}"
        )

    def test_normal_variance_all_under_10_percent(
        self, normal_variance_data: ExampleSet
    ) -> None:
        """Every normal-variance row must have <10% variance magnitude."""
        for i, row in enumerate(normal_variance_data.data):
            budget: Decimal | None = row.get("budget_amount")  
            actual: Decimal | None = row.get("actual_amount")  
            assert budget is not None and actual is not None, (
                f"Row {i} missing budget_amount or actual_amount"
            )
            if budget == Decimal("0.00"):
                continue
            variance_pct = abs((actual - budget) / budget) * Decimal("100.00")
            assert variance_pct < Decimal("10.00"), (
                f"Row {i}: variance {variance_pct:.2f}% is not < 10% "
                f"(budget={budget}, actual={actual})"
            )


class TestHeadcountExample:
    """Tests for headcount data CSV."""

    def test_headcount_row_count(self, headcount_data: ExampleSet) -> None:
        """Headcount CSV should have exactly 10 rows."""
        assert headcount_data.row_count() == 10, (
            f"Expected 10 rows, got {headcount_data.row_count()}"
        )

    def test_headcount_compensation_is_decimal(
        self, headcount_data: ExampleSet
    ) -> None:
        """Total compensation must be parsed as Decimal."""
        for i, row in enumerate(headcount_data.data):
            comp = row.get("total_compensation")
            assert isinstance(comp, Decimal), (
                f"Row {i}: total_compensation {comp!r} is "
                f"{type(comp).__name__}, expected Decimal"
            )

    def test_headcount_headcount_is_integer(self, headcount_data: ExampleSet) -> None:
        """Headcount values should be positive integers (encoded as Decimal)."""
        for i, row in enumerate(headcount_data.data):
            hc = row.get("headcount")
            assert isinstance(hc, Decimal), (
                f"Row {i}: headcount {hc!r} is {type(hc).__name__}, expected Decimal"
            )
            assert hc == int(hc), (
                f"Row {i}: headcount {hc} is not an integer value"
            )
            assert hc > Decimal("0"), (
                f"Row {i}: headcount {hc} must be positive"
            )


class TestForecastVsActualExample:
    """Tests for forecast vs actual comparison CSV."""

    def test_forecast_vs_actual_row_count(
        self, forecast_vs_actual_data: ExampleSet
    ) -> None:
        """Forecast-vs-actual CSV should have exactly 10 rows."""
        assert forecast_vs_actual_data.row_count() == 10, (
            f"Expected 10 rows, got {forecast_vs_actual_data.row_count()}"
        )

    def test_forecast_amounts_are_decimal(
        self, forecast_vs_actual_data: ExampleSet
    ) -> None:
        """forecast_amount and actual_amount must be Decimal."""
        for i, row in enumerate(forecast_vs_actual_data.data):
            fa = row.get("forecast_amount")
            aa = row.get("actual_amount")
            assert isinstance(fa, Decimal), (
                f"Row {i}: forecast_amount {fa!r} is {type(fa).__name__}"
            )
            assert isinstance(aa, Decimal), (
                f"Row {i}: actual_amount {aa!r} is {type(aa).__name__}"
            )

    def test_forecast_version_is_present(
        self, forecast_vs_actual_data: ExampleSet
    ) -> None:
        """Every row should have a forecast_version."""
        for i, row in enumerate(forecast_vs_actual_data.data):
            fv = row.get("forecast_version")
            assert fv is not None, (
                f"Row {i}: forecast_version is missing or null"
            )
