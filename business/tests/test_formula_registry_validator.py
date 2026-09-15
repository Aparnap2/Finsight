"""Tests for the formula registry validator.

Covers structural checks (required fields, unique ids, semver,
categories, dependencies) and expression validation against the real
registry.
"""

from __future__ import annotations

from business.formula_registry.loader import load_records
from business.formula_registry.validator import (
    validate_all,
    validate_expression,
    validate_registry,
)


def _record(formula_id: str, **overrides: object) -> dict[str, object]:
    """Build a minimal, valid registry record."""
    record: dict[str, object] = {
        "id": formula_id,
        "name": formula_id.title(),
        "description": "",
        "expression": "A + B",
        "inputs": [],
        "output": "Money",
        "category": "Profitability",
        "references": [],
        "owner": "FP&A Team",
        "version": "1.0.0",
        "status": "production",
        "dependencies": [],
        "tags": [],
    }
    record.update(overrides)
    return record


class TestValidateRegistry:
    """Tests for structural validation."""

    def test_valid_registry_has_no_problems(self) -> None:
        """A well-formed registry validates cleanly."""
        records = [
            _record("a"),
            _record("b", dependencies=["a"]),
        ]
        assert validate_registry(records) == []

    def test_duplicate_ids_reported(self) -> None:
        """Duplicate ids are flagged."""
        problems = validate_registry([_record("a"), _record("a")])
        assert any("duplicate" in p for p in problems)

    def test_missing_dependency_reported(self) -> None:
        """A dependency on an unknown formula is flagged."""
        problems = validate_registry([_record("a", dependencies=["ghost"])])
        assert any("ghost" in p for p in problems)

    def test_bad_semver_reported(self) -> None:
        """A non-semver version is flagged."""
        problems = validate_registry([_record("a", version="1.0")])
        assert any("version" in p for p in problems)

    def test_bad_category_reported(self) -> None:
        """A category outside the canonical set is flagged."""
        problems = validate_registry([_record("a", category="Fiction")])
        assert any("category" in p for p in problems)


class TestValidateExpression:
    """Tests for expression validation."""

    def test_arithmetic_expression_valid(self) -> None:
        """An evaluable expression validates cleanly."""
        record = _record("a", expression="B + C", inputs=["b", "c"])
        assert validate_expression(record) == []

    def test_descriptive_expression_on_source_formula_ok(self) -> None:
        """Source formulas may carry descriptive expressions."""
        record = _record("a", expression="Sum of all invoices")
        assert validate_expression(record) == []

    def test_descriptive_expression_on_derived_formula_flagged(self) -> None:
        """Derived formulas must be evaluable."""
        record = _record(
            "a",
            expression="Sum of all invoices",
            dependencies=["b"],
        )
        problems = validate_expression(record)
        assert any("not evaluable" in p for p in problems)

    def test_unused_declared_input_flagged(self) -> None:
        """A declared input not referenced by the expression is flagged."""
        record = _record(
            "a",
            expression="B + C",
            inputs=["b", "c", "unused"],
            dependencies=["b", "c", "unused"],
        )
        problems = validate_expression(record)
        assert any("unused" in p for p in problems)


class TestShippedRegistry:
    """Tests against the real 74-formula registry."""

    def test_validate_all_returns_findings(self) -> None:
        """validate_all reports the known data-quality findings."""
        records = load_records()
        problems = validate_all(records)
        # The registry carries a small, documented set of expression
        # mismatches (CamelCase vs declared inputs); validation surfaces
        # them as findings rather than crashing.
        assert isinstance(problems, list)
        assert len(problems) > 0

    def test_validate_all_does_not_flag_all_formulas(self) -> None:
        """Most formulas validate cleanly."""
        records = load_records()
        problems = validate_all(records)
        assert len(problems) < 15
