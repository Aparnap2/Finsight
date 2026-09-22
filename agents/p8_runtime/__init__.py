"""P8-01 provider-neutral model runtime boundary.

Observational seam only: carries untrusted model text to explicit
validation under finite budgets. Mints no financial facts, evidence,
capabilities, tenant scope, or execution authority (P6/P7 own those).
"""

from agents.p8_runtime import contract

__all__ = ["contract"]
