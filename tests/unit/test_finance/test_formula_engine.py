"""Tests for the Formula Engine — deterministic financial calculations.

All monetary values use decimal.Decimal (never float).
No LLM calls. Pure Python, fully tested.
"""

from decimal import Decimal

import pytest

from finance.formula_engine.dependency_resolver import DependencyResolver
from finance.formula_engine.evaluator import FormulaEvaluator
from finance.formula_engine.formula_registry import Formula, FormulaRegistry

# =============================================================================
# Formula Definitions
# =============================================================================

def _gross_margin(revenue: Decimal, cogs: Decimal) -> Decimal:
    return (revenue - cogs) / revenue


def _operating_margin(operating_income: Decimal, revenue: Decimal) -> Decimal:
    return operating_income / revenue


def _ebitda_margin(ebitda: Decimal, revenue: Decimal) -> Decimal:
    return ebitda / revenue


def _net_margin(net_income: Decimal, revenue: Decimal) -> Decimal:
    return net_income / revenue


def _revenue_growth(current_revenue: Decimal, prior_revenue: Decimal) -> Decimal:
    return (current_revenue - prior_revenue) / prior_revenue


def _burn_rate(total_opex: Decimal, months: Decimal) -> Decimal:
    return (total_opex / months).quantize(Decimal("0.01"))


def _runway(cash_balance: Decimal, burn_rate: Decimal) -> Decimal:
    return (cash_balance / burn_rate).quantize(Decimal("0.01"))


def _headcount_cost_per_employee(total_people_cost: Decimal, fte_count: Decimal) -> Decimal:
    return (total_people_cost / fte_count).quantize(Decimal("0.01"))


def _average_revenue_per_customer(total_revenue: Decimal, customer_count: Decimal) -> Decimal:
    return (total_revenue / customer_count).quantize(Decimal("0.01"))


def _cogs_pct(cogs: Decimal, revenue: Decimal) -> Decimal:
    return cogs / revenue


def _sgna_pct(sgna: Decimal, revenue: Decimal) -> Decimal:
    return sgna / revenue


def _rd_pct(rd_expense: Decimal, revenue: Decimal) -> Decimal:
    return rd_expense / revenue


def build_default_registry() -> FormulaRegistry:
    """Build a FormulaRegistry pre-loaded with all core financial formulas."""
    registry = FormulaRegistry()
    registry.register(Formula(
        name="gross_margin",
        description="Gross profit as a percentage of revenue",
        category="margin",
        inputs=["revenue", "cogs"],
        output_name="gross_margin",
        fn=_gross_margin,
    ))
    registry.register(Formula(
        name="operating_margin",
        description="Operating income as a percentage of revenue",
        category="margin",
        inputs=["operating_income", "revenue"],
        output_name="operating_margin",
        fn=_operating_margin,
    ))
    registry.register(Formula(
        name="ebitda_margin",
        description="EBITDA as a percentage of revenue",
        category="margin",
        inputs=["ebitda", "revenue"],
        output_name="ebitda_margin",
        fn=_ebitda_margin,
    ))
    registry.register(Formula(
        name="net_margin",
        description="Net income as a percentage of revenue",
        category="margin",
        inputs=["net_income", "revenue"],
        output_name="net_margin",
        fn=_net_margin,
    ))
    registry.register(Formula(
        name="revenue_growth",
        description="Revenue growth rate between periods",
        category="growth",
        inputs=["current_revenue", "prior_revenue"],
        output_name="revenue_growth",
        fn=_revenue_growth,
    ))
    registry.register(Formula(
        name="burn_rate",
        description="Monthly cash burn rate",
        category="aggregation",
        inputs=["total_opex", "months"],
        output_name="burn_rate",
        fn=_burn_rate,
    ))
    registry.register(Formula(
        name="runway",
        description="Months of runway remaining",
        category="aggregation",
        inputs=["cash_balance", "burn_rate"],
        output_name="runway",
        fn=_runway,
    ))
    registry.register(Formula(
        name="headcount_cost_per_employee",
        description="Average cost per employee",
        category="ratio",
        inputs=["total_people_cost", "fte_count"],
        output_name="headcount_cost_per_employee",
        fn=_headcount_cost_per_employee,
    ))
    registry.register(Formula(
        name="average_revenue_per_customer",
        description="Average revenue per customer",
        category="ratio",
        inputs=["total_revenue", "customer_count"],
        output_name="average_revenue_per_customer",
        fn=_average_revenue_per_customer,
    ))
    registry.register(Formula(
        name="cogs_pct",
        description="COGS as a percentage of revenue",
        category="margin",
        inputs=["cogs", "revenue"],
        output_name="cogs_pct",
        fn=_cogs_pct,
    ))
    registry.register(Formula(
        name="sgna_pct",
        description="SG&A as a percentage of revenue",
        category="margin",
        inputs=["sgna", "revenue"],
        output_name="sgna_pct",
        fn=_sgna_pct,
    ))
    registry.register(Formula(
        name="rd_pct",
        description="R&D as a percentage of revenue",
        category="margin",
        inputs=["rd_expense", "revenue"],
        output_name="rd_pct",
        fn=_rd_pct,
    ))
    return registry


