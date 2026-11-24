---
type: Module
title: finance.reconciliation.statement_workflow
description: 'Three-source statement reconciliation: invoice register, processor,
  bank.'
resource: /finance/reconciliation/statement_workflow.py
tags: [reconciliation, module]
generated: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
verified: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
status: stable
sources:
- {id: src, resource: /finance/reconciliation/statement_workflow.py, title: statement_workflow.py}
source_fingerprint: a0df92af4a4a95bf50e70e338dac1a1d8e5a5e1f7543df762dfb66dd8c32d761
---

# Statement Workflow

## Classes

- `DepositEvidence`
- `DepositResult`
- `DerivedComparison`
- `InvoiceChargeLink`
- `ReconciliationReport`
- `StatementSources`

## Public functions

- `difference()`
- `main()`
- `run_statement_reconciliation()`
- `sources_from_export()`
- `to_dict()`

## In-scope dependencies

- [finance.reconciliation.allocation](/code/modules/finance-reconciliation-allocation.md)
- [finance.reconciliation.bank](/code/modules/finance-reconciliation-bank.md)
- [finance.reconciliation.errors](/code/modules/finance-reconciliation-errors.md)
- [finance.reconciliation.models](/code/modules/finance-reconciliation-models.md)
- [finance.reconciliation.reconciler](/code/modules/finance-reconciliation-reconciler.md)
- [finance.reconciliation.tolerances](/code/modules/finance-reconciliation-tolerances.md)

## Provenance

Source fingerprint (SHA-256): `a0df92af4a4a95bf50e70e338dac1a1d8e5a5e1f7543df762dfb66dd8c32d761`

> Structural relationships above are derived from static AST analysis. Runtime behaviour (dependency injection, dynamic dispatch) is not captured; see `/coverage.md`.

