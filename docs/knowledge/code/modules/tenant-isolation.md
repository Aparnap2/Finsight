---
type: Architecture
title: Tenant Isolation Boundary
description: Row-level security and transaction-local tenant GUC wiring for reconciliation
  tables.
tags: [reconciliation, architecture]
generated: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
verified: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
status: stable
sources:
- {id: src, resource: /finance/reconciliation, title: reconciliation runtime}
source_fingerprint: 0780b94772bf18d5f0964d1354ead6e590ea303749b502f0699640a3c34d19cd
---

# Tenant Isolation Boundary

Row-level security and transaction-local tenant GUC wiring for reconciliation tables.

## Related concepts

- [finance.reconciliation.persistence](/code/modules/finance-reconciliation-persistence.md)
- [apps.api.reconciliation_routes](/code/modules/apps-api-reconciliation_routes.md)
- [shared.models.reconciliation](/code/modules/shared-models-reconciliation.md)

## Provenance

Source fingerprint (SHA-256): `0780b94772bf18d5f0964d1354ead6e590ea303749b502f0699640a3c34d19cd`

> Architecture concept derived from source structure and existing specs. Runtime behaviour is not inferred from imports alone.

