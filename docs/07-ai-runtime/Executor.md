# Executor

## Purpose

The executor takes the planner's `ActionPlan` and runs each action against deterministic financial engines. Every calculation is auditable, reproducible, and uses `Decimal` arithmetic.

## Engine Routing

Each action is routed to the appropriate engine based on its `tool` field:

| Tool | Engine | Responsibility |
|------|--------|---------------|
| `variance_engine` | VarianceEngine | Budget vs actual variance computation |
| `kpi_engine` | KPIEngine | KPI evaluation (ratios, growth rates, margins) |
| `evidence_engine` | EvidenceEngine | Evidence gathering and scoring |
| `validation_suite` | ValidationSuite | Policy compliance, materiality, assertion validation |

## Per-Action Lifecycle

```
  PENDING
    │
    ├──▶ routing to engine
    │       │
    │       ├── SUCCESS (output produced, evidence collected)
    │       │
    │       ├── FAILED (engine error, max retries exceeded)
    │       │
    │       └── SKIPPED (dependency failure)
    │
    ▼
  TERMINAL
```

Each action tracks:
- **status**: PENDING → SUCCESS / FAILED / SKIPPED
- **retry_count**: incremented on each retry (max 3)
- **latency_ms**: wall-clock execution time
- **evidence_ids**: evidence items produced by the action
- **outputs**: engine results stored in the action

## Dependency Ordering

Actions within a plan are executed in order. If an action depends on outputs from a prior action, the executor waits for that dependency before proceeding. Failed actions do not block subsequent actions unless specified as hard dependencies.

## Determinism Guarantee

All engines use `Decimal` arithmetic. No floating-point operations touch monetary values. Every calculation is bitwise reproducible across runs.
