"""Tests for the formula lineage graph.

Covers dependency traversal, dependents, impact analysis, leaves, and
cycle detection.
"""

from __future__ import annotations

from business.formula_registry.lineage import FormulaLineage
from business.formula_registry.loader import load_records


def _record(formula_id: str, deps: list[str] | None = None) -> dict[str, object]:
    """Build a minimal registry record."""
    return {
        "id": formula_id,
        "name": formula_id.title(),
        "description": "",
        "expression": "",
        "inputs": deps or [],
        "output": "Money",
        "category": "Profitability",
        "references": [],
        "owner": "FP&A Team",
        "version": "1.0.0",
        "status": "production",
        "dependencies": deps or [],
        "tags": [],
    }


class TestFormulaLineage:
    """Tests for the lineage graph."""

    def test_dependencies_of_returns_closure(self) -> None:
        """dependencies_of returns the full transitive closure."""
        lineage = FormulaLineage(
            [
                _record("c", ["b"]),
                _record("b", ["a"]),
                _record("a"),
            ]
        )
        assert lineage.dependencies_of("c") == ["a", "b"]

    def test_dependents_of_direct(self) -> None:
        """dependents_of returns direct consumers only."""
        lineage = FormulaLineage(
            [
                _record("a"),
                _record("b", ["a"]),
                _record("c", ["a"]),
                _record("d", ["b"]),
            ]
        )
        assert set(lineage.dependents_of("a")) == {"b", "c"}
        assert set(lineage.dependents_of("b")) == {"d"}

    def test_find_leaves(self) -> None:
        """Leaves are formulas nothing depends on."""
        lineage = FormulaLineage(
            [
                _record("a"),
                _record("b", ["a"]),
                _record("c", ["b"]),
            ]
        )
        assert lineage.find_leaves() == ["c"]

    def test_impact_analysis(self) -> None:
        """Impact analysis separates direct and transitive dependents."""
        lineage = FormulaLineage(
            [
                _record("a"),
                _record("b", ["a"]),
                _record("c", ["a"]),
                _record("d", ["b"]),
                _record("e", ["c"]),
            ]
        )
        impact = lineage.impact_analysis("a")
        assert set(impact["direct_dependents"]) == {"b", "c"}
        assert set(impact["transitive_dependents"]) == {"d", "e"}
        assert set(impact["all_affected"]) == {"b", "c", "d", "e"}
        assert "a" not in impact["all_affected"]

    def test_detect_cycles(self) -> None:
        """Cycles are reported in cycle order."""
        lineage = FormulaLineage(
            [
                _record("a", ["b"]),
                _record("b", ["c"]),
                _record("c", ["a"]),
            ]
        )
        cycles = lineage.detect_cycles()
        assert len(cycles) == 1
        assert cycles[0][0] == cycles[0][-1]

    def test_no_cycles_returns_empty(self) -> None:
        """An acyclic graph reports no cycles."""
        lineage = FormulaLineage(
            [
                _record("a"),
                _record("b", ["a"]),
                _record("c", ["b"]),
            ]
        )
        assert lineage.detect_cycles() == []

    def test_duplicate_id_raises(self) -> None:
        """Duplicate ids are rejected at construction."""
        try:
            FormulaLineage([_record("a"), _record("a")])
        except ValueError:
            return
        raise AssertionError("expected ValueError for duplicate ids")

    def test_unknown_dependency_raises(self) -> None:
        """Dependencies on unknown formulas are rejected."""
        try:
            FormulaLineage([_record("a", ["ghost"])])
        except ValueError:
            return
        raise AssertionError("expected ValueError for unknown dependency")

    def test_contains_and_len(self) -> None:
        """Membership and length are supported."""
        lineage = FormulaLineage([_record("a")])
        assert "a" in lineage
        assert len(lineage) == 1


class TestShippedRegistryLineage:
    """Tests against the real 74-formula registry."""

    def test_registry_is_acyclic(self) -> None:
        """The shipped registry has no dependency cycles."""
        lineage = FormulaLineage(load_records())
        assert lineage.detect_cycles() == []

    def test_registry_has_leaves(self) -> None:
        """The shipped registry has source-formula leaves."""
        lineage = FormulaLineage(load_records())
        assert len(lineage.find_leaves()) >= 30

    def test_impact_chain_for_net_revenue(self) -> None:
        """Net revenue changes propagate to many derived metrics."""
        lineage = FormulaLineage(load_records())
        impact = lineage.impact_analysis("net_revenue")
        assert impact["direct_dependents"]
        assert len(impact["all_affected"]) >= 10
