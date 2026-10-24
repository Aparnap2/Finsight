# Design: CI Test Architecture — Layered, Risk-Driven Release Gates

## Context

FinSight is an internal agentic financial-operations system. Its product value is a controlled resolution loop:

```
detect → reconcile deterministically → investigate with traceable evidence
       → propose a typed resolution → enforce policy + required human approval
       → execute through an idempotent boundary → independently reread authoritative state
       → close only after verification
```

Two facts frame this design.

**The product's correctness is not a unit-level property.** A refund that is correctly computed but executed twice is wrong. A proposal that is correctly authored but approved for a different amount is wrong. A close that is correctly reached without an independent reread is wrong. The failure modes that matter are *cross-boundary*: DB transactions, third-party integrations, async execution, AI-generated proposals, approval boundaries, and partial failure. So the gate structure must be organized by *risk boundary*, not by test count.

**CI green is necessary and not sufficient.** A green suite is evidence that executed tests passed. It is not evidence that the executed set covers the risks, that the risks are enforced rather than assumed, or that a release is qualified. The gap between "green" and "qualified" is the entire subject of this design.

### Verified starting state (measured at `main` = `f68c7e4`, 2026-10-21)

| Measure | Value | How measured |
| --- | --- | --- |
| Tests collected | 3,822 | `pytest --collect-only -q` |
| Test files | 203 | `find tests -name 'test_*.py'` |
| Workflows | 6 | `ls .github/workflows/` |
| Required status checks | 5 | `gh api .../branches/main/protection` |
| Tests executed by CI | 3,677 | 3,822 minus 145 unexecuted (G1) |
| Unexecuted test files | 14 | 11 in `tests/test_python_runtime/`, plus `tests/evaluation/`, `tests/evals/llm/` |
| `hypothesis` imports / `@given` decorators | 0 / 0 | `rg "from hypothesis"`, `rg "@given"` |
| Mutation-testing harnesses | 0 | `rg "mutmut\|cosmic.ray"` |
| Load/perf harnesses | 0 | `rg "locust\|k6\|benchmark"` |
| Scheduled workflows (`schedule:`/`cron:`) | 0 | `rg "schedule:\|cron:" .github/workflows/` |
| Coverage measurement in CI | none | `rg "cov" .github/workflows/` → no matches |
| Artifacts uploaded by `ci.yml` | none | `rg -l upload-artifact .github/workflows/` → `integration.yml` only |
| Pre-existing failures on `main` | 4 | `pytest tests/test_python_runtime/test_api.py` → 401 (missing `X-Tenant-ID`/`X-Role`) |

### Per-directory test inventory (collected counts)

