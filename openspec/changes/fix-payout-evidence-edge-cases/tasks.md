# Tasks

## 1. Spec correction

- [x] 1.1 Restate "Payout Reconciliation Outcomes" with the deposit-only `PENDING_EVIDENCE` / `NO_CANDIDATE` path and the empty-evidence guard
- [x] 1.2 Restate "Deduplication Precedes Allocation" with duplicate precedence over residual classification
- [x] 1.3 Validate the change with `openspec validate fix-payout-evidence-edge-cases --strict`

## 2. Regression first (red)

- [x] 2.1 `test_deposit_with_no_processor_legs_is_pending_evidence`
- [x] 2.2 `test_empty_charges_without_deposit_still_rejected`
- [x] 2.3 `test_drifted_duplicate_is_flagged_before_partial`
- [x] 2.4 `test_duplicate_precedes_fee_drift_classification`
- [x] 2.5 `test_duplicate_flag_does_not_override_missing_charge_evidence`

## 3. Minimal core fixes (green)

- [x] 3.1 `_validate_inputs` scopes empty charges from the deposit; keeps the no-evidence guard
- [x] 3.2 `allocate_deposit` returns `PENDING_EVIDENCE` / `NO_CANDIDATE` before the window filter when no charges exist
- [x] 3.3 `_classify_residual` returns `I-DUPLICATE` / `DUPLICATE` first when `duplicate` is set

## 4. Gates

- [x] 4.1 `pytest tests/unit/reconciliation -q` (200 passed)
- [x] 4.2 `pytest tests/unit tests/contract -q -p no:randomly` (3588 passed, 1 skipped)
- [x] 4.3 `ruff check .`
- [x] 4.4 mypy baseline check reports no new errors
- [x] 4.5 `openspec validate fix-payout-evidence-edge-cases --strict`
- [x] 4.6 Triangle fixture run reproduces the corrected outcomes (all 9 scenarios; s4b `PENDING_EVIDENCE`/`NO_CANDIDATE` with 600.00 unallocated; s6 `EXCEPTION`/`I-DUPLICATE` with 2.00 open balance)
