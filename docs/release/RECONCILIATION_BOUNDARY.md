# Reconciliation runtime boundary

Purpose: state exactly which files the payment-reconciliation runtime needs, so
repository consolidation can delete historical product generations without
touching the engine, the workflow, or the demonstration evidence.

The boundary is **computed**, not asserted by hand:

```bash
python scripts/reconciliation_boundary.py --check   # exit 1 on drift
```

`docs/release/reconciliation-boundary.json` is the committed manifest;
`tests/unit/reconciliation/test_boundary_manifest.py` fails when the code and
the manifest disagree.

## 1. The boundary today

Entry point: `finance.reconciliation.operator_report` — the one-command
operator demo (`python -m finance.reconciliation.operator_report`).

| Item | Count | Detail |
|---|---|---|
| Modules | 14 | `finance` + `finance.reconciliation` + 12 stage/composition modules |
| Files | 14 | all under `finance/reconciliation/`, plus the empty `finance/__init__.py` |
| Fixtures | 3 | `tests/fixtures/reconciliation/triangle/{cases,expected,operator_expected}.json` |
| Third-party imports | **0** | standard library only |
| Environment variables | **0** | no DB, network, clock, randomness, or LLM on this path |

| Module | Role |
|---|---|
| `models.py` | immutable `PaymentRecord` / `ReconciliationResult` contracts; Decimal-only money |
| `normalizer.py`, `bank.py` | provider and bank-statement normalization |
| `matcher.py`, `tolerances.py`, `reconciler.py` | deterministic matching and classification |
| `allocation.py` | deposit → charge allocation, fees, refunds, duplicates, ambiguity |
| `classifier.py`, `fingerprints.py`, `errors.py` | outcome codes, stable identity, typed failures |
| `statement_workflow.py` | the three-source composition (invoice + processor + bank) |
| `operator_report.py` | CLI, Markdown/JSON report, 266-check evidence pass |

### Outside the CLI closure but inside the package

`finance/reconciliation/ledger_resolution.py` is **not** reachable from the CLI.
It is used by the separate FP&A execution path (`finance/execution/executor.py`,
`finance/accounting/commands.py`). Keep it while that application exists; it
becomes a removal candidate once the FP&A surface is gone. The manifest records
it under `package_members_outside_closure` so it is neither deleted by accident
nor mistaken for part of the demo.

## 2. Evidence reproducibility

`tests/unit/reconciliation/test_golden_evidence.py` re-runs the documented
command into a temporary directory and asserts that `report.md`, `report.json`,
and `run.json` are **byte-identical** to the committed bundle in
`docs/evidence/operator-run/`, and that two runs agree. Any change to
classification, allocation, rendering, or evidence shape fails there first.

```bash
python -m pytest tests/unit/reconciliation/test_golden_evidence.py -q
```

## 3. Baseline

Measured on `feat/reconciliation-three-source-workflow` at `5556ee7` plus this
change set (2026-11-19). Recorded so later cleanup can prove it changed nothing.

| Gate | Command | Before cleanup | After `business/` removal |
|---|---|---|---|
| Lint | `ruff check .` | pass | pass |
| Format | `ruff format --check .` | 753 files | 679 files |
| Type | `mypy .` + `scripts/mypy_baseline_check.py` | recorded 1137, current 1137, new 0 | unchanged (no baseline entry lived in `business/`) |
| Fast suite | `pytest tests/unit tests/contract -q` | 3629 passed, 1 skipped | 3336 passed, 1 skipped |
| Collected tests | `pytest --collect-only -q` | 4047 | 3754 |
| Reconciliation | `pytest tests/unit/reconciliation -q` | 241 passed | 241 passed |
| Operator demo | `python -m finance.reconciliation.operator_report` | exit 0, 266 checks, `Verdict: PASS` | unchanged |
| Integration (compose) | `docker compose -f docker-compose.test.yml up --exit-code-from test` | 206 passed, 6 skipped | unchanged |

## 4. Excluded historical generations

These trees are outside the boundary. They are **not** part of the product being
kept. Disposition is deliberately staged: nothing is deleted until its import
boundary is re-verified in the commit that deletes it.

