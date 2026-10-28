# Design: Bank Deposits and Payout Allocation

## Context

`finance/reconciliation/` is a frozen, pure core: `normalize → match → classify`, with `Decimal` money, no clock,
no randomness, no I/O. It assumes one expected leg and one observed leg. Settlement violates that assumption in two
independent ways, and the triangle fixture measured both:

1. **Cardinality.** One deposit settles N charges. The core cannot represent N:1, so it refuses with
   `InvariantViolation`.
2. **Provenance.** The deposit is net of fees the bank never itemizes. Any fee the system needs must come from the
   processor or ledger leg, not from the statement.

A third property matters and is easy to get wrong: the relation is **not transitive**. invoice = charge and
charge = deposit does not imply invoice = deposit, because fees are removed between the second and third legs. The
core must never be asked to infer the third edge.

## Goals / Non-Goals

### Goals

1. Normalize a bank CSV row into a validated `BankDepositRecord` with tenant-declared mapping.
2. Allocate one deposit across a bounded candidate set of charges, deterministically and order-independently.
3. Report ambiguity rather than resolving it.
4. Distinguish three states that the one-to-one contract collapses: matched, mismatched, and not-yet-visible.
5. Keep every step pure and Decimal-only so it is unit-testable without a database or network.

### Non-Goals

N:1 charge aggregation into a synthetic single payment, approximate/maximum-subset allocation, heuristic column
guessing, statement deduplication across files, and any write path.

## Decisions

### D1 — Allocation is exact subset enumeration over a bounded candidate window

`allocate_deposit` enumerates subsets of *visible, unconsumed* charges whose `net` sum, plus the fee provenance,
reproduces the deposit within tolerance. It is exact, not greedy: greedy allocation is what produces the silent
wrong answer on `970.00` against `[388, 291, 291, 970]`, where the greedy first-fit takes the 970 charge and hides
the three-charge alternative.

Cost is exponential in candidate count, so the candidate set is bounded (`MAX_ALLOCATION_CANDIDATES = 20`). Beyond
the bound the result is `requires_human` — never a partial or approximate allocation. The bound is a declared
constant with a test, not an implicit loop guard.

**Rejected:** greedy/largest-first (silently wrong, above), dynamic programming (does not enumerate *distinct*
allocations, so it cannot detect ambiguity), and any approach that returns one allocation without reporting the
others.

### D2 — Ambiguity is an outcome, not a tie-break

If two or more distinct subsets reproduce the deposit within tolerance, the result is `AmbiguousAllocation` carrying
every candidate subset. Deterministic ordering of the *report* is allowed; selecting among them is not. The existing
`classify` tie-break order (refund → fee → gross) is about classifying one already-chosen pair and is untouched.

This is deliberately stricter than the matcher: `find_match` returns the first adequate candidate, which is
acceptable for a single-leg lookup and unacceptable for a money-moving allocation.

### D3 — Fee provenance is copied, never parsed

`Allocation.fee` is the sum of `fee` on the allocated charge legs. It is never read from the statement, never
inferred from `deposit.amount - invoice_total`, and never defaulted to zero when the difference is unexplained. If
the allocated charges' fees do not explain the gap, the outcome is `I-FEE-DRIFT`; if they do, the gap is closed and
the case is not an exception.

Consequence: an unenriched bank leg (`gross=971.00, fee=0`) cannot by itself produce a correct fee verdict. That is
expected and is why the API takes charges, not a pre-built bank leg.

### D4 — Partial settlement is a first-class outcome

When the best available allocation leaves a residual larger than tolerance, the result is
`EXCEPTION` with `I-PARTIAL` and `residual = deposit.amount - allocated_total - fee_total`. The allocation is still
returned so the invoice's remaining balance is visible. `I-REFUND-LAG` is not used for this: a missing 400.00 of a
1000.00 invoice is not a refund, and classifying it as one is the defect the fixture records.

### D5 — "Not yet visible" is distinct from "does not add up"

`PENDING_EVIDENCE` means: no candidate set exists **because** every plausible charge is outside `window_seconds`,
or there are no charges at all. `EXCEPTION` means candidates exist inside the window and the money does not
reconcile. This is what lets a charge with no deposit, and a deposit whose charges have not posted, both be
represented instead of returning nothing.

### D6 — Deduplication runs before allocation

`duplicate=True` reaches `classify` only after the tolerance check, so an exact duplicate closes as `MATCHED` and
never surfaces as `I-DUPLICATE`; a drifted duplicate (150.00 vs 148.00) does surface. Allocation must therefore
consume a deduplicated candidate list, keyed on the existing fingerprint, and must never allocate the same
`payment_id` twice in one run.

