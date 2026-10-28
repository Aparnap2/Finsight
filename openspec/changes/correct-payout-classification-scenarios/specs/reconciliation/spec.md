## MODIFIED Requirements

### Requirement: Fee and Refund Provenance
The system SHALL attribute fees and refunds from the processor or ledger legs only. A bank statement MUST NEVER be
the source of a fee or refund value.

- `Allocation.fee_total` MUST equal the sum of `fee` on the allocated charge legs.
- The system MUST NOT derive a fee or refund by subtracting an allocated total from a deposit amount and labelling
  the difference.
- A shortfall alone MUST NOT be reported as `I-FEE-DRIFT`: an unexplained shortfall is an open balance and MUST be
  reported as `I-PARTIAL`. `I-FEE-DRIFT` requires fee evidence — at least one allocated leg carries a non-zero fee
  and the unallocated remainder is not explained by `fee_total`.
- A gap MUST NOT be attributed to a refund unless the charge legs carry refund evidence.

#### Scenario: Unexplained shortfall is partial, not fee drift
- **WHEN** a charge with `gross="1000.00"`, `fee="0.00"`, `net="1000.00"` is allocated against a `971.00` deposit
- **THEN** the outcome is `EXCEPTION` with `I-PARTIAL` and reason `PARTIAL`, `allocated_total` is `971.00`,
  `open_balance` is `29.00`, `unallocated_deposit` is `0.00`, and `fee_total` is `0.00`

#### Scenario: Fee drift requires fee evidence
- **WHEN** charges with `gross="1000.00"`, `fee="29.00"`, `net="971.00"` and `gross="30.00"`, `fee="0.00"`,
  `net="30.00"` are allocated against a `1031.00` deposit
- **THEN** the outcome is `EXCEPTION` with `I-FEE-DRIFT` and reason `FEE_DRIFT`, `fee_total` is `29.00`,
  `allocated_total` is `1001.00`, and `unallocated_deposit` is `30.00`

#### Scenario: Fee explained by the charge leg
- **WHEN** a charge with `gross="1000.00"`, `fee="29.00"`, `net="971.00"` is allocated against a `971.00` deposit
- **THEN** the outcome is `MATCHED`, `fee_total` is `29.00`, and no exception code is set

### Requirement: Monetary Conservation and Rounding Policy
The system SHALL conserve money exactly across normalization, allocation, and reporting. No residual may be
discarded, rounded away, or absorbed without being named.

- Every allocation MUST satisfy, in exact `Decimal` arithmetic:
  `allocated_total + unallocated_deposit == deposit.amount`,
  `allocated_total + open_balance == sum(net of every eligible charge)`,
  `fee_total == sum(allocated leg fee)`, `refund_total == sum(allocated leg refund)`, and
  `sum(allocated leg gross) - fee_total - refund_total == allocated_total`.
- `unallocated_deposit` and `open_balance` are signed; a negative value is a real shortfall and is reported, never
  clamped away.
- A non-zero `unallocated_deposit` or `open_balance` MUST be reported as its own field and MUST determine the
  outcome; it MUST NOT be folded into `fee_total`, `refund_total`, or tolerance.
- One allocation MUST cover exactly one currency. FX conversion MUST NOT occur anywhere on the path.
- Money MUST be quantized to the currency's minor unit at the normalization boundary, using a declared exponent
  (2 for USD/EUR/GBP, 0 for JPY, 3 for KWD/BHD; unknown codes require an explicit declared exponent).
- The allocator MUST NOT quantize or round. A computed amount carrying more precision than the currency minor unit
  MUST be rejected as an invariant violation rather than rounded.
- Tolerance MUST NOT be used to hide a residual: a difference inside tolerance changes the outcome only, never the
  reported amounts.

#### Scenario: Conservation holds for a three-charge payout
- **WHEN** charges with `gross` `400.00`, `300.00`, `300.00` and `fee` `12.00`, `9.00`, `9.00` settle a `970.00` deposit
- **THEN** the nets are `388.00`, `291.00`, `291.00`, `allocated_total` is `970.00`, `fee_total` is `30.00`,
  `unallocated_deposit` and `open_balance` are `0.00`, and
  `sum(gross) - fee_total - refund_total` equals `970.00`

#### Scenario: Over-precise residual rejected
- **WHEN** allocation arithmetic would produce a residual of `0.001` in USD
- **THEN** the system raises an invariant violation instead of rounding the residual to `0.00`

#### Scenario: Unexplained remainder is named, not absorbed
- **WHEN** a `971.00` deposit has exactly one visible `900.00` charge
- **THEN** `unallocated_deposit` is `71.00` and the outcome carries reason `UNALLOCATED_DEPOSIT`, even if `71.00`
  is inside the injected tolerance
