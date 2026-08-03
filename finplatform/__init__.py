"""FinSight Layer-0 platform package.

Shared multi-tenant SaaS infrastructure for the Finance Operations Platform.
Lives at repo root as ``finplatform/`` (NOT ``platform/`` — see
docs/adr/0001-platform-package-name-and-orphaned-tests.md for why the stdlib
shadowing name is avoided).

Sub-packages:
- identity:      Organization -> Tenant -> User -> Role models (authorization focus)
- rbac:          role -> permission -> action matrix
- abac:          simple PolicyEngine.evaluate(policy, context) -> (bool, reason)
- config:        tenant.yaml schema, feature flags, config loading
- policies:      policy engine wiring/evaluation
- registries:    Metadata Registry (formula, policy, connector, dataset, schema,
                 feature, capability)
- connectors:    connector protocol + registry (CSV, Sheets, ERPNext, QuickBooks, ...)
- dispatcher:    job dispatcher (permissions, queue, retry, timeout)
- audit:         who/tenant/role/policy/tool/evidence/decision/version
- observability: metrics, logs, tenant-scoped traces

This is Layer 0: it imports nothing internal. No re-exports.
"""
