# CI Test Architecture — Layered, Risk-Driven Release Gates

**Status**: plan (design approved for review; implementation sequenced, not started)
**Baseline measured at**: `main` = `f68c7e4`
**OpenSpec change**: `openspec/changes/add-ci-test-architecture/`
**Last updated**: 2026-10-21

---

## 0. The problem this solves

FinSight's CI is green. That green is thinner than it looks.

The suite collects **3,822 tests** across 203 files. The workflows execute **3,677** of them. The required-check set is **5 job contexts**. The result is that a large, well-organized suite produces a green signal that says considerably less than the test count implies.

Four verified findings, each with a file or command that can be re-run:

**F1 — 145 collected tests never execute in any workflow.**
`tests/test_python_runtime/` (133 tests, 11 files) is not selected by `ci.yml` (which runs `tests/unit tests/contract`), not by `integration.yml` (which runs `tests/integration tests/failure tests/e2e`), not by `ai-evals.yml`, and not by the ministack job (`-m ministack`). `tests/evaluation/` (12) and `tests/evals/llm/` (6) are likewise unrun. The damage is already visible: `tests/test_python_runtime/test_api.py` has **4 failures on `main`** — the tenant middleware requires `X-Tenant-ID`/`X-Role` and the file sends neither — and nobody saw it, because nothing runs it.

> A test that does not execute cannot fail. A gate that cannot fail cannot qualify a release.

**F2 — coverage is measured as volume, not as risk.**
There is no artifact stating which test enforces which financial invariant, which security boundary, or which workflow transition. 3,822 is a number, not evidence. The invariants that matter — monetary conservation, proposal-bound approval, idempotent execution, independent post-action verification, cross-tenant isolation — are spread across 65–100 files each, but nothing records whether any one of them would catch a regression in the others' blind spots.

**F3 — six release-relevant capabilities have no gate at all.**

| Capability | Present? | Evidence |
| --- | --- | --- |
| Property-based testing | **no** | `hypothesis` not a dependency; `rg "from hypothesis" tests/` → 0; `rg "@given" tests/` → 0. The 30 textual hits are docstring prose plus two `_scratch_*.py` probes that are not collected. |
| Mutation testing | **no** | no `mutmut`, no `cosmic-ray` |
| Load / performance | **no** | no `locust`, no `k6`, no benchmark harness |
| Migration / upgrade safety | **no gate** | `tests/unit/test_platform/test_migrations.py` exists, but no workflow verifies fresh-schema build + upgrade-from-previous. The outbox migration `b7e2d9f4a516` reached `main` without CI ever applying it. |
| Provider sandbox | **no** | no Razorpay Test Mode suite exists |
| Scheduled extended validation | **no** | `rg "schedule:\|cron:" .github/workflows/` → 0 |

Plus: **no coverage measurement** (`pytest-cov` is a dependency; no workflow passes `--cov`; no `[tool.coverage]` section) and **partial evidence retention** (`integration.yml` uploads its log; `ci.yml` tees `pytest-unit.log` and uploads nothing).

**F4 — the release path is a shape, not a qualification.**
`deploy-staging.yml`, `deploy-prod.yml`, `rollback.yml` (merged `ec28cbd`) are correct fail-closed scaffolds — `workflow_dispatch` only, with `environment:` keys. They prove nothing about a deploy. There is no pre-release qualification stage, no post-deploy verification stage, and no definition of what evidence qualifies a release.

---

## 1. Test categories (the taxonomy)

Categories describe **what is verified**. Tools describe **how a dependency is stood in for**.

> **Mockoon, LocalStack, and every other simulator is a tool, not a test category.** Contract, integration, and fault-injection tests can all use Mockoon; that does not make any of them "the Mockoon category".

