# Fix two payout-evidence edge cases the frozen contract already requires

## Why

Two normative statements in `add-bank-payout-reconciliation` cannot be reached
through the implementation, so callers cannot produce the outcome the contract
requires:

1. **No processor legs.** "Payout Reconciliation Outcomes" says
   `PENDING_EVIDENCE` MUST be returned when no candidate is visible, naming
   "no charges at all" as the first case. `_validate_inputs` rejects an empty
   charge sequence outright, so the only legal deposit-only outcome is a raised
   `InvariantViolation`. The fixed triangle fixture exposes this in
   `s4b_partial_payment`, whose processor block is empty.
2. **Drifted duplicate.** "Deduplication Precedes Allocation" says a duplicate
   that survives deduplication because its amount drifted MUST produce
   `I-DUPLICATE` and MUST NOT be silently allocated as a separate leg. On the
   deposit surface the duplicate flag is only consulted after an exact or
   tolerant amount fit, so a drifted re-import is classified by residual
   precedence instead (`I-PARTIAL`, and `I-FEE-DRIFT` when fee evidence exists).
   `s6_duplicate` exercises exactly that shape.

Both are gaps between the approved contract and the code, not defects in the
requirement text. The fixes are deliberately local: one validation branch, one
early `PENDING_EVIDENCE` branch, and one precedence guard.

## What Changes

- A deposit with no visible processor legs is `PENDING_EVIDENCE` /
  `NO_CANDIDATE` with the full deposit left unallocated. Absence of processor
  evidence is never reported as `MATCHED`, `I-PARTIAL`, or `I-PAYOUT`.
- A call with neither a deposit nor a charge still raises `InvariantViolation`;
  there is no evidence to scope the result at all.
- Duplicate evidence takes precedence over residual classification on the
  deposit surface. A drifted duplicate reports `I-DUPLICATE` while preserving
  the allocated legs and the residual amounts (`open_balance` and/or
  `unallocated_deposit`) so the amount discrepancy stays visible as evidence.
- The pairwise `classify` order (refund, then fee, then gross) is unchanged,
  and no new exception code or `PayoutReason` is introduced.

## Impact

- Code: `finance/reconciliation/allocation.py` only (`_validate_inputs`,
  `allocate_deposit`, `_classify_residual`).
- Spec: `openspec/changes/fix-payout-evidence-edge-cases/specs/reconciliation/spec.md`
  (MODIFIED requirements only).
- Tests: `tests/unit/reconciliation/test_allocation.py`.
- Follow-on Milestone 2 work (`finance/reconciliation/statement_workflow.py`)
  depends on both corrections for contract-correct fixture outcomes.
