"""Finance-domain example datasets (invoices, trial balances, variances, etc.).

All CSV files in this package are parsed into ExampleSet objects at import
time via the :func:`load_all` helper. The :data:`FINANCE_EXAMPLE_SETS` list
contains every registered set for use in tests and documentation.
"""

from business.examples.finance.examples import FINANCE_EXAMPLE_SETS, load_all

__all__ = [
    "FINANCE_EXAMPLE_SETS",
    "load_all",
]