| # | Category | Verifies | FinSight exemplar | Merge-blocking | Release-blocking |
| --- | --- | --- | --- | --- | --- |
| 1 | Unit | individual functions/components | Decimal normalization, currency parsing, fee calc | yes | yes |
| 2 | Financial-domain invariants | money rules across input combinations | partial payments, duplicate payouts, refunds, rounding, split settlement | yes | yes |
| 3 | DB schema & integrity | persistence constraints, transaction correctness | FKs, tenant isolation, uniqueness, rollback, concurrent writes | yes (relevant) | yes |
| 4 | Third-party contract | adapter assumptions match provider contracts | Razorpay payloads, accounting schemas, S3 contract | yes (affected) | yes |
| 5 | Mocked integration | components together, controlled dependencies | API → reconciliation → DB → queue | yes | yes |
| 6 | Workflow / state machine | multi-step ops preserve state and recover | retry after timeout, approval expiry, worker crash, duplicate delivery | yes | yes |
| 7 | Policy & control | financial controls, authorization, evidence | LLM cannot authorize; approval binds exact proposal | yes | yes |
| 8 | Security & privacy | unauthorized access, leakage prevention | cross-tenant, PII in logs, secret exposure, webhook signature | yes | yes |
| 9 | Mocked E2E | complete user-facing workflow | import → reconcile → investigate → approve → execute → verify | yes | yes |
| 10 | Provider sandbox | integration against a real provider test env | Razorpay Test Mode payment/refund behavior | no | yes |
| 11 | Load & performance | latency and throughput limits | large batches, queue backlog, concurrent webhooks | no | yes (when material) |
| 12 | LLM evaluation | probabilistic reasoning useful and constrained | classification, grounded hypotheses, unsupported-claim rejection | threshold-gated | yes |
| 13 | Migration & upgrade | version transitions are safe | fresh schema, upgrade from prior, rollback/roll-forward | no | yes |
| 14 | Resilience & fault injection | partial failure does not corrupt financial state | DB down, provider timeout, redelivery, worker kill | no | yes |
| 15 | Deployment & operational smoke | deployed system is correctly configured | health, connectivity, worker readiness, telemetry/alert delivery | n/a | deployment gate |

Plus, scheduled-only: **mutation testing on critical rules** (fee calc, approval binding, confidence threshold, close condition) — release-blocking, never merge-blocking.

### Domain-test ownership

Categories 1 and 2 overlap in surface but not in ownership:

- a **business-logic** test verifies the *rule* (e.g. "the same idempotency key is accepted once");
- a **financial-domain** test verifies the rule still yields the **correct ledger and settlement result** under real financial edge cases (partial + duplicate + fee-bearing + reversed).

Each financial invariant has exactly one owning test file, named in the risk matrix.

---

## 2. Test inventory (measured at `f68c7e4`)

| Directory | Tests | Executing gate | Category |
| --- | --- | --- | --- |
| `tests/unit/test_domain/` | 703 | CI (fast) | 1, 2 |
| `tests/contract/` | 489 | CI (fast) | 4, 7 |
| `tests/unit/test_finance/` | 482 | CI (fast) | 1, 2 |
| `tests/unit/domain/` | 249 | CI (fast) | 2, 6 |
| `tests/unit/verification/` | 209 | CI (fast) | 7 |
| `tests/integration/` | 191 | Integration (PG) | 3, 5 |
| `tests/unit/investigation/` | 134 | CI (fast) | 1 |
| `tests/unit/privacy/` | 113 | CI (fast) | 8 |
| `tests/unit/security/` | 102 | CI (fast) | 8 |
| `tests/unit/test_platform/` | 96 | CI (fast) | 8, 13 |
| `tests/unit/reconciliation/` | 90 | CI (fast) | 2 |
| `tests/unit/legacy_execution/` | 86 | CI (fast) | 2 (optional legacy) |
| `tests/unit/legacy/` | 78 | CI (fast) | 2 (optional legacy) |
| `tests/unit/api/` | 73 | CI (fast) | 7, 8 |
| `tests/unit/tracing/` | 67 | CI (fast) | 15 |
| `tests/unit/llm/` | 64 | CI (fast) | 12 |
| **`tests/test_python_runtime/`** | **133** | **NONE** | mixed — F1 |
| `tests/unit/ci/` | 59 | CI (fast) | 1 (CI-gate self-tests) |
| `tests/ministack/` | 54 | Integration (ministack) | 4 (S3) |
| `tests/unit/detection/` | 35 | CI (fast) | 2 |
| `tests/unit/capabilities/` | 30 | CI (fast) | 7 |
| `tests/unit/exceptions/` | 28 | CI (fast) | 2 |
| `tests/unit/approval/` | 28 | CI (fast) | 7 |
| `tests/unit/execution/` | 27 | CI (fast) | 6 |
| `tests/unit/correlation/` | 24 | CI (fast) | 6 |
| `tests/unit/object_store/` | 23 | CI (fast) | 4 (Fake) |
| `tests/unit/stripe/` | 21 | CI (fast) | 4 |
| `tests/e2e/` | 17 | Integration (PG) | 9 |
| `tests/unit/orchestrator/` | 17 | CI (fast) | 6 |
| `tests/unit/test_trajectory/` | 13 | CI (fast) | 12 |
| `tests/unit/proposals/` | 13 | CI (fast) | 7 |
| `tests/unit/approvals/` | 13 | CI (fast) | 7 |
| **`tests/evaluation/`** | **12** | **NONE** | 12 |
| `tests/unit/test_variance_agent/` | 10 | CI (fast) | 1 |
| `tests/unit/tenant_isolation/` | 10 | CI (fast) | 8 |
| `tests/unit/test_workers/` | 7 | CI (fast) | 6 |
| `tests/unit/test_shared/` | 6 | CI (fast) | 1 |
| `tests/unit/test_agents/` | 6 | CI (fast) | 1 |
| **`tests/evals/llm/`** | **6** | **NONE** (manual `live_llm` only) | 12 |
| `tests/failure/` | 4 | Integration (PG) | 14 |