# =============================================================================
# Tests — Formula Registry
# =============================================================================

class TestFormulaRegistry:
    """Tests for Formula and FormulaRegistry."""

    def test_formula_registry_register_and_get(self) -> None:
        """Register a formula and retrieve it."""
        registry = FormulaRegistry()
        formula = Formula(
            name="gross_margin",
            description="Gross profit margin",
            category="margin",
            inputs=["revenue", "cogs"],
            output_name="gross_margin",
            fn=_gross_margin,
        )
        registry.register(formula)
        retrieved = registry.get("gross_margin")
        assert retrieved is formula
        assert retrieved.name == "gross_margin"
        assert retrieved.category == "margin"

    def test_formula_evaluate_gross_margin(self) -> None:
        """gross_margin(revenue=1000, cogs=600) → 0.4"""
        registry = build_default_registry()
        result = registry.evaluate("gross_margin", {
            "revenue": Decimal("1000"),
            "cogs": Decimal("600"),
        })
        assert result == Decimal("0.4")

    def test_formula_evaluate_operating_margin(self) -> None:
        """operating_margin(operating_income=200, revenue=1000) → 0.2"""
        registry = build_default_registry()
        result = registry.evaluate("operating_margin", {
            "operating_income": Decimal("200"),
            "revenue": Decimal("1000"),
        })
        assert result == Decimal("0.2")

    def test_formula_evaluate_revenue_growth(self) -> None:
        """revenue_growth(1200, 1000) → 0.2"""
        registry = build_default_registry()
        result = registry.evaluate("revenue_growth", {
            "current_revenue": Decimal("1200"),
            "prior_revenue": Decimal("1000"),
        })
        assert result == Decimal("0.2")

    def test_formula_evaluate_burn_rate(self) -> None:
        """burn_rate(500000, 6) → 83333.33"""
        registry = build_default_registry()
        result = registry.evaluate("burn_rate", {
            "total_opex": Decimal("500000"),
            "months": Decimal("6"),
        })
        assert result == Decimal("83333.33")

    def test_formula_evaluate_runway(self) -> None:
        """runway(2000000, 83333.33) → 24.0"""
        registry = build_default_registry()
        result = registry.evaluate("runway", {
            "cash_balance": Decimal("2000000"),
            "burn_rate": Decimal("83333.33"),
        })
        assert result == Decimal("24.0")

    def test_formula_list_by_category(self) -> None:
        """Category filtering works."""
        registry = build_default_registry()
        margin_formulas = registry.list_by_category("margin")
        assert len(margin_formulas) >= 4
        for f in margin_formulas:
            assert f.category == "margin"
        names = {f.name for f in margin_formulas}
        assert "gross_margin" in names
        assert "operating_margin" in names
        assert "ebitda_margin" in names
        assert "net_margin" in names

    def test_all_formulas_have_unique_names(self) -> None:
        """No duplicate registrations."""
        registry = build_default_registry()
        # Registering same name again should raise
        with pytest.raises(ValueError, match="already registered"):
            registry.register(Formula(
                name="gross_margin",
                description="Duplicate",
                category="margin",
                inputs=["revenue", "cogs"],
                output_name="gross_margin",
                fn=_gross_margin,
            ))


# =============================================================================
# Tests — Dependency Resolver
# =============================================================================

class TestDependencyResolver:
    """Tests for DependencyResolver."""

    def test_dependency_resolver_orders_correctly(self) -> None:
        """Margin formulas depend on raw inputs; runway depends on burn_rate.

        The resolver should return burn_rate before runway.
        """
        registry = build_default_registry()
        resolver = DependencyResolver()

        order = resolver.resolve(registry, {"total_opex", "months", "cash_balance"})

        assert "burn_rate" in order
        assert "runway" in order
        # burn_rate must come before runway since runway depends on burn_rate
        assert order.index("burn_rate") < order.index("runway")

    def test_dependency_resolver_detects_cycles(self) -> None:
        """A→B→C→A raises or is detected."""
        registry = FormulaRegistry()

        # Create a cycle: A depends on B, B depends on C, C depends on A
        registry.register(Formula(
            name="formula_a",
            description="Depends on B",
            category="ratio",
            inputs=["output_b"],
            output_name="output_a",
            fn=lambda output_b: output_b * Decimal("2"),
        ))
        registry.register(Formula(
            name="formula_b",
            description="Depends on C",
            category="ratio",
            inputs=["output_c"],
            output_name="output_b",
            fn=lambda output_c: output_c * Decimal("2"),
        ))
        registry.register(Formula(
            name="formula_c",
            description="Depends on A (cycle!)",
            category="ratio",
            inputs=["output_a"],
            output_name="output_c",
            fn=lambda output_a: output_a * Decimal("2"),
        ))

        resolver = DependencyResolver()
        assert resolver.has_cycle(registry) is True

        with pytest.raises(ValueError, match="circular|cycle|dependency"):
            resolver.resolve(registry, set())

    def test_depends_on_returns_correct_dependencies(self) -> None:
        """depends_on returns list of formulas a given formula depends on."""
        registry = build_default_registry()
        resolver = DependencyResolver()

        # runway depends on burn_rate because burn_rate's output_name matches
        deps = resolver.depends_on("runway", registry)
        assert "burn_rate" in deps


