# Finance Operations Platform — SaaS Implementation Plan (v2)

> **Layer:** Platform Layer (multi-tenant SaaS infrastructure) + Finance Domain Layer
> **Audience:** Staff engineers, architects, reviewers
> **Status:** Draft v3 — incorporates 4 required changes + stack lock + persistence/job model
> **Product:** Finance Operations OS (branding)
> **Platform:** Finance Operations Platform (engineering)

---

## 0. Thesis

FinSight is repositioned from an internal finance tool to a **reusable multi-tenant SaaS platform**, demonstrated through a realistic customer deployment (Acme Corp, Customer A). The repository is the platform; `tenants/demo/acme-corp/` is the demo deployment.

Two systems, one repository:

```
Finance Operations Platform                 Finance Operations OS
├── Identity          (reduced)             ├── Domain Models
├── Tenant                                   ├── Formula Registry  (first-class)
├── RBAC                                     ├── Validation
├── Policy Engine     (simple ABAC)         ├── Analytics
├── Registry Engine                          ├── Recommendations
├── Connector Framework                      ├── Reports
└── Job Dispatcher → Redis (Dramatiq)       └── Agent Runtime
    → Execution Runtime (apps/compute)

Metadata Registry (formula, policy, connector, dataset, schema, feature, capability)
Business Capability Layer (elevated): every service/event/agent/KPI maps to a capability
```

---

## 1. Guiding Principles

1. **Isolation is a security architecture, not a pricing model.** Tenant isolation is enforced at the database layer (RLS), independent of auth. Every row, index, and query carries `tenant_id`.
2. **No customer-specific code.** Every threshold, approval limit, materiality rule, and prompt lives in per-tenant config or a registry. Demo tenants differ only by `tenant.yaml`.
3. **Everything is a registry.** Formula, Policy, Prompt, Validation, Evaluation, Feature. AI becomes configurable.
4. **Connectors are a product.** A connector registry (CSV, Sheets, ERPNext, QuickBooks, SAP, NetSuite) — not single integrations.
5. **The LLM never sees raw data or the database.** It receives verified context (assertions, evidence, policies). Tenant A memory ≠ Tenant B memory.
6. **Audit answers 10 questions.** Who? Tenant? Role? Policy? Tool? Prompt? Evidence? Decision? Timestamp? Version?
7. **Compute is tenant-scoped.** Job Dispatcher owns permissions/queue/retry/timeout; Execution Runtime owns the work; both feed Artifacts. Jobs receive authorized datasets, never raw files.
8. **Reference data ≠ transaction data.** Master data (currencies, countries, COA, tax codes, fiscal calendars) lives in `reference-data/`, never mixed with transaction tables.
9. **Nothing ephemeral.** Job → Task → Artifact → Audit → Report. Every run is reproducible (persist inputs, trace, logs, metrics).
10. **Job-oriented, not interactive.** `POST /jobs` → 202 + `job_id` → client polls `GET /jobs/:id`. No WebSockets in MVP.

---

## 2. Review Feedback — 4 Required Changes

| # | Change | How it's incorporated |
|---|--------|-----------------------|
| 1 | **Reduce identity scope** | MVP = `Organization → Tenant → User → Role`. `Environment` deferred. Auth delegated to Auth0/Clerk (or a minimal signed-token verifier for the demo); focus on **authorization**, not authN. |
| 2 | **Keep ABAC simple** | `PolicyEngine.evaluate(policy, context) -> (bool, reason)`. Typed rules over amount, department, role, tenant, status. No general-purpose authz language; OPA/Cedar can replace later. |
| 3 | **Business Capability layer** | `business/capabilities/` elevated to a first-class layer between tenant/platform and finance domain. Everything (services, events, agents, KPIs) maps to a capability. |
| 4 | **Formula Registry first-class** | `business/formula_registry/` (72 formulas) elevated: versioned formulas, dependencies, owners, references (IAS/GAAP), lineage, evaluation via the registry — never `if EBITDA...` in code. |

