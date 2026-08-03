"""Tests for the safe formula compiler.

Covers compilation of registry expressions, Decimal-safe evaluation,
source-input handling, and rejection of unsafe AST constructs.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from business.formula_registry.compiler import (
    FormulaEvaluationError,
    _normalise,
    compile_formula,
)
from business.formula_registry.loader import load_records

GROSS_MARGIN = {
    "id": "gross_margin",
    "name": "Gross Margin",
    "expression": "(NetRevenue - COGS) / NetRevenue * 100",
    "inputs": ["net_revenue", "cogs"],
    "output": "Percentage",
    "category": "Profitability",
    "references": [],
    "owner": "FP&A Team",
    "version": "1.0.0",
    "status": "production",
    "dependencies": ["net_revenue", "cogs"],
    "tags": [],
}


class TestNormalise:
    """Tests for the CamelCase/snake_case normaliser."""

    def test_camel_and_snake_match(self) -> None:
        """NetRevenue and net_revenue normalise identically."""
        assert _normalise("NetRevenue") == _normalise("net_revenue") == "netrevenue"

    def test_strips_non_alphanumeric(self) -> None:
        """Punctuation is stripped."""
        assert _normalise("D&A") == "da"


class TestCompileFormula:
    """Tests for :func:`compile_formula`."""

    def test_compiles_arithmetic(self) -> None:
        """A simple arithmetic expression compiles as supported."""
        compiled = compile_formula(GROSS_MARGIN)
        assert compiled.supported
        assert compiled.inputs == ["cogs", "net_revenue"]

    def test_evaluate_with_decimal_inputs(self) -> None:
        """Evaluation returns a Decimal result."""
        compiled = compile_formula(GROSS_MARGIN)
        result = compiled.evaluate(
            {"net_revenue": Decimal("1000"), "cogs": Decimal("600")}
        )
        assert result == Decimal("40.0")
        assert isinstance(result, Decimal)

    def test_evaluate_rejects_float_inputs(self) -> None:
        """Float inputs are coerced through Decimal, not used raw."""
        compiled = compile_formula(GROSS_MARGIN)
        inputs: dict[str, Decimal] = {
            "net_revenue": 1000,  # type: ignore[dict-item]
            "cogs": 600,  # type: ignore[dict-item]
        }
        result = compiled.evaluate(inputs)
        assert isinstance(result, Decimal)

    def test_missing_input_raises(self) -> None:
        """Evaluation without all inputs raises."""
        compiled = compile_formula(GROSS_MARGIN)
        with pytest.raises(FormulaEvaluationError):
            compiled.evaluate({"net_revenue": Decimal("1000")})

    def test_source_inputs_for_unknown_names(self) -> None:
        """Unresolved CamelCase names become caller-supplied source inputs."""
        record = {
            **GROSS_MARGIN,
            "expression": "NetRevenue - Returns - Discounts",
            "inputs": ["net_revenue"],
        }
        compiled = compile_formula(record)
        assert compiled.supported
        assert "Returns" in compiled.source_inputs
        assert "Discounts" in compiled.source_inputs

    def test_evaluate_with_source_inputs(self) -> None:
        """Evaluation accepts raw source field names."""
        record = {
            **GROSS_MARGIN,
            "expression": "NetRevenue - Returns - Discounts",
            "inputs": ["net_revenue"],
        }
        compiled = compile_formula(record)
        result = compiled.evaluate(
            {
                "net_revenue": Decimal("1200"),
                "Returns": Decimal("100"),
                "Discounts": Decimal("100"),
            }
        )
        assert result == Decimal("1000")

    def test_disallowed_call_rejected(self) -> None:
        """Calls outside the allow-list are unsupported."""
        record = {
            **GROSS_MARGIN,
            "expression": "open('x').read()",
            "inputs": [],
        }
        compiled = compile_formula(record)
        assert not compiled.supported
        assert compiled.unsupported_reason

    def test_bool_constant_rejected(self) -> None:
        """Boolean constants are not coerced to numbers."""
        record = {**GROSS_MARGIN, "expression": "True", "inputs": []}
        compiled = compile_formula(record)
        assert not compiled.supported

    def test_registry_wide_name_resolution(self) -> None:
        """Names resolve against a registry name index."""
        records = load_records()
        name_index = {
            _normalise(r["id"]): r["id"] for r in records
        }
        record = next(r for r in records if r["id"] == "gross_margin")
        compiled = compile_formula(record, name_index)
        assert compiled.supported
        assert "net_revenue" in compiled.inputs


class TestCompiledFormula:
    """Tests for the CompiledFormula object."""

    def test_attributes_exposed(self) -> None:
        """Key metadata is exposed as attributes."""
        compiled = compile_formula(GROSS_MARGIN)
        assert compiled.formula_id == "gross_margin"
        assert compiled.expression == "(NetRevenue - COGS) / NetRevenue * 100"
        assert compiled.supported is True

    def test_division_by_zero_raises(self) -> None:
        """Division by zero raises a FormulaEvaluationError."""
        compiled = compile_formula(
            {**GROSS_MARGIN, "expression": "A / B", "inputs": []}
        )
        with pytest.raises(FormulaEvaluationError):
            compiled.evaluate({"A": Decimal("1"), "B": Decimal("0")})

    def test_power_and_functions(self) -> None:
        """Allow-listed functions and power operator evaluate."""
        compiled = compile_formula(
            {
                **GROSS_MARGIN,
                "expression": "max(A, B) ** 2 + abs(C)",
                "inputs": [],
            }
        )
        result = compiled.evaluate(
            {"A": Decimal("2"), "B": Decimal("3"), "C": Decimal("-4")}
        )
        assert result == Decimal("13")
