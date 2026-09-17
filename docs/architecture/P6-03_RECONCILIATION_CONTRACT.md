# P6-03 Reconciliation and Detection Contract — Meridian Commerce

**Status:** Draft spec for P6-03 on `feat/finsight-p6-03-reconciliation-detection`.
**Base:** `7d0d93f` (P6-02 merge). P6-02 lifecycle semantics are FROZEN.
**Scope:** Single company (`company_id = meridian`, INR, Decimal-only money).
**Sources:** `docs/domain/meridian-process-model.md` (§1 entities, §2 lifecycle,
§4 FS-231), `docs/architecture/P6-01_INTEGRATION_CONTRACTS.md` (C-RAZORPAY,
C-QUICKBOOKS, C-SHEETS stub, C-GMAIL, C-SLACK stub, C-LEGACY).
**Type:** DOC-ONLY. No code, no agent changes, no P1 edits, no new services.

Conventions: `tenant_id` in older code/docs means `company_id = meridian`
plus `environment` (dev / staging / prod). All money is `Decimal` with
2 dp; `float` is forbidden everywhere in this contract. FinSight owns
reasoning state; source systems own facts. The LLM never creates facts,
never computes money, and never approves, executes, or mutates policy.

P1 core is frozen: this spec WRAPS P1 engine behavior behind the fact
and equation contracts below. The P1 engine inventory runs in parallel
and is cited by name only; this spec does not depend on its internals.

## 0. Lifecycle freeze (normative)

P6-02 lifecycle states are FROZEN. This spec adds, renames, and redefines
nothing. The canonical forward chain is:

```text
DETECTED -> TRIAGED -> INVESTIGATING -> CORRELATED -> EXPLAINED
  -> PROPOSED -> APPROVED -> EXECUTING -> VERIFYING -> CLOSED
```

Side states: `ESCALATED` and `REJECTED` only, with the re-entry rules
from the process model (§2.1) and the banned transitions (§2.2).

There is NO `MATCHED` lifecycle state. `MATCHED` and `WITHIN_TOLERANCE`
(§3) are reconciliation classification outcomes, not states. A
reconciled-clean outcome means NO `FinancialSituation` is created at
all: clean batches leave no case object, no `DETECTED` entry, and no
lifecycle footprint. Only a discrepancy classification listed in §4.1
creates a `FinancialSituation` in `DETECTED`.

## 1. Canonical facts (detection inputs)

Detection consumes exactly six fact shapes. Every fact is produced by a
deterministic adapter over an owning source system (P6-01 contracts);
the LLM NEVER creates, edits, or backfills facts. A fact missing any
required field, carrying a `float` amount, carrying a non-INR currency,
carrying a naive (tz-unaware) timestamp, or missing provenance is
REJECTED at the boundary and classified per §3 (`INSUFFICIENT_EVIDENCE`
or rejection rules in §1.7). Rejected facts never enter equations.

### 1.1 PaymentFact (owns: Razorpay via C-RAZORPAY)

| Field | Type | Notes |
|-------|------|-------|
| `external_id` | `str` | Razorpay `payment_id` (provider truth) |
| `source_system` | `str` | Always `razorpay` |
| `company_id` | `str` | Always `meridian` |
| `merchant_id` | `str` | Payee merchant key |
| `gross_amount` | `Decimal` | Gross captured, INR, 2 dp |
| `fee_amount` | `Decimal` | Fee slice, INR, 2 dp |
| `currency` | `str` | Always `INR` (else reject, §1.7) |
| `captured_at` | `datetime` | Tz-aware provider timestamp |
| `ingested_at` | `datetime` | Tz-aware FinSight ingest time |
| `status` | `str` | `CAPTURED`, `REFUNDED`, `ADJUSTED` |
| `provenance` | `str` | Ingest path, e.g. adapter + run id |
| `source_version` | `str` | Adapter/schema version string |
| `source_hash` | `str` | Content hash of the source record |