### Defect classes this inventory exposes

| Class | Instances | Detail |
| --- | --- | --- |
| **Not executed** | 14 files / 145 tests | `tests/test_python_runtime/` (11 files), `tests/evaluation/`, `tests/evals/llm/` |
| **Possibly duplicated** | 3 pairs | `test_domain`/`domain` (703 vs 249), `approval`/`approvals` (28 vs 13), `legacy`/`legacy_execution` (78 vs 86) — to be *measured*, not assumed |
| **Not collected** | 2 files | `tests/unit/test_domain/_scratch_hyp.py`, `_scratch_polars.py` — inflate the apparent property-testing footprint |
| **Unowned category** | 8 of 15 | categories 10, 11, 13 (as a gate), 14 (as a gate), 15 (as a gate), plus mutation testing and provider sandbox |

---

## 3. Risk-to-test matrix (shape — to be populated in the inventory slice)

The matrix is the artifact that replaces "3,822 tests" as the answer to "are we covered?". Each row: invariant ID → statement → enforcing test file → CI gate. Missing enforcers are `GAP`, and a `GAP` in a merge-blocking category fails the ratchet.

### 3.1 Money and arithmetic

| ID | Invariant | Enforcer | Gate | Status |
| --- | --- | --- | --- | --- |
| INV-MONEY-01 | Monetary arithmetic uses `Decimal`, never binary float; no value created or lost in normalization | `tests/unit/test_finance/` + `tests/unit/api/test_decimal_layer.py` | CI (fast) | covered (owner TBD) |
| INV-MONEY-02 | `gross − fees − refunds − adjustments = net` for every settlement shape | — | — | **GAP — no property-based enforcement** |
| INV-MONEY-03 | Currency-specific precision and rounding; no currency mismatch silently summed | `tests/unit/test_finance/` | CI (fast) | covered (owner TBD) |
| INV-MONEY-04 | Fees, taxes, partial settlements handled per policy | `tests/unit/test_finance/` | CI (fast) | covered (owner TBD) |

### 3.2 Reconciliation

| ID | Invariant | Enforcer | Gate | Status |
| --- | --- | --- | --- | --- |
| INV-RECON-01 | Exact, partial, many-to-one, one-to-many matches resolve deterministically | `tests/unit/reconciliation/` | CI (fast) | covered (owner TBD) |
| INV-RECON-02 | Duplicate invoices, payouts, refunds, bank rows are detected, not double-counted | `tests/unit/reconciliation/` | CI (fast) | covered (owner TBD) |
| INV-RECON-03 | Fee/timing differences distinguished from genuine discrepancies | `tests/unit/reconciliation/` | CI (fast) | covered (owner TBD) |
| INV-RECON-04 | Unmatched, stale, reversed, out-of-order transactions handled explicitly | `tests/unit/domain/` | CI (fast) | covered (owner TBD) |
| INV-RECON-05 | Every auto-reconciliation has a reproducible explanation and evidence | `tests/unit/reconciliation/` + `tests/unit/verification/` | CI (fast) | covered (owner TBD) |

### 3.3 Financial control

