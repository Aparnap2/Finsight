"""Example data library for the Enterprise Semantic Layer.

Provides standardized example datasets, edge cases, and fixture loading
for testing FP&A domain logic across all business subpackages.
"""

from business.examples.classification import ExampleCatalog, ExampleClassification
from business.examples.edge_cases import EDGE_CASE_SETS, get_edge_case_examples
from business.examples.finance.examples import FINANCE_EXAMPLE_SETS
from business.examples.malicious_cases import MALICIOUS_SETS, get_malicious_examples
from business.examples.models import ExampleLibrary, ExampleSet

#: Catalog classifying all example sets into the good / bad / edge /
#: malicious categories used by docs, tests, demos, and evaluations.
EXAMPLE_CATALOG: ExampleCatalog = ExampleCatalog(
    [*FINANCE_EXAMPLE_SETS, *EDGE_CASE_SETS, *MALICIOUS_SETS]
)

__all__ = [
    "EDGE_CASE_SETS",
    "EXAMPLE_CATALOG",
    "ExampleCatalog",
    "ExampleClassification",
    "ExampleLibrary",
    "ExampleSet",
    "FINANCE_EXAMPLE_SETS",
    "MALICIOUS_SETS",
    "get_edge_case_examples",
    "get_malicious_examples",
]
