# Proposal: CI Test Architecture — Layered, Risk-Driven Release Gates

## Why

FinSight's CI is green, and that green is thinner than it looks. The suite collects **3,822 tests** across 203 files, but the workflows execute only a subset, and the required-check set enforces **5 job contexts** that mostly collapse to "lint + unit/contract" and "integration".

Three concrete, verified gaps make the current green insufficient to qualify a financial-resolution release:

**G1 — 145 collected tests never execute in any workflow.** `tests/test_python_runtime/` (133 tests, 11 files) is not run by `ci.yml` (which runs `tests/unit tests/contract`), not by `integration.yml` (which runs `tests/integration tests/failure tests/e2e`), not by `ai-evals.yml`, and not by the ministack job (`-m ministack`). `tests/evaluation/test_llm_quality_regression.py` (12 tests) and `tests/evals/llm/` (6 tests) are likewise unrun. The consequence is already visible: `tests/test_python_runtime/test_api.py` has **4 failures on `main`** — the tenant middleware requires `X-Tenant-ID`/`X-Role` and the test file sends neither — and nobody saw it, because nothing runs that file. A suite that does not execute cannot fail; a gate that cannot fail cannot qualify a release.

**G2 — no risk-to-test mapping exists, so coverage is inferred from test count.** 3,822 tests is a number, not evidence. There is no artifact anywhere in the repo that states which test enforces which financial invariant, which security boundary, or which workflow transition. Coverage of the *count* is measured; coverage of the *risk* is assumed. The invariants that matter most — monetary conservation, proposal-bound approval, idempotent execution, independent post-action verification, cross-tenant isolation — appear across 65–100 test files each, but nothing records whether any single one of them would catch a regression in the others' blind spots.

**G3 — release-critical capabilities have no gate at all.** Against the 15-category taxonomy:

- **Property-based testing: 0 tests.** `hypothesis` is not a dependency; `rg` finds 30 textual hits in `tests/` and **zero** `from hypothesis` imports and **zero** `@given` decorators. The 30 hits are docstring prose and two `_scratch_*.py` probes that are not collected (leading underscore). The monetary-conservation property (`gross - fees - refunds - adjustments = net`) named in `openspec/project.md` is asserted only by example, never by generation.
- **Mutation testing: 0.** No `mutmut`, no `cosmic-ray`. A deliberately broken fee calculation or approval check would not be detected as such.
- **Load/performance: 0.** No `locust`, no `k6`, no benchmark harness. Queue backlog and large-batch reconciliation throughput are unmeasured.
- **Migration/upgrade safety: 0 as a gate.** `tests/unit/test_platform/test_migrations.py` exists, but no workflow verifies a fresh schema build plus an upgrade-from-previous-schema, and the outbox migration `b7e2d9f4a516` shipped to `main` without ever being applied by CI.
- **Provider sandbox: 0.** No Razorpay Test Mode contract suite exists at all. The flagship workflow depends on Razorpay Test Mode; nothing verifies FinSight's adapter against it.
- **Scheduled/extended validation: 0.** No workflow in `.github/workflows/` declares `schedule:` or `cron:`. Extended validation does not exist, so it cannot regress between releases.
- **Coverage measurement: 0.** `pytest-cov` is a dependency, but no workflow passes `--cov`, no `[tool.coverage]` section exists in `pyproject.toml`, and no coverage artifact is retained.
- **Evidence retention: partial.** `integration.yml` uploads `pytest-integration.log`; `ci.yml` tees `pytest-unit.log` and **does not upload it**. The fast gate's raw output is not retained as a release artifact.

**G4 — the release path is a shape, not a qualification.** `deploy-staging.yml`, `deploy-prod.yml`, and `rollback.yml` (merged as `ec28cbd`) are fail-closed scaffolds: `workflow_dispatch` only, with `environment:` keys for `staging` and `prod`. They are correct as scaffolding and prove nothing about a deploy. There is no pre-release qualification stage, no post-deploy verification stage, and no definition of what evidence qualifies a release.

