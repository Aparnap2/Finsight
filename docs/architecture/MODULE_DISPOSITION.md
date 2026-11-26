# FinSight Module Disposition Inventory

**Version:** 1.0 (Task D deliverable)
**Status:** Read-only investigation
**Branch:** feat/reconciliation-three-source-workflow
**HEAD:** 0aab59a (verify with `git rev-parse HEAD`)
**Date:** 2026-11-22

---

## Legend

| Disposition | Meaning | Required action |
|---|---|---|
| KEEP | Active, useful implementation serving the reconciliation product | Preserve and document |
| REFACTOR | Active but structurally problematic | Define bounded refactoring |
| CONSOLIDATE | Duplicated functionality | Select canonical implementation, migrate consumers |
| REMOVE | Proven obsolete or unreachable | Delete with dependency and regression evidence |
| DEFER | Not needed for current product scope | Preserve only if justified; document explicitly |
| INVESTIGATE | Insufficient evidence | Bounded investigation with decision deadline |

---

## 1. Top-Level Production Packages

### 1.1 `finance/reconciliation/` — KEEP

| Module | LOC | Consumers | Disposition | Evidence |
|---|---|---|---|---|
| `models.py` | ~200 | Engine, workflow, operator report, tests | KEEP | Core domain types; 111 contract assertions |
| `allocation.py` | ~400 | statement_workflow, tests | KEEP | Payout allocation with conservation invariants |
| `bank.py` | ~300 | statement_workflow, tests | KEEP | Bank statement normalization |
| `statement_workflow.py` | ~400 | operator_report, tests | KEEP | Three-source composition |
| `operator_report.py` | ~300 | CLI, tests, golden evidence | KEEP | 266 checks, byte-reproducible |
| `fingerprints.py` | ~100 | statement_workflow, tests | KEEP | SHA-256 provenance |
| `tolerances.py` | ~50 | allocation, tests | KEEP | Tolerance configuration |
| `errors.py` | ~30 | models, bank, allocation | KEEP | Error types |
| `reconciler.py` | ~200 | tests | KEEP | Two-leg reconciliation |
| `matcher.py` | ~150 | tests | KEEP | Invoice-charge matching |
| `normalizer.py` | ~100 | bank, tests | KEEP | Minor unit exponent |

**Total**: ~2,500 LOC, 352 tests. This is the product core. Protected.

### 1.2 `finance/` (other subpackages) — Most are REMOVE/DEFER

