# Tasks

## 1. Spec correction

- [x] 1.1 Restate "Fee and Refund Provenance" with `I-PARTIAL` for unexplained shortfalls and fee evidence required for `I-FEE-DRIFT`
- [x] 1.2 Restate "Monetary Conservation and Rounding Policy" with gross `400/300/300`, fees `12/9/9`, net `388/291/291`
- [x] 1.3 Validate the change with `openspec validate correct-payout-classification-scenarios --strict`

## 2. Regression

- [x] 2.1 Add `test_unexplained_shortfall_is_partial_not_fee_drift` (deposit 971.00 vs charge net 1000.00, fee 0)
- [x] 2.2 Add `test_conservation_is_exact_for_three_charges` (gross 1000 - fees 30 == nets 970)
- [x] 2.3 Confirm fee drift, no-candidate, ambiguity, and exact-allocation assertions remain covered

## 3. Gates

- [x] 3.1 `pytest tests/unit/reconciliation -q`
- [x] 3.2 `pytest tests/unit tests/contract -q`
- [x] 3.3 `ruff check .`
- [x] 3.4 mypy baseline check reports no new errors
