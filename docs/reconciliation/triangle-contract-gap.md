# Three-source reconciliation: what the frozen core handles

_Evidence: `tests/unit/finance/test_reconciliation_triangle.py` over
`tests/fixtures/reconciliation/triangle/`. 18 passing checks, 3 strict xfails.
No production code in `finance/` was changed._

The scenario is a month of card revenue: an invoice register says what should
be paid, Stripe says what was charged, a bank statement says what landed.

## Handled today

| Case | Behaviour |
|---|---|
| Exact agreement on all three legs | `MATCHED`, difference `0.00` |
| Stripe fee 29.00 between a 1000.00 invoice and a 971.00 deposit | `I-FEE-DRIFT`, `-29.00`, when the bank leg carries `gross=1000, fee=29` |
| Charge net vs deposit | `MATCHED`: Stripe's `net` already excludes the fee |
| Refund folded into net (1000 gross, 29 fee, 400 refund, 571 deposited) | `MATCHED` |
| Deposit arriving three days later | `find_match(..., window_seconds=259200)` matches; `3600` returns `None` |
| Duplicate bank import | `find_duplicates` groups by `idempotency_key`; `ensure_unique` raises |
| Duplicate that also drifted (150.00 vs 148.00) | `I-DUPLICATE` when `duplicate=True` |

## Not representable

1. **Many-to-one payouts.** `reconcile(processor, ledger, tolerance)` accepts
   exactly one leg per side. 388.00 + 291.00 + 291.00 = one 970.00 deposit has
   no entry point; passing the list raises `InvariantViolation`.
2. **A bank leg with no fee column.** A deposit is one credit. Normalized as
   its own `gross`, the 29.00 fee becomes a gross delta; the classifier has no
   gross-only code, so **a pure fee difference is reported as `I-REFUND-LAG`**
   (`test_s2_naive_bank_leg_misattributes_fee_drift_to_a_refund_lag`). The
   triangle is also not transitive: invoice = charge and charge = deposit, yet
   invoice ≠ deposit. Bank rows must be enriched from the processor leg.
3. **Underpayment.** A 400.00 shortfall with no refund is `I-REFUND-LAG`; there
   is no partial-payment code, so it is indistinguishable from refund timing.
4. **A missing deposit.** `reconcile` needs two legs, so "expected but never
   observed" produces nothing at all. Absence and not-yet-arrived are the same
   non-result.
5. **Ambiguous allocation.** 970.00 could be three charges or one 970.00
   charge. `find_match` returns the first equal-net candidate; no ambiguity is
   signalled, so a plausible-but-wrong allocation passes silently.
6. **Dedup ordering.** `duplicate=True` only reaches `classify` after the
   tolerance check fails, so an exact-matching duplicate closes as `MATCHED`.
   Dedup must run before `reconcile`; the core does not enforce that order.

There is also no bank importer and no invoice vocabulary: `finance/` has no
bank-statement or invoice mapping, and `finance/stripe/adapter.py` handles only
`charge.succeeded` and `refund.created` (no payout events).

## Smallest missing contract

Signatures only; nothing below is implemented.

```python
# finance/reconciliation/bank.py
@dataclass(frozen=True)
class BankDepositRecord:
    deposit_id: str
    net_credit: Decimal      # the statement line, never a float
    currency: str
    posted_at: datetime      # tz-aware
    tenant_id: str
    reference: str | None    # bank memo / payout id when the statement has one

def normalize_bank_row(row: Mapping[str, str], *, tenant_id: str) -> BankDepositRecord: ...

# finance/reconciliation/allocation.py
@dataclass(frozen=True)
class Allocation:
    deposit_id: str
    charge_payment_id: str
    amount: Decimal
    fee: Decimal             # copied from the charge, so fee drift stays I-FEE-DRIFT

def allocate_deposit(
    deposit: BankDepositRecord,
    charges: Sequence[PaymentRecord],
    tolerance: ReconciliationTolerance,
) -> tuple[Allocation, ...]:   # raises AmbiguousAllocation when 2+ sums balance
    ...

def reconcile_payout(
    deposit: BankDepositRecord,
    charges: Sequence[PaymentRecord],
    tolerance: ReconciliationTolerance,
    *,
    window_seconds: int | None = None,
) -> ReconciliationResult:     # one result for N charges against one deposit
    ...
```

Two constraints belong in the contract, not in the implementation:

- `Allocation.fee` is copied from the charge, so the existing classifier keeps
  returning `I-FEE-DRIFT` instead of mislabelling it.
- `allocate_deposit` must **refuse** to choose when more than one subset sums
  to the deposit; ambiguity is an outcome, not a tie-break.

Everything else — the normalizer, matcher, classifier, fingerprints, and
`I-REFUND-LAG` / `I-FEE-DRIFT` / `I-DUPLICATE` — is sufficient as it stands.
