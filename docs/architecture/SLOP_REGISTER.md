# FinSight Slop Register

**Version:** 1.0 (Task D deliverable)
**Status:** Read-only investigation
**Date:** 2026-11-22

---

## 1. Dead Code

| ID | Location | LOC | Evidence | Impact | Priority | Action |
|---|---|---|---|---|---|---|
| DC-01 | `finance/` (40+ subpackages excluding reconciliation/) | ~25,000 | 0 production importers for most; FP&A product generation | High maintenance burden, confusion | P1 | Remove in slices 7-8 |
| DC-02 | `agents/` (20+ subpackages excluding p8_runtime) | ~10,000 | 0 production importers for most; FP&A/AI platform generation | High maintenance burden | P1 | Remove in slices 7-8 |
| DC-03 | `shared/utils/` (11 unreachable modules) | 1,642 | 0 production importers | Medium | P2 (slice 6) | Remove unreachable |
| DC-04 | `shared/tracing/` (9 modules) | 1,895 | 1 production importer | Medium | P2 (slice 6) | Assess observability needs |
| DC-05 | `finplatform/` (12 of 13 modules) | ~250 | Only `rbac.matrix` live | Low | P3 (slice 7) | Remove unused |
| DC-06 | `python_runtime/` (13 of 21 modules) | ~590 | Only dispatcher + handlers live | Low | P3 (slice 6) | Remove unreachable |
| DC-07 | `finance/legacy/`, `finance/legacy_execution/` | ~2,020 | 0 production importers (transport.py imports object_store) | Medium | P1 (slice 8) | Remove |
| DC-08 | `finance/llm/` (empty stub) | 10 | Docstring only | Low | P3 | Remove |
| DC-09 | `finance/execution/` (trivial) | 26 | 0 consumers | Low | P3 | Remove |
| DC-10 | Empty subpackages (`finance/driver_engine/`, `forecast_engine/`, `kpi_engine/`, `recommendation_engine/`, `scenario_engine/`) | 0 | Empty `__init__.py` | Low | P3 | Remove |

## 2. Duplicate Code

| ID | Category | Implementations | Canonical | Status |
|---|---|---|---|---|
| DP-01 | LLM clients | `shared/utils/llm_client.py` vs `shared/llm/` | `shared/llm/` | **RESOLVED** (Slice 5) |
| DP-02 | Tracing | `shared/tracing/` (9 modules) vs `shared/tracing/observability.py` | TBD (Slice 6) | Pending investigation |
| DP-03 | Financial types | `finance/reconciliation/models.py` vs `finance/domain/` | `finance/reconciliation/models.py` | Remove finance/domain/ (slice 8) |
| DP-04 | Execution | `finance/execution/` vs `finance/legacy_execution/` | TBD | Assess (slice 8) |
| DP-05 | Auth | `finplatform/rbac/matrix.py` vs `finplatform/abac/` | `finplatform/rbac/matrix.py` | Remove abac (slice 7) |

## 3. Abstraction Slop

| ID | Location | Issue | Impact | Priority |
|---|---|---|---|---|
| AS-01 | `finance/llm/__init__.py` | Empty stub with docstring only | Low | P3 |
| AS-02 | `agents/p8_runtime/` | Provider-neutral runtime with no production consumer (except contract.py) | Medium | P2 (slice 4b) |
| AS-03 | `shared/tracing/` | 9 modules, 1 production importer | Medium | P2 (slice 6) |
| AS-04 | `finplatform/` | 12 of 13 modules are 1-line stubs | Low | P3 (slice 7) |

**Note:** Financial provenance, explicit state transitions, and tenant isolation are necessary complexity, not candidates for simplification.

## 4. Architecture Slop

| ID | Issue | Evidence | Impact | Priority |
|---|---|---|---|---|
| AR-01 | FP&A product generation still present | `finance/` (40+ subpackages), `agents/` (20+ subpackages) | High confusion, 35K+ LOC | P1 |
| AR-02 | Four competing product definitions | PRD.md, FinSight_PRD_v1.md, Technical Architecture, IMPLEMENTATION_PLAN.md (archived) | Conflicting scope | Done (archived) |
| AR-03 | Two LLM implementations | `shared/utils/llm_client.py` vs `shared/llm/` | RESOLVED (Slice 5) | Done |
| AR-04 | Two UI generations | Next.js (deleted) vs NiceGUI (canonical) | RESOLVED (Slice 2) | Done |

## 5. Dependency Slop

