# FinSight Test Quality Review

**Version:** 1.0 (Task D deliverable)
**Status:** Read-only investigation
**Date:** 2026-11-22

---

## 1. Test Inventory

| Tier | Directory | Collected | CI Gate | Notes |
|---|---|---|---|---|
| Unit (finance) | `tests/unit/test_finance/` | ~1,200 | Fast (every PR) | Engine, models, allocation, normalization |
| Unit (reconciliation) | `tests/unit/reconciliation/` | 352 | Fast (every PR) | Engine, workflow, operator report, contract, golden evidence, boundary |
| Unit (agents) | `tests/unit/test_agents/` | ~400 | Fast (every PR) | Agent nodes, reasoning, privacy |
| Unit (other) | `tests/unit/` | ~1,000 | Fast (every PR) | LLM, validation, privacy, correlation, etc. |
| Contract | `tests/contract/` | ~165 (p8) + golden | Fast (every PR) | p8 contract red tests, golden dataset |
| Integration | `tests/integration/` | ~50 | PG-gated (docker compose) | API, persistence, security, AI, observability |
| Failure | `tests/failure/` | ~20 | PG-gated | Failure injection |
| E2E | `tests/e2e/` | ~5 | PG-gated | Browser-level (Playwright) |
| Eval support | `tests/eval_support/` | 0 (not collected) | Manual | LLM quality runner |
| Ministack | `tests/ministack/` | ~10 | PG-gated (LocalStack) | S3 contract tests |

**Total collected:** ~3,805 (after slice 5)

---

## 2. Test Quality Assessment

### Strengths

| Area | Assessment | Evidence |
|---|---|---|
| Reconciliation engine | **Strong** | 352 tests; independent assertions (111 contract tests read engine outputs, not operator_report._invariants); 40 generated allocations (property-based sweep); byte-reproducible golden evidence; mutation-prone invariants |
| Financial contract | **Strong** | 111 tests asserting invariants A-H independently; permutation invariance; provenance verification |
| LLM provider seam | **Strong** | Structured output validation, fake/replay providers, privacy boundary routing |
| Privacy boundary | **Strong** | 5 integration points tested with PII-bearing inputs; spy-based verification |
| Golden evidence | **Strong** | Byte-identical report.md/report.json/run.json across runs |

### Weaknesses

| Area | Assessment | Evidence |
|---|---|---|
| Mutation testing | **Absent** | No mutation testing framework or known mutations |
| Property-based testing (Hypothesis) | **Absent** | Generated sweep uses `random.Random`, not Hypothesis |
| Metamorphic testing | **Partial** | Permutation invariance tested for invoices/charges, but not systematically for all transformations |
| Boundary value testing | **Partial** | Some boundary tests (zero amounts, empty files) but not comprehensive |
| Failure injection | **Partial** | Some failure tests exist but no DB disconnect, timeout, or crash recovery tests for reconciliation |
| Implementation coupling | **Present** | Some tests import private helpers or assert internal call order |
| Tautological assertions | **Mitigated** | Removed in slice 4a (test_f2 should_retry); remaining tests need review |
| Weak assertions (`result is not None`) | **Present** | Need systematic review |
| Test count inflation | **Mitigated** | 60 orphaned tests removed across slices 1-4a |

### Anti-patterns identified

| Anti-pattern | Location | Status |
|---|---|---|
| Tautological assertion (`should_retry` using same logic) | `test_f2_provider_fault_matrix.py` (deleted in 4a) | Removed |
| Implementation coupling (importing `_valid_structured` from test module) | `test_adversarial_system.py` test_06 (removed in 4a) | Removed |
| Weak assertions (`result is not None`) | Various test files | Need review |
| Excessive mocking | Some integration tests mock DB, engine, provider, repository together | Need review |
| Static happy path | Many tests use single hardcoded invoice/charge | Need property-based expansion |

### Missing test categories