| Subpackage | LOC | Production importers | Disposition | Evidence |
|---|---|---|---|---|
| `finance/analytics/` | 436 | 0 (unreachable) | REMOVE (slice 8) | `predictive.py` is scaffolding (NullPredictiveProvider). No ML. Deterministic feature calc only. |
| `finance/approval/` | 1,162 | 0 | REMOVE (slice 8) | FP&A approval workflow; no reconciliation consumer |
| `finance/approvals/` | 23 | 0 | REMOVE (slice 8) | Duplicate of approval/ |
| `finance/accounting/` | 49 | 0 | REMOVE (slice 8) | Trivial, no consumers |
| `finance/assertion_pipeline.py` | ~200 | 0 | REMOVE (slice 8) | FP&A assertion pipeline |
| `finance/business_rules/` | 1 | 0 | REMOVE | Empty stub |
| `finance/cognition/` | 1,256 | `finance/evaluation/runner.py` | CONSOLIDATE (slice 8) | Used by eval runner; assess if eval gate can be retired |
| `finance/context/` | 67 | 0 | REMOVE (slice 8) | FP&A context builder |
| `finance/correlation/` | 927 | 0 | REMOVE (slice 8) | FP&A correlation engine |
| `finance/detection/` | 702 | 0 | REMOVE (slice 8) | FP&A anomaly detection |
| `finance/domain/` | 3,478 | 0 (unreachable) | REMOVE (slice 8) | Large FP&A domain model; no reconciliation consumer |
| `finance/driver_engine/` | 0 (empty) | 0 | REMOVE | Empty |
| `finance/evaluation/` | 2,104 | CI (`ai-evals.yml`) | **PROTECT** | Live in CI golden-dataset gate. Do not remove until migrated. |
| `finance/evidence/` | 327 | 0 | REMOVE (slice 8) | FP&A evidence assembly |
| `finance/exceptions/` | 46 | 0 | REMOVE (slice 8) | Trivial |
| `finance/execution/` | 26 | 0 | REMOVE (slice 8) | Trivial |
| `finance/facts/` | 603 | 0 | REMOVE (slice 8) | FP&A fact extraction |
| `finance/feature_store/` | 1,514 | `finance/analytics/diagnostic.py`, `descriptive.py` | CONSOLIDATE (slice 8) | Deterministic feature engineering; assess consumers |
| `finance/forecast_engine/` | 0 (empty) | 0 | REMOVE | Empty |
| `finance/formula_engine/` | 470 | 0 | REMOVE (slice 8) | FP&A formula engine |
| `finance/ingestion/` | 461 | `finance/ingestion/publisher.py` imports shared.tracing | REMOVE (slice 8) | FP&A ingestion; publisher uses tracing. **Do not confuse with `finance/source_ingestion/`, which is reconciliation ingestion and must be preserved.** |
| `finance/integration/` | 575 | 0 | REMOVE (slice 8) | FP&A integration layer |
| `finance/investigation/` | 1,322 | 0 | REMOVE (slice 8) | FP&A investigation (not reconciliation AI) |
| `finance/kpi_engine/` | 0 (empty) | 0 | REMOVE | Empty |
| `finance/legacy/` | 1 | 0 | REMOVE (slice 8) | Trivial |
| `finance/legacy_execution/` | 2,020 | 0 (except transport.py imports object_store) | REMOVE (slice 8) | FP&A legacy execution |
| `finance/llm/` | 10 | 0 | REMOVE (slice 8) | Empty stub (docstring only) |
| `finance/object_store/` | 294 | `finance/verification/`, `finance/legacy_execution/transport.py` | CONSOLIDATE (slice 8) | S3 adapter; assess if needed for P1 uploads |
| `finance/p8_durability/` | 179 | 0 (test-only) | DEFER | DB-backed; needs migration decision |
| `finance/policy/` | 15 | 0 | REMOVE (slice 8) | Trivial |
| `finance/prompts/` | 532 | 0 | REMOVE (slice 8) | FP&A prompts |
| `finance/proposals/` | 32 | 0 | REMOVE (slice 8) | Trivial |
| `finance/reasoning/` | 809 | 0 | REMOVE (slice 8) | FP&A reasoning (llm_boundary used by tests) |
| `finance/recommendation_engine/` | 0 (empty) | 0 | REMOVE | Empty |
| `finance/reporting/` | 266 | 0 | REMOVE (slice 8) | FP&A reporting |
| `finance/scenario_engine/` | 0 (empty) | 0 | REMOVE | Empty |
| `finance/stripe/` | 930 | 0 | REMOVE (slice 8) | FP&A Stripe integration |
| `finance/validation/` | 575 | 0 | REMOVE (slice 8) | FP&A validation |
| `finance/variance_engine/` | 456 | 0 | REMOVE (slice 8) | FP&A variance engine |
| `finance/verification/` | 110 | 0 | REMOVE (slice 8) | FP&A verification (uses object_store) |
| `finance/workflows/` | 202 | 0 | REMOVE (slice 8) | FP&A workflows |
| `finance/reconciliation/` | ~2,500 | Live (engine + CLI) | **KEEP** | Product core; 352 tests |
| `finance/domain/forecast.py` | (part of domain/) | 0 | REMOVE (slice 8) | Legacy forecast entities |
| `finance/evaluation/` | 2,104 | CI (`ai-evals.yml`) | **PROTECT** | Live in CI golden-dataset gate |

**ML assessment (cross-checked):**
- `finance/ml/` — REMOVED (Slice 1)
- `finance/analytics/predictive.py` — scaffolding only (NullPredictiveProvider). No ML.
- `finance/feature_store/` — deterministic feature engineering. No model training.
- `finance/domain/forecast.py` — legacy Pydantic entities. No forecasting model.
- `finance/evaluation/golden.py` — reference implementations (naive forecast, threshold anomaly, duplicate detector). Deterministic, not ML.
- No ML dependencies in pyproject.toml (no scikit-learn, XGBoost, PyTorch, TensorFlow, MLflow).
- **Conclusion**: Traditional ML is out of scope. Deterministic analytics retained where useful. LLM investigation is the only AI capability.

### 1.3 `agents/` — Most are REMOVE

| Subpackage | LOC | Production importers | Disposition | Evidence |
|---|---|---|---|---|
| `agents/commentary/` | ~400 | `apps/api/routes.py` (via generate_commentary) | REFACTOR (slice 8) | Used by FP&A routes; assess if reconciliation needs commentary |
| `agents/driver/` | ~300 | `apps/api/routes.py` (via investigate_root_causes) | REFACTOR (slice 8) | Used by FP&A routes; assess if reconciliation needs root cause |
| `agents/variance/` | ~200 | `apps/api/routes.py` (via variance_node) | REFACTOR (slice 8) | Used by FP&A routes |
| `agents/authority/` | ~859 | 0 | REMOVE (slice 8) | Authority/claims framework; no reconciliation consumer |
| `agents/brief/` | 428 | 0 | REMOVE (slice 8) | Brief generation |
| `agents/capabilities/` | 1,229 | 0 | REMOVE (slice 8) | Capability executor |
| `agents/discovery/` | 584 | 0 | REMOVE (slice 8) | Discovery engine |
| `agents/evaluation/` | 240 | 0 | REMOVE (slice 8) | Agent evaluation |
| `agents/forecast/` | ~100 | 0 | REMOVE (slice 8) | Forecast agent |
| `agents/integration/` | 300 | 0 | REMOVE (slice 8) | Integration layer |
| `agents/investigation/` | 1,003 | 0 | CONSOLIDATE (P4) | Investigation planner; may be reused for P4 AI investigation |
| `agents/orchestrator/` | 505 | 0 | REMOVE (slice 8) | Orchestration framework |
| `agents/p8_runtime/` | 1,441 | `apps/api/observability.py` (lazy) | DEFER/RETAIN | contract.py retained; execution.py retained (durability dep); durability deferred |
| `agents/reasoning/` | 582 | 0 | REMOVE (slice 8) | Reasoning pipeline |
| `agents/recommendation/` | ~100 | 0 | REMOVE (slice 8) | Recommendation engine |
| `agents/runtime/` | 583 | 0 | REMOVE (slice 8) | Runtime factory |
| `agents/scenario.py` | 24 | 0 | REMOVE (slice 8) | Trivial |
| `agents/tools/` | 506 | 0 | REMOVE (slice 8) | Tool registry |
| `agents/trajectory/` | 787 | 0 | REMOVE (slice 8) | Trajectory recorder |
| `agents/verification/` | 664 | 0 | REMOVE (slice 8) | Verification agent |