| Directory | Tests | CI job that runs it | Category (§2) |
| --- | --- | --- | --- |
| `tests/unit/test_domain/` | 703 | CI (fast) | 1 unit, 2 financial invariants |
| `tests/contract/` | 489 | CI (fast) | 4 provider contract, 7 policy/control |
| `tests/unit/test_finance/` | 482 | CI (fast) | 1 unit, 2 financial invariants |
| `tests/unit/domain/` | 249 | CI (fast) | 2 financial invariants, 6 workflow |
| `tests/unit/verification/` | 209 | CI (fast) | 7 policy/control |
| `tests/integration/` | 191 | Integration (PG-gated) | 3 DB integrity, 5 mocked integration |
| `tests/unit/investigation/` | 134 | CI (fast) | 1 unit |
| `tests/unit/privacy/` | 113 | CI (fast) | 8 security/privacy |
| `tests/unit/security/` | 102 | CI (fast) | 8 security/privacy |
| `tests/unit/test_platform/` | 96 | CI (fast) | 13 migration/upgrade, 8 security/privacy |
| `tests/unit/reconciliation/` | 90 | CI (fast) | 2 financial invariants |
| `tests/unit/legacy_execution/` | 86 | CI (fast) | 2 financial invariants (optional legacy) |
| `tests/unit/legacy/` | 78 | CI (fast) | 2 financial invariants (optional legacy) |
| `tests/unit/api/` | 73 | CI (fast) | 7 policy/control, 8 security/privacy |
| `tests/unit/tracing/` | 67 | CI (fast) | 15 operational |
| `tests/unit/llm/` | 64 | CI (fast) | 12 LLM evaluation |
| `tests/test_python_runtime/` | 133 | **NONE** | mixed — see G1 |
| `tests/unit/ci/` | 59 | CI (fast) | 1 unit (CI-gate self-tests) |
| `tests/ministack/` | 54 | Integration (ministack) | 4 provider contract (S3) |
| `tests/unit/detection/` | 35 | CI (fast) | 2 financial invariants |
| `tests/unit/capabilities/` | 30 | CI (fast) | 7 policy/control |
| `tests/unit/exceptions/` | 28 | CI (fast) | 2 financial invariants |
| `tests/unit/approval/` | 28 | CI (fast) | 7 policy/control |
| `tests/unit/execution/` | 27 | CI (fast) | 6 workflow/state-machine |
| `tests/unit/correlation/` | 24 | CI (fast) | 6 workflow/state-machine |
| `tests/unit/object_store/` | 23 | CI (fast) | 4 provider contract (Fake) |
| `tests/unit/stripe/` | 21 | CI (fast) | 4 provider contract |
| `tests/e2e/` | 17 | Integration (PG-gated) | 9 mocked E2E |
| `tests/unit/orchestrator/` | 17 | CI (fast) | 6 workflow/state-machine |
| `tests/unit/test_trajectory/` | 13 | CI (fast) | 12 LLM evaluation |
| `tests/unit/proposals/` | 13 | CI (fast) | 7 policy/control |
| `tests/unit/approvals/` | 13 | CI (fast) | 7 policy/control |
| `tests/evaluation/` | 12 | **NONE** | 12 LLM evaluation |
| `tests/unit/test_variance_agent/` | 10 | CI (fast) | 1 unit |
| `tests/unit/tenant_isolation/` | 10 | CI (fast) | 8 security/privacy |
| `tests/unit/test_workers/` | 7 | CI (fast) | 6 workflow/state-machine |
| `tests/unit/test_shared/` | 6 | CI (fast) | 1 unit |
| `tests/unit/test_agents/` | 6 | CI (fast) | 1 unit |
| `tests/evals/llm/` | 6 | **NONE** (manual `live_llm` only) | 12 LLM evaluation |
| `tests/failure/` | 4 | Integration (PG-gated) | 14 resilience/fault-injection |

**Duplicate-naming findings (not yet proven to be duplicated logic — flagged for the inventory slice):** `tests/unit/approval/` (28) vs `tests/unit/approvals/` (13); `tests/unit/legacy/` (78) vs `tests/unit/legacy_execution/` (86); `tests/unit/test_domain/` (703) vs `tests/unit/domain/` (249). The `test_domain`/`domain` pair in particular may be a historical naming split rather than a genuine coverage split. **The inventory slice must measure this, not assume it** — but the directory structure currently makes "which file enforces which invariant" unanswerable, which is itself the problem this design fixes.

**Non-collected scratch files:** `tests/unit/test_domain/_scratch_hyp.py` and `_scratch_polars.py` are not collected (leading underscore) and are documented as "not collected" probes. They are inventory noise and should be deleted or moved out of `tests/`, since their presence inflates the apparent property-testing footprint (`hypothesis` appears in one of them) to a reader auditing the tree.

## Goals / Non-Goals

**Goals**
- G-A Every test file is assigned to exactly one category in a machine-readable manifest, and a CI gate fails if that invariant breaks.
- G-B Every critical financial invariant, security boundary, and workflow transition names the test that enforces it, or is recorded as an explicit `GAP`.
- G-C Every category has a named gate, and every gate has a named failure semantics (block-merge / block-release / scheduled-only) and a negative control.
- G-D A release qualification is a set of artifacts referenced by run ID, not a green badge.
- G-E Infrastructure failure is distinguishable from test failure, and never reads as pass.

