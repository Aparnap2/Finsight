# Code

## Modules

* [Reconciliation schema migrations](/code/modules/alembic-reconciliation-migrations.md) - Alembic revisions creating the reconciliation tables and RLS policies.
* [apps.api.reconciliation_routes](/code/modules/apps-api-reconciliation_routes.md) - FastAPI routes for the reconciliation workflow (contract §2).
* [finance.reconciliation.allocation](/code/modules/finance-reconciliation-allocation.md) - Deterministic allocation of one bank deposit to payment charges.
* [finance.reconciliation.bank](/code/modules/finance-reconciliation-bank.md) - Tenant-declared bank statement normalization into deposit records.
* [finance.reconciliation.classifier](/code/modules/finance-reconciliation-classifier.md) - Break classification into the 3 versioned P0 exception types.
* [finance.reconciliation.errors](/code/modules/finance-reconciliation-errors.md) - Error taxonomy for the P1 pure reconciliation core.
* [finance.reconciliation.exception_lifecycle](/code/modules/finance-reconciliation-exception_lifecycle.md) - Reconciliation exception lifecycle: state machine and transition validation.
* [finance.reconciliation.fingerprints](/code/modules/finance-reconciliation-fingerprints.md) - Stable sha256 fingerprints over canonical payment representations.
* [finance.reconciliation.investigation](/code/modules/finance-reconciliation-investigation.md) - Bounded AI investigation of reconciliation exceptions.
* [finance.reconciliation.ledger_resolution](/code/modules/finance-reconciliation-ledger_resolution.md) - Commit 3B: deterministic ledger lookup -> frozen P1 reconcile -> verdict, STOP.
* [finance.reconciliation.matcher](/code/modules/finance-reconciliation-matcher.md) - Deterministic matching primitives for reconciling leg pairs.
* [finance.reconciliation.models](/code/modules/finance-reconciliation-models.md) - Canonical payment and reconciliation-result contracts.
* [finance.reconciliation.normalizer](/code/modules/finance-reconciliation-normalizer.md) - Provider-agnostic normalization of raw payment payloads.
* [finance.reconciliation.operator_report](/code/modules/finance-reconciliation-operator_report.md) - Operator-facing evidence for the three-source statement reconciliation.
* [finance.reconciliation.persistence](/code/modules/finance-reconciliation-persistence.md) - Thin persistence functions for the reconciliation domain.
* [finance.reconciliation.reconciler](/code/modules/finance-reconciliation-reconciler.md) - Pure deterministic reconciliation entry point.
* [finance.reconciliation.statement_workflow](/code/modules/finance-reconciliation-statement_workflow.md) - Three-source statement reconciliation: invoice register, processor, bank.
* [finance.reconciliation.tolerances](/code/modules/finance-reconciliation-tolerances.md) - Tenant-injected reconciliation tolerances.
* [Reconciliation Workflow](/code/modules/reconciliation-workflow.md) - Three-source reconciliation execution path: ingest, validate, reconcile, persist, decide, audit.
* [shared.models.reconciliation](/code/modules/shared-models-reconciliation.md) - SQLAlchemy ORM models for the 12 reconciliation tables.
* [Tenant Isolation Boundary](/code/modules/tenant-isolation.md) - Row-level security and transaction-local tenant GUC wiring for reconciliation tables.
