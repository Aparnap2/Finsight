# Tasks: add-ci-test-architecture

> Plan-phase deliverable. Task group 1 is this change (design artifacts only — no CI behaviour change).
> Task group 2+ are the implementation slices, each independently green and independently mergeable,
> sequenced after approval. No task in group 2+ starts until the plan is approved.

## 1. Plan phase (this change)

- [x] 1.1 Measure the verified starting state at `main` = `f68c7e4` — collected test count, per-directory counts, test-file count, workflows, required status checks, and the six zero-coverage categories (property-based, mutation, load/perf, scheduled validation, coverage measurement, provider sandbox). Record in `design.md` §Context.
- [x] 1.2 Enumerate the four G1 defect classes — tests not executed by any workflow (14 files / 145 tests), duplicated-coverage candidates, category gaps, and unowned categories — from the per-directory inventory table in `design.md`.
- [x] 1.3 Adopt the 15-category taxonomy with the simulators-are-tools rule, the domain-test-ownership rule, and the LLM-evaluation-is-structured rule (`design.md` D1, D8).
- [x] 1.4 Define the five CI stages with the shared gate contract and the normative failure-semantics table, including the rule that an infrastructure failure is failed-or-inconclusive and never a green skip (`design.md` D3).
- [x] 1.5 Define the evidence-and-reporting standard and the release-qualification artifact list (`design.md` D4).
- [x] 1.6 Define the release policy — per category: merge-blocking, release-blocking, or scheduled-only, with the merge-blocking set held deliberately small (`design.md` D5).
- [x] 1.7 Write the human-readable plan to `docs/testing/CI_TEST_ARCHITECTURE.md` (taxonomy, inventory, risk-to-test matrix, stage design, evidence standard, release policy).
- [x] 1.8 Write the normative spec deltas under `specs/ci-test-architecture/spec.md` and validate with `openspec validate add-ci-test-architecture --strict`.
- [x] 1.9 Record the first implementation slice as the G1 repair (the 4 pre-existing `test_api.py` failures + the unexecuted suites) rather than a new category — the suite must be made honest before it is made larger.

## 2. Implementation slice 1 — G1 repair (make the existing suite honest)

- [ ] 2.1 Fix the 4 pre-existing failures in `tests/test_python_runtime/test_api.py` — the tenant middleware requires `X-Tenant-ID` and `X-Role`; the test file sends neither. Add the headers, and assert the middleware's 401 behaviour explicitly rather than leaving it implicit.
- [ ] 2.2 Add `tests/test_python_runtime/` to a CI job so its 133 tests actually execute and can fail.
- [ ] 2.3 Wire `tests/evaluation/` (12 tests) into a CI job; wire `tests/evals/llm/` (6 tests) into the scheduled job under `-m live_llm` only — never in PR CI.
- [ ] 2.4 Delete or relocate `tests/unit/test_domain/_scratch_hyp.py` and `_scratch_polars.py` so the tree reflects what actually executes.
- [ ] 2.5 Gates: ruff, ruff format, mypy baseline, unit+contract, postgres-gated integration, ministack, golden eval — all green; the 4 failures no longer reproduce.

## 3. Implementation slice 2 — inventory ratchet (Stage 1 required check)

- [ ] 3.1 Create `docs/testing/test-inventory.json` — every test file → category → enforcing gate, generated from one declarative mapping.
- [ ] 3.2 Create `scripts/test_inventory.py` — fails when a test file is unlisted, when a category has no enforcing gate, or when a merge-blocking category has no job.
- [ ] 3.3 Create `tests/unit/ci/test_test_inventory.py` — unit tests for the ratchet itself, including its failure modes.
- [ ] 3.4 Add the ratchet as a required check in the Stage 1 fast gate.
- [ ] 3.5 Evidence: paste a run where a deliberately unlisted test file makes the job RED, then revert.

## 4. Implementation slice 3 — shared gate contract + evidence retention

