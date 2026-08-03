"""Tests for edge cases in FP&A domain logic.

Covers boundary conditions and error handling:
- Division by zero when budget is ₍0₎
- Negative amounts in different contexts
- Cross-currency without exchange rates
- Future periods in historical data
- Missing optional fields (department, vendor)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from business.examples.models import ExampleSet


class TestZeroBudgetDivisionByZero:
    """Tests for zero-budget edge cases in variance calculations."""

    def test_zero_budget_set_exists(self, edge_cases: list[ExampleSet]) -> None:
        """The zero_budget_variance edge case should be present."""
        ids = {ex.example_id for ex in edge_cases}
        assert "zero_budget_variance" in ids, (
            "zero_budget_variance edge case not found"
        )

    def test_zero_budget_variance_amount(self, edge_cases: list[ExampleSet]) -> None:
        """With zero budget, variance should equal actual."""
        for ex in edge_cases:
            if ex.example_id != "zero_budget_variance":
                continue
            for row in ex.data:
                budget: Decimal | None = row.get("budget_amount")  
                actual: Decimal | None = row.get("actual_amount")  
                variance: Decimal | None = row.get("variance_amount")  
                assert budget == Decimal("0.00"), (
                    f"Expected zero budget, got {budget}"
                )
                assert variance == actual, (
                    f"With budget=0, variance should equal actual "
                    f"({actual}), got {variance}"
                )

    def test_zero_budget_variance_pct_is_none(
        self, edge_cases: list[ExampleSet]
    ) -> None:
        """Variance % should be None (undefined) when budget is zero."""
        for ex in edge_cases:
            if ex.example_id != "zero_budget_variance":
                continue
            for i, row in enumerate(ex.data):
                pct = row.get("variance_pct")
                assert pct is None, (
                    f"Row {i}: variance_pct should be None when budget is "
                    f"zero, got {pct!r}"
                )

    @staticmethod
    def safe_variance_pct(actual: Decimal, budget: Decimal) -> Decimal | None:
        """Compute variance % with explicit division-by-zero guard."""
        if budget == Decimal("0.00"):
            return None
        return (actual - budget) / abs(budget) * Decimal("100.00")

    def test_safe_variance_pct_guard(self) -> None:
        """The safe wrapper should return None for zero budget."""
        result = self.safe_variance_pct(Decimal("50000.00"), Decimal("0.00"))
        assert result is None, "Division by zero should yield None"

    def test_safe_variance_pct_normal(self) -> None:
        """The safe wrapper should compute correctly for non-zero budget."""
        result = self.safe_variance_pct(Decimal("55000.00"), Decimal("50000.00"))
        assert result is not None
        assert result == Decimal("10.00"), (
            f"Expected 10.00% variance, got {result}"
        )


class TestNegativeAmounts:
    """Tests for negative amounts in financial data."""

    def test_negative_invoice_amounts_present(
        self, negative_amount_invoices: ExampleSet
    ) -> None:
        """At least 2 invoices should have negative amounts."""
        negative_count = 0
        for row in negative_amount_invoices.data:
            amount: Decimal | None = row.get("amount")  
            if amount is not None and amount < Decimal("0.00"):
                negative_count += 1
        assert negative_count >= 2, (
            f"Expected at least 2 negative amounts, found {negative_count}"
        )

    def test_negative_budget_set_exists(self, edge_cases: list[ExampleSet]) -> None:
        """negative_budget edge case should be present."""
        ids = {ex.example_id for ex in edge_cases}
        assert "negative_budget" in ids, "negative_budget edge case not found"

    def test_negative_budget_variance_sign(self, edge_cases: list[ExampleSet]) -> None:
        """With negative budgets, variance sign should reflect actual - budget."""
        for ex in edge_cases:
            if ex.example_id != "negative_budget":
                continue
            for i, row in enumerate(ex.data):
                budget_val: Decimal | None = row.get("budget_amount")
                actual_val: Decimal | None = row.get("actual_amount")
                assert budget_val is not None, f"Row {i}: budget_amount is None"
                assert actual_val is not None, f"Row {i}: actual_amount is None"
                expected_variance = actual_val - budget_val
                assert row.get("variance_amount") == expected_variance, (
                    f"Row {i}: variance_amount mismatch for negative budget"
                )

    def test_mixed_sign_variance_computation(self) -> None:
        """Ensure variance formula works with mixed positive/negative values."""
        test_cases: list[tuple[Decimal, Decimal, Decimal, Decimal | None]] = [
            # (actual, budget, expected_variance, expected_pct)
            (Decimal("100.00"), Decimal("-100.00"), Decimal("200.00"), Decimal("200.00")),
            (Decimal("-100.00"), Decimal("100.00"), Decimal("-200.00"), Decimal("-200.00")),
            (Decimal("-50.00"), Decimal("-100.00"), Decimal("50.00"), Decimal("50.00")),
        ]
        for actual, budget, exp_var, exp_pct in test_cases:
            variance, pct = self._compute_variance(actual, budget)
            assert variance == exp_var, (
                f"Variance({actual}, {budget}) = {variance}, expected {exp_var}"
            )
            if exp_pct is None:
                assert pct is None
            else:
                assert pct is not None and pct == exp_pct, (
                    f"Variance%({actual}, {budget}) = {pct}, expected {exp_pct}"
                )

    @staticmethod
    def _compute_variance(
        actual: Decimal, budget: Decimal
    ) -> tuple[Decimal, Decimal | None]:
        if budget == Decimal("0.00"):
            return actual - budget, None
        var = actual - budget
        pct = (var / abs(budget)) * Decimal("100.00")
        return var, pct


class TestCrossCurrency:
    """Tests for cross-currency scenarios without exchange rates."""

    def test_cross_currency_set_exists(self, edge_cases: list[ExampleSet]) -> None:
        """cross_currency_invoices edge case should be present."""
        ids = {ex.example_id for ex in edge_cases}
        assert "cross_currency_invoices" in ids, (
            "cross_currency_invoices edge case not found"
        )

    def test_multiple_currencies_present(self, edge_cases: list[ExampleSet]) -> None:
        """The cross-currency set should contain at least 2 currencies."""
        for ex in edge_cases:
            if ex.example_id != "cross_currency_invoices":
                continue
            currencies: set[str] = set()
            for row in ex.data:
                curr = row.get("currency")
                if curr is not None:
                    currencies.add(str(curr))
            assert len(currencies) >= 2, (
                f"Expected at least 2 currencies, found {currencies}"
            )

    def test_non_usd_amounts_present(self, edge_cases: list[ExampleSet]) -> None:
        """At least one row should have a non-USD currency."""
        for ex in edge_cases:
            if ex.example_id != "cross_currency_invoices":
                continue
            has_non_usd = any(
                str(row.get("currency", "")) != "USD" for row in ex.data
            )
            assert has_non_usd, "Expected at least one non-USD currency row"

    @staticmethod
    def requires_fx_rate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Identify rows that need FX conversion (non-USD amounts)."""
        return [
            r for r in rows if str(r.get("currency", "")) != "USD"
        ]

    def test_fx_required_rows_identified(self, edge_cases: list[ExampleSet]) -> None:
        """Non-USD rows should be correctly flagged as needing FX."""
        for ex in edge_cases:
            if ex.example_id != "cross_currency_invoices":
                continue
            needs_fx = self.requires_fx_rate(ex.data)
            assert len(needs_fx) >= 2, (
                f"Expected at least 2 rows needing FX, got {len(needs_fx)}"
            )


