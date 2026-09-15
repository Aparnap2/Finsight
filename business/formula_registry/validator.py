"""Validation for the elevated formula registry.

Checks that a registry (``registry.yaml``) is internally consistent:

* every record has the required registry-v1 fields;
* ids are unique and dependency references resolve;
* versions are three-part semantic versions;
* categories and output types come from the canonical sets;
* expressions compile safely (via :mod:`business.formula_registry.compiler`)
  and reference only declared inputs.

All checks are *report-style*: they accumulate human-readable problem
strings instead of raising, so a registry can be linted in CI.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from business.formula_registry.compiler import _normalise, compile_formula
from business.formula_registry.lineage import FormulaLineage

#: Canonical category values (must match ``FormulaCategory`` enum values).
_CATEGORIES: frozenset[str] = frozenset(
    {
        "Revenue",
        "Expense",
        "Profitability",
        "Liquidity",
        "Efficiency",
        "Budgeting",
        "Variance",
        "BalanceSheet",
        "CashFlow",
        "Forecasting",
    },
)

#: Canonical output types (must match ``DataType`` literal values).
_OUTPUTS: frozenset[str] = frozenset({"Money", "Percentage", "Ratio", "Count", "Days"})

#: Canonical lifecycle statuses.
_STATUSES: frozenset[str] = frozenset({"discovery", "implemented", "production", "deprecated"})

#: Fields required on every registry-v1 record.
_REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "description",
        "expression",
        "inputs",
        "output",
        "category",
        "references",
        "owner",
        "version",
        "status",
        "dependencies",
    },
)


def _semver_ok(version: str) -> bool:
    """Check a string is a three-part semantic version.

    Args:
        version: Version string.

    Returns:
        True when the version matches ``MAJOR.MINOR.PATCH``.
    """
    parts = version.split(".")
    return len(parts) == 3 and all(p.isdigit() for p in parts)


def validate_registry(records: list[dict[str, Any]]) -> list[str]:
    """Validate a registry's structural integrity.

    Args:
        records: List of registry-v1 formula records.

    Returns:
        List of problem strings; empty when the registry is valid.
    """
    problems: list[str] = []
    seen_ids: set[str] = set()
    id_map = {str(r.get("id")): r for r in records if r.get("id") is not None}

    for record in records:
        formula_id = str(record.get("id"))

        missing = _REQUIRED_FIELDS - set(record)
        if missing:
            problems.append(
                f"formula '{formula_id}' missing fields: {', '.join(sorted(missing))}"
            )
            continue

        if formula_id in seen_ids:
            problems.append(f"duplicate formula id '{formula_id}'")
        seen_ids.add(formula_id)

        if not _semver_ok(str(record["version"])):
            problems.append(
                f"formula '{formula_id}' version '{record['version']}' "
                "is not MAJOR.MINOR.PATCH"
            )

        if record["category"] not in _CATEGORIES:
            problems.append(
                f"formula '{formula_id}' unknown category '{record['category']}'"
            )

        if record["output"] not in _OUTPUTS:
            problems.append(
                f"formula '{formula_id}' unknown output '{record['output']}'"
            )

        if record["status"] not in _STATUSES:
            problems.append(
                f"formula '{formula_id}' unknown status '{record['status']}'"
            )

        for dep in record["dependencies"]:
            if dep not in id_map:
                problems.append(
                    f"formula '{formula_id}' depends on unknown '{dep}'"
                )

    # Cycle detection over the whole registry.
    try:
        lineage = FormulaLineage(records)
    except ValueError as exc:
        problems.append(f"lineage construction failed: {exc}")
        return problems

    for cycle in lineage.detect_cycles():
        problems.append(f"dependency cycle detected: {' -> '.join(cycle)}")

    return problems


def _name_index(records: list[dict[str, Any]]) -> dict[str, str]:
    """Build a registry-wide normalised name → formula_id index.

    Both ids and human-readable names are indexed so expressions can
    reference a formula by either its id (``net_revenue``) or its
    CamelCase display name (``NetRevenue``).

    Args:
        records: List of registry-v1 formula records.

    Returns:
        Mapping of normalised name → formula_id.
    """
    index: dict[str, str] = {}
    for record in records:
        formula_id = str(record.get("id"))
        index[_normalise(formula_id)] = formula_id
        index[_normalise(str(record.get("name", "")))] = formula_id
    return index


def validate_expression(
    record: dict[str, Any],
    name_index: Mapping[str, str] | None = None,
) -> list[str]:
    """Validate a single record's expression.

    Args:
        record: A registry-v1 formula record.
        name_index: Optional registry-wide name index; when provided,
            names are resolved against the whole registry in addition to
            the record's declared inputs.

    Returns:
        List of problem strings; empty when the expression is valid.
    """
    formula_id = str(record.get("id"))
    problems: list[str] = []

    compiled = compile_formula(record, name_index)
    if not compiled.supported:
        # Source formulas (no dependencies) legitimately carry
        # descriptive expressions — they are computed from raw source
        # data, not from other formulas.
        if not record.get("dependencies"):
            return problems
        problems.append(
            f"formula '{formula_id}' expression is not evaluable: "
            f"{compiled.unsupported_reason}"
        )
        return problems

    # Every declared input must be referenced. Source fields are exempt —
    # they are raw inputs a caller supplies at evaluation time.
    declared = set(str(i) for i in record.get("inputs", []))
    referenced = set(compiled._name_map.values())  # noqa: SLF001 - compiler contract

    unreferenced = declared - referenced
    if unreferenced:
        problems.append(
            f"formula '{formula_id}' declares unused inputs: "
            f"{', '.join(sorted(unreferenced))}"
        )

    return problems


def validate_all(
    records: list[dict[str, Any]],
    name_index: Mapping[str, str] | None = None,
) -> list[str]:
    """Run both structural and expression validation.

    Args:
        records: List of registry-v1 formula records.
        name_index: Optional registry-wide name index forwarded to
            :func:`validate_expression`.

    Returns:
        Combined list of problem strings; empty when fully valid.
    """
    problems = validate_registry(records)
    index = name_index if name_index is not None else _name_index(records)
    for record in records:
        problems.extend(validate_expression(record, index))
    return problems
