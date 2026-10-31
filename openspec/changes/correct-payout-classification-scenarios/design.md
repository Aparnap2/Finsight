# Design: classification follows evidence

## Context

`reconcile_payout` allocates a deposit against visible charges and classifies
what it cannot allocate. Two spec examples disagreed with the precedence the
implementation uses. The adjudication below is the authority for the corrected
examples; the normative rules are unchanged.

Evidence base: `finance/reconciliation/allocation.py`
(`_classify_residual`, `reconcile_payout`), `tests/unit/reconciliation/
test_allocation.py`, and `docs/reconciliation/triangle-contract-gap.md`.

## Decisions

### D1 — An unexplained shortfall is `I-PARTIAL`, never `I-FEE-DRIFT`

`I-PARTIAL` is emitted when a deposit is absorbed and an open balance remains:
`allocated_total > 0` and `open_balance > 0`. A `971.00` deposit against a
`1000.00` charge with `fee="0.00"` is exactly that state. The 29.00 difference
is *unpaid principal*, not evidence of a fee, and there is no processor
evidence to attribute it to a fee.

`I-FEE-DRIFT` requires fee evidence: `fee_total > 0` on the allocated legs and
`unallocated_deposit != fee_total`. Evidence, not magnitude, selects the code.

Rejected alternatives:

- *Classify by percentage or absolute size* (for example, treating 2.9% as a
  card fee): invents evidence, breaks determinism, and would mislabel genuine
  underpayments.
- *Split into a new code:* the taxonomy is additive and already has `I-PARTIAL`;
  adding a sixth code for the same state is unnecessary.

### D2 — Correct the example, never the invariant

The conservation invariant is `gross - fee == net` per leg and
`sum(gross) - fee_total - refund_total == allocated_total` in aggregate. Fees
`11/9/9` with nets `388/291/291` violate it; the source records use
`12/9/9` and gross `400/300/300`. Weakening or special-casing the invariant to
fit a bad example would hide real residual errors, so only the example changes.

Rejected alternatives:

- *Change the fixture to fees `11/9/9`*: then net would be `389/291/291` and the
  `970.00` deposit would no longer match; it merely relocates the error.
- *Edit the examples inside `add-bank-payout-reconciliation` in place*: the
  original was reviewed; a separate change keeps the adjudication auditable.

## Consequences

- The two scenarios are restated with the values the fixture actually holds.
- `test_unexplained_shortfall_is_partial_not_fee_drift` and
  `test_conservation_is_exact_for_three_charges` pin the corrected behaviour.
- No API, enum, or runtime behaviour changes, so the payout surface is frozen
  until a new slice is approved.