### 1.2 RefundFact (owns: Razorpay via C-RAZORPAY)

| Field | Type | Notes |
|-------|------|-------|
| `external_id` | `str` | Razorpay `refund_id` |
| `source_system` | `str` | Always `razorpay` |
| `company_id` | `str` | Always `meridian` |
| `merchant_id` | `str` | Payee merchant key |
| `payment_id` | `str` | Parent `payment_id` |
| `amount` | `Decimal` | Refund amount, INR, 2 dp |
| `currency` | `str` | Always `INR` (else reject, §1.7) |
| `issued_at` | `datetime` | Tz-aware provider timestamp |
| `ingested_at` | `datetime` | Tz-aware FinSight ingest time |
| `reason` | `str` | Reason code / note |
| `provenance` | `str` | Ingest path, e.g. adapter + run id |
| `source_version` | `str` | Adapter/schema version string |
| `source_hash` | `str` | Content hash of the source record |

### 1.3 SettlementFact (owns: Razorpay via C-RAZORPAY)

Provider-computed settlement leg for one batch window. Carries the
signed adjustment total and the pending (not-yet-settled) total as
separate fields so the equation in §2 stays unambiguous.

| Field | Type | Notes |
|-------|------|-------|
| `external_id` | `str` | Provider settlement/batch reference |
| `source_system` | `str` | Always `razorpay` |
| `company_id` | `str` | Always `meridian` |
| `merchant_id` | `str` | Merchant key, or `MULTI` for a batch |
| `batch_id` | `str` | Settlement window key |
| `gross_amount` | `Decimal` | Window gross, INR, 2 dp |
| `fee_total` | `Decimal` | Window fee slice sum, INR, 2 dp |
| `refund_total` | `Decimal` | Window refund sum, INR, 2 dp |
| `adjustments_total` | `Decimal` | SIGNED sum, INR, 2 dp |
| `pending_total` | `Decimal` | Not-yet-settled, INR, tracked apart |
| `currency` | `str` | Always `INR` (else reject, §1.7) |
| `settled_at` | `datetime` | Tz-aware provider timestamp |
| `ingested_at` | `datetime` | Tz-aware FinSight ingest time |
| `provenance` | `str` | Ingest path, e.g. adapter + run id |
| `source_version` | `str` | Adapter/schema version string |
| `source_hash` | `str` | Content hash of the source record |

### 1.4 AccountingEntryFact (owns: QuickBooks via C-QUICKBOOKS)

| Field | Type | Notes |
|-------|------|-------|
| `external_id` | `str` | QB `entry_id` (`MOCK-` prefix in sandbox) |
| `source_system` | `str` | Always `quickbooks` |
| `company_id` | `str` | Always `meridian`; scope miss = refuse |
| `merchant_id` | `str` | Merchant key from `source_reference` |
| `account_code` | `str` | Static AccountMappings code |
| `debit` | `Decimal` | Debit leg, INR, 2 dp |
| `credit` | `Decimal` | Credit leg, INR, 2 dp |
| `currency` | `str` | Always `INR` (else reject, §1.7) |
| `period` | `str` | Accounting period (closed blocks read) |
| `posted_at` | `datetime` | Tz-aware posting timestamp |
| `ingested_at` | `datetime` | Tz-aware FinSight ingest time |
| `provenance` | `str` | Ingest path, e.g. adapter + run id |
| `source_version` | `str` | Adapter/schema version string |
| `source_hash` | `str` | Content hash of the source record |

### 1.5 ExpectedSettlementFact (owns: Sheets via C-SHEETS stub)

Advisory business view. NEVER authoritative over provider, accounting,
or legacy legs. Until the C-SHEETS stub binding lands, values arrive
via the `InMemoryLedgerRepository` fixture and are fenced as DATA.