**G5 — CI cannot establish the property the product actually needs.** Passing CI is necessary and not sufficient. For a system whose product value is *investigate → propose → authorize → execute → verify*, the release question is not "did the code work in isolation" but "does the system preserve financial invariants across database transactions, third-party integrations, asynchronous execution, AI-generated proposals, approval boundaries, and failures". That is a different question, and today's gates do not answer it.

## What Changes

**Design the taxonomy and the plan now; expand implementation only after this change is approved.** The PR queue is resolved (`main` = `f68c7e4`), so the design phase is unblocked; the implementation slices below are sequenced but not started.

- **Adds a 15-category test taxonomy** (unit, financial invariants, DB integrity, provider contract, mocked integration, workflow/state-machine, policy/control, security/privacy, mocked E2E, provider sandbox, load/performance, LLM evaluation, migration/upgrade, resilience/fault-injection, deployment/operational smoke) as a normative mapping — with the explicit rule that **Mockoon, LocalStack, and any other simulator is a tool, not a test category**.
- **Adds a test inventory** that maps every existing test file to exactly one category, and enumerates the four defect classes: tests not executed by any workflow, duplicated coverage, category coverage gaps, and unowned categories.
- **Adds a risk-to-test matrix** mapping each critical financial invariant, security boundary, and workflow transition to at least one enforcing test, with the enforced-by file and CI gate named. Invariants with no enforcing test are recorded as `GAP` — not silently assumed covered.
- **Adds a five-stage CI structure**: PR fast gate (Stage 1), PR integration gate (Stage 2), scheduled extended validation (Stage 3), pre-release qualification (Stage 4), post-deployment verification (Stage 5) — with a workflow-separation design that keeps each job independently understandable and reuses a single gate-contract script.
- **Adds an evidence-and-reporting standard**: every job retains its raw log, a machine-readable summary, coverage data, evaluation results, and migration logs as artifacts with an explicit retention window; release qualification references artifacts by run ID.
- **Adds a release policy** specifying, per test category, whether it blocks a merge, blocks a release, or is scheduled-only — plus the rule that **an infrastructure failure yields an explicit failed or inconclusive result, never a silently skipped green**.
- **Adds the `test-inventory` ratchet** as a CI gate: a manifest of every test file, its category, and its enforcing gate, with a gate that fails when a test file is added without a category or when a category loses its enforcing gate.

**Non-goals (explicit):** no weakening or removal of any existing gate; no restructuring of the pipeline beyond the stages above; no live-provider tests in PR-triggered workflows; no change to test assertions, thresholds, or expected outcomes; no introduction of a second test runner; no LLM-output equality assertions.

## Impact

- **Affected specs (ADDED):** `ci-test-architecture` capability — taxonomy, inventory ratchet, risk-to-test matrix, staged gates, evidence retention, release policy.
- **Affected code (plan-phase only):** `openspec/changes/add-ci-test-architecture/**`, `docs/testing/CI_TEST_ARCHITECTURE.md` (the human-readable plan), `scripts/test_inventory.py` + `tests/unit/ci/test_test_inventory.py` (the ratchet, Stage 1 gate), `docs/testing/test-inventory.json` (the manifest).
- **Affected code (implementation-phase, subsequent slices):** `.github/workflows/*.yml` (stage separation, scheduled workflow, artifact retention), `pyproject.toml` (optional `hypothesis` dependency group), `tests/property/**`, `tests/migration/**`, `tests/sandbox/**` (Razorpay Test Mode), `scripts/gate_contract.py` (shared gate contract).
- **No financial-path change.** Deterministic calculations, policy-gated actions, idempotency, auditability, and independent post-action verification are untouched. This change adds gates around them; it never relaxes them.
- **No LLM-authority change.** The LLM remains a candidate producer; deterministic software decides admissibility.
- **Related open work:** APA-83 (CI validation-coverage gaps — Claim_Ops-scoped, adjacent), APA-81 (release control — Claim_Ops-scoped, already satisfied on this repo), APA-79 / GitHub #105 (repo-root dotenv vs `Settings(extra="forbid")`), and the 4 pre-existing `tests/test_python_runtime/test_api.py` failures, which the inventory explicitly surfaces as the first G1 repair.
