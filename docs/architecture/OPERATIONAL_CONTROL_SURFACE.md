# Operational Control Surface — bounded roadmap (DEFERRED)

**Status:** deferred backlog. **Not part of the current release remediation.**

This document records the intended shape of FinSight's operational control
surface so that the boundaries are explicit before any of it is built. It is a
design record and a TODO list, not an approved implementation plan. Nothing here
authorizes new frameworks, services, queues, or an enterprise IAM platform.

## Why this exists

FinSight needs operability and **controlled** configurability: enough for a
developer/SRE to diagnose the runtime, a platform administrator to manage
tenants and imports, a finance operator to run the reconciliation workflow, and
an auditor to inspect history — without collapsing those into one super-admin
role.

It must remain deliberately bounded:

- Not a generic admin panel.
- Not an enterprise IAM/configuration platform.
- No GUI for editing arbitrary environment variables, SQL, or infrastructure.
- No configuration path that lets an administrator or an LLM override
  deterministic reconciliation, policy, authorization, or financial outcomes.

## Actors and trust boundaries

| Actor | Concern | Boundary |
|---|---|---|
| Developer / DevOps / SRE | Inspect, diagnose, configure, operate at infrastructure/runtime level | Infrastructure + diagnosis; **no** business authorization to change financial decisions |
| Platform administrator | Manage tenants, users, imports, policies, operational configuration | Administrative data; **must not** silently bypass tenant isolation |
| Business operator (finance) | Import, reconcile, investigate, record decisions, export evidence | Own tenant's workflow |
| Auditor | Inspect historical activity, provenance and exports | Read-only |

Two invariants:

1. SRE access to infrastructure does **not** grant authority to change
   reconciliation decisions.
2. Platform-admin access does **not** grant unrestricted database or
   infrastructure access.

Cross-tenant access must be explicit, authorized, scoped, and audited.

## Control surface levels

| Level | Surface | Audience | Build posture |
|---|---|---|---|
| 1 | Code / infrastructure: env + deployment config, Compose/Postgres/migrations/backups, logs/metrics/traces/health, DB inspection, feature flags, CLI | Developer, SRE | Mostly exists; keep it CLI/docs-first |
| 2 | Platform administration: tenant list/status/config, users & roles, import/session inspection, run inspection, failure visibility, audit search | Platform admin, support | Add selectively, after real auth |
| 3 | Business administration: matching tolerances, source mappings, reconciliation policies, exception review/assignment, export permissions | Finance admin / reconciliation manager | Add selectively, versioned |
| 4 | Business operation: import, reconcile, review matches/allocations, investigate, decide, export | Finance operator, auditor | Core workflow — already the priority |

## What should be configurable

| Category | GUI-configurable | Code / infra |
|---|---|---|
| Runtime and infrastructure | Limited, read-only diagnostics | Yes |
| Tenant and user administration | Yes | Yes, via controlled bootstrap/CLI |
| Reconciliation policies | Yes, within validated limits | Yes |
| Source formats and field mappings | Yes, within supported adapters | Yes, for new adapters |
| AI investigation behavior | Limited policy settings | Yes: provider/model/prompt/safety |

### A. Runtime and infrastructure — inspect, not freely modify

Show: app version / Git SHA / environment; DB connectivity and migration
status; API and GUI health; storage connectivity; LLM provider availability;
recent errors and operational events; queue/worker status **only if such
infrastructure is actually introduced**.

Actual infrastructure changes stay in env config, Compose, deploy scripts,
migrations, and CLI maintenance scripts.

### B. Tenant administration

List/inspect tenants, activate/deactivate, view/configure supported
tenant-specific settings, inspect tenant imports/runs/failures, manage tenant
users and roles (once real authentication exists).

### C. Reconciliation configuration

Validated configuration objects only — never arbitrary Python or SQL. Examples:
currency; amount tolerance; date tolerance; fee handling; partial payment;
duplicate handling; ambiguous-match policy; refund treatment.

Every change carries: validation, tenant scope, version/revision, effective
timestamp, actor identity, audit event, and a defined effect on future vs.
existing runs.

**Do not silently recalculate historical runs** when a policy changes.
Historical results retain the policy version under which they were produced.

### D. Source configuration

Configurable: CSV column mappings, date/number formats, currency conventions,
required/optional fields, source-specific normalization. Adding a CSV mapping is
a GUI capability; implementing a new bank API adapter is developer work.

### E. AI configuration

GUI may toggle AI investigation, select from approved providers/models, set
investigation depth/output limits, allowed evidence categories, and
confidence/escalation thresholds **where they have defined operational
semantics**.