| Field | Type | Notes |
|-------|------|-------|
| `external_id` | `str` | `spreadsheet_id:range:content_hash` |
| `source_system` | `str` | Always `sheets` |
| `company_id` | `str` | Always `meridian` |
| `merchant_id` | `str` | Merchant key, or `MULTI` for a batch |
| `batch_id` | `str` | Settlement window key |
| `expected_total` | `Decimal` | Expected settlement, INR, 2 dp |
| `currency` | `str` | Always `INR` (else reject, §1.7) |
| `period` | `str` | Business period label |
| `observed_at` | `datetime` | Tz-aware read timestamp |
| `ingested_at` | `datetime` | Tz-aware FinSight ingest time |
| `provenance` | `str` | Fixture id / read path + run id |
| `source_version` | `str` | Reader/schema version string |
| `source_hash` | `str` | Content hash (dedupe key for reads) |

### 1.6 LegacyPostingFact (owns: COBOL ledger via C-LEGACY)

| Field | Type | Notes |
|-------|------|-------|
| `external_id` | `str` | `batch_id:sequence` (8-digit sequence) |
| `source_system` | `str` | Always `cobol_legacy` |
| `company_id` | `str` | Always `meridian` |
| `merchant_id` | `str` | Merchant key from the record |
| `batch_id` | `str` | `LEGACY-YYYYMMDD-NNNN` |
| `account_code` | `str` | Posting account code |
| `amount` | `Decimal` | Record amount, INR, 2 dp |
| `currency` | `str` | Always `INR` (else reject, §1.7) |
| `disposition` | `str` | `AC`, `RJ`, or `DU` from result file |
| `reject_reason` | `str \| None` | Verbatim reason, e.g. reason string |
| `posted_at` | `datetime` | Tz-aware result-file timestamp |
| `ingested_at` | `datetime` | Tz-aware FinSight ingest time |
| `provenance` | `str` | S3 key + result-file id + run id |
| `source_version` | `str` | Protocol version, currently `01` |
| `source_hash` | `str` | Line checksum + content hash |

### 1.7 Boundary rejection rules (normative)

1. `float` amounts are rejected. Any amount field arriving as `float`
   (or bool, or scaled int without Decimal conversion inside the
   adapter) is rejected at the boundary; the fact never exists.
2. INR-only. Any fact with `currency != INR` is rejected. Mixed
   currencies are never converted, never coerced, never compared.
3. Tz-aware timestamps. Any naive `datetime` is rejected. Adapters
   must attach the source timezone explicitly before handoff.
4. Provenance required. A fact without `provenance`, `source_version`,
   and `source_hash` is rejected; anonymous facts never reconcile.
5. Rejection is fail-closed per fact, not per batch: one bad fact is
   dropped (and logged with codes/hashes, never secret bytes) while
   valid facts still reconcile; missing coverage then classifies as
   `INSUFFICIENT_EVIDENCE` (§3) rather than as a clean match.

## 2. Deterministic equations (Decimal Python only)

All arithmetic below runs in deterministic Decimal Python. The LLM
reasons about WHY a variance exists; it never computes one.

### 2.1 Provider net

```text
provider_net = gross − fees − refunds + adjustments
```

- `gross`: sum of `PaymentFact.gross_amount` over the window.
- `fees`: sum of `PaymentFact.fee_amount` over the window.
- `refunds`: sum of `RefundFact.amount` over the window.
- `adjustments`: SIGNED sum from `SettlementFact.adjustments_total`
  (credit-positive, debit-negative). The `+` is a signed add: a
  provider debit adjustment DECREASES the net. Pending
  (`SettlementFact.pending_total`) is tracked separately and NEVER
  folded into `provider_net`.

### 2.2 Actionable variance (the ONLY case-creating variance)

```text
provider_books_variance = books_total − provider_net   (ACTIONABLE)
```

- `books_total`: sum of `AccountingEntryFact` net postings (credit
  minus debit per mapping) over the window.
- A nonzero `provider_books_variance` outside tolerance (§3) opens a
  case: it means accounting truth disagrees with provider truth, which
  is the discrepancy FinSight exists to resolve.

### 2.3 Informational gap (never case-creating, timing-separated)