class TestFutureDatedInvoices:
    """Tests for invoices dated in the future relative to their period."""

    def test_future_dated_set_exists(self, edge_cases: list[ExampleSet]) -> None:
        """future_dated_invoices edge case should be present."""
        ids = {ex.example_id for ex in edge_cases}
        assert "future_dated_invoices" in ids, (
            "future_dated_invoices edge case not found"
        )

    @staticmethod
    def is_future_dated(invoice_date: str, period: str) -> bool:
        """Check if invoice_date (YYYY-MM-DD) is after the period end.

        Simple heuristic: compare year-month portions. If the invoice date
        falls in a later year-month than the period, it's future-dated.
        """
        date_ym = invoice_date[:7]  # YYYY-MM part
        return date_ym > period

    def test_future_dates_detected(self, edge_cases: list[ExampleSet]) -> None:
        """All rows in the future-dated set should be flagged as future-dated."""
        for ex in edge_cases:
            if ex.example_id != "future_dated_invoices":
                continue
            for i, row in enumerate(ex.data):
                inv_date = str(row.get("invoice_date", ""))
                period = str(row.get("period", ""))
                assert self.is_future_dated(inv_date, period), (
                    f"Row {i}: invoice_date {inv_date} should be "
                    f"future-dated relative to period {period}"
                )

    def test_normal_invoice_not_future_dated(
        self, good_invoices: ExampleSet
    ) -> None:
        """Good invoices should not be flagged as future-dated."""
        flagged = 0
        for row in good_invoices.data:
            inv_date = str(row.get("invoice_date", ""))
            # For good invoices, infer period from date
            period = inv_date[:7]
            if self.is_future_dated(inv_date, period):
                flagged += 1
        assert flagged == 0, (
            f"Found {flagged} future-dated invoices in good data"
        )