Code owns tool permissions, system prompts/templates, evidence-access
boundaries, output schemas, validation, provider integration, and safety
constraints. An admin must never configure the LLM to bypass deterministic
reconciliation or auto-resolve financial exceptions.

## Permission matrix (conceptual)

Not a directive to implement every role now.

| Capability | Platform admin | Tenant admin | Finance operator | Auditor | SRE |
|---|---|---|---|---|---|
| View system health | Yes | No | No | No | Yes |
| View all tenants | Yes | No | No | No | Limited |
| Manage tenant settings | Yes | Own tenant | No | No | No |
| Manage users | Yes | Own tenant | No | No | No |
| Import source files | No | Yes | Yes | No | No |
| Run reconciliation | No | Yes | Yes | No | No |
| Configure matching policy | Yes | Own tenant | No | No | No |
| Resolve exceptions | No | Yes | Yes | No | No |
| View audit history | Yes, scoped | Own tenant | Own tenant | Own tenant | Operational |
| Modify infrastructure | No | No | No | No | Yes |

Current limitation: header-based tenant identity is **not** sufficient for these
roles. Real authentication/authorization is a prerequisite for Level 2+.

## GUI surfaces (after the core workflow works)

An `Administration` section, shown only once the reconciliation workflow is
functional:

- **Overview** — system status, recent failures, operational summary.
- **Tenants** — list, status, configuration.
- **Users & Roles** — access and permissions.
- **Imports** — history, validation failures, source configuration.
- **Reconciliation** — run history, policy versions, failed runs.
- **Policies** — matching tolerances and exception rules.
- **AI Settings** — provider status and bounded investigation configuration.
- **Audit Log** — who changed what, when, within which tenant.
- **Diagnostics** — health, migration state, version, integration status.

The SRE/DevOps interface stays separate from the finance-facing admin interface.
It can remain a CLI plus deployment documentation initially.

## Three configuration boundaries

- **Code-defined** — what the system is *capable* of: adapters, algorithms,
  schemas, authorization rules, safety constraints, infrastructure topology.
- **Platform-defined** — how it is *deployed and operated*: environment,
  providers, storage, database, feature availability, operational limits.
- **Tenant/admin-defined** — how a tenant *uses supported capabilities*:
  mappings, matching policies, tolerances, users, workflow preferences.

**Invariant:** a lower-trust configuration layer must never override the safety
constraints of a higher-trust layer.

## Staging (recommended order)

| Stage | Scope | Priority |
|---|---|---|
| 0 | Fix release blockers; make the core workflow functional | **Now (current remediation)** |
| 1 | Operational visibility: health, versions, migration state, errors, audit search | High |
| 2 | Tenant admin: tenant settings, source mappings, user/role management | After real auth |
| 3 | Reconciliation policy management with versioning | High |
| 4 | AI and provider configuration | Moderate |
| 5 | Advanced SRE operations GUI | Low; CLI is sufficient initially |

## TODO checklist

Cross-cutting specs to author before building (docs only, no code yet):

- [ ] `ADMINISTRATION_CONTRACT.md` — admin capabilities, roles, permissions, boundaries.
- [ ] `CONFIGURATION_CONTRACT.md` — configuration hierarchy, validation, defaults, versioning, effective dates.
- [ ] `OPERATIONS_RUNBOOK.md` — developer/SRE CLI, deployment, migration, backup, recovery, diagnostics.
- [ ] Extend `OBSERVABILITY_CONTRACT.md` — operational visibility, health checks, structured logs, audit requirements.

Stage 1 (operational visibility, no new auth model required):

- [ ] Expose app version / Git SHA / environment on a diagnostics surface.
- [ ] Expose DB connectivity + alembic migration head.
- [ ] Expose storage and LLM provider availability.
- [ ] Read-only operational error feed.
- [ ] Tenant-scoped audit event search.

Stage 2+ (requires real authentication/authorization first):

- [ ] Tenant listing/status/config with explicit, audited cross-tenant access.
- [ ] User and role administration (replacing header identity).
- [ ] Import/session and run inspection for support.
- [ ] Versioned reconciliation policy configuration (never silently recompute history).
- [ ] CSV field-mapping configuration within supported adapters.
- [ ] Bounded AI investigation settings that cannot bypass deterministic finance.

## Open decision (blocking Stage 2)

**Single-operator portfolio demo vs. multi-tenant platform where a platform
administrator manages independent customer organizations?**

Recommendation: **design the boundaries for multi-tenancy, implement only the
minimum single-operator administration needed for a credible portfolio
release.**