| ID | Issue | Evidence | Impact | Priority |
|---|---|---|---|---|
| DS-01 | Unused compose services | Temporal, Redpanda, Qdrant, Redis, Jaeger, Langfuse, Phoenix, Litellm in `docker-compose.yml` | Medium (compose complexity) | P3 |
| DS-02 | Test-only AWS config | `shared/aws/config.py` (MiniStack) | Low | DEFER |
| DS-03 | No ML dependencies (correct) | pyproject.toml has no scikit-learn, XGBoost, etc. | None (correct state) | N/A |

## 6. Test Slop

| ID | Issue | Evidence | Impact | Priority |
|---|---|---|---|---|
| TS-01 | Pre-existing broken test (removed in 4a) | `test_adversarial_system.py` test_06 (AttributeError) | Low (removed) | Done |
| TS-02 | Tautological assertions (removed in 4a) | `test_f2_provider_fault_matrix.py` (should_retry using same logic) | Low (removed) | Done |
| TS-03 | No mutation testing | Financial invariants have no mutation suite | Medium (testing gap) | P2 |
| TS-04 | No property-based testing library | Generated sweep uses `random.Random`, not Hypothesis | Medium (testing gap) | P2 |
| TS-05 | Implementation-coupled tests | Some tests import private helpers | Medium | P2 (review during slices) |
| TS-06 | Weak assertions (`result is not None`) | Various test files | Medium | P2 (review) |

## 7. Documentation Slop

| ID | Issue | Evidence | Impact | Priority |
|---|---|---|---|---|
| DS-01 | 21 `docs/architecture/*_CONTRACT.md` files | Still cited by 3 test files | Medium | P3 (slice 9) |
| DS-02 | FP&A docs describe deleted generations | `docs/07-ai-runtime/`, `docs/14-platform/` | Medium confusion | P3 (slice 9) |
| DS-03 | Broken references to deleted modules | `docs/11-data-contracts/` references `finance/data_contracts/` (doesn't exist) | Low | P3 (slice 9) |
| DS-04 | Duplicate product definitions (archived) | `docs/archive/` contains 7 historical docs | Low (already archived) | Done |
| DS-05 | `finance/llm/__init__.py` referenced deleted `shared.utils.llm_client` | Fixed in slice 5 | Low | Done |

## 8. Configuration Slop

| ID | Issue | Evidence | Impact | Priority |
|---|---|---|---|---|
| CS-01 | `DATABASE_URL` env var | Read by nothing | Low | P3 |
| CS-02 | Unused compose services | Temporal, Redpanda, Qdrant, Redis, Jaeger, Langfuse, Phoenix, Litellm | Medium | P3 |

## 9. CI Slop

| ID | Issue | Evidence | Impact | Priority |
|---|---|---|---|---|
| CI-01 | `ai-evals.yml` uses FP&A evaluation code | `finance/evaluation/` is FP&A generation | Medium (protect until migrated) | P3 |
| CI-02 | Multiple compose files | `docker-compose.yml` (dev), `docker-compose.staging.yml`, `docker-compose.test.yml`, `docker-compose.ministack.yml`, `docker-compose.override.yml`, `docker-compose.langfuse.yml`, `docker-compose.phoenix.yml` | Medium | P3 |

## 10. Data Slop

| ID | Issue | Evidence | Impact | Priority |
|---|---|---|---|---|
| DT-01 | p8 durability tables in migration chain | `c9d5e7f1a204` creates p8_run_states, p8_run_audit | Low (deferred) | P3 (slice 4b) |
| DT-02 | No reconciliation tables | No DB schema for runs/matches/exceptions | High (product gap) | P1 (P2) |

## 11. Observability Slop

| ID | Issue | Evidence | Impact | Priority |
|---|---|---|---|---|
| OB-01 | Multiple tracing implementations | `shared/tracing/` (9 modules) | Medium | P2 (slice 6) |
| OB-02 | Unused metrics/instrumentation | Various | Low | P3 |

## 12. Naming Slop

| ID | Issue | Evidence | Impact | Priority |
|---|---|---|---|---|
| NM-01 | "execution" used for both finance execution and p8 execution | Various | Low confusion | P3 |
| NM-02 | "contracts" package (deleted) vs "data contracts" (planned) | `docs/11-data-contracts/` | Low | Done (contracts/ deleted) |

---

## Summary

**Total slop findings:** ~40 (across 12 categories)
**Already resolved:** ~10 (slices 1-5)
**Remaining:** ~30 (mostly FP&A generation removal, pending slices 6-10)

**Priority order for remaining slop:**
1. FP&A generation removal (slices 7-8) — highest impact
2. Tracing/utilities consolidation (slice 6) — medium impact
3. Documentation consolidation (slice 9) — medium impact
4. Final boundary verification (slice 10) — low impact

**Key principle:** Slop removal should not block productization. Only remove slop that blocks P1/P2 (e.g., LLM consolidation for P4). Everything else can run in parallel.