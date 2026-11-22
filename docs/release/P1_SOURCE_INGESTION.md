# P1 — Source Ingestion and Normalization

**Status:** Delivered (library only)
**Date:** 2026-11-22
**Specification:** `docs/specs/DOMAIN_MODEL.md` §3.0–§3.1, `docs/specs/ACCEPTANCE_MATRIX.md` §2
**Scope authority:** revised P1 (source-independent ingestion), spec amendment `aff4fd6`

---

## 1. What P1 is, and is not

P1 is the smallest useful ingestion layer for three-source reconciliation:
three canonical schemas, one transport-independent adapter interface, one
deterministic normalizer/validator, CSV as the initial adapter, and row-level
validation with provenance.

P1 is **not** a file-import product. It adds:

- no persistence;
- no HTTP endpoint, session, or upload lifecycle;
- no UI;
- no Google OAuth, Sheets, Excel, Stripe API, or bank API connector;
- no generic ETL framework;
- no AI-assisted column mapping;
- no reconciliation decision (no matching, classification, allocation, or
  exception resolution).

The interface is source-independent so a Google Sheets adapter can be added
later without touching reconciliation logic. That is proven, not asserted: an
in-memory `TableAdapter` already flows through the identical schema resolution
and normalization, and a test asserts both transports produce equal canonical
records and equal table digests.

---

## 2. Module boundary

New package: `finance/source_ingestion/`

| Module | Lines | Responsibility |
|---|---|---|
| `schemas.py` | 307 | `SourceType`, `ColumnSpec`, `SourceSchema`, three canonical schemas, deterministic header folding and alias resolution |
| `adapters.py` | 406 | `SourceAdapter` protocol, `ParsedTable`, `RowShapeIssue`, `CsvAdapter`, `TableAdapter`, `content_digest` |
| `issues.py` | 158 | `ApiErrorCode`, `IssueCode`, `IngestionError`, `RowIssue` |
| `normalizer.py` | 692 | Row → canonical record composition, provenance, precision/currency/date rules, duplicate and conflict detection |
| `service.py` | 339 | `ingest_source`, `ingest_table`, `IngestionReport` (validation preview + roll-up API code) |
| `__init__.py` | 96 | Public surface |

**Why not `finance/ingestion/`:** that package is the FP&A-generation ingestion
layer (outbox, publisher, GL agent, FP&A Sheets adapter) and is marked for
removal in Slice 8. Placing reconciliation ingestion inside it would couple the
new code to a deletion target. `finance/source_ingestion/` is disjoint, and
`MODULE_DISPOSITION.md` now records that it must be preserved.

**Dependency direction:** `finance/source_ingestion` → `finance/reconciliation`
(frozen core). The core does not import ingestion, so ingestion stays outside
the reconciliation decision path.

---

## 3. Canonical schemas

Header matching is exact after folding case, spaces, hyphens, dots, slashes,
and repeated underscores. No fuzzy matching, no inference.

| Source | Required fields | Optional fields |
|---|---|---|
| Invoice | `invoice_id`, `amount`, `currency`, `issued_at` | `fee`, `refund`, `status`, `reference` |
| Stripe | `charge_id`, `amount`, `currency`, `created_at` | `fee`, `refund`, `status`, `event_id`, `reference` |
| Bank | `deposit_id`, `amount`, `posted_at` (+ declared statement currency) | `currency`, `fee`, `account`, `reference`, `description` |

Aliases are declared per field (for example `invoice_number`, `total`,
`currency_code`, `invoice_date`). Unknown headers are reported on the report and
are not fatal. Two headers claiming one canonical field is a schema error.

---

## 4. Money, dates, and precision

- Money is `Decimal` only. `float`/`bool` never reach the domain boundary.
- Thousands separators (`1,970.00`) are parsed; no other currency formatting is
  guessed at.
- Amounts are checked against the currency's minor unit. `10.005 USD` is
  refused with `OVER_PRECISION` rather than rounded; `10.000 USD` is accepted;
  `1000.5 JPY` is refused; `1.234 BHD` is accepted. This mirrors the frozen bank
  statement boundary rather than inventing a second rule.
- `gross < 0`, `fee < 0`, `refund < 0`, and `gross - fee - refund < 0` are all
  refused as `NEGATIVE_AMOUNT`.
- A bare calendar date is read as UTC midnight, matching
  `finance.reconciliation.bank`. A timestamp without a UTC offset is refused as
  ambiguous. Offsets are normalized to UTC.
- Currency is uppercased and must match `[A-Z]{3}`.

---

## 5. Provenance and the no-silent-drop guarantee

Every accepted record carries a `Provenance`: source type, transport,
`content_digest` (sha256 of the raw bytes), `table_digest` (sha256 of the parsed
table, transport-independent), 1-based physical line, and filename when known.
The original cells are preserved verbatim on the record envelope.

Every refused row carries a `RowIssue`: reason code, physical line, canonical
field, actionable detail, original cells, and — for duplicates — the line it
duplicates.

The report is self-accounting:

```
row_count == accepted_count + rejected_count + skipped_debits
```

`IngestionReport.__post_init__` enforces that identity, so a dropped row is a
construction error, not a silent omission.

