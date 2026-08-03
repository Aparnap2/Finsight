"""Formula Registry — authoritative catalog of every derived financial metric.

This package is part of the Business Knowledge Layer (Layer 0) and defines
the metadata models, dependency graph, and populated registry for all FP&A
formulas in the FinSight platform.

Two representations coexist:

* The runtime registry (``models.py`` + ``registry.py``) — in-memory
  :class:`FormulaRegistry` with 72 formulas used by the application.
* The elevated file registry (``registry.yaml`` + ``loader.py`` +
  ``compiler.py`` + ``lineage.py`` + ``validator.py``) — the persisted,
  versioned catalog used by tooling, data contracts, and audit.

Usage::

    from business.formula_registry import REGISTRY, FormulaCategory
    from business.formula_registry.loader import load_records
    from business.formula_registry.compiler import compile_formula
    from business.formula_registry.validator import validate_all

    # Look up a formula
    net_revenue = REGISTRY.lookup("net_revenue")

    # List all formulas in a category
    liquidity = REGISTRY.list_by_category(FormulaCategory.LIQUIDITY)

    # Check for circular dependencies
    cycles = REGISTRY.graph.detect_cycles()

    # Resolve evaluation order
    order = REGISTRY.resolve_dependencies("ebitda")

    # Elevated registry: compile and validate the persisted catalog
    records = load_records()
    problems = validate_all(records)
"""

from business.formula_registry.compiler import (
    CompiledFormula,
    FormulaCompilationError,
    FormulaEvaluationError,
    compile_formula,
)
from business.formula_registry.lineage import FormulaLineage
from business.formula_registry.loader import RegistryFileError, load_records, record_by_id
from business.formula_registry.models import (
    DataType,
    FormulaCategory,
    FormulaDefinition,
    FormulaDependencyGraph,
    FormulaRegistry,
    SourceType,
)
from business.formula_registry.registry import REGISTRY, build_registry
from business.formula_registry.validator import validate_all, validate_expression, validate_registry

__all__ = [
    "CompiledFormula",
    "DataType",
    "FormulaCategory",
    "FormulaCompilationError",
    "FormulaDefinition",
    "FormulaDependencyGraph",
    "FormulaEvaluationError",
    "FormulaLineage",
    "FormulaRegistry",
    "REGISTRY",
    "RegistryFileError",
    "SourceType",
    "build_registry",
    "compile_formula",
    "load_records",
    "record_by_id",
    "validate_all",
    "validate_expression",
    "validate_registry",
]
