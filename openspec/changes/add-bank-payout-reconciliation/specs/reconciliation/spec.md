## ADDED Requirements

### Requirement: BankDepositRecord
The system SHALL normalize every bank statement deposit into a `BankDepositRecord` with `deposit_id`, `tenant_id`,
`provider`, `amount`, `currency`, `direction`, `posted_at`, `reference`, `source_reference`, and `idempotency_key`.

- `amount` MUST be `MoneyDecimal` and MUST be positive; sign is carried by `direction` (`CREDIT | DEBIT`) and MUST
  NOT be encoded in `amount`.
- The system MUST reject `float` amounts at the validation boundary and MUST validate `currency` as ISO 4217.
- The system MUST require `posted_at` to be tz-aware and MUST require `deposit_id`, `tenant_id`, and
  `idempotency_key` to be non-empty strings.
- The system MUST allow `reference` to be null; a bank narrative is opaque and MUST NOT be treated as a payment id.
- The record MUST NOT contain `fee` or `refund` fields; those originate on the processor or ledger leg only.

#### Scenario: Valid deposit normalized
- **WHEN** a statement row yields `amount="971.00"`, currency `USD`, `direction=CREDIT`, a tz-aware `posted_at`, and a
  present `idempotency_key`
- **THEN** the system produces a `BankDepositRecord` with a positive Decimal `amount`, no fee field, and the
  timestamp preserved in UTC

#### Scenario: Float or naive timestamp rejected
- **WHEN** a row supplies `amount` as a JSON float or `posted_at` without a timezone
- **THEN** the system rejects the record with a validation error naming the offending field and creates no
  `BankDepositRecord`

### Requirement: Tenant-Declared Statement Normalization
The system SHALL normalize bank CSV statements using a mapping declared per tenant, not inferred from headers.

- The mapping MUST declare column names, amount unit (`MAJOR | MINOR`), sign convention (`SIGNED`, or
  `DEBIT_CREDIT` with a separate credit column), date format, and the statement currency.
- The system MUST reject a mapping that omits any required field, and MUST reject a row whose currency disagrees
  with the mapping.
- The system MUST NOT guess a column by fuzzy header match, MUST NOT coercing an unparsable amount to zero, and
  MUST NOT drop a row.
- Every unparsable row MUST be returned as a `RejectedRow` carrying the source line number and reason; the ingest
  result MUST expose the rejected rows and a row count so coverage is auditable.
- Normalization MUST be pure and deterministic: the same bytes and mapping MUST produce the same records and the
  same rejects.

#### Scenario: Unparsable row surfaced, not dropped
- **WHEN** a statement of 3 rows contains one row whose amount cell is empty
- **THEN** the result contains 2 `BankDepositRecord`s and 1 `RejectedRow` naming line 3 and the reason, and the
  result reports 3 rows read

#### Scenario: Duplicate header present twice
- **WHEN** a mapping names a column that appears twice in the file
- **THEN** ingest fails with a mapping error before any row is normalized, rather than reading the first match

### Requirement: Fee and Refund Provenance
The system SHALL attribute fees and refunds from the processor or ledger legs only. A bank statement MUST NEVER be
the source of a fee or refund value.

- `Allocation.fee_total` MUST equal the sum of `fee` on the allocated charge legs.
- The system MUST NOT derive a fee or refund by subtracting an allocated total from a deposit amount and labelling
  the difference.
- When a charge leg carries `fee="0.00"` and the deposit is short by the processor fee, the system MUST report the
  gap as `I-FEE-DRIFT`, not as `I-REFUND-LAG`, and MUST NOT attribute the gap to a refund.

#### Scenario: Fee drift from a zero-fee leg
- **WHEN** a charge with `gross="1000.00"`, `fee="0.00"`, `net="1000.00"` is allocated against a `971.00` deposit
- **THEN** the outcome is `EXCEPTION` with `I-FEE-DRIFT` and a `29.00` discrepancy, and `fee_total` is `0.00`