Duplicates are distinguished from conflicts: a repeated identifier with
identical financial content is `DUPLICATE_ROW` (first row kept); a repeated
identifier with different money or date is `CONFLICTING_ROW`. Bank debits are
counted as `skipped_debits`, matching the frozen statement rule.

Line numbers stay physical across blank lines and refused rows. The frozen
statement normalizer numbers rows positionally, so bank line numbers are mapped
back to the real source line after normalization; a test covers a blank line, a
refused row, and a duplicate after a blank line.

---

## 6. Error mapping

| Layer | Shape | Codes |
|---|---|---|
| Envelope | `IngestionError` raised | `INVALID_FILE` (empty, undecodable, unsupported format, no data rows), `INVALID_SCHEMA` (missing/blank/duplicate columns, missing statement currency, non-canonical bank mapping) |
| Row | `RowIssue` on the report | `VALIDATION_FAILED` for field failures, `DUPLICATE_IMPORT` for duplicate rows |
| Report roll-up | `IngestionReport.api_error_code` | `None` when clean; `DUPLICATE_IMPORT` when the only issues are duplicates; otherwise `VALIDATION_FAILED` |

All codes come from `docs/specs/ERROR_CATALOG.md`. P2 can translate the report
to HTTP without re-deriving semantics.

---

## 7. Test evidence

`tests/unit/source_ingestion/` — **71 tests**, all passing.

| File | Tests | Covers |
|---|---|---|
| `test_source_ingestion.py` | 28 | canonical values per source, thousands separators, fee/refund net equation, bank digest and posting instant, provenance (digest, line, raw cells, filename), source independence, alias resolution, header folding, unknown headers, replay determinism, permutation invariance, additive-row invariance, tenant boundary, absence of reconciliation decisions, JSON-safe preview |
| `test_source_ingestion_validation.py` | 43 | envelope failures, missing/blank/duplicate columns, row shape, missing fields, non-numeric and negative amounts, over-precision per currency, bad/naive dates, offset normalization, currency and status validation, duplicate vs conflict, bank debit counting, bank currency mismatch, physical line mapping, report roll-up and count identity |

Expected values are explicit literals (`Decimal("961.00")` for
`1000.00 - 29.00 - 10.00`) or independently derived arithmetic — never the
production function's own output. Invariants are asserted as invariants
(`net == gross - fee - refund`, count identity), not as snapshots.

### Mutation check (tests must fail for the right reason)

| Mutation | Result |
|---|---|
| `gross - fee - refund < 0` → `<= 0` | 1 test failed |
| Precision guard disabled | 3 tests failed |
| Conflicts reported as duplicates | 1 test failed |
| `content_digest` made constant | 2 tests failed |

All mutations were reverted; the suite is green at 71/71.

Two real defects were found by these tests during development and fixed:

1. the bank duplicate guard was inverted, so a duplicate deposit disappeared
   without an issue and `row_count` undercounted;
2. bank line numbers were positional, so a blank line produced a phantom
   missing-field row.

---

## 8. Gates (local, before commit)

| Gate | Result |
|---|---|
| `ruff check .` | pass |
| `ruff format --check .` | 662 files formatted |
| mypy baseline | 1137 recorded / 1137 current / **0 new** |
| `pytest tests/unit tests/contract` | 3,427 passed, 1 skipped |
| `pytest tests/unit/reconciliation` | 352 passed |
| operator report | exit 0, 266/266 checks |
| `scripts/reconciliation_boundary.py --check` | exit 0 |
| `scripts/reconciliation_contract_report.py` | verdict pass, 9 scenarios, 266 checks |

The reconciliation engine, the 111 behavioral contract tests, the nine golden
scenarios, and the 266 operator checks are unchanged and green.

---

## 9. Specification deviations and amendments

1. **`parse_table` added to `SourceAdapter`.** The frozen protocol declared
   `parse`, `headers`, `source_type`, `supported_formats`. Carrying the physical
   line number of each row requires the adapter to expose rows with their line
   numbers; otherwise line provenance would have to be re-derived by parsing
   twice. `parse` remains the row-only view from the original contract.
   Recorded in `docs/specs/DOMAIN_MODEL.md` §3.0.
2. **Package path.** `finance/source_ingestion/` rather than the
   `finance/ingestion/{parser,validator,service}.py` names in the acceptance
   matrix, because `finance/ingestion/` is an FP&A deletion target. The matrix
   component and test paths are updated.
3. **P1 vs P2 split.** IN-01, IN-06 persistence lookup, IN-07 size limit, and
   the HTTP endpoints are P2. The acceptance matrix now states this explicitly
   so planned work is not read as passing.
4. **`source_reference` is not provenance.** Provenance lives on the
   `IngestedRecord` envelope so canonical records stay transport-independent.
   `PaymentRecord.source_reference` carries the source's own `reference` column
   when present.

---

## 10. Not verified by this work

- No HTTP layer, so no upload, session, or preview endpoint behavior.
- No persistence, so no duplicate-file detection against stored hashes.
- No file-size enforcement (P2 boundary).
- No Google Sheets adapter, no OAuth, no Excel.
- No end-to-end reconciliation of ingested files through the engine; P1 proves
  canonical output, not the full pipeline.
- Green local gates are not production readiness. Authentication, tenant
  isolation at the HTTP/database boundary, durable audit, recovery, and
  observability remain unverified.