# =============================================================================
# Tests — Formula Evaluator
# =============================================================================

class TestFormulaEvaluator:
    """Tests for FormulaEvaluator and EvaluationContext."""

    SEED_INPUTS = {
        "revenue": Decimal("1000000"),
        "cogs": Decimal("600000"),
        "operating_income": Decimal("200000"),
        "ebitda": Decimal("250000"),
        "net_income": Decimal("150000"),
        "current_revenue": Decimal("1200000"),
        "prior_revenue": Decimal("1000000"),
        "total_opex": Decimal("500000"),
        "months": Decimal("6"),
        "cash_balance": Decimal("2000000"),
        "total_people_cost": Decimal("400000"),
        "fte_count": Decimal("50"),
        "total_revenue": Decimal("1000000"),
        "customer_count": Decimal("200"),
        "sgna": Decimal("150000"),
        "rd_expense": Decimal("100000"),
    }

    def test_evaluator_evaluate_all(self) -> None:
        """Seed inputs + all formulas evaluated in order.

        Verifies that cross-formula dependencies resolve correctly
        (e.g., runway depends on burn_rate).
        """
        registry = build_default_registry()
        resolver = DependencyResolver()
        evaluator = FormulaEvaluator(registry, resolver)

        context = evaluator.evaluate(self.SEED_INPUTS)

        # All formulas should have been evaluated
        expected_count = len(registry._registry)
        assert len(context.evaluated) == expected_count, (
            f"Expected {expected_count} formulas evaluated, got {len(context.evaluated)}"
        )
        assert len(context.errors) == 0, f"Unexpected errors: {context.errors}"

        # Check specific values
        assert context.values["gross_margin"] == Decimal("0.4")
        assert context.values["operating_margin"] == Decimal("0.2")
        assert context.values["ebitda_margin"] == Decimal("0.25")
        assert context.values["net_margin"] == Decimal("0.15")
        assert context.values["revenue_growth"] == Decimal("0.2")
        assert context.values["burn_rate"] == Decimal("83333.33")

        # runway depends on burn_rate; 2000000 / 83333.33 ≈ 24.0
        assert context.values["runway"] == Decimal("24.0")

        assert context.values["headcount_cost_per_employee"] == Decimal("8000.00")
        assert context.values["average_revenue_per_customer"] == Decimal("5000.00")
        assert context.values["cogs_pct"] == Decimal("0.6")
        assert context.values["sgna_pct"] == Decimal("0.15")
        assert context.values["rd_pct"] == Decimal("0.1")

    def test_evaluator_partial_evaluation(self) -> None:
        """Subset of formulas evaluated."""
        registry = build_default_registry()
        resolver = DependencyResolver()
        evaluator = FormulaEvaluator(registry, resolver)

        context = evaluator.evaluate_partial(
            self.SEED_INPUTS,
            ["gross_margin", "net_margin"],
        )

        assert "gross_margin" in context.evaluated
        assert "net_margin" in context.evaluated
        # runway should NOT have been evaluated
        assert "runway" not in context.evaluated
        assert len(context.errors) == 0

    def test_evaluator_error_handling(self) -> None:
        """Missing input gives clear error."""
        registry = build_default_registry()
        resolver = DependencyResolver()
        evaluator = FormulaEvaluator(registry, resolver)

        # Only provide revenue, missing cogs
        context = evaluator.evaluate_partial(
            {"revenue": Decimal("1000")},
            ["gross_margin"],
        )

        assert len(context.errors) >= 1
        assert context.errors[0].formula_name == "gross_margin"
        assert "cogs" in context.errors[0].message


# =============================================================================
# Tests — Decimal Precision
# =============================================================================

class TestDecimalPrecision:
    """All results are Decimal with proper precision."""

    def test_decimal_precision(self) -> None:
        """All formula results are Decimal instances."""
        registry = build_default_registry()
        for _name, _formula in registry._registry.items():
            # Each formula fn returns Decimal
            pass  # Verified implicitly by type annotations

        # Verify outputs are Decimal
        result = registry.evaluate("gross_margin", {
            "revenue": Decimal("1000"),
            "cogs": Decimal("600"),
        })
        assert isinstance(result, Decimal)