class TestMissingOptionalFields:
    """Tests for handling of missing optional fields (department, vendor, etc.)."""

    def test_missing_department_set_exists(self, edge_cases: list[ExampleSet]) -> None:
        """missing_department_codes edge case should be present."""
        ids = {ex.example_id for ex in edge_cases}
        assert "missing_department_codes" in ids, (
            "missing_department_codes edge case not found"
        )

    def test_missing_vendor_detected(
        self, missing_vendor_invoices: ExampleSet
    ) -> None:
        """Rows with missing vendors should be identifiable."""
        missing_count = 0
        for row in missing_vendor_invoices.data:
            vendor = row.get("vendor_name")
            if vendor is None or vendor == "":
                missing_count += 1
        assert missing_count == 2, (
            f"Expected 2 missing vendors, found {missing_count}"
        )

    @staticmethod
    def has_department(row: dict[str, Any]) -> bool:
        """Check whether a row has a usable department field."""
        dept = row.get("department")
        return dept is not None and dept != "" and dept != "Unassigned"

    def test_department_absent_variants(self, edge_cases: list[ExampleSet]) -> None:
        """Test each variant of missing department (None, empty, 'Unassigned')."""
        for ex in edge_cases:
            if ex.example_id != "missing_department_codes":
                continue
            none_row = ex.data[0]
            empty_row = ex.data[1]
            unassigned_row = ex.data[2]

            assert not self.has_department(none_row), (
                "None department should be flagged as absent"
            )
            assert not self.has_department(empty_row), (
                "Empty department should be flagged as absent"
            )
            assert not self.has_department(unassigned_row), (
                "'Unassigned' department should be flagged as absent"
            )


class TestDormantPeriod:
    """Tests for periods with budget but zero actuals."""

    def test_period_with_no_actuals_exists(
        self, edge_cases: list[ExampleSet]
    ) -> None:
        """period_with_no_actuals edge case should be present."""
        ids = {ex.example_id for ex in edge_cases}
        assert "period_with_no_actuals" in ids, (
            "period_with_no_actuals edge case not found"
        )

    def test_all_actuals_are_zero(self, edge_cases: list[ExampleSet]) -> None:
        """All rows in the dormant period should have zero actuals."""
        for ex in edge_cases:
            if ex.example_id != "period_with_no_actuals":
                continue
            for i, row in enumerate(ex.data):
                actual: Decimal | None = row.get("actual_amount")  
                assert actual == Decimal("0.00"), (
                    f"Row {i}: expected actual_amount of 0, got {actual}"
                )

    def test_dormant_period_key(self, edge_cases: list[ExampleSet]) -> None:
        """All rows must share the same period."""
        for ex in edge_cases:
            if ex.example_id != "period_with_no_actuals":
                continue
            periods = {row.get("period") for row in ex.data}
            assert len(periods) == 1, (
                f"Dormant period rows span multiple periods: {periods}"
            )
            assert "2026-06" in periods, (
                f"Expected period 2026-06, got {periods}"
            )