---

## 3. Explicit NOT-Build List (portfolio scope)

| Don't build | Reason |
|-------------|--------|
| Billing, subscriptions, Stripe, usage metering, tenant portal | SaaS business features, not Finance AI |
| Email, notifications, Slack, Teams, webhooks | Not needed for the demo |
| Multi-region, HA, Redis cluster, Kubernetes, Helm, Terraform | Way beyond portfolio value |
| Production/Sandbox `Environment` model | One environment per demo tenant suffices |
| Generic policy language / OPA / Cedar | Simple deterministic evaluator is enough |

---

## 4. Final Architecture

Two independent FastAPI services, separate Docker images and lifecycles. Everything server-side is Python — no second backend stack.

```
Next.js 15 (Frontend) ── REST ──► FastAPI Platform API (apps/api)
                                   ├── Multi-tenancy, RBAC/ABAC, REST endpoints
                                   ├── Job creation, artifact access, audit
                                   └── Platform orchestration
                                      │
                              PostgreSQL 17 + RLS + pgvector (SQLAlchemy)
                                      │
                                      ▼
                             Job Dispatcher → Redis (Dramatiq)
                                      │
                                      ▼
                      FastAPI Execution Runtime (apps/compute)
                      ├── Validation, analytics, formula evaluation
                      ├── ML (optional), report generation
                      └── Artifact production (Polars • DuckDB)
```

```
Finance Operations Platform (reusable infra)
├── Identity           (Organization → Tenant → User → Role)
├── RBAC               (role → permission → action matrix)
├── Policy Engine      (simple ABAC: evaluate() -> (bool, reason))
├── Registry Engine    (Formula, Policy, Prompt, Validation, Evaluation, Feature)
├── Connector Framework (registry + adapters: CSV, Sheets, ERPNext, QuickBooks)
├── Job Dispatcher     (permissions, queue [Dramatiq/Redis], retry, timeout)
├── Execution Runtime  (apps/compute, separate service)
├── Audit              (who/tenant/role/policy/tool/evidence/decision/version)
├── Observability      (metrics, logs, Langfuse tenant traces)
├── Configuration      (tenant.yaml + feature flags)
└── Business Capability Layer (Budgeting, Forecasting, Variance, Close, …)

Finance Operations OS (finance domain)
├── Domain Models      (ledger, trial balance, budget, forecast, variance, statements)
├── Formula Registry   (versioned, owner, references, lineage)
├── Validation
├── Analytics
├── Recommendations
├── Reports
└── Agent Runtime
```

---

## 4b. Locked Stack (final — do not expand horizontally)

| Layer | Decision | Explicitly NOT used |
|-------|----------|---------------------|
| Frontend | Next.js 15 (repo currently on 16.2.10, lock remains 15 target) + React + Tailwind + shadcn/ui | MUI, AntD, Chart.js |
| API | **FastAPI + SQLAlchemy** (apps/api) | Hono, Drizzle, Prisma |
| Auth | Better Auth (frontend) + FastAPI integration | custom JWT identity system |
| Database | PostgreSQL 17 + RLS + pgvector + SQLAlchemy | — |
| Queue | Redis + **Dramatiq** | Celery, Temporal (reserved for OpsCore) |
| Execution Runtime | FastAPI, **separate service** (apps/compute) | — |
| Data | Polars + DuckDB | pandas-only, SQLAlchemy analytics |
| Validation | Pydantic v2 + Pandera | — |
| AI | LiteLLM + LangGraph | — |
| ML | scikit-learn (optional) | PyTorch, TensorFlow |
| Docs | OpenSpec + ADR + MkDocs | — |
| Deployment | Docker Compose | K8s, Helm, Terraform |

**Removed from MVP:** WebSockets, Hono, Drizzle, real-time notifications, streaming, live dashboards. Job-oriented polling instead.