| ID | Invariant | Enforcer | Gate | Status |
| --- | --- | --- | --- | --- |
| INV-CTRL-01 | An LLM can propose a resolution but cannot grant itself authorization | `tests/unit/approval/`, `tests/unit/capabilities/`, `tests/unit/security/` | CI (fast) | covered (owner TBD) |
| INV-CTRL-02 | Approval is bound to the exact proposal, amount, target, and policy version | `tests/unit/approval/` + `tests/unit/approvals/` | CI (fast) | covered (owner TBD) |
| INV-CTRL-03 | A changed proposal invalidates a stale approval | `tests/unit/approval/` | CI (fast) | covered (owner TBD) |
| INV-CTRL-04 | Retrying an action cannot cause a duplicate refund or adjustment | `tests/unit/execution/`, `tests/unit/idempotency` (65 files match "idempoten") | CI (fast) + Integration | covered (owner TBD) |
| INV-CTRL-05 | An HTTP success response alone does not prove the financial operation completed | `tests/unit/verification/`, `tests/unit/execution/` | CI (fast) | covered (owner TBD) |
| INV-CTRL-06 | A discrepancy cannot close without independent verification against authoritative state | `tests/unit/verification/` (209), `tests/unit/domain/test_close_gate.py` | CI (fast) | covered (owner TBD) |

### 3.4 Ledger and audit

| ID | Invariant | Enforcer | Gate | Status |
| --- | --- | --- | --- | --- |
| INV-AUDIT-01 | Ledger entries immutable, or corrected only by explicit compensating entries | `tests/unit/domain/` (21 files match "immutab") | CI (fast) | covered (owner TBD) |
| INV-AUDIT-02 | Every material action carries actor, timestamp, evidence, decision, correlation IDs | `tests/unit/correlation/`, `tests/unit/verification/` | CI (fast) | covered (owner TBD) |
| INV-AUDIT-03 | Concurrent workers cannot create conflicting final resolutions | `tests/unit/approvals/test_races.py` | CI (fast) | covered (owner TBD) |
| INV-AUDIT-04 | A failed transaction leaves no partially committed financial state | `tests/integration/`, `tests/failure/` | Integration (PG) | covered (owner TBD) |
| INV-AUDIT-05 | Publisher/consumer claim protocol is atomic and fenced (no double-claim, no fenced success) | `tests/integration/test_webhook_outbox.py` (20) | Integration (PG) | covered — **owner confirmed** |

### 3.5 Security and privacy boundaries

| ID | Invariant | Enforcer | Gate | Status |
| --- | --- | --- | --- | --- |
| INV-SEC-01 | Cross-tenant access denied at the application and DB layers | `tests/unit/tenant_isolation/` (10), `tests/integration/` RLS suites | CI (fast) + Integration | covered (owner TBD) |
| INV-SEC-02 | Webhook signatures verified; one-byte mutation rejected | `tests/unit/stripe/test_stripe_signature.py` | CI (fast) | covered (owner TBD) |
| INV-SEC-03 | No secret material in logs, reports, or committed files | `scripts/secret_gate.py` + `tests/unit/ci/` | CI (fast) | covered — **owner confirmed** |
| INV-SEC-04 | PII absent from logs, error paths, telemetry | `tests/unit/privacy/` (113), 14 files match "pii" | CI (fast) | covered (owner TBD) — **see APA-86** |
| INV-SEC-05 | Tenant middleware rejects callers without `X-Tenant-ID`/`X-Role` | `tests/test_python_runtime/test_api.py` | **NONE** | **GAP — F1** |

### 3.6 Workflow transitions

| ID | Invariant | Enforcer | Gate | Status |
| --- | --- | --- | --- | --- |
| INV-WF-01 | 11-stage loop preserves state across every transition; invalid transitions rejected | `tests/unit/domain/test_invalid_transitions.py`, `tests/unit/domain/test_lifecycle.py` | CI (fast) | covered (owner TBD) |
| INV-WF-02 | Retry after timeout converges; expired leases become claimable; attempts bounded | `tests/unit/legacy_execution/`, `tests/integration/test_webhook_outbox.py` | CI (fast) + Integration | covered (owner TBD) |
| INV-WF-03 | Worker crash mid-flight leaves no partial state; replacement worker recovers | `tests/unit/test_workers/`, `tests/failure/` | CI (fast) + Integration | covered (owner TBD) |
| INV-WF-04 | Duplicate event delivery is idempotent (same execution, one effect) | `tests/integration/test_webhook_outbox.py` | Integration (PG) | covered — **owner confirmed** |
| INV-WF-05 | Provider timeout *after* an action was sent: the system determines whether the action happened before re-executing | — | — | **GAP** |