```text
expected_books_variance = expected_total − books_total  (INFORMATIONAL)
```

- `expected_total`: `ExpectedSettlementFact.expected_total`.
- This gap is recorded as context on a case (e.g. the `7500` timing
  item in FS-231) but NEVER creates or sizes a `FinancialSituation`.
  Timing cut-off effects live here, separated from real discrepancies.

### 2.4 Forbidden variance (normative prohibition)

`expected − provider` (expected_total minus provider_net) is FORBIDDEN
as the actionable variance. It mixes two independent effects — the
timing/business-view gap (§2.3) and the provider-vs-books discrepancy
(§2.2) — into one number that is actionable against neither leg. In
FS-231 that forbidden number is `27500` (`1000000 − 972500`); filing
`27500`, or filing the `17500` expected-books gap, as the case variance
misattributes timing noise to a ledger fault and would drive a wrong
correction amount. Detection MUST compute §2.2 and §2.3 separately and
MUST size every case from §2.2 only.

## 3. Classification catalog (deterministic, arithmetic-only)

Classification is pure arithmetic over canonical facts plus
tolerance/boundary checks. It decides WHAT the numbers say. The LLM
later investigates WHY (hypotheses, email context, legacy reasons);
it never re-decides the classification. Tolerance: `100` (INR), pinned
by the FS-231 verification residual. `|v| <= 100` is within tolerance.

Each entry gives the exact trigger (ALL conditions required,
decided HERE by arithmetic) and what the LLM may later investigate
(reserved for investigation; MUST NOT change the label).

### 3.1 `MATCHED`

- Trigger: `provider_books_variance == 0` AND full coverage (every
  payment has its facts; every book line has a source fact; every
  legacy record is `AC`).
- LLM later: nothing. No case exists (§0).

### 3.2 `WITHIN_TOLERANCE`

- Trigger: `0 < |provider_books_variance| <= 100` AND full coverage
  as in §3.1.
- LLM later: nothing deterministic. No case exists (§0).

### 3.3 `PARTIAL_REFUND_LAG`

- Trigger: a `RefundFact` exists in provider state with NO matching
  `AccountingEntryFact` in-window, AND `provider_books_variance`
  equals the missing refund sum within tolerance.
- LLM later: refund-request email context; whether the lag is normal
  timing or a stuck posting.

### 3.4 `FEE_MISMATCH`

- Trigger: `SettlementFact.fee_total` differs from the booked fee
  slice sum by more than tolerance, AND the residual equals that fee
  delta within tolerance.
- LLM later: fee-change notes; which fee schedule version applies.

### 3.5 `DUPLICATE_LEDGER_ENTRY`

- Trigger: two `AccountingEntryFact` rows share one idempotency
  fingerprint (same `external_id` / same provider `refund_id` fold).
  Amount equality alone is NEVER a duplicate verdict here.
- LLM later: how the replay happened; guardrail gaps.

### 3.6 `LEGACY_POSTING_MISSING`

- Trigger: a `LegacyPostingFact` has disposition `RJ` (verbatim
  `reject_reason` + code) or is absent for a posted book leg, AND the
  residual equals the rejected/missing amount within tolerance.
- LLM later: the COBOL reason string meaning; the corrected account
  code for the P6-05+ proposal.

### 3.7 `INSUFFICIENT_EVIDENCE` (`UNKNOWN`)

- Trigger: coverage incomplete (boundary rejections per §1.7, absent
  legs, unreadable result file) so NO other trigger's antecedents are
  provable.
- LLM later: nothing conclusive. Flagged unknown; must not be
  auto-explained and creates no case (§4.1).

### 3.8 `CONFLICTING_AUTHORITIES`

- Trigger: the same `external_id` arrives with DIFFERENT fact bodies
  (different amount, disposition, or hash) from one or more
  authorities.
- LLM later: which authority is right. INVESTIGATE ONLY: never
  auto-resolve, never silent-overwrite, never majority-vote money.

