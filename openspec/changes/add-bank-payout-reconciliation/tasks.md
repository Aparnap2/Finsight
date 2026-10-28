# Tasks: add-bank-payout-reconciliation

> Contract first. Do not implement `finance/` code until this proposal is approved.
> The three strict `xfail` tests in `tests/unit/reconciliation/test_triangle.py` are the acceptance tests and are
> removed only when they pass.

## S0 Contract Freeze (this change; approval gate)

- [x] S0.1 Record measured findings from the triangle fixture (`cf4d852`) in `proposal.md`
- [x] S0.2 Freeze `BankDepositRecord`, `Allocation`, `PayoutOutcome`, and the two additive codes
- [x] S0.3 Freeze fee provenance, ambiguity, absence, and non-transitivity rules as requirements
- [x] S0.4 Write decision record and rejected alternatives in `design.md`
- [ ] S0.5 `openspec validate add-bank-payout-reconciliation --strict` passes
- [ ] S0.6 Human approval recorded; explicit STOP gate lifted

## S1 Bank Deposit Record and Normalizer (unit)

- [ ] S1.1 `BankDepositRecord` Pydantic model: Decimal-only, ISO 4217, tz-aware, positive amount, no fee field
- [ ] S1.2 Declared mapping schema; reject incomplete or duplicate-column mappings before reading rows
- [ ] S1.3 CSV normalization: signed and debit/credit conventions, major/minor units, per-row rejects with line
      numbers, coverage counts
- [ ] S1.4 Unit tests: valid row, float rejected, naive timestamp rejected, empty cell rejected and counted,
      duplicate header rejected, determinism under repeated normalization

## S2 Allocation (unit, pure)

- [ ] S2.1 Exact subset enumeration over charges scoped by tenant and currency, bounded by
      `MAX_ALLOCATION_CANDIDATES`
- [ ] S2.2 `Allocation` with `allocated_total`, `fee_total`, `unallocated_deposit`, `open_balance`, Decimal-only
- [ ] S2.3 Ambiguity detection returning every satisfied subset; no tie-break anywhere in the path
- [ ] S2.4 Partial allocation: absorb the deposit, keep the charge open, emit `I-PARTIAL`
- [ ] S2.5 Determinism test: permuted candidates yield an identical allocation including report order
- [ ] S2.6 Bound test: candidates above the bound return `requires_human`, never an approximate result

## S3 Payout Reconciliation (unit, pure)

- [ ] S3.1 `reconcile_payout` outcome mapping: `MATCHED | TOLERANCE_MATCHED | EXCEPTION | PENDING_EVIDENCE |
      REQUIRES_HUMAN`
- [ ] S3.2 Window semantics: outside-window candidates yield `PENDING_EVIDENCE`, inside-window mismatch yields
      `EXCEPTION`
- [ ] S3.3 Fee provenance: zero-fee leg yields `I-FEE-DRIFT`; enriched leg yields `MATCHED`
- [ ] S3.4 Deduplication before allocation; drifted duplicate yields `I-DUPLICATE` with one leg
- [ ] S3.5 Zero default tolerance and explicit per-call injection; no hardcoded epsilon

## S4 Acceptance and Regression

- [ ] S4.1 Convert the three `xfail` triangle tests to passing tests; remove the markers
- [ ] S4.2 Keep `s2_fee_explained` and the naive-bank-leg case in `cases.json` as the provenance pair
- [ ] S4.3 `ruff check .`, `ruff format --check .`, `mypy .` (baseline 1137), `pytest tests/unit tests/contract`
- [ ] S4.4 Record the new exception codes in the platform exception taxonomy docs
- [ ] S4.5 Update `docs/reconciliation/triangle-contract-gap.md` from proposal to implemented status