- [ ] 4.1 Generalize `scripts/ci_gate.py` into `scripts/gate_contract.py`: teed-log parsing, passed/failed/skipped/xfailed counts, skip budget, named required-test identity assertions, machine-readable JSON summary.
- [ ] 4.2 Add named required-test identity assertions for Stage 2 (proposed starting set: outbox 20, tenant-isolation matrix, money conservation, approval binding).
- [ ] 4.3 Upload `pytest-unit.log` from `ci.yml`; add artifact retention with an explicit window to every job.
- [ ] 4.4 Evidence: paste a run where a required test is skipped and the job is RED; paste the artifact listing.

## 5. Implementation slice 4 — stage separation + scheduled validation

- [ ] 5.1 Split the workflows into independently understandable jobs per Stage 1/2/3.
- [ ] 5.2 Add the scheduled Stage 3 workflow (`schedule:` + `workflow_dispatch`).
- [ ] 5.3 Add `concurrency` to every workflow that lacks it (currently only `ci.yml` and `integration.yml` have it).
- [ ] 5.4 Evidence: paste a superseded Stage 3 run reaching conclusion `cancelled`.

## 6. Implementation slice 5 — coverage + property-based tests

- [ ] 6.1 Add coverage instrumentation to the Stage 1 and Stage 2 jobs; add `[tool.coverage]` to `pyproject.toml`; upload XML + HTML.
- [ ] 6.2 Add the `hypothesis` dependency group (test-only) and property tests for: monetary conservation (`gross - fees - refunds - adjustments = net`), normalization invariance, duplicate-event idempotency, reconciliation invariants.
- [ ] 6.3 Evidence: paste a property run that SHRINKS to a concrete failing case, and the resulting RED.

## 7. Implementation slice 6 — migration-safety gate

- [ ] 7.1 Add a required job verifying fresh-schema creation and upgrade-from-previous-schema.
- [ ] 7.2 Wire the outbox migration `b7e2d9f4a516` into that job.
- [ ] 7.3 Add a rollback/roll-forward verification transcript artifact.
- [ ] 7.4 Evidence: paste a RED run for a deliberately broken migration, then revert.

## 8. Implementation slice 7 — Razorpay Test Mode sandbox (Stage 4 release gate)

- [ ] 8.1 Build the Razorpay Test Mode contract suite: valid + malformed responses, 400/401/403/429/5xx, timeouts, duplicate and out-of-order webhooks, invalid signatures, pagination, rate limits, schema drift.
- [ ] 8.2 Add the Stage 4 pre-release qualification workflow that runs it.
- [ ] 8.3 Evidence: paste a sandbox run and a RED run against a deliberately wrong credential (inconclusive vs pass must be distinguishable).

## 9. Implementation slice 8 — mutation testing on critical rules (Stage 3)

- [ ] 9.1 Scope mutation testing to the critical rule files only: fee calculation, approval binding, confidence threshold, close condition.
- [ ] 9.2 Evidence: paste a RED run for a deliberately broken fee calculation, then revert.

## 10. Implementation slice 9 — load & fault injection (Stage 3)

- [ ] 10.1 Measure large-batch reconciliation throughput and queue backlog; record the measured baseline (no target is invented before the measurement).
- [ ] 10.2 Add fault-injection scenarios: DB unavailable, provider timeout after execution sent, queue redelivery, worker termination mid-flight.
- [ ] 10.3 Evidence: paste the measured baseline and the fault-injection transcripts.

## 11. Deferred governance set (carried forward, not started)

- [ ] 11.1 R-1 CODEOWNERS
- [ ] 11.2 R-2 split required CI jobs (folded into slice 4)
- [ ] 11.3 R-3 test-inventory ratchet (becomes slice 2)
- [ ] 11.4 R-4 fixture hash manifest
- [ ] 11.5 R-5 workflow-integrity gate
- [ ] 11.6 R-6 secret/dependency hardening
- [ ] 11.7 R-7 migration-safety job (becomes slice 6)
- [ ] 11.8 R-8 diff-scoped coverage
