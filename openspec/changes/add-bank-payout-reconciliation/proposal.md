## Why
The frozen core reconciles exactly one expected leg against exactly one observed leg. Real settlement does not
look like that: a single bank deposit covers several charges, net of processor fees, and arrives days later. Two
measured consequences follow.

- `reconcile([ch1, ch2, ch3], deposit, tol)` raises `InvariantViolation` — the one-to-one contract cannot express
  a payout at all.
- Forced into the one-to-one shape, the money is explained wrongly. A 1000.00 invoice settled as a 971.00 deposit
  with a 29.00 processor fee classifies as `I-REFUND-LAG`; the same 29.00 against a bank leg enriched with
  `gross=1000.00, fee=29.00` classifies correctly as `I-FEE-DRIFT`.

The triangle fixture (`cf4d852`, 21 tests, 3 strict `xfail`) encodes these findings. The gap report
(`docs/reconciliation/triangle-contract-gap.md`) proposes the smallest contract that closes them. This change turns
that proposal into a frozen, reviewable specification.

## What Changes
- Add `BankDepositRecord` and a tenant-declared bank statement normalizer (CSV only; no bank API integration).
- Add the many-to-one contract: `allocate_deposit(deposit, charges, tolerance)` and
  `reconcile_payout(deposit, charges, tolerance, *, window_seconds=None)`.
- Make ambiguity an explicit outcome (`AmbiguousAllocation`) instead of a silent tie-break.
- Freeze fee and refund provenance: bank text never supplies fees; they are copied from the charge legs.
- Represent absence explicitly: a charge with no visible deposit is `PENDING_EVIDENCE`, not "no result".
- Extend the exception taxonomy additively with `I-PARTIAL` and `I-PAYOUT`; the three existing codes are unchanged.

## Impact
- Affected specs: `reconciliation` (ADDED requirements only; no existing requirement is modified).
- Affected code:
  - `finance/reconciliation/models.py` — `BankDepositRecord`, `Allocation`, `PayoutOutcome`.
  - `finance/reconciliation/bank.py` (new) — statement normalization.
  - `finance/reconciliation/allocation.py` (new) — subset allocation + payout reconciliation.
  - `finance/reconciliation/classifier.py` — additive codes only; existing tie-break order preserved.
  - `tests/unit/reconciliation/` — new unit tests; the three `xfail` markers in `test_triangle.py` become the
    acceptance tests and are removed only when they pass.
- Non-goals:
  - No live bank, Plaid, or statement-PDF ingestion. CSV with a declared mapping only.
  - No general subset-sum solver and no approximate allocation. Candidate sets are bounded; beyond the bound the
    outcome is "requires human allocation", never a best guess.
  - No new monetary type: money stays `Decimal` end to end.
  - No change to `reconcile()`'s one-to-one semantics; the payout contract is additive.
  - No journal entry generation or ERP write.