## 4. FinancialSituation creation rules

### 4.1 Which classifications create a case

- CREATE in `DETECTED`: `PARTIAL_REFUND_LAG`, `FEE_MISMATCH`,
  `DUPLICATE_LEDGER_ENTRY`, `LEGACY_POSTING_MISSING`,
  `CONFLICTING_AUTHORITIES`. Each creation carries `variance` sized
  from §2.2 only, plus the informational §2.3 gap as context.
- CREATE NOTHING: `MATCHED`, `WITHIN_TOLERANCE` (§0: no situation).
- `INSUFFICIENT_EVIDENCE` (`UNKNOWN`): creates NO case. Partial data
  is recorded as a detection-attempt log with the missing legs named,
  and detection retries when coverage completes. Unknown data is never
  promoted into a `DETECTED` case with a guessed variance.

### 4.2 Required evidence refs at creation (D3-compatible)

Creation MAY precede `PROPOSED`, but the case MUST carry at creation
every ref that `PROPOSED` will later need for `EVIDENCE_VERIFIED`:

1. The content `source_hash` of every fact consumed by the equations.
2. The (`source_system`, `external_id`, `source_version`) triple per
   fact, so any ref resolves back to exactly one source record.
3. The deterministic inputs snapshot: window key, fact list, equation
   versions, tolerance value (`100`), and both computed variances
   (§2.2 actionable, §2.3 informational) with full Decimal precision.
4. The classification code plus the trigger arithmetic (which sums
   were compared, which delta matched within tolerance).
5. For legacy legs: S3 key + result-file id + verbatim reason/code.

Without all five, creation is refused and the outcome stays
`INSUFFICIENT_EVIDENCE`. Evidence refs are hash-chained into
`evidence_ids` and immutable from `DETECTED` onward.

### 4.3 Idempotency

Same external event delivered twice yields the SAME situation, never
a duplicate. Dedup keys: provider folds on (`source_system`,
`external_id`) per P6-01; execution stays idempotent on
(`company_id`, `proposal_hash`, `batch_id`). Redelivery of an
already-consumed fact (same hash) is absorbed with no new case, no
new evidence entry, and no variance drift.

### 4.4 Conflict (same external ID, different facts)

If the same `external_id` arrives with a DIFFERENT body (amount,
disposition, hash, or version), detection MUST classify
`CONFLICTING_AUTHORITIES`, open (or hold) ONE case for investigation,
and MUST NEVER silently overwrite the first fact with the second.
Both bodies stay in evidence with their hashes; resolution happens
through investigation and a new proposal version, never through
last-write-wins.

## 5. Acceptance scenarios (numbered, normative)

1. Exact match. Inputs: gross `500000`, fees `3750`, refunds `0`,
   adjustments `0` → provider_net `496250`; books `496250`;
   expected `496250`. Conclusion: `MATCHED`, NO situation created.
2. Within tolerance. Inputs: provider_net `496250`, books `496251`
   (variance `1`). Conclusion: `WITHIN_TOLERANCE`, NO situation.
3. Outside tolerance. Inputs: provider_net `496250`, books `496351`
   (variance `101`). Conclusion: discrepancy → `DETECTED` case with
   variance `101` (pending classification by §3 triggers).
4. Fee classification. Inputs: fee_total `7500` vs booked fee slice
   `7000` (delta `500`), residual `500`. Conclusion:
   `FEE_MISMATCH` → `DETECTED`, variance sized from §2.2 only.
5. Refund-lag classification. Inputs: `RefundFact` `2500` with no QB
   leg in-window, residual `2500`. Conclusion: `PARTIAL_REFUND_LAG`
   → `DETECTED`, variance `2500`.
6. Duplicate classification. Inputs: two `AccountingEntryFact` rows,
   same fingerprint, books overstated by `2500`, residual `2500`.
   Conclusion: `DUPLICATE_LEDGER_ENTRY` → `DETECTED`. (Amount-only
   equality with different fingerprints would NOT classify here.)