**Non-Goals**
- No weakening, removal, or threshold-loosening of any existing gate.
- No second test runner; no restructuring beyond the five stages.
- No live-provider test in a PR-triggered workflow.
- No change to test assertions, thresholds, or expected outcomes (except adding new tests and adding a manifest).
- No LLM-output equality assertion. Nondeterministic models are evaluated on structured-output validity, grounding, policy compliance, calibrated confidence, and rejection of invalid proposals.

## Decisions

### D1 — Categories are risk-scoped, and simulators are tools, not categories

The 15 categories below are adopted. The critical distinction the human drew is preserved verbatim in the design: **Mockoon, LocalStack, and every other simulator is a tool used by a test, never a test category itself.** A category describes *what is being verified*; a tool describes *how the dependency is stood in for*.

| # | Category | Verifies | FinSight exemplar |
| --- | --- | --- | --- |
| 1 | Unit | individual functions | Decimal normalization, currency parsing |
| 2 | Financial-domain invariants | money rules across input combinations | partial payments, duplicate payouts, refunds, rounding, split settlement |
| 3 | DB schema & integrity | persistence constraints, transaction correctness | FKs, tenant isolation, uniqueness, rollback, concurrent writes |
| 4 | Third-party contract | adapter assumptions match provider contracts | Razorpay payloads, accounting API schemas, S3 contract |
| 5 | Mocked integration | components together, controlled dependencies | API → reconciliation → DB → queue |
| 6 | Workflow / state machine | multi-step ops preserve state and recover | retry after timeout, approval expiry, worker crash, duplicate delivery |
| 7 | Policy & control | financial controls, authorization, evidence | LLM cannot authorize; approval binds exact proposal |
| 8 | Security & privacy | unauthorized access, leakage | cross-tenant, PII in logs, secret exposure, webhook signature |
| 9 | Mocked E2E | complete user-facing workflow | import → reconcile → investigate → approve → execute → verify |
| 10 | Provider sandbox | integration against a real provider test env | Razorpay Test Mode payment/refund behavior |
| 11 | Load & performance | latency and throughput limits | large batches, queue backlog, concurrent webhooks |
| 12 | LLM evaluation | probabilistic reasoning useful and constrained | classification, grounded hypotheses, unsupported-claim rejection |
| 13 | Migration & upgrade | version transitions are safe | fresh schema, upgrade from prior, rollback/roll-forward |
| 14 | Resilience & fault injection | partial failure does not corrupt financial state | DB down, provider timeout, redelivery, worker termination |
| 15 | Deployment & operational smoke | deployed system is correctly configured | health, connectivity, worker readiness, telemetry/alert delivery |

**Domain-test ownership rule.** Categories 1 and 2 overlap in surface but not in ownership: a *business-logic* test verifies a rule (e.g. "the same idempotency key is accepted once"), while a *financial-domain* test verifies the rule still yields the correct ledger and settlement result under real financial edge cases (partial + duplicate + fee-bearing + reversed). A financial invariant is owned by exactly one test file, named in the risk matrix.

**Alternative rejected:** a flat "unit/integration/e2e" pyramid. Rejected because it cannot express the risk boundaries that matter here — it makes "financial invariant" and "generic business logic" indistinguishable, and gives no way to say that category 7 (policy/control) must block a merge while category 11 (load) does not.

### D2 — Invariants are named, and every invariant names its enforcer

The financial-domain invariant set (money & arithmetic; reconciliation; financial control; ledger & audit) is written as explicit, testable statements. Each carries an ID (`INV-MONEY-01`, `INV-CTRL-03`, …) and the risk matrix (§3) maps ID → enforcing test file → CI gate. An invariant with no enforcing test is `GAP`, and a `GAP` in a critical category fails the inventory ratchet. This inverts the current state, where coverage is inferred from a test count.