**12-point feature checklist** — every new capability must satisfy all 12 before it ships:
1. glossary entry  2. capability mapping  3. ontology class  4. formula/policy registry entry  5. reference-data wired  6. Pydantic model  7. DB schema  8. API contract  9. compute runtime path  10. agent tool  11. evaluation dataset  12. observability

---

## 5. Phased Plan

### Phase 0 — Restructure & Positioning (Foundation)
**Goal:** Establish finplatform/ vs domain/ separation, demo tenant skeleton, reference-data package, metadata + contracts foundations.

- Create `finplatform/` package (identity, rbac, abac, registry, connectors, dispatcher, audit, observability, config) — Layer 0, imports nothing internal. (Named `finplatform/`, not `platform/`, to avoid shadowing the Python stdlib `platform` module — see `docs/adr/0001-platform-package-name-and-orphaned-tests.md`.)
- Create `tenants/` with `demo/acme-corp/tenant.yaml`, `demo/globex/tenant.yaml`, `demo/initech/tenant.yaml` — each with currency, fiscal_year, materiality, approval_limits, **feature flags**.
- Create `reference-data/` package: currencies (ISO 4217), countries (ISO 3166), chart-of-accounts, tax codes, fiscal calendars. Extended per review: `currency/`, `country/`, `calendar/`, `coa/`, `departments/`, `cost_centers/`, `tax/`, `approval_limits/`, `materiality/`.
- Rename `python_runtime/` → `apps/compute/` (Execution Runtime) — it will eventually execute analytics, validation, ML, SQL, formulas, reports, not just Python.
- Create `contracts/` directory: versioned contracts for `api/`, `events/`, `datasets/`, `prompts/`, `formulas/`, `connectors/`. Registries reference contracts, never inline definitions.
- Create `business/metadata/` Metadata Registry: every entity (formula, policy, connector, dataset, schema, feature, capability) has `id, version, owner, status, created, updated, dependencies, references`.
- Create `business/examples/` classification: `good/`, `bad/`, `edge/`, `malicious/` per aggregate (e.g. Invoice: good, duplicate, currency-mismatch, negative-amount, future-date, cross-tenant, tampered) — reused for docs, tests, demos, evaluations.
- Capability maturity: `business/capabilities/` gains lifecycle `Discovery → Implemented → Production → Deprecated`.
- Fix duplicate dirs: merge `business/data-dictionary/` → `business/data_dictionary/`.
- Remove orphaned `tests/backend/` tree (imports nonexistent `backend.*`; see `docs/adr/0001-platform-package-name-and-orphaned-tests.md`); live coverage lives in `tests/unit/`, `tests/integration/`, `tests/test_python_runtime/`, `business/tests/`.
- README rewrite: "Finance Operations OS" product on "Finance Operations Platform" infra.

**Deliverables:** `finplatform/` skeleton, `reference-data/`, demo tenants, `contracts/`, Metadata Registry, Execution Runtime rename, cleanup.

### Phase 1 — Identity & Authorization (Security Core, reduced)
**Goal:** A request is an authenticated actor in a tenant with enforceable permissions.

- **Models** (`shared/models/identity.py`): `Organization`, `Tenant`, `User`, `Role` (+ `UserRole` join). `Environment` **deferred**. Migration: backfill `tenant_id` on legacy tables.
- **Auth**: delegate to Auth0/Clerk OR minimal signed-token verifier in `apps/api/middleware.py`. **Focus on authorization.** Middleware resolves user → tenant → role and sets tenant context via `SELECT set_tenant_context(...)` (existing `001_extensions.sql`).
- **Unify RLS**: single session var (`app.current_tenant_id`) used by all RLS policies; align `docs/12-database/rls.md` with code. (current codebase de-facto uses `app.tenant_id`; unify scheduled in Phase 1)
- **RBAC**: roles `analyst`, `manager`, `director`, `cfo`; permission matrix (e.g., `approve_budget`, `view_ledger`, `manage_tenants`).
- **Simple ABAC**: `finplatform/abac/engine.py` — `PolicyEngine.evaluate(policy, context) -> (bool, reason)`, typed rules (amount, department, role, tenant, status). Supersedes hardcoded `if amount > x`.

