# Correct two contradictory payout-classification scenarios

## Why

Two examples in `add-bank-payout-reconciliation` cannot be true alongside the
requirement text they illustrate:

1. **Zero-fee drift.** The provenance requirement says a charge leg with
   `fee="0.00"` and a `971.00` deposit against a `1000.00` expected amount must
   report `I-FEE-DRIFT` with a `29.00` discrepancy and `fee_total="0.00"`. With
   no fee evidence, nothing distinguishes that 29.00 from an unpaid remainder,
   and the outcome requirement reserves `I-PARTIAL` for exactly that residual
   open balance. The scenario asks for two incompatible codes for one state.
2. **Conservation arithmetic.** The conservation scenario pairs nets
   `388.00 / 291.00 / 291.00` with fees `11.00 / 9.00 / 9.00`. Fees totalling
   `29.00` imply a net of `971.00`, not `970.00`; the three figures cannot hold
   simultaneously. The fixture's source records are gross `400.00 / 300.00 /
   300.00` with fees `12.00 / 9.00 / 9.00`.

Neither contradiction changes the normative rules; both are example defects.
Classification must follow evidence, not the size of a difference.

## What Changes

- `I-PARTIAL` is the outcome for an unexplained shortfall: a visible charge
  with no fee evidence leaves an open balance, and an open balance is partial
  settlement.
- `I-FEE-DRIFT` requires fee evidence: at least one allocated leg carries a
  non-zero fee, and the unallocated remainder is not explained by those fees.
- The conservation example states gross, fee, and net consistently
  (`400/300/300` gross, `12/9/9` fees, `388/291/291` net, `30.00` total fees).
- Regression tests pin both adjudicated behaviours.

## Impact

- Spec: `openspec/changes/correct-payout-classification-scenarios/specs/reconciliation/spec.md`
  (MODIFIED requirements only).
- Tests: `tests/unit/reconciliation/test_allocation.py`.
- No production code change, no new dependency, no exception-taxonomy change.
- The source change `add-bank-payout-reconciliation` keeps its original text;
  this change records the adjudication and the corrected examples beside it.
