"""Formula Registry — authoritative catalog of every derived financial metric.

This package is part of the Business Knowledge Layer (Layer 0) and defines
the metadata models, dependency graph, and populated registry for all FP&A
formulas in the FinSight platform.

Usage::

    from business.formula_registry import REGISTRY, FormulaCategory

    # Look up a formula
    net_revenue = REGISTRY.lookup("net_revenue")

    # List all formulas in a category
    liquidity = REGISTRY.list_by_category(FormulaCategory.LIQUIDITY)

    # Check for circular dependencies
    cycles = REGISTRY.graph.detect_cycles()

    # Resolve evaluation order
    order = REGISTRY.resolve_dependencies("ebitda")
"""

from business.formula_registry.models import (
    DataType,
    FormulaCategory,
    FormulaDefinition,
    FormulaDependencyGraph,
    FormulaRegistry,
    SourceType,
)
from business.formula_registry.registry import REGISTRY, build_registry

__all__ = [
    "DataType",
    "FormulaCategory",
    "FormulaDefinition",
    "FormulaDependencyGraph",
    "FormulaRegistry",
    "REGISTRY",
    "SourceType",
    "build_registry",
]