**Alternative rejected:** measuring coverage by line percentage alone. Rejected because line coverage is silent about *which* risk a line serves, and FinSight's risk is in cross-boundary behaviour, not in a module's interior.

### D3 — Five stages, with a shared gate contract and a common failure semantics

```
Stage 1  PR fast gate          every PR          2–5 min   lint/type/format, unit + contract,
                                                             secret scan, fast security/tenant
                                                             isolation, inventory ratchet, workflow
                                                             integrity
Stage 2  PR integration gate   every PR          ~5–10 min  real Postgres, schema/transaction/
                                                             concurrency/rollback, provider simulation
                                                             (Mockoon/LocalStack), API + webhook
                                                             contract, queue/worker/retry/idempotency,
                                                             mocked reconciliation E2E
Stage 3  Extended validation    nightly + weekly   30–90 min full property-based + financial edge
                                                             suites, mutation testing on critical rules,
                                                             LLM eval regression, load/stress/soak,
                                                             fault injection, broader privacy suite
Stage 4  Pre-release qualify   release candidate  ~2–4 h    migration + upgrade verification, provider
                                                             sandbox (Razorpay Test Mode), full
                                                             critical-path E2E, backup/restore and
                                                             rollback/roll-forward, security +
                                                             observability + operational readiness
Stage 5  Post-deploy verify    after deploy       continuous health, worker readiness, read-only smoke,
                                                             telemetry/alert/queue-lag, credential-
                                                             separation check
```

Time targets are **design goals, not guarantees** — the actual budgets are established from CI measurements, and `docs/testing/CI_TEST_ARCHITECTURE.md` records the measured baselines once Stage 1 instrumentation lands.

**Shared gate contract.** Every job in every stage calls one script (`scripts/gate_contract.py`) that owns: reading the teed pytest log, counting passed/failed/skipped/xfailed, applying the job's skip budget, evaluating a category-specific minimum, and emitting a machine-readable JSON summary. The existing `scripts/ci_gate.py` is the proven seed of this contract; it is generalized, not replaced with a different mechanism.