| Tree | Evidence | Disposition |
|---|---|---|
| `business/` | 68 modules, 19,511 LOC, **zero** importers in production code; 16 test files / 281 tests that pass but are never collected (`pyproject.toml` `testpaths = ["tests"]`, CI runs `pytest tests/unit tests/contract`) | **Deleted** (see deletion log) |
| `contracts/` | 349 LOC of empty `__init__` packages | **Deleted** (see deletion log) |
| `finance/legacy_execution/` | 3,215 LOC; only `handoff` is imported, by `apps/api/execution_routes.py` | Delete with the FP&A surface |
| `finance/evaluation/`, `finance/feature_store/`, `finance/investigation/`, `finance/cognition/` | 0 importers outside their own tests | Delete with their tests |
| `agents/p8_runtime/` (except `contract`) | `execution.py` retained (dependency of deferred durability.py); `orchestration.py` deleted in slice 4a; `durability.py` deferred (DB-backed) | Split: delete orchestration (done); execution retained due to durability dependency; defer durability; retain contract |
| `shared/llm/` | 1,211 LOC unreachable; the live LLM path is `shared/utils/llm_client.py` | Evaluate reuse, then delete |
| `shared/tracing/` | 1,895 LOC unreachable | Delete |
| `finplatform/` (except `rbac.matrix`) | 304 LOC unreachable | Delete |
| `frontend/` + `Dockerfile.frontend` | zero references in CI, compose, or `Makefile`; the deployed UI is `apps/api/operator_console.py` (`/gui`) | **Deleted**: Next.js generation removed; NiceGUI at `/gui` is the canonical UI (see `docs/PRODUCT.md`) |
| `docs/architecture/*_{CONTRACT,GAP_*}.md` (21 files) | phase documents for the excluded generations | Archive under `docs/archive/` |
| root `PRD.md`, `FinSight_PRD_v1.md`, `FinSight_Technical_Architecture.md`, `IMPLEMENTATION_PLAN.md` | four competing product definitions; `IMPLEMENTATION_PLAN.md` describes a deleted `backend/` package | **Archived** under `docs/archive/`; `docs/PRODUCT.md` is now the canonical spec |

`apps/` is **not** excluded. It is the currently deployed FP&A application and
stays until the reconciliation API replaces it; deleting it first would leave
the repository with no HTTP surface.

### Deletion log

| Tree | Boundary check | Effect |
|---|---|---|
| `business/` | no `from business`/`import business` outside the tree except 8 test modules; 6 of those tested only `business/`, and 2 mixed files were trimmed to keep their `finance.domain` coverage (`test_variance.py`, `test_money.py`) | 87 files, 19,511 LOC, 293 collected tests; boundary unchanged; reconciliation suite, operator demo, and integration tier unchanged |\n| `finance/ml/` | zero importers in production code or dynamic references; one orphaned test module (`tests/unit/test_finance/test_ml.py`, 20 tests) | 8 files, 1,931 LOC, 20 collected tests; boundary unchanged; reconciliation suite, operator demo, fast suite (3,427 passed), contract report, and integration tier unchanged |\n| `frontend/` + `Dockerfile.frontend` | zero references in CI, compose, Makefile, or any deployment workflow; the canonical UI is `apps/api/operator_console.py` at `/gui` (NiceGUI) | 25 files (including pnpm-lock.yaml, 2,200+ LOC) and 1 Dockerfile removed; API image build path unchanged; NiceGUI `/gui` route untouched; reconciliation contract, operator demo, fast suite, and integration tier unchanged |\n| `contracts/` | zero production importers, zero test importers, zero references in CI/compose/Makefile/scripts/alembic/pyproject/uv.lock; docstring named the deleted `business/` generation | 4 files, 349 LOC removed; no collected tests affected; ruff, mypy baseline (1137/1137, 0 new), fast suite (3,427 passed), reconciliation suite (352), operator demo, contract record, and boundary check all unchanged |\n| `agents/p8_runtime/orchestration.py` | zero production importers; 40 exclusively-dependent contract tests (test_p8_04) | 649 LOC removed; 1 contract test module deleted; ruff, mypy baseline (1052/1052, 0 new), fast suite (3,349 passed), reconciliation contract unchanged |

`business/` was the only tree that no production module imported, and its own
test suite was never collected by CI. The remaining trees in the table need
their own boundary verification, because several are imported by `apps/` or by
their own tests.

## 5. Deletion protocol (one tree per commit)

1. Re-verify the import boundary for that tree:
   `rg "^\s*(from|import) <tree>" --glob '!<tree>/**'` → no hits, or hits only
   from a tree deleted in the same commit (e.g. `finance/legacy_execution` is
   imported by `apps/`, so it cannot be deleted before `apps/`).
2. Re-verify prose references: `rg "<tree>\." --glob '!<tree>/**'` → only
   docstrings/comments that the same commit updates.
3. Confirm the collected-test count is unchanged (tests for uncollected trees
   disappear without changing `pytest --collect-only -q`).
4. Run the full local gate sequence from §3.
5. Commit, push, wait for CI. Never batch two trees in one commit — a bisect
   must be able to attribute a regression to a single deletion.

## 6. What this document does not claim

- It does not claim the engine is correct on real statements — that is the
  frozen fixture contract, unchanged here.
- It does not authorise deleting `apps/`, the reconciliation engine, or the
  fixtures.
- It does not claim the repository is consolidated. It fixes the boundary so
  consolidation can proceed measurably.