7. Legacy-missing classification. Inputs: one `RJ` record
   (`INVALID_ACCOUNT_CODE`), books short by `10000`, residual
   `10000`. Conclusion: `LEGACY_POSTING_MISSING` → `DETECTED`.
8. FS-231 golden. Inputs: expected `1000000`, provider_net `972500`,
   books `982500`, legacy accepted `982500`, 1 `RJ` (`10000` leg).
   Conclusion: ONE case, actionable variance `10000` (books minus
   provider). The `7500` timing item rides as §2.3 context only.
9. Forbidden-variance guard. Same FS-231 inputs. Conclusion: filing
   `27500` (expected minus provider) or filing `17500`
   (expected minus books) as the actionable variance is REJECTED;
   both numbers must never size a case or a proposal amount.
10. Idempotent redelivery. Inputs: scenario 5 facts delivered twice
    with identical hashes. Conclusion: ONE situation; second
    delivery absorbed, no duplicate case, no variance drift.
11. Conflicting same-ID facts. Inputs: one `external_id` with amount
    `10000` (hash A) then `12000` (hash B). Conclusion:
    `CONFLICTING_AUTHORITIES`; both bodies kept in evidence; no
    silent overwrite; single case held for investigation.
12. Float rejected. Inputs: `PaymentFact` with `gross_amount` as
    `float` `500000.0`. Conclusion: fact REJECTED at the boundary
    per §1.7; coverage gap yields `INSUFFICIENT_EVIDENCE`, never a
    computed variance over the float.
13. Currency mismatch rejected. Inputs: `RefundFact` with currency
    `USD`. Conclusion: fact REJECTED per §1.7; no conversion, no
    comparison, no case from the mixed-currency arithmetic.
14. Missing provenance rejected. Inputs: settlement facts without
    `provenance` / `source_version` / `source_hash`. Conclusion:
    facts REJECTED per §1.7; outcome `INSUFFICIENT_EVIDENCE` until
    attributed facts arrive; creation refused per §4.2.
15. Partial data stays unknown. Inputs: provider legs present, QB
    legs absent (result file unreadable). Conclusion:
    `INSUFFICIENT_EVIDENCE` (`UNKNOWN`); NO `DETECTED` case with a
    guessed variance; detection-attempt log names the missing legs.
16. Conflicting authorities route to investigation. Inputs:
    scenario 11 case state. Conclusion: case advances
    `DETECTED -> TRIAGED -> INVESTIGATING` for human-led review;
    auto-resolve, majority-vote, and last-write-wins are all
    FORBIDDEN; close requires the frozen verification path.

## 6. Explicit non-goals

1. No Temporal, Qdrant, graph stores, SQS/queues, or LLM-orchestration
   frameworks. Detection is deterministic Decimal Python plus the
   frozen P6-01 transports (S3 for legacy, read-only SDKs elsewhere).
2. No new lifecycle states and no state redefinitions. P6-02 §2 is
   frozen; `MATCHED`/`WITHIN_TOLERANCE`/`UNKNOWN` are §3 labels, not
   states, and clean outcomes create no case (§0).
3. No execution or approval semantics. Proposal hashing, Slack HITL
   tiers, S3 correction upload, and verification verdicts belong to
   P6-05+; this spec stops at `DETECTED` creation with D3-ready refs.
4. No P1 engine edits. P1 is wrapped and cited by name only; the
   engine inventory owns its internals in parallel.
5. No new queues, streams, AWS services, or live transports beyond
   the P6-01 matrix. The C-SHEETS and C-SLACK stubs stay stubs until
   their owning P6 steps land.
6. No float math, no currency conversion, no multi-company logic, no
   closed-period mutation, no Gmail approvals — all still forbidden
   by the process model (§5–§6) and P5 fences.

---

*P6-03 reconciliation and detection contract. Detection decides WHAT
the numbers say; investigation (LLM) explains WHY; P6-05+ acts.*
