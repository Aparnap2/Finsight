---
type: Module
title: finance.reconciliation.allocation
description: Deterministic allocation of one bank deposit to payment charges.
resource: /finance/reconciliation/allocation.py
tags: [reconciliation, module]
generated: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
verified: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
status: stable
sources:
- {id: src, resource: /finance/reconciliation/allocation.py, title: allocation.py}
source_fingerprint: f6563e48b1dc4a4e1dad26a8d951acd208882b872ae1d1bdb3f779c3f2c8c0bc
---

# Allocation

## Classes

- `Allocation`
- `AllocationLeg`
- `CandidateAllocation`
- `PayoutReason`
- `_Search`

## Public functions

- `allocate_deposit()`
- `canonical()`
- `reconcile_payout()`

## In-scope dependencies

- [finance.reconciliation.bank](/code/modules/finance-reconciliation-bank.md)
- [finance.reconciliation.errors](/code/modules/finance-reconciliation-errors.md)
- [finance.reconciliation.fingerprints](/code/modules/finance-reconciliation-fingerprints.md)
- [finance.reconciliation.models](/code/modules/finance-reconciliation-models.md)
- [finance.reconciliation.tolerances](/code/modules/finance-reconciliation-tolerances.md)

## Provenance

Source fingerprint (SHA-256): `f6563e48b1dc4a4e1dad26a8d951acd208882b872ae1d1bdb3f779c3f2c8c0bc`

> Structural relationships above are derived from static AST analysis. Runtime behaviour (dependency injection, dynamic dispatch) is not captured; see `/coverage.md`.

