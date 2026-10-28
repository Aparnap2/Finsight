# Three-source reconciliation: pairwise core vs payout surface

_Evidence: `tests/unit/reconciliation/test_triangle.py` over
`tests/fixtures/reconciliation/triangle/`. 21 checks, 0 strict xfails.
The pairwise `reconcile()` core is unchanged; payouts are handled by the
additive `reconcile_payout()` contract._

The scenario is a month of card revenue: an invoice register says what should
be paid, Stripe says what was charged, a bank statement says what landed.

## Handled by `reconcile_payout` (bank payout contract)

| Case | Behaviour |
|---|---|
| One deposit settles N charges (`388.00 + 291.00 + 291.00 = 970.00`) | `MATCHED`, `allocated_total 970.00`, `open_balance 0.00` |
| Deposit covers only part of one charge (600.00 vs 1000.00 net) | `EXCEPTION` / `I-PARTIAL`, `open_balance 400.00` |
| Two subsets both reproduce the deposit | `REQUIRES_HUMAN` / `AMBIGUOUS`, every candidate subset reported, no legs chosen |
| Charge with no bank line at all | `PENDING_EVIDENCE` / `NO_DEPOSIT`, `open_balance` equals the charge net |
| Deposit larger than every candidate | `EXCEPTION` / `I-PAYOUT` / `UNALLOCATED_DEPOSIT` |
| Fee gap not explained by charge fees | `EXCEPTION` / `I-FEE-DRIFT` / `FEE_DRIFT` |
| Cross-currency payout | `CurrencyMismatch`, no allocation |

## Handled by the remaining pairwise core

| Case | Behaviour |
|---|---|
| Exact agreement on all three legs | `MATCHED`, difference `0.00` |
| Stripe fee 29.00 between a 1000.00 invoice and a 971.00 deposit | `I-FEE-DRIFT`, `-29.00`, when the bank leg carries `gross=1000, fee=29` |
| Charge net vs deposit | `MATCHED`: Stripe's `net` already excludes the fee |
| Refund folded into net (1000 gross, 29 fee, 400 refund, 571 deposited) | `MATCHED` |
| Deposit arriving three days later | `find_match(..., window_seconds=259200)` matches; `3600` returns `None` |
| Duplicate bank import | `find_duplicates` groups by `idempotency_key`; `ensure_unique` raises |
| Duplicate that also drifted (150.00 vs 148.00) | `I-DUPLICATE` when `duplicate=True` |

## Still not representable on the pairwise surface

1. **A bank leg with no fee column.** A deposit is one credit. Normalized as
   its own `gross`, the 29.00 fee becomes a gross delta; the classifier has no
   gross-only code, so **a pure fee difference is reported as `I-REFUND-LAG`**
   (`test_s2_naive_bank_leg_misattributes_fee_drift_to_a_refund_lag`). The
   triangle is also not transitive: invoice = charge and charge = deposit, yet
   invoice ≠ deposit. Bank rows must be enriched from the processor leg.
2. **Underpayment on `reconcile()`.** A 400.00 shortfall with no refund is
   `I-REFUND-LAG`; pairwise has no partial-payment code, so it is
   indistinguishable from refund timing. `reconcile_payout()` reports it as
   `I-PARTIAL` (see above); the fixture keeps the pairwise characterization.
3. **Dedup ordering.** `duplicate=True` only reaches `classify` after the
   tolerance check fails, so an exact-matching duplicate closes as `MATCHED`.
   Dedup must run before `reconcile`; the core does not enforce that order.

Bank-statement ingestion is available through
`finance/reconciliation/bank.py` (`normalize_bank_statement`), not through the
pairwise core.

## Implemented contract

```python
# finance/reconciliation/bank.py
@dataclass(frozen=True)
class BankDepositRecord:
    deposit_id: str
    tenant_id: str
    amount: Decimal          # the statement line, never a float
    currency: str
    posted_at: datetime      # tz-aware
    statement_digest: str
    line_number: int
    fee: Decimal = Decimal("0")
    reference: str = ""
    ...

# finance/reconciliation/allocation.py
@dataclass(frozen=True)
class AllocationLeg:
    payment_id: str
    fingerprint: str
    net: Decimal             # charge net
    allocated: Decimal       # 0 < allocated <= net

def allocate_deposit(
    deposit: BankDepositRecord,
    charges: Sequence[PaymentRecord],
    tolerance: ReconciliationTolerance,
    *,
    max_candidates: int = MAX_ALLOCATION_CANDIDATES,
    tenant_id: str | None = None,
) -> Allocation: ...

def reconcile_payout(
    deposit: BankDepositRecord | None,
    charges: Sequence[PaymentRecord],
    tolerance: ReconciliationTolerance,
    *,
    window_seconds: int | None = None,
    max_candidates: int = MAX_ALLOCATION_CANDIDATES,
    tenant_id: str | None = None,
    now: datetime | None = None,
) -> Allocation: ...
```

Contract constraints, all enforced in `finance/reconciliation/allocation.py`:

- Leg fees are copied from the charge, so fee gaps stay `I-FEE-DRIFT` instead
  of being mislabelled as refund lags.
- Two or more subsets that reproduce the deposit are reported, never
  tie-broken on recency, id, size, or input order.
- `AllocationLeg.allocated` carries partial amounts; conservation is checked
  per leg (`0 < allocated <= net`) and in aggregate (`allocated_total`,
  `open_balance`, `unallocated_deposit`).

## Open adjudication notes

- The spec's "Fee drift from a zero-fee leg" scenario (charge net 1000.00,
  fee 0.00, deposit 971.00 ⇒ `I-FEE-DRIFT`) collides with its own
  `I-PARTIAL` rule: a 971.00 deposit against a 1000.00 charge is a residual
  open balance, so the implemented precedence reports `I-PARTIAL`.
  `I-FEE-DRIFT` is emitted when the charge legs carry fees that do not
  explain the shortfall. The spec scenario is left untouched for
  adjudication rather than silently rewritten.
- The conservation scenario lists nets `388.00/291.00/291.00` with fees
  `11.00/9.00/9.00`, which cannot come from whole-number grosses; the fixture
  uses fees `12.00/9.00/9.00`. The normative sentence is satisfied either way.
