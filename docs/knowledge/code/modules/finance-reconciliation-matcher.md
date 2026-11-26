---
type: Module
title: finance.reconciliation.matcher
description: Deterministic matching primitives for reconciling leg pairs.
resource: /finance/reconciliation/matcher.py
tags: [reconciliation, module]
generated: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
verified: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
status: stable
sources:
- {id: src, resource: /finance/reconciliation/matcher.py, title: matcher.py}
source_fingerprint: e39b79c98ba9a81c205bb267d02f988b8002a65d7ebd9da8062c937a7d0d7ddc
---

# Matcher

## Public functions

- `ensure_unique()`
- `exact_match()`
- `find_duplicates()`
- `find_match()`
- `within_tolerance()`

## In-scope dependencies

- [finance.reconciliation.errors](/code/modules/finance-reconciliation-errors.md)
- [finance.reconciliation.models](/code/modules/finance-reconciliation-models.md)
- [finance.reconciliation.tolerances](/code/modules/finance-reconciliation-tolerances.md)

## Provenance

Source fingerprint (SHA-256): `e39b79c98ba9a81c205bb267d02f988b8002a65d7ebd9da8062c937a7d0d7ddc`

> Structural relationships above are derived from static AST analysis. Runtime behaviour (dependency injection, dynamic dispatch) is not captured; see `/coverage.md`.

