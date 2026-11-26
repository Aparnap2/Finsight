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
source_fingerprint: 6144d7e76e85dc18b85b5f7156f08f09e48777b583b10eef5daa48fea48795ab
---

# Tenant Isolation Boundary

Row-level security and transaction-local tenant GUC wiring for reconciliation tables.

## Related concepts

- [finance.reconciliation.persistence](/code/modules/finance-reconciliation-persistence.md)
- [apps.api.reconciliation_routes](/code/modules/apps-api-reconciliation_routes.md)
- [shared.models.reconciliation](/code/modules/shared-models-reconciliation.md)

## Provenance

Source fingerprint (SHA-256): `6144d7e76e85dc18b85b5f7156f08f09e48777b583b10eef5daa48fea48795ab`

> Architecture concept derived from source structure and existing specs. Runtime behaviour is not inferred from imports alone.

