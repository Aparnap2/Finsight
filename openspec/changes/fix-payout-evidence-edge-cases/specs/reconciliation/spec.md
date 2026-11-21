## MODIFIED Requirements

### Requirement: Payout Reconciliation Outcomes
The system SHALL reconcile a deposit against its candidate charges and return exactly one outcome from
`MATCHED | TOLERANCE_MATCHED | EXCEPTION | PENDING_EVIDENCE | REQUIRES_HUMAN`.

- `MATCHED` requires `unallocated_deposit` and `open_balance` to be zero, and every allocated leg to fall within
  `window_seconds` of the deposit when a window is supplied.
- `TOLERANCE_MATCHED` requires both residuals to be within the injected tolerance and non-zero.
- `PENDING_EVIDENCE` MUST be returned when no candidate is visible: no charges at all, or every plausible charge
  lies outside `window_seconds`. It MUST NOT be returned when a visible candidate set exists and simply fails to
  reconcile.
- A deposit with no visible charge legs MUST be `PENDING_EVIDENCE` with reason `NO_CANDIDATE` and the full deposit
  left in `unallocated_deposit`. The absence of processor evidence MUST NOT be reported as `MATCHED`, `I-PARTIAL`,
  or `I-PAYOUT`, and MUST NOT be treated as a reconciled zero-value payment.
- A call with neither a deposit nor a charge MUST be rejected as an invariant violation, because no tenant or
  currency can be scoped from empty evidence.
- `EXCEPTION` MUST carry exactly one code: `I-PARTIAL` when an open balance remains after the deposit is absorbed,
  `I-FEE-DRIFT` when the allocated fees do not explain the gap, `I-DUPLICATE` when duplicate legs remain after
  deduplication, and `I-PAYOUT` otherwise.
- Every non-closing outcome MUST also carry exactly one deterministic `reason`, distinguishing at minimum
  `PARTIAL`, `FEE_DRIFT`, `REFUND_LAG`, `DUPLICATE`, `CURRENCY_MISMATCH`, `UNALLOCATED_DEPOSIT`, `NO_DEPOSIT`,
  `OUTSIDE_WINDOW`, `NO_CANDIDATE`, `CANDIDATE_LIMIT`, `AMBIGUOUS`, and `FX_UNSUPPORTED`. The reason MUST be stable across runs for
  the same inputs.
- A refund that is not explained by the charge legs MUST produce `I-REFUND-LAG` with reason `REFUND_LAG`; it MUST
  NOT be absorbed into a partial allocation.
- A currency difference MUST NOT be converted or netted. A deposit whose currency differs from any candidate charge
  MUST raise `CurrencyMismatch` and produce no allocation, mirroring `reconcile()`.
- FX rates are never applied anywhere on the path; a caller needing cross-currency settlement must pre-split the
  payout per currency. `FX_UNSUPPORTED` is reserved for a payout that itself spans currencies.
- `REQUIRES_HUMAN` MUST be returned when the candidate count exceeds the allocation bound or an ambiguity was
  reported.
- Tolerance MUST be injected per call and MUST default to zero; the system MUST NOT hardcode a tolerance.

#### Scenario: Three-day settlement lag inside the window
- **WHEN** a deposit posts 72 hours after its charges and `window_seconds=259200`
- **THEN** the outcome is `MATCHED` and the same case with `window_seconds=3600` is `PENDING_EVIDENCE`

#### Scenario: Visible candidates that do not reconcile
- **WHEN** a `970.00` deposit has a single visible `900.00` charge inside the window
- **THEN** the outcome is `EXCEPTION` with `I-PAYOUT` and a `70.00` discrepancy, not `PENDING_EVIDENCE`

#### Scenario: Unsettled charge with no deposit
- **WHEN** a charge has no deposit candidate inside the window
- **THEN** the system reports `PENDING_EVIDENCE` for that charge rather than omitting it from the result

#### Scenario: Deposit with no processor legs is pending evidence
- **WHEN** a `600.00` deposit is presented with an empty charge sequence
- **THEN** the outcome is `PENDING_EVIDENCE` with reason `NO_CANDIDATE`, `allocated_total` is `0.00`,
  `eligible_net_total` is `0.00`, `open_balance` is `0.00`, `unallocated_deposit` is `600.00`, and no exception
  code is set

### Requirement: Deduplication Precedes Allocation
The system SHALL deduplicate candidate charges before allocating.

- Deduplication MUST use the existing fingerprint over normalized fields and MUST run before enumeration, because
  the tolerance check precedes classification and an exact duplicate otherwise closes as `MATCHED`.
- A `payment_id` MUST NOT be allocated more than once within a reconciliation run.
- A duplicate that survives deduplication because its amount drifted MUST produce `I-DUPLICATE` and MUST NOT be
  silently allocated as a separate leg.
- On the deposit surface, duplicate evidence declared by the caller MUST take precedence over residual
  classification. The result MUST report `I-DUPLICATE` with reason `DUPLICATE` while preserving the allocated
  legs and the computed residuals, so the amount discrepancy remains visible as `open_balance` or
  `unallocated_deposit`. The one-to-one `classify` order MUST remain unchanged.

#### Scenario: Drifted duplicate is not allocated twice
- **WHEN** a `150.00` charge and a `148.00` charge share a fingerprint and one `148.00` deposit is presented
- **THEN** the outcome is `EXCEPTION` with `I-DUPLICATE`, and only one leg is allocated

#### Scenario: Exact duplicate never reaches allocation as two legs
- **WHEN** two identical charges with the same fingerprint are presented with a deposit equal to one of them
- **THEN** deduplication leaves one candidate, the outcome is `MATCHED`, and no duplicate leg appears

#### Scenario: Drifted duplicate preserves its amount discrepancy
- **WHEN** a `150.00` charge is reconciled against a `148.00` deposit flagged as a re-imported duplicate
- **THEN** the outcome is `EXCEPTION` with `I-DUPLICATE` and reason `DUPLICATE`, one leg is allocated for
  `148.00`, `open_balance` is `2.00`, and `unallocated_deposit` is `0.00`

#### Scenario: Duplicate outranks fee-drift classification
- **WHEN** a `1000.00` charge carrying a `29.00` fee is reconciled against a `990.00` deposit flagged as a
  duplicate
- **THEN** the outcome is `EXCEPTION` with `I-DUPLICATE` and `unallocated_deposit` is `19.00`, not `I-FEE-DRIFT`
