"""Versioned data contracts for the FinSight platform.

Contracts are the authoritative shape definitions that registries and
pipelines reference instead of inlining field definitions. Each
subpackage holds one or more versioned contracts, e.g.
``contracts.formulas.registry_v1``.

Contracts are intentionally *pure*: they only validate shape and
versioning. Business meaning lives in ``business/``; contracts live
outside it so the compute runtime, connectors, and analytics can all
depend on the same wire formats without importing the domain layer.
"""