**Deliverables:** identity models + migration, auth middleware + RLS wiring, RBAC matrix, simple ABAC engine. Tenant-isolation tests.

### Phase 2 — Tenant Configuration & Feature Flags (Configurability)
**Goal:** Demo tenants differ only by `tenant.yaml`; onboarding is configuration, not deployment.

- **`tenant.yaml` schema** (`finplatform/config/tenant_schema.py`): company, currency, fiscal_year, materiality (amount + pct), approval_limits (manager/director/cfo), tax_regime, sox_enabled, connectors, **features**.
- **Feature flags**: `features: {forecasting: true, recommendations: false, rag: false, ml: false}` + `FeatureRegistry` (`finplatform/config/features.py`) with enablement checks, tenant/license/dependency resolution.
- **Config loader**: `TenantConfig.load(tenant_id)` → frozen Pydantic, validated.
- **De-hardcode thresholds**:
  - `agents/variance/variance_agent.py:27-35` (`5000.0/5.0`) → tenant config.
  - `business/policies/registry.py:36` (`mat-001 > 50000`) → parameterized by tenant.
  - `finance/variance_engine/materiality.py` tiers → per-tenant.
- **Multi-tenant seed** (`shared/utils/seed.py`): Acme (USD, JAN, 5000/5%), Globex (EUR, JUL, 25000/8%), Initech (GBP, APR, 10000/6%).
- **Frontend entity switcher** (`frontend/src/app/page.tsx:15`): replace hardcoded `CF001` with tenant/feature-aware selector.

**Deliverables:** tenant schema + loader, feature registry, threshold de-hardcoding, multi-tenant seed, frontend switcher.

### Phase 3 — Registries & Capability Layer (Semantics)
**Goal:** Registries are authoritative and enforced; everything maps to a capability.

