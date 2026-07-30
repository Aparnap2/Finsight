"""Example data library for the Enterprise Semantic Layer.

Provides standardized example datasets, edge cases, and fixture loading
for testing FP&A domain logic across all business subpackages.
"""

from business.examples.edge_cases import EDGE_CASE_SETS, get_edge_case_examples
from business.examples.finance.examples import FINANCE_EXAMPLE_SETS
from business.examples.models import ExampleLibrary, ExampleSet

__all__ = [
    "EDGE_CASE_SETS",
    "ExampleLibrary",
    "ExampleSet",
    "FINANCE_EXAMPLE_SETS",
    "get_edge_case_examples",
]
