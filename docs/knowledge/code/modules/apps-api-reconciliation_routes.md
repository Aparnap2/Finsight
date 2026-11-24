---
type: API Module
title: apps.api.reconciliation_routes
description: FastAPI routes for the reconciliation workflow (contract §2).
resource: /apps/api/reconciliation_routes.py
tags: [reconciliation, api]
generated: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
verified: {by: 'process:knowledge-graph', at: '2026-01-01T00:00:00Z'}
status: stable
sources:
- {id: src, resource: /apps/api/reconciliation_routes.py, title: reconciliation_routes.py}
source_fingerprint: 129ab75e455706d65dc6af619499c4094279fb1f1a386ec55ae57404f537c88e
---

# Reconciliation API routes

## Endpoints

- `GET /exceptions/{exception_id}`
- `GET /exports/{export_id}`
- `GET /import-sessions/{session_id}`
- `GET /reconciliation/runs/{run_id}`
- `GET /reconciliation/runs/{run_id}/audit`
- `GET /runs/{run_id}/allocations`
- `GET /runs/{run_id}/exceptions`
- `GET /runs/{run_id}/matches`
- `POST /exceptions/{exception_id}/decisions`
- `POST /reconciliation/exceptions/{exception_id}/investigate`
- `POST /reconciliation/sessions`
- `POST /reconciliation/sessions/{session_id}/reconcile`
- `POST /reconciliation/sessions/{session_id}/validate`
- `POST /runs/{run_id}/exports`

## In-scope dependencies

- [finance.reconciliation.persistence](/code/modules/finance-reconciliation-persistence.md)
- [shared.models.reconciliation](/code/modules/shared-models-reconciliation.md)

## Provenance

Source fingerprint (SHA-256): `129ab75e455706d65dc6af619499c4094279fb1f1a386ec55ae57404f537c88e`

> Route list derived from static decorator scanning.