class TestMultiPeriodBudgetRevisions:
    """Tests for budget lines revised across multiple versions."""

    def test_multi_period_set_exists(self, edge_cases: list[ExampleSet]) -> None:
        """multi_period_budget_revisions edge case should be present."""
        ids = {ex.example_id for ex in edge_cases}
        assert "multi_period_budget_revisions" in ids, (
            "multi_period_budget_revisions edge case not found"
        )

    def test_revision_versions_present(self, edge_cases: list[ExampleSet]) -> None:
        """The same account/period should have multiple budget versions."""
        for ex in edge_cases:
            if ex.example_id != "multi_period_budget_revisions":
                continue
            key_to_versions: dict[tuple[str, str, str], list[int]] = {}
            for row in ex.data:
                key = (
                    str(row.get("entity_id", "")),
                    str(row.get("period", "")),
                    str(row.get("account_id", "")),
                )
                ver = row.get("budget_version")
                ver_int = int(ver) if isinstance(ver, Decimal) else int(str(ver))  
                key_to_versions.setdefault(key, []).append(ver_int)

            has_multi = any(len(v) > 1 for v in key_to_versions.values())
            assert has_multi, (
                "Expected at least one account/period with multiple budget versions"
            )

    def test_revision_amounts_differ(self, edge_cases: list[ExampleSet]) -> None:
        """Different versions of the same budget line should have different amounts."""
        for ex in edge_cases:
            if ex.example_id != "multi_period_budget_revisions":
                continue
            key_to_amounts: dict[tuple[str, str, str], set[Decimal]] = {}
            for row in ex.data:
                key = (
                    str(row.get("entity_id", "")),
                    str(row.get("period", "")),
                    str(row.get("account_id", "")),
                )
                amount: Decimal | None = row.get("amount")  
                if amount is not None:
                    key_to_amounts.setdefault(key, set()).add(amount)

            differing = any(len(v) > 1 for v in key_to_amounts.values())
            assert differing, (
                "Expected different amounts across budget versions"
            )


class TestExampleLibrary:
    """Tests for the ExampleLibrary registry itself."""

    def test_library_populated(self, example_library: Any) -> None:
        """The example library should contain registered sets."""
        assert len(example_library) > 0, "Example library is empty"

    def test_lookup_by_domain(self, example_library: Any) -> None:
        """Domain filtering should return the correct sets."""
        invoice_sets = example_library.by_domain("invoices")
        assert len(invoice_sets) >= 4, (
            f"Expected at least 4 invoice sets, got {len(invoice_sets)}"
        )
        variance_sets = example_library.by_domain("variance")
        assert len(variance_sets) >= 3, (
            f"Expected at least 3 variance sets, got {len(variance_sets)}"
        )

    def test_lookup_by_tag(self, example_library: Any) -> None:
        """Tag filtering should return correct sets."""
        edge_case_sets = example_library.by_tag("edge-case")
        assert len(edge_case_sets) >= 1, (
            f"Expected at least 1 edge-case set, got {len(edge_case_sets)}"
        )
        valid_sets = example_library.by_tag("valid")
        assert len(valid_sets) >= 1, (
            f"Expected at least 1 valid set, got {len(valid_sets)}"
        )

    def test_get_edge_cases(self, example_library: Any) -> None:
        """Library should return edge cases from both CSV and programmatic sources."""
        edge_cases_list = example_library.get_edge_cases()
        assert len(edge_cases_list) > 0, "No edge cases registered"
        ids = {ex.example_id for ex in edge_cases_list}
        assert "zero_budget_variance" in ids, (
            "Programmatic edge case not found in library"
        )

    def test_round_trip_csv(self) -> None:
        """An ExampleSet should survive a CSV round-trip."""
        from business.examples.models import ExampleSet

        original = ExampleSet(
            example_id="round_trip_test",
            name="Round Trip",
            description="Test round-trip fidelity",
            domain="test",
            data=[
                {"a": Decimal("1.00"), "b": "hello"},
                {"a": Decimal("2.50"), "b": "world"},
            ],
            tags=["test"],
            source="programmatic",
        )
        csv_str = original.to_csv_string()
        assert "a,b" in csv_str, "CSV header missing"
        assert "1.00" in csv_str, "Decimal value missing in CSV"

        # Parse it back
        import csv
        import io

        reader = csv.DictReader(io.StringIO(csv_str))
        rows = list(reader)
        assert len(rows) == 2, f"Expected 2 rows, got {len(rows)}"
        assert rows[0]["a"] == "1.00", (
            f"Round-trip value changed: {rows[0]['a']}"
        )