**Note:** `agents/commentary/`, `agents/driver/`, `agents/variance/` are used by `apps/api/routes.py` (FP&A routes). These are part of the FP&A product generation. They should be assessed in slice 8 — either removed (if reconciliation doesn't need commentary/variance/drivers) or retained as the basis for P4 AI investigation.

### 1.4 `shared/` — Mixed

| Subpackage | LOC | Production importers | Disposition | Evidence |
|---|---|---|---|---|
| `shared/config/` | ~200 | Many (settings) | KEEP | Application settings |
| `shared/models/` | ~300 | Many (DB models, assertions, state) | KEEP | Core models |
| `shared/llm/` | 1,211 | `agents/`, `finance/evaluation/`, `apps/api/routes.py` (after slice 5) | CONSOLIDATED | Canonical LLM framework (slice 5 complete) |
| `shared/utils/` | 1,642 | 11 unreachable modules | REMOVE (slice 6) | Assess individually |
| `shared/tracing/` | 1,895 | `finance/ingestion/publisher.py` | REMOVE/DEFER (slice 6) | Assess observability needs |
| `shared/aws/` | 103 | Tests only | DEFER | Test-only MiniStack config |
| `shared/migrations/` | 219 | 0 | REMOVE (slice 6) | Assess |
| `shared/prompts/` | 0 | 0 | REMOVE | Empty |
| `shared/safety/` | 82 | 0 | REMOVE (slice 6) | Assess |
| `shared/schemas/` | 0 | 0 | REMOVE | Empty |
| `shared/privacy/` | ~300 | `agents/`, `finance/` | KEEP | Privacy boundary (P10) |

### 1.5 `apps/` — Mixed

| Module | LOC | Disposition | Evidence |
|---|---|---|---|
| `apps/api/main.py` | ~50 | KEEP | FastAPI app factory, mounts all routers + NiceGUI |
| `apps/api/routes.py` | 869 | REFACTOR (P1/P2) | FP&A routes; needs reconciliation routes added |
| `apps/api/schemas.py` | ~200 | KEEP | Pydantic schemas, MoneyDecimal |
| `apps/api/middleware.py` | ~100 | KEEP | Tenant auth, RLS |
| `apps/api/observability.py` | ~200 | KEEP | Request ID, readiness, budget_check_response |
| `apps/api/operator_console.py` | ~100 | KEEP | NiceGUI console at /gui |
| `apps/api/approvals.py` | ~200 | REFACTOR (P3) | FP&A approvals; may be reused for exception decisions |
| `apps/api/execution_routes.py` | ~200 | REFACTOR (P2) | Execution routes; assess for reconciliation |
| `apps/api/observations.py` | ~100 | REFACTOR (P2) | Observations; assess |
| `apps/api/webhooks.py` | ~100 | REFACTOR (P2) | Webhooks; assess |
| `apps/api/serializers.py` | ~50 | KEEP | Decimal serialization |
| `apps/workers/sqs_execute.py` | ~100 | DEFER | Background worker; not needed for sync reconciliation |

### 1.6 `python_runtime/` — DEFER

| Module | LOC | Production importers | Disposition |
|---|---|---|---|
| `python_runtime/dispatcher.py` | ~100 | `apps/api/routes.py` | KEEP (compute runtime) |
| `python_runtime/cache.py` | 136 | 0 | REMOVE (slice 6) |
| `python_runtime/exporters/` | 141 | 0 | REMOVE (slice 6) |
| `python_runtime/handlers/` | 1 | 0 | REMOVE (slice 6) |
| `python_runtime/importers/` | 1 | 0 | REMOVE (slice 6) |
| `python_runtime/telemetry/` | 76 | 0 | REMOVE (slice 6) |
| `python_runtime/transforms/` | 227 | 0 | REMOVE (slice 6) |
| `python_runtime/validation/` | 1 | 0 | REMOVE (slice 6) |

### 1.7 `finplatform/` — CONSOLIDATE

| Module | LOC | Production importers | Disposition |
|---|---|---|---|
| `finplatform/rbac/matrix.py` | ~50 | `apps/api/middleware.py` | KEEP |
| `finplatform/abac/` | ~215 | 0 | REMOVE (slice 7) |
| `finplatform/audit/` | 1 | 0 | REMOVE (slice 7) |
| `finplatform/config/` | 59 | `agents/variance/`, `finance/ml/` (deleted) | REMOVE (slice 7) |
| `finplatform/connectors/` | 1 | 0 | REMOVE (slice 7) |
| `finplatform/dispatcher/` | 1 | 0 | REMOVE (slice 7) |
| `finplatform/identity/` | 1 | 0 | REMOVE (slice 7) |
| `finplatform/observability/` | 1 | 0 | REMOVE (slice 7) |
| `finplatform/policies/` | 1 | 0 | REMOVE (slice 7) |
| `finplatform/registries/` | 1 | 0 | REMOVE (slice 7) |

### 1.8 `scripts/` — KEEP (with assessment)

| Script | LOC | Purpose | Disposition |
|---|---|---|---|
| `reconciliation_boundary.py` | 174 | Boundary manifest | KEEP |
| `reconciliation_contract_report.py` | 344 | Contract report | KEEP |
| `mypy_baseline_check.py` | 128 | Mypy ratchet | KEEP |
| `ci_gate.py` | 75 | CI completeness gate | KEEP |
| `secret_gate.py` | 407 | Secret scanning | KEEP |
| `pr_verification.py` | 1,367 | PR verification | KEEP (CI) |
| `ministack_init.py` | 89 | S3 init for tests | KEEP (test infra) |
| `record_llm_fixtures.py` | 147 | LLM fixture recording | DEFER |
| `smoke_groq.py` | 173 | Groq smoke test | DEFER |

### 1.9 `docs/` — Mixed

| Directory | Disposition | Notes |
|---|---|---|
| `docs/PRODUCT.md` | KEEP (authoritative) | Canonical product spec |
| `docs/release/` | KEEP | Boundary, contract, deployment |
| `docs/specs/` | KEEP (new) | 8 architecture specs |
| `docs/archive/` | KEEP (archive) | Historical docs |
| `docs/09-platform/` | REFACTOR | Platform layer docs; some stale |
| `docs/07-ai-runtime/` | REMOVE/ARCHIVE | FP&A AI runtime guide |
| `docs/14-platform/` | REMOVE/ARCHIVE | FP&A implementation plan |
| `docs/architecture/*_CONTRACT.md` | ARCHIVE | 21 phase docs (still cited by tests) |
| `docs/11-data-contracts/` | REMOVE/ARCHIVE | FP&A data contracts plan |
| `docs/12-database/` | KEEP/REFACTOR | Database docs (some useful) |
| `docs/08-evaluation/` | KEEP/REFACTOR | Evaluation docs |

---

## 2. Duplicate Implementation Audit

### 2.1 LLM Clients (CONSOLIDATED — Slice 5)

| Implementation | LOC | Status | Disposition |
|---|---|---|---|
| `shared/utils/llm_client.py` | 192 | **Deleted** (Slice 5) | Consolidated into `shared/llm/` |
| `shared/llm/` (10 modules) | 1,211 | **Canonical** | KEEP |
| `finance/reasoning/llm_boundary.py` | ~200 | Duck-typed `generate(prompt) -> str` | Higher-level abstraction; not a duplicate client. Future migration target. |

### 2.2 Tracing

| Implementation | LOC | Consumers | Disposition |
|---|---|---|---|
| `shared/tracing/` (9 modules) | 1,895 | `finance/ingestion/publisher.py` (1) | INVESTIGATE (Slice 6) |
| `shared/tracing/observability.py` | ~200 | 0 | REMOVE candidate |
| `shared/tracing/correlation.py` | ~200 | 0 | REMOVE candidate |

### 2.3 Configuration

| Implementation | LOC | Consumers | Disposition |
|---|---|---|---|
| `shared/config/config.py` (Settings) | ~100 | Many | KEEP (canonical) |
| `shared/llm/config.py` (LLMProviderConfig) | ~200 | `shared/llm/` | KEEP (LLM-specific) |
| `finplatform/config/` | 59 | `agents/variance/`, `finance/ml/` (deleted) | REMOVE (slice 7) |

### 2.4 Financial Types

| Implementation | LOC | Consumers | Disposition |
|---|---|---|---|
| `finance/reconciliation/models.py` (PaymentRecord, etc.) | ~200 | Engine, tests | KEEP (canonical) |
| `finance/domain/` (FP&A domain) | 3,478 | 0 | REMOVE (slice 8) |
| `business/` (deleted) | — | — | REMOVED (Slice 1) |

### 2.5 Persistence/Repository

| Implementation | LOC | Consumers | Disposition |
|---|---|---|---|
| `shared/models/database.py` (SQLAlchemy models) | ~300 | Many | KEEP |
| `finance/p8_durability/postgres_store.py` | ~200 | Tests only | DEFER |
| No reconciliation repository layer | — | — | **MISSING** (P2 build target) |

---

## 3. Technical Slop Register

### Slop Categories

| Category | Finding | Location | Evidence | Impact | Priority |
|---|---|---|---|---|---|
| Dead code | `finance/` FP&A generation (40+ subpackages, ~25K LOC) | `finance/` (excluding reconciliation/) | 0 production importers for most | High maintenance burden, confusion | P1 (slices 7-8) |
| Dead code | `agents/` FP&A generation (20+ subpackages, ~10K LOC) | `agents/` (excluding p8_runtime) | 0 production importers for most | High maintenance burden | P1 (slices 7-8) |
| Dead code | `shared/utils/` unreachable modules (11, 1,642 LOC) | `shared/utils/` | 0 production importers | Medium | P2 (slice 6) |
| Dead code | `shared/tracing/` (9 modules, 1,895 LOC) | `shared/tracing/` | 1 production importer | Medium | P2 (slice 6) |
| Dead code | `finplatform/` (12 of 13 modules, ~250 LOC) | `finplatform/` | Only `rbac.matrix` live | Low | P3 (slice 7) |
| Dead code | `python_runtime/` (13 of 21 modules, ~590 LOC) | `python_runtime/` | Only dispatcher + handlers live | Low | P3 (slice 6) |
| Duplicate code | LLM clients (RESOLVED) | `shared/utils/llm_client.py` → `shared/llm/` | Slice 5 complete | — | Done |
| Duplicate code | Tracing implementations | `shared/tracing/` vs `shared/tracing/observability.py` | Need investigation | Medium | P2 (slice 6) |
| Abstraction slop | `finance/llm/` empty stub | `finance/llm/__init__.py` (10 LOC) | Docstring only | Low | P3 |
| Abstraction slop | `finance/execution/` trivial module | `finance/execution/` (26 LOC) | No consumers | Low | P3 |
| Architecture slop | FP&A product generation | `finance/`, `agents/` | Previous product, replaced by reconciliation | High confusion | P1 (slices 7-8) |
| Dependency slop | Unused compose services (Temporal, Redpanda, Qdrant, Redis, Jaeger, Langfuse, Phoenix, Litellm) | `docker-compose.yml` | No reconciliation consumer | Medium | P3 (productization) |
| Test slop | `test_p8_runtime_to_p7.py` (deleted in 4a) | — | Was 100% execution-dependent | — | Done |
| Test slop | Pre-existing broken test_06 in test_adversarial_system.py | `tests/integration/test_adversarial_system.py` | AttributeError on `_valid_structured` | Low (removed in 4a) | Done |
| Documentation slop | 21 `docs/architecture/*_CONTRACT.md` files | `docs/architecture/` | Still cited by 3 test files | Medium | P3 (slice 9) |
| Documentation slop | FP&A docs (ai-architecture-guide, implementation-plan) | `docs/07-ai-runtime/`, `docs/14-platform/` | Describe deleted/obsolete generations | Medium | P3 (slice 9) |
| Configuration slop | `POOLSIDE_API_KEY`, `GROQ_API_KEY`, etc. | `shared/config/config.py` | Used by LLM client | Low (legitimate) | N/A |
| CI slop | `ai-evals.yml` golden gate uses FP&A evaluation code | `.github/workflows/ai-evals.yml` | `finance/evaluation/` is FP&A generation | Medium | P3 (protect until migrated) |
| Data slop | `finance/p8_durability/` tables in migration chain | Alembic `c9d5e7f1a204` | DB-backed, deferred | Low | P3 (slice 4b) |
| Observability slop | Multiple tracing implementations | `shared/tracing/` | 1 production importer | Medium | P2 (slice 6) |
| Naming slop | "execution" used for both finance execution and p8 execution | Various | Confusing | Low | P3 |

### ML-specific slop (cross-checked)

| Finding | Location | Evidence | Disposition |
|---|---|---|---|
| `finance/ml/` | REMOVED (Slice 1) | 8 modules, 1,931 LOC, 0 importers | Done |
| `finance/analytics/predictive.py` | Scaffolding only | NullPredictiveProvider returns input unchanged | REMOVE (slice 8) |
| `finance/feature_store/` | Deterministic | Feature engineering, no model training | CONSOLIDATE (slice 8) |
| `finance/domain/forecast.py` | Legacy entities | Pydantic forecast scenarios, no model | REMOVE (slice 8) |
| `finance/evaluation/golden.py` | Reference implementations | Naive forecast, threshold anomaly, duplicate detector | PROTECT (CI dependency) |
| No ML dependencies | pyproject.toml | No scikit-learn, XGBoost, PyTorch, TensorFlow, MLflow | N/A (correct) |

**Decision: Traditional ML is out of scope. Deterministic financial computation is core. LLM investigation is optional, bounded.**

---

## 4. Documentation Disposition

| Document | Classification | Authority | Issues |
|---|---|---|---|
| `docs/PRODUCT.md` | AUTHORITATIVE | Product scope | Canonical. Keep. |
| `docs/ARCHITECTURE.md` | (does not exist) | — | Needs creation from actual architecture |
| `docs/specs/*` (8 files) | AUTHORITATIVE | Technical contracts | New. Frozen pending consistency review. |
| `docs/release/RECONCILIATION_BOUNDARY.md` | AUTHORITATIVE | Cleanup boundary | Keep. Updated per slice. |
| `docs/release/RECONCILIATION_CONTRACT.md` | AUTHORITATIVE | Behavioral contract | Keep. |
| `AGENTS.md` | AUTHORITATIVE | Agent instructions | Testing standard added. |
| `CONTRIBUTING.md` | AUTHORITATIVE | Contributor workflow | Testing standard added. |
| `docs/09-platform/*.md` | SUPPORTING | Platform layer docs | Some stale (references deleted frontend). |
| `docs/07-ai-runtime/ai-architecture-guide.md` | HISTORICAL | AI runtime guide | Describes FP&A generation. Archive candidate. |
| `docs/14-platform/implementation-plan.md` | HISTORICAL | FP&A plan | Describes deleted backend/ package. Archive candidate. |
| `docs/archive/*` | HISTORICAL | Archived docs | Keep (reference only). |
| `docs/architecture/*_CONTRACT.md` (21 files) | STALE | Phase docs | Still cited by 3 test files. Archive after refs updated. |
| `docs/11-data-contracts/` | STALE | Data contracts plan | References finance/data_contracts/ (doesn't exist). |
| `docs/12-database/` | SUPPORTING | Database docs | Some useful (RLS). Keep. |
| `docs/repository.md` | SUPPORTING | Folder map | Updated (frontend/ removed). |
| `README.md` | AUTHORITATIVE | Project README | Rewritten to reconciliation product. |
| `openspec/` | SUPPORTING | Spec-driven workflow | Active. |

### Broken References Identified

1. `docs/09-platform/devsecops.md` — referenced `Dockerfile.frontend` (fixed in slice 2).
2. `docs/repository.md` — referenced `frontend/` (fixed in slice 2).
3. `CONTRIBUTING.md` — referenced `apps/frontend/` (fixed in slice 2).
4. `docs/11-data-contracts/implementation-plan.md` — references `finance/data_contracts/` (doesn't exist).
5. `docs/architecture/*_CONTRACT.md` — cited by `tests/unit/approval/test_approval.py`, `tests/unit/correlation/test_correlation.py`, `tests/contract/test_p7_08_control_plane_integration_red.py:560`.
6. `finance/llm/__init__.py` — referenced `shared.utils.llm_client` (fixed in slice 5).

---

## 5. Test Quality Review

### Existing test strengths

| Area | Tests | Quality assessment |
|---|---|---|
| Reconciliation engine | 352 | Strong: independent assertions, property-based sweep (40 generated allocations), golden evidence, mutation-prone invariants |
| Reconciliation contract | 111 | Strong: reads engine outputs, asserts invariants independently |
| p8 runtime (contract) | 165 (→ 125 after slice 4a) | Moderate: tests P8 runtime behavior, but P8 is not on production path |
| p8 integration | ~50 | Moderate: tests P8→P7 wiring, but P8 is not on production path |
| Privacy/LLM path wiring | ~10 | Strong: tests privacy boundary routing through all 5 LLM call sites |
| LLM provider seam | ~20 | Strong: tests structured output validation, fake/replay providers |
| Financial contract (mutation) | 0 | **Gap**: no mutation testing yet |
| Property-based (Hypothesis) | 0 | **Gap**: no Hypothesis tests yet (generated sweep uses random.Random, not Hypothesis) |
| Metamorphic | 4 | Moderate: permutation invariance tested, but not systematically |

### Test quality issues identified

1. **Tautological risk**: Some tests in `test_f2_provider_fault_matrix.py` (deleted in 4a) asserted `should_retry` using the same logic as the implementation. Mitigated by removal.
2. **Implementation coupling**: `test_p8_runtime_to_p7.py` (deleted in 4a) tested P8 execution internals through P7 integration. Mitigated by removal.
3. **Weak assertions**: Some tests assert `result is not None` without checking values. Need systematic review.
4. **Missing boundary tests**: No tests for zero/negative/extreme amounts in the API layer (not yet built).
5. **Missing failure-injection tests**: No DB disconnect, timeout, or crash recovery tests for reconciliation (not yet built).
6. **No mutation testing**: Financial invariants have no known mutation test suite.
7. **No property-based testing library**: Generated sweep uses `random.Random`, not Hypothesis.

### Recommendations

- Apply Hypothesis to allocation conservation, permutation invariance, replay determinism.
- Create mutation test suite for financial invariants (wrong operator, omitted fee, duplicate allocation, missing refund, currency mismatch, premature settlement, tenant filter bypass).
- Review all remaining tests for implementation coupling before deleting more code.
- Never delete tests solely because their production module is unreachable.

---

## 6. Dependency/Configuration Inventory

### Runtime dependencies (pyproject.toml)

| Dependency | Used by | Status |
|---|---|---|
| fastapi | apps/api | KEEP |
| sqlalchemy | shared/models, middleware | KEEP |
| alembic | migrations | KEEP |
| pydantic | shared/llm, finance/reconciliation | KEEP |
| polars | finance/feature_store, finance/analytics | CONSOLIDATE (slice 8) |
| duckdb | finance/analytics | CONSOLIDATE (slice 8) |
| pandera | (data validation) | KEEP (DataOps) |
| pyarrow | finance/analytics | CONSOLIDATE (slice 8) |
| openai | shared/llm/openai_compatible | KEEP (LLM) |
| httpx | (async HTTP) | KEEP |
| nicegui | apps/api/operator_console | KEEP |
| python-multipart | apps/api (file upload) | KEEP |
| psycopg | (PostgreSQL driver) | KEEP |
| boto3 | shared/aws (test-only) | DEFER |

### Environment variables

| Variable | Used by | Status |
|---|---|---|
| POSTGRES_URI | shared/config, middleware | KEEP (runtime DB contract) |
| DATABASE_URL | Nothing (read by nothing) | REMOVE (dead config) |
| POOLSIDE_API_KEY | shared/llm/config | KEEP (LLM) |
| GROQ_API_KEY | shared/llm/config | KEEP (LLM) |
| OPENROUTER_API_KEY | shared/llm/config | KEEP (LLM) |
| OPENAI_API_KEY | shared/llm/config | KEEP (LLM) |
| AWS_ENDPOINT_URL | shared/aws/config (test-only) | DEFER |
| LLM_PROVIDER | shared/llm/config | KEEP (LLM) |
| LLM_API_KEY | shared/llm/config | KEEP (LLM) |
| LLM_CHAT_MODEL | shared/llm/config | KEEP (LLM) |
| LLM_TIMEOUT_S | shared/llm/config | KEEP (LLM) |
| LLM_MAX_RETRIES | shared/llm/config | KEEP (LLM) |
| OPERATOR_CONSOLE_DEMO_TENANT_ID | apps/api/operator_console | KEEP (demo) |
| OPERATOR_CONSOLE_DEMO_ROLE | apps/api/operator_console | KEEP (demo) |
| OPERATOR_CONSOLE_DEMO_USER_ID | apps/api/operator_console | KEEP (demo) |

### CI workflows

| Workflow | Purpose | Status |
|---|---|---|
| ci.yml (fast) | Lint, typecheck, unit/contract, contract report | KEEP |
| integration.yml | PostgreSQL-gated, ministack S3 | KEEP |
| ai-evals.yml | Golden-dataset eval gate, manual LLM eval | KEEP (but finance/evaluation/ is FP&A generation) |
| verification.yml | PR verification, scope/risk classification | KEEP |
| deploy-prod.yml | Production deployment | KEEP (local Docker Compose) |
| deploy-staging.yml | Staging deployment | KEEP |
| rollback.yml | Rollback procedure | KEEP |

---

## 7. Existing-to-Target Map

### Target: B2B Payment Reconciliation Application

| Target Capability | Existing Implementation | Status | Gap |
|---|---|---|---|
| Deterministic reconciliation engine | `finance/reconciliation/` (frozen) | **KEEP** | None — engine is complete and tested |
| CSV ingestion (3 sources) | None | **MISSING** | No parser, normalizer, or validator for CSV input |
| HTTP API for reconciliation | None (zero reconciliation routes) | **MISSING** | No endpoints, no schemas, no service layer |
| Persistence of runs/results/exceptions | None (no reconciliation tables) | **MISSING** | No DB schema, no repository, no migration |
| Exception lifecycle | None | **MISSING** | No state machine, no decision recording |
| AI investigation | `agents/investigation/` (FP&A generation) | **REUSE?** | Needs assessment: can investigation planner be adapted? |
| NiceGUI reconciliation screens | None (operator_console is read-only FP&A) | **MISSING** | No upload, reconcile, inspect, investigate, resolve, export screens |
| CSV report export | None | **MISSING** | Engine produces operator report (Markdown/JSON); no CSV export endpoint |
| Authentication | Demo headers (X-Tenant-ID, X-User-ID, X-Role) | **REFACTOR** | Need real auth (JWT or session) |
| Tenant isolation (RLS) | `TenantAuthMiddleware` + `set_config('app.tenant_id')` | **KEEP** (verify) | RLS exists but not verified end-to-end for reconciliation |
| LLM client | `shared/llm/` (consolidated in Slice 5) | **KEEP** | Canonical framework; FakeLLM for CI |
| Observability | `shared/tracing/` (1 importer), Jaeger compose | **REFACTOR** | Consolidate tracing (Slice 6) |
| Docker deployment | `Dockerfile` + `docker-compose.staging.yml` | **KEEP** | Single image, API + PostgreSQL |
| CI/CD | GitHub Actions (quality, integration, ai-evals, verification) | **KEEP** | Add staging workflow (P6) |

### Existing capabilities to retain

| Capability | Location | Relevance to reconciliation product |
|---|---|---|
| Reconciliation engine | `finance/reconciliation/` | Core product. KEEP. |
| Operator report (Markdown/JSON/evidence) | `finance/reconciliation/operator_report.py` | Reuse for export (P2/P7). |
| Golden evidence bundle | `docs/evidence/operator-run/` | Byte-reproducible. KEEP. |
| Boundary manifest | `scripts/reconciliation_boundary.py` | Cleanup guard. KEEP. |
| Contract report | `scripts/reconciliation_contract_report.py` | CI gate. KEEP. |
| Tenant auth middleware | `apps/api/middleware.py` | Reuse for reconciliation API. |
| RLS infrastructure | `database/migrations/` | Reuse for reconciliation tables. |
| NiceGUI console | `apps/api/operator_console.py` | Extend for reconciliation screens. |
| LLM framework | `shared/llm/` | Reuse for P4 AI investigation. |
| Privacy boundary | `shared/privacy/` | Reuse for P4 (already wired). |
| S3 adapter | `finance/object_store/s3_adapter.py` | Reuse for P1 file storage (if S3 chosen). |
| Alembic migrations | `alembic/` | Extend for reconciliation tables. |

### Existing capabilities to remove (pending slices)

| Capability | Location | Reason |
|---|---|---|
| FP&A domain logic | `finance/` (40+ subpackages) | Previous product generation |
| FP&A agents | `agents/` (20+ subpackages) | Previous product generation |
| FP&A evaluation | `finance/evaluation/` | FP&A golden datasets; protect until migrated |
| Tracing (unused) | `shared/tracing/` (9 modules) | 1 production importer |
| Unreachable utils | `shared/utils/` (11 modules) | 0 production importers |
| FinPlatform (unused) | `finplatform/` (12 modules) | Only `rbac.matrix` live |
| Python runtime (unused) | `python_runtime/` (13 modules) | Only dispatcher + handlers live |
| Historical docs | `docs/architecture/*_CONTRACT.md` (21 files) | Phase docs for excluded generations |
| FP&A docs | `docs/07-ai-runtime/`, `docs/14-platform/` | Describe deleted/obsolete generations |

---

## 8. Unresolved Decisions

| # | Decision | Options | Impact | Status |
|---|---|---|---|---|
| 1 | execution.py vs durability.py | (a) Retain execution.py as durability dep, (b) Refactor durability to be self-contained | 875 LOC, 38 tests, durability behavior | **Retain (user decision)** |
| 2 | AI eval CI | (a) Migrate `finance/evaluation/` to reconciliation, (b) Retire `ai-evals.yml` golden gate | 34 files, 2,104 LOC, CI gate | **Protect until resolved** |
| 3 | Auth strategy | (a) JWT, (b) Session-based, (c) Demo headers (dev only) | Security-critical | **Unresolved** |
| 4 | Background workers | (a) Synchronous only, (b) SQS/Temporal | Determines compose complexity | **Unresolved** (recommend sync first) |
| 5 | S3 for file storage | (a) S3-compatible, (b) Local filesystem (dev) | Determines `finance/object_store/` fate | **Unresolved** (recommend local for portfolio) |
| 6 | Observability stack | (a) Jaeger+Langfuse+Phoenix, (b) Consolidate to one, (c) stdlib logging | Compose complexity | **Unresolved** (recommend stdlib + Prometheus) |
| 7 | Mutation testing tool | (a) mutmut, (b) cosmic-ray, (c) custom | Testing infrastructure | **Unresolved** |
| 8 | Property testing library | (a) Hypothesis, (b) custom generators | Test dependency | **Recommend Hypothesis** |
| 9 | Doc consolidation scope | (a) Full restructure (190 docs), (b) Minimal | Effort | **Recommend minimal** |
| 10 | Durability for AI investigation | (a) Reuse p8 durability, (b) Retire with migration | DB schema, 179 LOC | **Defer** |

---

## 9. Summary

**What exists and is reusable:**
- Deterministic reconciliation engine (352 tests, 266 operator checks, byte-reproducible)
- LLM framework (shared/llm/, consolidated in Slice 5)
- Privacy boundary (shared/privacy/, already wired)
- Tenant auth middleware (apps/api/middleware.py)
- RLS infrastructure (database/migrations/)
- NiceGUI console (apps/api/operator_console.py)
- Alembic migrations (7, head d4e5f6a7b8c9)
- S3 adapter (finance/object_store/s3_adapter.py)
- Docker build (verified)
- Source ingestion and normalization (`finance/source_ingestion/`, P1): three
  canonical schemas, CSV + table adapters, deterministic validation, provenance

**What is missing (must be built):**
- Reconciliation persistence (tables, repository, migration)
- Reconciliation API (routes, schemas, service layer)
- Exception lifecycle (state machine, decisions, audit)
- AI investigation (endpoint, wiring, structured output)
- NiceGUI reconciliation screens
- HTTP E2E tests (Playwright)
- Real authentication (replace demo headers)

**What should be removed (pending slices):**
- ~25,000 LOC of FP&A generation (finance/, agents/ except reusable parts)
- ~5,000 LOC of unreachable shared/finplatform/python_runtime modules
- ~21 historical architecture contract docs
- Unused compose services (Temporal, Redpanda, Qdrant, etc.)

**Protected (do not touch):**
- `finance/reconciliation/` (engine, 352 tests)
- `tests/unit/reconciliation/` (all tests)
- `docs/evidence/operator-run/` (golden evidence)
- `finance/evaluation/` (CI dependency)
- `shared/llm/` (canonical LLM framework)
- `apps/api/operator_console.py` (NiceGUI)

---

*This document is the output of Task D (architecture convergence investigation). It is read-only — no production code was changed. The 8 specification files in `docs/specs/` were produced based on this evidence and the target architecture defined in the user's directives.*