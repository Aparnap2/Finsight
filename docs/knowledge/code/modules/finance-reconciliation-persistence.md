---
type: Module
title: finance.reconciliation.persistence
description: Thin persistence functions for the reconciliation domain.
resource: /finance/reconciliation/persistence.py
tags: [reconciliation, module]
generated: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
verified: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
status: stable
sources:
- {id: src, resource: /finance/reconciliation/persistence.py, title: persistence.py}
source_fingerprint: 41f80e339ac6817da5ebd63fa29172b2b98123201caf136578e31f606569af73
---

# Persistence

## Classes

- `IdempotencyConflictError`

## Public functions

- `create_import_session()`
- `get_audit_events()`
- `get_import_session()`
- `get_run()`
- `get_run_exceptions()`
- `list_exceptions()`
- `persist_ingestion_report()`
- `record_audit_event()`
- `record_decision()`
- `start_reconciliation()`
- `upload_source_file()`

## In-scope dependencies

- [finance.reconciliation.exception_lifecycle](/code/modules/finance-reconciliation-exception_lifecycle.md)
- [finance.reconciliation.statement_workflow](/code/modules/finance-reconciliation-statement_workflow.md)
- [shared.models.reconciliation](/code/modules/shared-models-reconciliation.md)

## Provenance

Source fingerprint (SHA-256): `41f80e339ac6817da5ebd63fa29172b2b98123201caf136578e31f606569af73`

> Structural relationships above are derived from static AST analysis. Runtime behaviour (dependency injection, dynamic dispatch) is not captured; see `/coverage.md`.