- **Elevate Formula Registry** (required change #4): `business/formula_registry/` gains versioned definitions, owner, references (IAS/GAAP), and **lineage** (formula → dependencies → source fields → reports). Compute evaluates via registry, never inline.
- **Policy engine enforcement**: `finplatform/policies/engine.py` evaluates `business/policies` against actor attributes + tenant config; wired into API routes, dispatcher, agent tools.
- **Validation registry**: promote `finance/validation/*` + `python_runtime/validation/schemas.py` to declarative config.
- **Evaluation registry**: promote `finance/evaluation/*` thresholds to config-driven registry (reuse `regression.py` YAML loader pattern).
- **Business Capability layer** (required change #3): wire `business/capabilities/` (38 capabilities) so services, events, agents, and KPIs map to capabilities; capability registry feeds routing and service catalog.

**Deliverables:** elevated formula registry, policy enforcement, validation/evaluation registries, capability wiring.

### Phase 4 — Job-Oriented Compute & Agent Isolation
**Goal:** Jobs and AI are tenant-scoped; every run is reproducible; LLM receives only verified context.

- **Persistent job model** (replaces ephemeral request/response + WebSockets): `Job → Task → Artifact → Execution Trace/Log/Metrics`. `POST /jobs` returns 202 + `job_id`; client polls `GET /jobs/:id`. SQLAlchemy models: `Job`, `Artifact`, `ExecutionTrace`, `ExecutionLog`, `ExecutionMetrics`. Remove `apps/api/websocket.py`.
- **Job Dispatcher → Execution Runtime → Artifacts**: `apps/compute/dispatcher.py` (or `finplatform/dispatcher`) owns permissions, queue (Dramatiq/Redis), retry, timeout; `apps/compute/models.py` Job gains `user_id`, `correlation_id`, `permission_set`. Runtime receives authorized datasets (storage paths `tenant/<id>/artifact/<version>/`), never raw files.
- **Agent tool permissions**: per-tool permission checks in `shared/utils/tools/*`; tools scope by tenant.
- **LLM boundary fix**: `agents/driver/root_cause_agent.py:13-18` sends raw variance data → replace with validated assertions (match `commentary_agent.py`).
- **Tenant memory isolation**: retrieval (RAG) scoped by tenant; vector keys include tenant_id.

**Deliverables:** job/task/artifact persistence + polling API, dispatcher security context, tool permissions, LLM boundary fix, tenant-scoped RAG.

### Phase 5 — Connectors + Reference Data
**Goal:** Connectors are pluggable and registered; master data is separate.

- **Connector contract** (`finplatform/connectors/base.py`): `Connector` protocol (connect, read, validate, schema, health).
- **Connector registry**: register/lookup/health; per-tenant enabled connectors from `tenant.yaml`.
- **Adapters**: refactor `finance/integration/` (CSV, Google Sheets) onto the contract; add `ERPNext`, `QuickBooks`; stub `SAP`, `NetSuite` schemas.
- **Reference data**: populate `reference-data/` (currencies, countries, COA, tax codes, fiscal calendars) with validation + versioning.

**Deliverables:** connector framework + registry (4-6 adapters), reference-data package.

### Phase 6 — Audit, Observability, Lineage & Service Catalog
**Goal:** Every action answers the 10 audit questions; lineage is one page.

- **Audit enrichment**: `007_audit_triggers.sql` / `AuditLog` gains role, policy decision, tool, prompt version, evidence IDs. Audit query API by tenant/actor/policy/action.
- **Observability**: per-tenant metrics (job latency, error rates, tool failures), structured logs with `correlation_id`, Langfuse tenant-scoped traces.
- **Data lineage doc**: one-page lineage for `Revenue → Google Sheet → Importer → Validation → DB → Formula → Report → Agent`.
- **Service catalog doc**: document services (Identity, Compute, Finance, Reporting, Evaluation), owners, dependencies, consumers.
- **Ops docs**: `docs/15-observability`, `docs/16-deployment`, `docs/17-runbooks`, `docs/18-postmortems`.

**Deliverables:** enriched audit + API, observability config, lineage + service catalog docs, ops docs.

### Phase 7 — SaaS Ops Docs & Deployment
**Goal:** Repository reads like a real enterprise engagement.

- **Docs restructure** to target numbering (01-workflow-analysis, 02-prd, 04-api, 06-security, 14-evaluation, 19-roadmap).
- **CI/CD**: `.github/workflows` (lint, mypy, pytest, golden datasets), branch protection.
- **Deployment guide**: docker-compose production profile, secrets management, DB migrations runbook, **tenant provisioning runbook** (onboard a new tenant = add `tenant.yaml` + seed, no code).
- **Demo narrative**: `docs/00-executive-summary` updated to "Acme Corp engagement"; `tenants/demo/acme-corp/` holds config + demo data.

**Deliverables:** docs restructure, CI/CD, deployment + provisioning runbooks.

---

## 6. Suggested Sequencing & Effort

| Phase | Focus | Effort | Depends On |
|-------|-------|--------|------------|
| 0 | Restructure + reference-data + contracts + metadata + Execution Runtime rename | 2-3d | — |
| 1 | Identity (reduced) + RLS + RBAC + simple ABAC | 3-4d | 0 |
| 2 | Tenant config + feature flags + de-hardcode | 3-4d | 1 |
| 3 | Registry wiring + capability layer | 3-4d | 2 |
| 4 | Job persistence + compute/agent isolation | 3-4d | 1,3 |
| 5 | Connectors + reference data | 2-3d | 0 |
| 6 | Audit + observability + lineage + catalog | 2-3d | 1 |
| 7 | Docs + CI/CD + runbooks | 2-3d | all |

**Total:** ~20-28 engineering days. **MVP for a demonstrable demo (Phases 0-2 + a slice of 3): ~7-9 days.**

---

## 7. MVP Definition (Ship Gate)

The demo is a credible multi-tenant SaaS if and only if:

- [ ] Two tenants (Acme, Globex) produce different materiality/approval behavior from `tenant.yaml` **with zero code change**.
- [ ] A request is authenticated (external IdP or signed token) and DB RLS actively filters by tenant — a cross-tenant query returns no rows.
- [ ] An analyst cannot approve a director-level amount; the ABAC engine blocks it with a reason.
- [ ] Feature flags toggle forecasting/rag per tenant without code changes.
- [ ] The variance agent's materiality comes from tenant config, not source code.
- [ ] Formula Registry is versioned, owner-attributed, reference-linked, and evaluated (not `if EBITDA...`).
- [ ] LLM receives only assertions/evidence; no raw variance data in prompts.
- [ ] Audit log captures who/tenant/role/policy/evidence for a sample action.
- [ ] Connector registry lists CSV/Sheets/ERPNext/QuickBooks with health status.
- [ ] Reference data (currencies, COA, fiscal calendars) is a separate package with validation.
- [ ] `POST /jobs` → 202 + `job_id` → poll `GET /jobs/:id`; Job/Task/Artifact persisted; no WebSockets in MVP.
- [ ] Execution Runtime runs as a separate service (`apps/compute`); `python_runtime/` renamed.
- [ ] Metadata Registry exists (id/version/owner/status/deps/references) for formula, policy, connector, dataset, feature, capability.
- [ ] `contracts/` dir holds versioned api/events/datasets/prompts/formulas/connectors contracts.
- [ ] Capability maturity states (Discovery→Implemented→Production→Deprecated) present in `business/capabilities/`.
- [ ] 685+ existing tests + new identity/isolation/ABAC/feature tests pass (`ruff`, `mypy`, `pytest`).

## 8. Stretch (Post-MVP)

- Sandboxed compute execution (container-per-job) per `docs/09-platform/compute-runtime.md`.
- `Environment` (prod/sandbox) model.
- Self-serve tenant onboarding UI.
- Tenant-aware prompt overrides per customer.
- OPA/Cedar drop-in for the policy engine.

---

## 9. Key Decisions for Review (v2)

| Decision | Proposal | Alternative |
|----------|----------|-------------|
| API layer | **FastAPI + SQLAlchemy** (no Hono/Drizzle — single Python stack) | Hono + Drizzle (rejected: second backend stack, months of work) |
| Identity scope | `Organization → Tenant → User → Role` (no Environment) | add Environment post-MVP |
| AuthN | Better Auth (frontend) + FastAPI integration; focus on authZ | build full JWT identity system |
| ABAC | `PolicyEngine.evaluate() -> (bool, reason)` typed rules | generic policy language (OPA) |
| RLS session var | `app.current_tenant_id` (unify doc + code) — current codebase de-facto uses `app.tenant_id`; unify scheduled in Phase 1 | keep `app.tenant_id` |
| Tenant config | YAML in `tenants/<id>/tenant.yaml` + feature flags | JSON / env vars |
| Reference data | separate `reference-data/` package (extended) | mixed into domain tables |
| Queue | Redis + **Dramatiq** | Celery, Temporal (OpsCore) |
| Interaction | **Job-oriented polling** (POST /jobs → 202 → GET /jobs/:id), no WebSockets | WebSockets / SSE |
| Execution Runtime | FastAPI **separate service** (`apps/compute`) | single runtime |
| Registry Engine | Metadata Registry (id/version/owner/status/deps/references) over all entities | per-registry-only |
| Connector contract | `finplatform/connectors/` protocol + registry | extend `finance/integration/` |
| Formula Registry | first-class, versioned, referenced, lineage | stay embedded in business/ |
| Demo tenants | acme-corp (USD), globex (EUR), initech (GBP) | single demo tenant |
