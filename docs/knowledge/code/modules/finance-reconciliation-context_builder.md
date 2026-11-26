---
type: Module
title: finance.reconciliation.context_builder
description: Deterministic context builder for CP1-C.
resource: /finance/reconciliation/context_builder.py
tags: [reconciliation, module]
generated: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
verified: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
status: stable
sources:
- {id: src, resource: /finance/reconciliation/context_builder.py, title: context_builder.py}
source_fingerprint: 31679d446e46b3ff3629ea06251ddc018b0e12e469196e6c9b1dee53162bb109
---

# Context Builder

## Classes

- `ContextNotFoundError`
- `CurrencyRequiredError`

## Public functions

- `build_exception_context()`

## In-scope dependencies

- [finance.reconciliation.context](/code/modules/finance-reconciliation-context.md)
- [shared.models.reconciliation](/code/modules/shared-models-reconciliation.md)

## Provenance

Source fingerprint (SHA-256): `31679d446e46b3ff3629ea06251ddc018b0e12e469196e6c9b1dee53162bb109`

> Structural relationships above are derived from static AST analysis. Runtime behaviour (dependency injection, dynamic dispatch) is not captured; see `/coverage.md`.