| Category | Current | Needed |
|---|---|---|
| Mutation testing | 0 | Targeted mutations for financial invariants |
| Property-based (Hypothesis) | 0 | Allocation conservation, permutation invariance, replay determinism |
| Metamorphic | 4 | Systematic: reorder, add unrelated, replay, repeat import |
| Boundary values | Partial | Zero, negative, extreme amounts; empty files; missing columns |
| Failure injection | Partial | DB disconnect, timeout, crash, concurrent requests |
| Security | Partial | Cross-tenant, authorization, injection, path traversal |
| E2E (Playwright) | 0 | Critical user journeys (upload → reconcile → export) |

---

## 3. Test Dependency on Removable Modules

| Test file | Depends on | Removable? | Notes |
|---|---|---|---|
| `tests/unit/reconciliation/*` | `finance/reconciliation/` | **No** (protected) | Product core |
| `tests/contract/test_p8_01_*` | `agents/p8_runtime/contract.py` | **No** (retained) | Budget primitive |
| `tests/contract/test_p8_03_*` | `agents/p8_runtime/durability.py` | **No** (deferred) | DB-backed |
| `tests/contract/test_p8_05_*` | `agents/p8_runtime/contract.py` | **No** (retained) | Decision result |
| `tests/integration/test_p8_runtime_to_p7.py` | `agents/p8_runtime/execution.py` | Retained (4a) | Restored (execution retained) |
| `tests/integration/test_p8_postgres_durability.py` | `agents/p8_runtime/durability.py` | DEFER | DB-backed |
| `tests/integration/test_observability.py` | `agents/p8_runtime/contract.py` (Budget) | **No** (retained) | Budget primitive |
| `tests/unit/llm/test_decision_transport.py` | `agents/p8_runtime/contract.py` | **No** (retained) | Contract |
| `tests/unit/privacy/test_llm_path_wiring.py` | `shared/llm/` (migrated in slice 5) | **No** (canonical) | LLM framework |
| `tests/unit/test_finance/test_evaluation_llm_compliance.py` | `finance/reasoning/llm_boundary.py` (duck-typed) | DEFER | Higher-level abstraction |
| `tests/contract/test_p7_08_control_plane_integration_red.py` | `docs/architecture/*_CONTRACT.md` | **No** (still cited) | Archive after refs updated |
| `tests/unit/approval/test_approval.py` | `docs/architecture/*_CONTRACT.md` | **No** (still cited) | Archive after refs updated |
| `tests/unit/correlation/test_correlation.py` | `docs/architecture/*_CONTRACT.md` | **No** (still cited) | Archive after refs updated |

---

## 4. Recommendations

1. **Apply Hypothesis** to allocation conservation, permutation invariance, replay determinism. Add to `tests/unit/reconciliation/` as new test files (not modifications to existing).
2. **Create mutation test suite** for financial invariants. Target: wrong operator, omitted fee, duplicate allocation, missing refund, currency mismatch, premature settlement, tenant filter bypass. Use `mutmut` or `cosmic-ray`.
3. **Review all remaining tests** for implementation coupling before deleting more code. Use the test review protocol (identify behavior, determine obsolescence, preserve useful assertions).
4. **Never delete tests** solely because their production module is unreachable. Establish whether they protect reusable contracts first.
5. **Add property-based tests** to the reconciliation contract (currently uses `random.Random` sweep; upgrade to Hypothesis).
6. **Add metamorphic tests** systematically: reorder invoices, reorder charges, reorder bank rows, add unrelated records, replay identical inputs.
7. **Add failure-injection tests** for DB disconnect, timeout, crash recovery, concurrent requests (P6 scope).
8. **Add mutation testing to CI** as a scheduled (not per-PR) gate for financial invariants.

---

## 5. Testing Standard Integration

The testing standard (added to `AGENTS.md` and `CONTRIBUTING.md` in commit `0aab59a`) should be applied to:
- All new tests in P1-P7 (reconciliation API, persistence, exception lifecycle, AI investigation, UI, E2E).
- Existing test review during deslop slices 6-10.
- Mutation testing setup (targeted, not percentage-optimized).

**Do not launch a massive test rewrite.** First expose weak tests in areas being touched, then progressively strengthen.