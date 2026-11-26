---
type: Module
title: finance.reconciliation.ledger_resolution
description: 'Commit 3B: deterministic ledger lookup -> frozen P1 reconcile -> verdict,
  STOP.'
resource: /finance/reconciliation/ledger_resolution.py
tags: [reconciliation, module]
generated: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
verified: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
status: stable
sources:
- {id: src, resource: /finance/reconciliation/ledger_resolution.py, title: ledger_resolution.py}
source_fingerprint: da042249be5e7dd0fcda4bc97166684ebe1cf18eaaa968e4ba71ab0ad1de68f5
---

# Ledger Resolution

## Classes

- `InMemoryLedgerRepository`
- `LedgerKey`
- `LedgerRepository`
- `LedgerResolution`
- `ResolutionStatus`

## Public functions

- `from_records()`
- `get()`
- `project_canonical_processor()`
- `resolve_payment()`
- `stub_processor_from_stripe_records()`

## In-scope dependencies

- [finance.reconciliation.errors](/code/modules/finance-reconciliation-errors.md)
- [finance.reconciliation.models](/code/modules/finance-reconciliation-models.md)
- [finance.reconciliation.reconciler](/code/modules/finance-reconciliation-reconciler.md)
- [finance.reconciliation.tolerances](/code/modules/finance-reconciliation-tolerances.md)

## Provenance

Source fingerprint (SHA-256): `da042249be5e7dd0fcda4bc97166684ebe1cf18eaaa968e4ba71ab0ad1de68f5`

> Structural relationships above are derived from static AST analysis. Runtime behaviour (dependency injection, dynamic dispatch) is not captured; see `/coverage.md`.