### 3.7 Migration and upgrade

| ID | Invariant | Enforcer | Gate | Status |
| --- | --- | --- | --- | --- |
| INV-MIG-01 | Fresh schema creation succeeds from empty | `tests/unit/test_platform/test_migrations.py` | CI (fast) | partial — **no dedicated gate** |
| INV-MIG-02 | Upgrade from the previous supported schema succeeds | — | — | **GAP** |
| INV-MIG-03 | Rollback / roll-forward is defined and verified | — | — | **GAP** |
| INV-MIG-04 | Outbox migration `b7e2d9f4a516` applies cleanly and is reversible | — | — | **GAP — never applied in CI** |

**Summary: 6 verified GAPs** (INV-MONEY-02, INV-SEC-05, INV-WF-05, INV-MIG-02/03/04) plus 3 partials (INV-MIG-01 and the migration-safety category as a whole). This is the concrete payoff of the matrix: without it, "3,822 tests" and "well covered" were indistinguishable claims.

---

## 4. CI stage design

```
Stage 1  PR fast gate          every PR        2–5 min    lint/type/format, unit + contract,
                                                           secret scan, fast security/tenant
                                                           isolation, inventory ratchet,
                                                           workflow integrity
Stage 2  PR integration gate   every PR        5–10 min   real Postgres, schema/transaction/
                                                           concurrency/rollback, provider simulation,
                                                           API + webhook contract, queue/worker/
                                                           retry/idempotency, mocked reconciliation E2E
Stage 3  Extended validation    nightly/weekly  30–90 min  full property + financial edge suites,
                                                           mutation testing on critical rules, LLM eval
                                                           regression, load/stress/soak, fault injection,
                                                           broader privacy suite
Stage 4  Pre-release qualify   release cand.   2–4 h      migration + upgrade verification, Razorpay
                                                           Test Mode sandbox, full critical-path E2E,
                                                           backup/restore + rollback/roll-forward,
                                                           security + observability + ops readiness
Stage 5  Post-deploy verify    after deploy    continuous  health, worker readiness, read-only smoke,
                                                           telemetry/alert/queue-lag, credential separation
```

Time figures are **design goals, not guarantees**; real budgets come from CI measurement, and the measured baselines are recorded here once Stage 1 instrumentation lands.

### Shared gate contract

Every job calls one script (`scripts/gate_contract.py`, generalizing the existing `scripts/ci_gate.py`) that owns: log parsing, passed/failed/skipped/xfailed counts, the job's skip budget, **named** required-test assertions, and emission of a machine-readable JSON summary.

### Failure semantics (normative)

| Situation | Required result | Forbidden |
| --- | --- | --- |
| Required test fails | **fail** | — |
| Required summary/artifact missing | **fail** | — |
| Zero required tests executed | **fail** | green with "0 tests ran" |
| Required evaluation skipped | **fail** | green with a silent skip |
| Required service unavailable | **fail** or **inconclusive** | green with skipped tests |
| Advisory check below threshold | **fail**, threshold printed | silent pass |

**A skipped test is not a passing test.** The current `ci_gate.py` enforces skip *counts* (5 in CI, 10 in integration, 0 in ministack) but not skip *identity* — so a job could skip the 10 most important tests and pass 100 trivial ones and still be green. Stage 2 asserts the identity of required tests.

### Immediate structural gap

`ci.yml` tees `pytest-unit.log` and uploads nothing; `integration.yml` uploads its log. Stage 1 must upload, with an explicit retention window.

---

## 5. Evidence and reporting

Every job retains: the raw teed log, the machine-readable gate summary, coverage data (once instrumented), evaluation results (per-dataset metrics, not pass/fail), migration logs, and performance data.

A release qualification is a **list of run IDs and artifact references** — not a green badge. A badge is neither re-auditable after retention expiry nor machine-verifiable.

Template:

