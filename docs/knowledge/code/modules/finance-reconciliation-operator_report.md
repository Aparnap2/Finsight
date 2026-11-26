---
type: Module
title: finance.reconciliation.operator_report
description: Operator-facing evidence for the three-source statement reconciliation.
resource: /finance/reconciliation/operator_report.py
tags: [reconciliation, module]
generated: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
verified: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
status: stable
sources:
- {id: src, resource: /finance/reconciliation/operator_report.py, title: operator_report.py}
source_fingerprint: 380a6e7bc30563afd8cee1f91e5d83d69d3c655c461611a224bacbc52f5f8b34
---

# Operator Report

## Classes

- `CheckResult`
- `OperatorInputError`
- `OperatorRun`

## Public functions

- `build_operator_run()`
- `compare()`
- `failures()`
- `main()`
- `passed()`
- `walk()`

## In-scope dependencies

- [finance.reconciliation.errors](/code/modules/finance-reconciliation-errors.md)
- [finance.reconciliation.models](/code/modules/finance-reconciliation-models.md)
- [finance.reconciliation.statement_workflow](/code/modules/finance-reconciliation-statement_workflow.md)
- [finance.reconciliation.tolerances](/code/modules/finance-reconciliation-tolerances.md)

## Provenance

Source fingerprint (SHA-256): `380a6e7bc30563afd8cee1f91e5d83d69d3c655c461611a224bacbc52f5f8b34`

> Structural relationships above are derived from static AST analysis. Runtime behaviour (dependency injection, dynamic dispatch) is not captured; see `/coverage.md`.