**Failure semantics (normative, and the correction to today's biggest CI weakness):**

| Situation | Required result | Forbidden |
| --- | --- | --- |
| A required test fails | job **fails** | — |
| Required summary/artifact missing | job **fails** | — |
| Zero required tests executed | job **fails** | green with "0 tests ran" |
| Required evaluation skipped | job **fails** | green with a silent skip |
| Service unavailable (infrastructure) | job **fails** or reports **inconclusive** | green with skipped tests |
| Advisory check below threshold | job **fails** with the threshold printed | silent pass |

The rule is a single sentence: **a skipped test is not a passing test.** Today, `integration.yml` enforces a skip budget of 10 and `ci.yml` a budget of 5 and the ministack job a budget of 0 — good — but the *identity* of a skipped test is not asserted, only the count. A stage-2 job that skips the 10 most important tests and passes 100 trivial ones is green under the current contract. The Stage 2 design asserts **named** required tests executed, not merely a count.

**Alternative rejected:** one monolithic workflow with all stages. Rejected because it makes the PR feedback loop slow and because a nightly-only failure would then be indistinguishable from a PR failure.

### D4 — Evidence and reporting: a release is a set of artifacts

Every job retains, with an explicit retention window:

- the raw teed pytest log;
- the machine-readable gate summary JSON (counts, skip budget, enforced-test identities, verdict);
- coverage data (XML + HTML), once coverage instrumentation lands;
- evaluation results for any LLM eval job (per-dataset metrics, not just pass/fail);
- migration logs (upgrade/rollback transcripts);
- performance trends for load/soak jobs.

A release qualification is a **list of run IDs and artifact references**, not a green badge. `docs/testing/CI_TEST_ARCHITECTURE.md` holds the template.

**Immediate gap closed here:** `ci.yml` tees `pytest-unit.log` but uploads nothing. Stage 1 must upload it.

**Alternative rejected:** relying on GitHub's UI as the evidence store. Rejected because a release must be re-auditable after retention expiry, and because a UI screenshot is not machine-verifiable.

### D5 — Release policy: what blocks what

| Category | Merge-blocking | Release-blocking | Rationale |
| --- | --- | --- | --- |
| 1 unit, types, lint, static analysis | yes | yes | basic correctness |
| 2 financial-domain invariants | yes | yes | incorrect money handling is unacceptable |
| 3 DB integrity + migration checks | yes (when relevant) | yes | prevent invalid persisted state |
| 7 policy & control | yes | yes | prevent unauthorized action |
| 8 security, authorization, privacy, secret gates | yes | yes | prevent exposure and unauthorized access |
| 4 provider contract (affected integrations) | yes | yes | prevent adapter/workflow regressions |
| 5 mocked integration | yes | yes | component regressions |
| 6 workflow / state machine | yes | yes | retry/recovery correctness |
| 9 mocked E2E critical paths | yes | yes | end-to-end control flow |
| 13 migration & upgrade | no (PR) | yes | release-time transition safety |
| 12 LLM evaluation | threshold-gated | yes | gate material regressions against defined thresholds, never exact-output equality |
| 10 provider sandbox | no (PR) | yes | real external dependency, flaky by nature |
| 14 resilience / fault injection | no (PR) | yes | partial-failure safety |
| 11 load / performance | no (PR) | yes (when material) | excessive runtime per PR |
| 15 deployment smoke | n/a | deployment gate | detect deployment-specific failures |
| 17 (Stage 3) mutation testing on critical rules | no | yes | prove the critical rules can detect breakage |

**Explicitly not merge-blocking:** mutation testing, load/soak, provider sandbox, and the full property-based suite — by cost, not by importance. They are release-blocking.

**Alternative rejected:** making every category merge-blocking. Rejected because a 90-minute nightly suite on every push destroys the fast-feedback property that makes CI useful, and pushes teams toward `--no-verify`.

### D6 — The inventory ratchet is a merge-blocking gate, and it starts with the G1 repair

The first implementation slice is not a new test category — it is making the existing suite honest:

1. **Repair the 4 pre-existing failures** in `tests/test_python_runtime/test_api.py` (add the required `X-Tenant-ID`/`X-Role` headers) and **add `tests/test_python_runtime/` to a CI job.** Until a test executes, it cannot fail; that is the root cause of this gap.
2. **Wire `tests/evaluation/` and `tests/evals/llm/`** into a scheduled job (the latter under `-m live_llm`, never in PR CI).
3. **Create `docs/testing/test-inventory.json`** — every test file → category → enforcing gate. `scripts/test_inventory.py` fails the build when a file is unlisted, when a category has no enforcing gate, or when a category marked merge-blocking has no job.
4. **Delete or relocate the `_scratch_*.py` probes** so the tree reflects what actually executes.

**Alternative rejected:** adding a "test count" check to CI. Rejected — a count is not a risk map, and the count can satisfy itself by adding trivial tests. The manifest-plus-matrix ratchet can satisfy itself only by naming an enforcer.

### D7 — Provider sandbox is a Razorpay Test Mode suite, and it is not QuickBooks-shaped

The flagship path is Razorpay Test Mode + accounting records. So the provider-contract boundary is explicit:

```
FinSight adapter → provider contract → Mockoon/LocalStack simulation   (Stage 2, every PR)
FinSight adapter → Razorpay Test Mode                                 (Stage 4, release)
```

**If QuickBooks is not the selected accounting adapter, no QuickBooks-specific tests are introduced** merely to make the matrix look comprehensive. The accounting side uses the explicitly selected adapter or an explicit fixture/mock. This is the human's rule, and it is a scoping rule, not a testing shortcut: a test for an integration that will not ship is maintenance debt, not coverage.

### D8 — LLM evaluation is structured, never string-matched

Evaluate: structured-output validity, evidence grounding, policy compliance, calibrated confidence, and rejection of invalid proposals. **The critical financial safety checks stay deterministic** — no LLM output is ever compared for equality, and no financial invariant is delegated to a model.

## Risks / Trade-offs

- **More required checks → slower PRs → temptation to bypass.** → Stage 1 stays under 5 minutes by keeping Stage 2 out of the push path, and the release-blocking-only categories keep the merge gate lean. Stage 1 targets are measured, not assumed.
- **The inventory manifest rots as files move.** → The ratchet fails closed on any unlisted file, so drift is a red build, not silent decay. The manifest is generated from a declarative mapping, not hand-maintained twice.
- **Skip-budget theatre (skip 10 important tests, pass 100 trivial ones).** → Stage 2 asserts the *identity* of required tests, not only a count.
- **Nightly failures get ignored.** → Stage 3 has a defined triage path and a recorded-failure budget; repeated nightly failure blocks a release even though it never blocks a PR.
- **Sandbox flakiness (Razorpay Test Mode is an external dependency).** → Stage 4 treats sandbox failure as infrastructure-inconclusive by default and distinguishes it from a product failure, but never as a pass. Release qualification requires a green sandbox run within its validity window, not a cached pass.
- **Mutation testing cost.** → Scope it to the critical rule files only (fee calculation, approval binding, confidence threshold, close condition), not the whole tree.
- **Volume risk: 3,822 tests today, more tomorrow.** → The manifest makes the *shape* of the suite reviewable; the risk matrix keeps quality from being inferred from volume.

## Migration Plan

Plan phase (this change, no CI behaviour change): produce the taxonomy, the inventory, the risk matrix, the stage design, the evidence standard, and the release policy; validate the artifacts; approve.

Implementation phase (subsequent slices, each independently green and independently mergeable):

1. **G1 repair** — fix the 4 `test_api.py` failures; add `tests/test_python_runtime/` to CI; wire `tests/evaluation/` + `tests/evals/llm/` into a scheduled job; delete `_scratch_*.py`.
2. **Inventory ratchet** — `docs/testing/test-inventory.json` + `scripts/test_inventory.py` + its unit tests, as a Stage 1 required check.
3. **Gate contract** — generalize `scripts/ci_gate.py` into `scripts/gate_contract.py` with named required-test assertions; upload `pytest-unit.log` from `ci.yml`.
4. **Stage separation** — split workflows into independently understandable jobs; add the scheduled Stage 3 workflow; add artifact retention across all jobs.
5. **Coverage + property-based** — coverage instrumentation and artifacts; `hypothesis` property tests for monetary conservation, normalization invariance, duplicate-event idempotency.
6. **Migration-safety gate** — fresh-schema + upgrade-from-previous-schema verification as a required job; wire the outbox migration `b7e2d9f4a516`.
7. **Provider sandbox** — Razorpay Test Mode contract suite as a Stage 4 release gate.
8. **Mutation testing** — scoped to critical rule files, Stage 3.
9. **Load & fault injection** — Stage 3 throughput/backlog measurement and fault-injection scenarios.

**Rollback:** each slice is additive and independently revertible. Slice 1's CI-path addition is revertible by removing the path; slices 2–4 are revertible by removing the required check; no slice removes an existing gate, so rollback never weakens protection.

## Open Questions

- Which accounting adapter is the selected one for the flagship path (QuickBooks adapter vs explicit fixture)? This determines whether a Stage 4 accounting-sandbox job exists at all (D7).
- What is the Stage 2 minimal required-test identity set — the smallest set whose absence must fail the job? Proposed starting point: the 20 outbox tests, the tenant-isolation matrix, the money-domain conservation property, and the approval-binding cases. Needs ratification with the invariant owners.
- Does Razorpay Test Mode credential provisioning happen in CI secrets or in a staging-only environment? Affects whether the Stage 4 sandbox job can run unattended.
- Nightly failure budget: how many consecutive Stage 3 failures block a release?