#### Scenario: Fee explained by the charge leg
- **WHEN** a charge with `gross="1000.00"`, `fee="29.00"`, `net="971.00"` is allocated against a `971.00` deposit
- **THEN** the outcome is `MATCHED`, `fee_total` is `29.00`, and no exception code is set

### Requirement: Deposit-to-Charge Allocation
The system SHALL allocate one deposit across a set of charges, expressing many-to-one settlement.

- `allocate_deposit(deposit, charges, tolerance)` MUST return an `Allocation` with the allocated legs, each leg's
  `payment_id` and allocated amount, plus `allocated_total`, `fee_total`, `unallocated_deposit`, and `open_balance`.
- `allocated_total` MUST equal the sum of allocated leg amounts in Decimal arithmetic, and `unallocated_deposit`
  MUST equal `deposit.amount - allocated_total`.
- `open_balance` MUST equal the sum of allocated charges' `net` minus `allocated_total`, so a partially settled
  charge exposes its remainder.
- Each charge MUST be allocated at most once, and only charges with a matching `tenant_id` and currency SHALL be
  candidates.
- A charge MAY be allocated partially; partial allocation MUST NOT mark the charge settled.
- The result MUST be independent of candidate input order: permuting `charges` MUST produce an identical allocation.
- Allocation MUST be exact. When the number of candidates exceeds the declared bound, the system MUST return
  `requires_human` and MUST NOT return an approximate allocation.

#### Scenario: Three charges settled by one deposit
- **WHEN** charges with `net` `388.00`, `291.00`, and `291.00` are allocated against a `970.00` deposit
- **THEN** `allocated_total` is `970.00`, `unallocated_deposit` is `0.00`, and `open_balance` is `0.00`

#### Scenario: Partial settlement exposes an open balance
- **WHEN** a charge with `net="1000.00"` is allocated against a `600.00` deposit
- **THEN** the allocation reports `allocated_total="600.00"`, `unallocated_deposit="0.00"`,
  `open_balance="400.00"`, and the outcome is `EXCEPTION` with `I-PARTIAL`

#### Scenario: Order independence
- **WHEN** the same candidate list is supplied in two different orders
- **THEN** both calls return an identical allocation, including leg order in the report

### Requirement: Ambiguity Is an Outcome
The system SHALL report allocation ambiguity and MUST NOT resolve it by tie-breaking.

- When two or more distinct candidate subsets reproduce the deposit within tolerance, the result MUST be
  `AmbiguousAllocation` carrying every candidate subset.
- The system MUST NOT prefer a subset by recency, id, size, or insertion order.
- Candidacy MUST be symmetric: if subsets A and B both satisfy tolerance, neither MAY be omitted from the report.
- Reporting order MAY be deterministic; selection MUST NOT occur.

#### Scenario: Single charge and three-charge subset both match
- **WHEN** a `970.00` deposit is allocated against charges with `net` `388.00`, `291.00`, `291.00`, and `970.00`
- **THEN** the result is `AmbiguousAllocation` listing both the single `970.00` candidate and the
  `{388.00, 291.00, 291.00}` subset

#### Scenario: Ambiguity is not silently resolved for the caller
- **WHEN** the caller attempts to read a single chosen allocation from an ambiguous result
- **THEN** no chosen allocation is available, and the caller must resolve the ambiguity explicitly

### Requirement: Payout Reconciliation Outcomes
The system SHALL reconcile a deposit against its candidate charges and return exactly one outcome from
`MATCHED | TOLERANCE_MATCHED | EXCEPTION | PENDING_EVIDENCE | REQUIRES_HUMAN`.

- `MATCHED` requires `unallocated_deposit` and `open_balance` to be zero, and every allocated leg to fall within
  `window_seconds` of the deposit when a window is supplied.
