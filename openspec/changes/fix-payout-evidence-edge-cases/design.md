# Design: missing evidence is pending, duplicate evidence outranks residuals

## Context

`reconcile_payout` is the deposit surface of the triangle. `_validate_inputs`
scopes the result to one tenant and one currency, `allocate_deposit` enumerates
candidate subsets, and `_classify_residual` explains whatever cannot be
allocated. Two contract statements have no reachable path through that code:

- empty `charges` raises before any outcome is built;
- the deposit-surface duplicate flag is only read inside the exact/tolerant fit
  branch.

Evidence base: `finance/reconciliation/allocation.py`,
`openspec/changes/add-bank-payout-reconciliation/specs/reconciliation/spec.md`,
`tests/unit/reconciliation/test_allocation.py`, and the
`tests/fixtures/reconciliation/triangle` fixture.

## Decisions

### D1 — No processor legs is `PENDING_EVIDENCE`, not a mismatch

A deposit without any processor leg is missing evidence. Nothing financial can
be asserted about it: there is no expected amount to compare, so `I-PAYOUT`
(which describes a mismatch between visible evidence) and `I-PARTIAL` (which
requires an absorbed charge) are both wrong. The contract's own wording —
"no charges at all" — selects `PENDING_EVIDENCE`.

Implementation: `_validate_inputs` derives the scope from the deposit when the
charge sequence is empty, and raises only when neither side exists.
`allocate_deposit` returns `PENDING_EVIDENCE` / `NO_CANDIDATE` before the
window filter with `unallocated_deposit == deposit.amount`, which conserves
exactly (`0 + deposit.amount == deposit.amount`).

A zero-value payment is a *record*, distinct from no record: an empty sequence
is checked before any amount logic, so the two cannot be conflated.

Rejected alternatives:

- *Treat a deposit-only period as `I-PAYOUT`.* Invents a discrepancy from
  absent evidence and breaks the requirement that `PENDING_EVIDENCE` covers
  "no charges at all".
- *Relax validation entirely.* `reconcile_payout(None, [])` has no tenant or
  currency to report; a silent empty outcome would be unfalsifiable. It keeps
  raising.

### D2 — Duplicate evidence outranks residual classification on the deposit surface

The contract puts deduplication *before* allocation precisely because a
duplicate that changes amount can otherwise be read as a genuine residual. The
guard therefore sits in `_classify_residual` as the first rule, ahead of
partial, refund, fee, and unallocated handling.

The classification keeps the arithmetic: `allocated_total`,
`unallocated_deposit`, and `open_balance` are computed from the legs and scope
as before. For a `148.00` re-import against a `150.00` charge the result is
`I-DUPLICATE` with `allocated_total="148.00"` and `open_balance="2.00"`; for a
duplicate over-deposit the excess stays in `unallocated_deposit`. The code
describes *why* the evidence is unsafe; the amounts describe *what* is
discrepant. Neither replaces the other.

The deposit-level scope is unchanged: one `duplicate` flag per call, declared
by the caller that detected the re-import. Multi-deposit duplicate detection
belongs to the orchestration layer, not the allocator.

Rejected alternatives:

- *Add a new exception code such as `I-DUPLICATE-DRIFT`.* Violates the closed,
  additive-only taxonomy and the requirement that persisted codes stay stable.
- *Drop the drifted deposit instead of allocating it.* Loses the amount
  discrepancy and leaves the operator without the evidence the contract asks
  to preserve.
- *Change the one-to-one `classify` order.* The requirement freezes that order
  for the pairwise surface; this decision touches the deposit surface only.

### D3 — Empty input semantics

`charges` must be non-empty only when `deposit is None`. With a deposit present
the tenant and currency come from the deposit, which is the stronger evidence
side. This keeps every existing `InvariantViolation` guarantee for malformed
policy inputs (tolerance, window, `max_candidates`, `duplicate`) untouched.