### D7 — Exception taxonomy grows additively

New codes are appended: `I-PARTIAL` (partial settlement) and `I-PAYOUT` (allocated set does not reproduce the
deposit for a reason other than partial/refund/fee). Existing values, their string forms, and their order in
`classify` are unchanged, so persisted `exception_code` values remain valid.

### D8 — Statement normalization fails loudly, per row

Tenant config declares column names, amount unit (major/minor), sign convention (signed column, or separate
debit/credit columns), date format, and currency. There is no header autodetection. A row that cannot be parsed is
returned as a `RejectedRow` with the source line number and reason; it is never dropped, zero-filled, or coerced.
A statement where any row is rejected yields an ingest result that names the rejects, so coverage is auditable.

## Risks

- **Candidate explosion.** A tenant with hundreds of open charges on one deposit hits the cap and always gets
  `requires_human`. Mitigated by scoping candidates to the window and to the same currency before enumeration.
- **Ambiguity noise.** Legitimate repeated amounts (three 291.00 charges) can produce many equal-sum subsets. The
  outcome stays ambiguous by design; operators resolve it, and the report lists the subsets rather than a count.
- **Cross-tenant leakage.** Allocation must filter candidates by `tenant_id` before enumeration, matching the
  existing tenant-scoped matcher.

## Open Questions

1. Should `residual` on a partial allocation be a separate field or derived from `difference`? Proposal assumes a
   separate, explicitly-signed field so `difference` keeps its existing meaning on the pair path.
2. Is `MAX_ALLOCATION_CANDIDATES = 20` acceptable for the largest real tenant, or should the bound be configurable
   per tenant?

## Acceptance Conditions (approval S0.6)

Approval is conditional on the specification enforcing these. Each maps to a requirement and a test.

| # | Condition | Requirement | Enforcing test |
|---|---|---|---|
| 1 | Conservation: allocated + fees + residual reconcile to the deposit; no residual silently discarded | Monetary Conservation and Rounding Policy | `test_conservation_holds_across_three_charges`, `test_unexplained_remainder_is_reported` |
| 2 | Provenance: every allocation links deposit, statement line, charge, and fingerprints | Allocation Provenance and Idempotency | `test_allocation_carries_provenance`, `test_replay_is_byte_identical` |
| 3 | Tenant isolation: declared by trusted context, enforced in allocation | Tenant Isolation for Import and Allocation | `test_cross_tenant_charge_rejected`, `test_row_tenant_is_ignored` |
| 4 | Ambiguity unresolved | Ambiguity Is an Outcome | `test_s7_ambiguous_allocation_is_reported_as_ambiguous` |
| 5 | Partial evidence distinct from mismatch | Payout Reconciliation Outcomes | `test_s5b_missing_deposit_yields_an_unmatched_expected_state` |
| 6 | Idempotency: re-import and replay create no duplicates | Allocation Provenance and Idempotency | `test_reimport_is_deduplicated`, `test_replay_yields_one_allocation` |

Deterministic reasons cover the cases that previously surfaced as implicit exceptions: unexplained fee (`FEE_DRIFT`),
refund not explained by the legs (`REFUND_LAG`), currency difference (`CURRENCY_MISMATCH`), missing payout record
(`NO_DEPOSIT`), outside the settlement window (`OUTSIDE_WINDOW`), candidate cap (`CANDIDATE_LIMIT`), ambiguity
(`AMBIGUOUS`), and mixed-currency payout (`FX_UNSUPPORTED`, `REQUIRES_HUMAN`).

## Adjudications (2026-10-28)

Two examples in `specs/reconciliation/spec.md` were internally inconsistent;
the normative requirements they illustrated were not. Both are recorded and
corrected in `openspec/changes/correct-payout-classification-scenarios/`:

- **Zero-fee shortfall.** "Fee drift from a zero-fee leg" demanded
  `I-FEE-DRIFT` for a 29.00 shortfall with no fee evidence, contradicting the
  `I-PARTIAL` rule in this change. Classification follows evidence: an
  unexplained shortfall is `I-PARTIAL`; `I-FEE-DRIFT` requires fee evidence.
  No implementation change.
- **Conservation arithmetic.** The conservation example paired nets
  `388/291/291` with fees `11/9/9`, which total 29.00 and imply a net of
  971.00. The invariant is unchanged; the corrected example uses gross
  `400/300/300` and fees `12/9/9`.

This section is the decision record; the corrected scenarios live in the
follow-up change so this change's reviewed text remains history.
