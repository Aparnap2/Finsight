---
type: Module
title: finance.reconciliation.exception_lifecycle
description: 'Reconciliation exception lifecycle: state machine and transition validation.'
resource: /finance/reconciliation/exception_lifecycle.py
tags: [reconciliation, module]
generated: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
verified: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
status: stable
sources:
- {id: src, resource: /finance/reconciliation/exception_lifecycle.py, title: exception_lifecycle.py}
source_fingerprint: d960f8ca35f881e44c14c1512d3266bbb806ae065f46c5eb8c7ab92439c72d52
---

# Exception Lifecycle

## Public functions

- `allowed_targets()`
- `is_terminal()`
- `validate_transition()`

## In-scope dependencies

- [finance.reconciliation.models](/code/modules/finance-reconciliation-models.md)

## Provenance

Source fingerprint (SHA-256): `d960f8ca35f881e44c14c1512d3266bbb806ae065f46c5eb8c7ab92439c72d52`

> Structural relationships above are derived from static AST analysis. Runtime behaviour (dependency injection, dynamic dispatch) is not captured; see `/coverage.md`.