- `TOLERANCE_MATCHED` requires both residuals to be within the injected tolerance and non-zero.
- `PENDING_EVIDENCE` MUST be returned when no candidate is visible: no charges at all, or every plausible charge
  lies outside `window_seconds`. It MUST NOT be returned when a visible candidate set exists and simply fails to
  reconcile.
- `EXCEPTION` MUST carry exactly one code: `I-PARTIAL` when an open balance remains after the deposit is absorbed,
  `I-FEE-DRIFT` when the allocated fees do not explain the gap, `I-DUPLICATE` when duplicate legs remain after
  deduplication, and `I-PAYOUT` otherwise.
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

### Requirement: Deduplication Precedes Allocation
The system SHALL deduplicate candidate charges before allocating.

- Deduplication MUST use the existing fingerprint over normalized fields and MUST run before enumeration, because
  the tolerance check precedes classification and an exact duplicate otherwise closes as `MATCHED`.
- A `payment_id` MUST NOT be allocated more than once within a reconciliation run.
- A duplicate that survives deduplication because its amount drifted MUST produce `I-DUPLICATE` and MUST NOT be
  silently allocated as a separate leg.

#### Scenario: Drifted duplicate is not allocated twice
- **WHEN** a `150.00` charge and a `148.00` charge share a fingerprint and one `148.00` deposit is presented
- **THEN** the outcome is `EXCEPTION` with `I-DUPLICATE`, and only one leg is allocated

#### Scenario: Exact duplicate never reaches allocation as two legs
- **WHEN** two identical charges with the same fingerprint are presented with a deposit equal to one of them
- **THEN** deduplication leaves one candidate, the outcome is `MATCHED`, and no duplicate leg appears

### Requirement: No Transitive Inference Across Edges
The system SHALL reconcile each edge of the payment chain independently and MUST NOT infer a third edge from two
matching edges.

- An invoice-to-charge match and a charge-to-deposit match MUST NOT be combined into an assertion that the invoice
  equals the deposit.
- The invoice-to-deposit comparison MUST be performed, or explicitly reported as out of scope, by the caller.
- The system MUST preserve per-edge results so an auditor can see which edges matched and which did not.

#### Scenario: Two matching edges with an unequal third
- **WHEN** an invoice matches its charge exactly and that charge's net matches the deposit exactly
- **THEN** the system does not assert invoice-to-deposit equality, and comparing the invoice gross to the deposit
  reports a `29.00` difference

#### Scenario: Edge results remain distinguishable
- **WHEN** an invoice-to-deposit comparison is derived from two reconciled edges
- **THEN** the result identifies the edge it was computed on, and does not overwrite the charge-level result

### Requirement: Additive Exception Taxonomy Extension
The system SHALL extend the exception taxonomy additively with `PARTIAL_SETTLEMENT="I-PARTIAL"` and
`PAYOUT_MISMATCH="I-PAYOUT"`.

- `PARTIAL_REFUND_ACCOUNTING_LAG="I-REFUND-LAG"`, `FEE_MISMATCH="I-FEE-DRIFT"`, and
  `DUPLICATE_LEDGER_ENTRY="I-DUPLICATE"` MUST keep their existing string values.
- The existing `classify` order (refund, then fee, then gross) MUST remain unchanged for the one-to-one path.
- `I-PARTIAL` MUST be emitted only for a residual open balance, and MUST NOT be emitted for a refund or a fee gap.
- Persisted records carrying an existing code MUST remain readable without migration.

#### Scenario: Partial is not reported as a refund
- **WHEN** a `1000.00` charge is settled by a `600.00` deposit with no refund event
- **THEN** the code is `I-PARTIAL` and no `I-REFUND-LAG` is emitted

#### Scenario: Existing codes unchanged
- **WHEN** an existing persisted record carries `I-REFUND-LAG`, `I-FEE-DRIFT`, or `I-DUPLICATE`
- **THEN** it deserializes to the same enum member and its `exception_code` string is unchanged