```
Release qualification
  commit:              <sha>
  Stage 1 (PR fast):        run <id>  — artifacts: pytest-unit.log, gate-summary.json, coverage.xml
  Stage 2 (PR integration): run <id>  — artifacts: pytest-integration.log, gate-summary.json, migration.log
  Stage 3 (scheduled):      run <id>  — artifacts: property-summary.json, mutation-report.json, load-baseline.json
  Stage 4 (pre-release):    run <id>  — artifacts: sandbox-contract-report.json, upgrade-transcript.log, rollback-transcript.log
  Stage 5 (post-deploy):    run <id>  — artifacts: health-smoke.json, queue-lag.png, alert-delivery.json
  unexecuted test files:    <count> (must be 0)
  open GAPs in blocking categories: <count> (must be 0)
```

---

## 6. Release policy

| Category | Merge | Release | Why |
| --- | --- | --- | --- |
| 1 unit, types, lint, static analysis | block | block | basic correctness |
| 2 financial-domain invariants | block | block | incorrect money handling is unacceptable |
| 3 DB integrity + migration checks | block (relevant) | block | prevent invalid persisted state |
| 7 policy & control | block | block | prevent unauthorized action |
| 8 security, authorization, privacy, secret gates | block | block | prevent exposure and unauthorized access |
| 4 provider contract (affected) | block | block | prevent adapter/workflow regressions |
| 5 mocked integration | block | block | component regressions |
| 6 workflow / state machine | block | block | retry/recovery correctness |
| 9 mocked E2E critical paths | block | block | end-to-end control flow |
| 12 LLM evaluation | threshold-gated | block | material regressions only — never exact-output equality |
| 13 migration & upgrade | — | block | release-time transition safety |
| 10 provider sandbox | — | block | real external dependency, flaky by nature |
| 14 resilience / fault injection | — | block | partial-failure safety |
| 11 load / performance | — | block (when material) | runtime cost per PR |
| 15 deployment smoke | — | deployment gate | deployment-specific failures |
| mutation testing (critical rules) | — | block | prove critical rules can detect breakage |

**A real regression fails the gate. An infrastructure failure yields an explicit failed or inconclusive result — never a silently skipped green.**

---

## 7. Provider boundary

```
FinSight adapter → provider contract → Mockoon / LocalStack simulation   (Stage 2, every PR)
FinSight adapter → Razorpay Test Mode                                 (Stage 4, release)
```

A simulated contract suite is **not** evidence of real-provider compatibility.

**Scope discipline:** if the accounting side of the flagship path is a fixture rather than a named external integration, no tests are written for a different external accounting provider merely to make the matrix look comprehensive. A test for an integration that will not ship is maintenance debt, not coverage.

---

## 8. Implementation sequence

| Slice | Content | Gate impact |
| --- | --- | --- |
| 1 | **G1 repair** — fix the 4 `test_api.py` failures; add `tests/test_python_runtime/` to CI; wire `tests/evaluation/` + `tests/evals/llm/`; delete `_scratch_*.py` | new paths added, none removed |
| 2 | Inventory ratchet (`test-inventory.json` + `scripts/test_inventory.py` + its own unit tests) | new required check |
| 3 | Shared gate contract + named required-test assertions + artifact retention | new required check |
| 4 | Stage separation + scheduled Stage 3 workflow + `concurrency` everywhere | restructure, no gate weakened |
| 5 | Coverage instrumentation + `hypothesis` property tests | new artifacts, new tests |
| 6 | Migration-safety gate (fresh schema + upgrade + rollback) | new required job |
| 7 | Razorpay Test Mode sandbox suite | new Stage 4 gate |
| 8 | Mutation testing on critical rules | new Stage 3 job |
| 9 | Load & fault injection | new Stage 3 job |

Each slice is additive, independently green, and independently revertible. **No slice removes an existing gate, so rollback never weakens protection.**

Every slice's acceptance requires a **negative control** — a run where the gate is deliberately broken and the job goes RED — because a gate observed only in green has not been demonstrated to fail closed.

---

## 9. Open questions

1. Which accounting adapter is selected for the flagship path (QuickBooks adapter vs explicit fixture)? This determines whether a Stage 4 accounting-sandbox job exists at all.
2. What is the Stage 2 minimal required-test identity set? Proposed start: the 20 outbox tests, the tenant-isolation matrix, the money-conservation property, the approval-binding cases. Needs ratification by invariant owners.
3. Razorpay Test Mode credentials in CI secrets or a staging-only environment? Determines whether the Stage 4 sandbox job can run unattended.
4. Nightly failure budget — how many consecutive Stage 3 failures block a release?
