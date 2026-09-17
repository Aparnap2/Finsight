# P6-01 Six-System Integration Contracts Matrix — Meridian Commerce

**Status:** Draft for P6-01 on `feat/finsight-p6-domain-contract`.
**Base:** P5 checkpoint `finsight-p5-security` (trust/security fences hold).
**Scope:** Single company (`company_id = meridian`, INR, Decimal-only money).
**Sources:** `docs/domain/meridian-process-model.md` (§4 FS-231, §5
authorities), `docs/domain/company.md` (IntegrationRegistry),
`docs/architecture/LEGACY_BATCH_PROTOCOL.md` (P5-10), and
`agents/capabilities/registry.py` (5-entry frozen registry).

Conventions used below: `tenant_id` in older code/docs means
`company_id = meridian` plus `environment` (dev / staging / prod).
All money is `Decimal` with 2 dp; `float` is forbidden. FinSight owns
reasoning state; the six systems below own facts. The LLM never
computes money and never approves, executes, or mutates policy.

## 0. Overview matrix

| # | System | Authority (truth owned) | Dir | Contract |
|---|--------|-------------------------|-----|----------|
| 1 | Razorpay | Provider capture/fee/refund | R | C-RAZORPAY |
| 2 | QuickBooks | Accounting journals/balance | R | C-QUICKBOOKS |
| 3 | Google Sheets | Expected settlement (biz) | R | C-SHEETS (STUBBED bind) |
| 4 | Gmail | Context only (no facts) | R | C-GMAIL |
| 5 | Slack | Approval signal (human) | R/W | C-SLACK (STUBBED) |
| 6 | COBOL ledger | Legacy settlement per batch | R/W | C-LEGACY |

R = read-only for FinSight; W = FinSight writes (Slack posts proposal
only; COBOL writes `CORRECTION` files via S3; nothing else writes).

## 1. C-RAZORPAY — Razorpay provider state (Razorpay-analog)

| Aspect | Contract |
|--------|----------|
| Authority | Capture, fee slice, refund, adjustment. Provider net |
| Authority | is deterministic: gross minus fee minus refund minus |
| Authority | adjustment minus pending. FinSight never rewrites it. |
| Direction | Read-only. FinSight never writes provider state. |
| Transport | `finance/stripe/adapter.py` (Razorpay-analog event |
| Transport | normalizer) + `get_stripe_payment` / `get_stripe_refunds` |
| Transport | capabilities over persisted folds keyed by `(tenant, id)`. |
| Data | `payment_id`, `merchant_id`, `gross_amount`, `fee_amount`, |
| Data | `net_amount`, `captured_at`, `status`; `refund_id`, |
| Data | `payment_id`, `amount`, `issued_at`, `reason` for refunds. |
| Data | Money `Decimal`-only (minor-unit scaling, no float/bool). |
| Data | Scoped by `(company_id = meridian, environment)`; caller |
| Data | supplies scope explicitly, there is no default tenant. |
| Failure | Timeout → `TransientError`-style retry, then surfaces; |
| Failure | auth → `ExecutorRejectedError` (frozen allowlist holds); |
| Failure | malformed (fee null vs 0, currency mix, refund > gross) |
| Failure | → record rejected, `LEDGER_RECORD_MISSING` downstream; |
| Failure | duplicate replay → idempotent fold on `(provider, |
| Failure | `refund_id)`, never subtracts twice (maps to `I-DUPLICATE`). |
| P5 | Provider rows are trusted facts, not instructions. Fee |
| P5 | tri-state (`KNOWN`/`UNKNOWN`/`NOT_APPLICABLE`) is checked |
| P5 | via `fee_knowledge_of`, never inferred from `fee == 0`. |

## 2. C-QUICKBOOKS — QuickBooks accounting truth

| Aspect | Contract |
|--------|----------|
| Authority | Journals, balances, accounting period open/closed. |
| Authority | Debits equal credits per batch; closed periods immutable. |
| Direction | Read-only for P6-01 (`get_entry` only). FinSight never |
| Direction | writes production books (mock scope routes refund-lag / |
| Direction | duplicate only; fee-drift is proposal-only, rejected). |
| Transport | `finance/accounting/mock.py` (sandbox `AccountingAdapter`) |
| Transport | via `get_qb_transaction` capability; entry ids carry a |
| Transport | `MOCK-` prefix so sandbox rows never mix with real books. |
| Data | `entry_id`, `company_id`, `total` (Decimal), `currency`, |
| Data | `status`, `lines[]` (`account`, `debit`, `credit` Decimal), |
| Data | `source_reference`, `memo`, `exception_id/type`. Tenant id |
| Data | on the entry must equal the request scope or the read is |
| Data | refused as out-of-scope (no existence oracle). |
| Failure | Timeout (scripted 5xx) → `TransientError`, same-key retry |
| Failure | safe (records persist only on the success path); auth / |
| Failure | scope miss → `EntryNotFoundError` (uniform, no leak); |
| Failure | malformed (business-rule breach) → `ValidationError`, no |
| Failure | record and no key reservation, corrected retry is safe; |
| Failure | duplicate key → `IdempotencyConflictError` (`I-DUPLICATE`). |
| P5 | Tenant/company fence on every read; uniform miss signal. |
| P5 | Secrets redaction applies to entry memos in audit/traces. |

## 3. C-SHEETS — Google Sheets expected settlement — STUBBED BINDING

| Aspect | Contract |
|--------|----------|
| Authority | Expected settlement figure (business view). Advisory, |
| Authority | never authoritative over provider/accounting/legacy legs. |
| Direction | Read-only. FinSight never writes expected state. |
| Transport | **STUBBED.** No `finance/` adapter binds the expected |
| Transport | schema yet. Helpers `finance/ingestion/sheets_adapter.py` |
| Transport | and `finance/integration/google_sheets_provider.py` exist |
| Transport | but are NOT wired as the authority; the capability reads |
| Transport | via `InMemoryLedgerRepository` fixture (`get_expected_state`). |
| Data | `spreadsheet_id`, `range`, cell grid; expected leg fields |
| Data | `expected_total` (Decimal), period, `company_id = meridian`. |
| Data | Exact header/cell binding is undefined until the stub is |
| Data | replaced — P6 later steps own that seam (see §8). |
| Failure | Timeout → retry-then-surface; auth (missing credentials |
| Failure | file) → `FileNotFoundError` before any read; malformed |
| Failure | (empty id/range, bad headers) → `ValueError`, empty result; |
| Failure | duplicate → n/a (idempotent read; dedupe on content hash). |
| P5 | **UNTRUSTED_CONTENT fence:** sheet cells are DATA-only, |
| P5 | never instructions. Prompt-injection suite (56 combos) pins |
| P5 | this: no auto-invoke, no planning directive from cell text. |

## 4. C-GMAIL — Gmail context (fixture corpus, never live)

| Aspect | Contract |
|--------|----------|
| Authority | Context only: refund request notes, fee-change notes. |
| Authority | Never a fact source; never an approval channel. |
| Direction | Read-only search. FinSight never sends mail. |
| Transport | Gmail fixture corpus via `search_gmail` capability in |
| Transport | `agents/capabilities/capabilities.py` (`AdapterBundle` |
| Transport | injects `gmail_corpus`; substring search, tenant-scoped). |
| Transport | No `finance/` Gmail adapter exists by design (not a stub, |
| Transport | a boundary: live Gmail is out of scope for P6-01). |
| Data | `message_id`, `subject`, `body` (snippet ≤ 280 chars in |
| Data | results), `content_hash`, `retrieved_at`, `tenant_id`. No |
| Data | money parsing from prose; amounts cited need grounding. |
| Failure | Timeout → empty result (fail-soft, context is optional); |
| Failure | auth → n/a (fixture, no credentials); malformed (empty |
| Failure | query) → empty result; duplicate → dedupe on content hash. |
| P5 | **UNTRUSTED_CONTENT fence:** bodies are DATA-only. Gmail |
| P5 | "approvals" are NEVER accepted (see payload_03 regression). |
| P5 | PII/secrets in snippets are hash-scoped and redacted. |

## 5. C-SLACK — Slack human approval — STUBBED TRANSPORT

| Aspect | Contract |
|--------|----------|
| Authority | The single human decision per proposal version. Amount |
| Authority | tiers: Manager 5k–50k, Director > 50k; legacy correction |
| Authority | always requires approval + valid code + balanced batch. |
| Direction | FinSight posts the proposal; reads back one decision. |
| Transport | **STUBBED (TBD).** No Slack adapter exists in `finance/`. |
| Transport | P6 later steps own this seam (see §8). Until then the |
| Transport | approval is a hash-pinned record, never a live API call. |
| Data | `approval_id`, `company_id`, `proposal_hash` (must match |
| Data | exactly), `decider`, `decision` (`APPROVE` or `REJECT`), |
| Data | `decided_at`. One decision per hash; double-approve is |
| Data | rejected; reject is terminal for that proposal version. |
| Failure | Timeout → stay `PROPOSED`, never auto-advance; auth → |
| Failure | `ExecutorRejectedError`, no silent approval; malformed |
| Failure | (hash mismatch, double decision) → rejected, re-propose; |
| Failure | duplicate signal → idempotent on `(company_id, |
| Failure | `proposal_hash)`, replay returns the recorded decision. |
| P5 | **Approval pinning:** decision binds the immutable |
| P5 | `proposal_hash`; any byte drift voids the approval. |

## 6. C-LEGACY — COBOL settlement ledger via S3 (no HTTP)

| Aspect | Contract |
|--------|----------|
| Authority | Legacy accepted totals per batch; per-record `AC`/`RJ`/`DU` |
| Authority | with verbatim reason (e.g. `INVALID_ACCOUNT_CODE` + code). |
| Direction | Write `CORRECTION_*.DAT` to outbound; read result file. |
| Transport | `finance/legacy/protocol.py` (80-char fixed-width, ver |
| Transport | `01`, SHA-256 4-hex checksum, control record type `99`) |
| Transport | over `finance/object_store` port (`port.py`, `s3_adapter.py`, |
| Transport | `fake.py`); buckets `finsight-legacy-outbound` (write) and |
| Transport | `finsight-legacy-result` (poll). No HTTP exists on purpose. |
| Data | Line: `version(2)` + `batch_id` compact 14 + `sequence(8)` |
| Data | + `record(52)` + `checksum(4)`; batch `LEGACY-YYYYMMDD-NNNN`; |
| Data | file `CORRECTION_YYYYMMDD_231.DAT`; key `{company_id}/` |
| Data | `{batch_id}/CORRECTION_*.DAT`; `control_total` Decimal 2dp |
| Data | over non-`99` records; result mirror with `AC`/`RJ`/`DU`. |
| Failure | S3 timeout → `LegacyTimeoutError` (10s read, 5min/1k rec); |
| Failure | result absent → poll 30 min then `LegacyResultTimeoutError`; |
| Failure | malformed line/checksum → `LegacyParseError` / |
| Failure | `LegacyChecksumError`, no retry (corruption assumed); |
| Failure | control drift → `LegacyControlTotalError`, fail-closed, no |
| Failure | partial accept; duplicate batch/record → `DU` for the unit; |
| Failure | rejected rows → human review, never auto-retried. |
| P5 | **UNTRUSTED_CONTENT fence:** result files are DATA-only. |
| P5 | Key-prefix isolation (`CompanyIsolationError` on cross |
| P5 | scope); upload retries ≤ 3 with backoff (1s, 2s, 4s). |

## 7. FS-231 data-flow trace (contract per hop)

Golden situation `FS-2026-0916-00231`, Meridian, INR, Decimal-only.
Batch `LEGACY-20260916-0042`: 500 sent, 499 accepted, 1 rejected.

| Hop | Value | Contract used |
|-----|-------|---------------|
| Sheets expected settlement | `1000000` | C-SHEETS (stub bind) |
| Razorpay net: gross `1000000` minus fee | `972500` | C-RAZORPAY |
| Razorpay split: fee `7500` + refund `2500` | — | C-RAZORPAY |
| Razorpay split: adjustment `10000` + pend | `7500` | C-RAZORPAY |
| QuickBooks total | `982500` | C-QUICKBOOKS |
| Legacy accepted total | `982500` | C-LEGACY |
| Gmail context (refund/fee notes, DATA) | — | C-GMAIL |
| Variance: `1000000` minus `982500` | `10000` | deterministic Decimal |
| Cause: 1 record `RJ INVALID_ACCOUNT_CODE` | code `4812` | C-LEGACY (`I-LEGACY-REJECT`) |
| Proposal: reprocess `10000` under `4812` | hashed | C-SLACK payload (stubbed) |
| Slack `APPROVE` pinned to proposal hash | — | C-SLACK (stubbed) |
| S3 upload `CORRECTION_20260916_231.DAT` | — | C-LEGACY + object-store port |
| Result record returns `ACCEPTED` (`AC`) | — | C-LEGACY |
| Legacy total now `982500 + 10000` | `992500` | C-LEGACY re-read |
| Pending `7500` closes to expected | `1000000` | deterministic re-reconcile |
| Residual within tolerance `100` | `VERIFIED` | `EXECUTION_VERIFIED` → `CLOSED` |

No `CLOSED` without `EXECUTION_VERIFIED`. A `FAILED` verdict returns
the situation to `INVESTIGATING`, never to `CLOSED`. Closed accounting
periods are never mutated on any hop.

## 8. STUBBED seams (P6 later steps own these)

1. **C-SLACK transport — STUBBED.** No adapter under `finance/`.
   Seams: post proposal payload, read decision, pin hash, enforce
   one-decision-per-hash and decider tiers. Do not invent a live
   Slack API inside agent or finance code without a P6 proposal.
2. **C-SHEETS expected-schema binding — STUBBED.** Transport helpers
   exist but no `finance/` module binds the expected-settlement
   schema to `get_expected_state`. Seam: header/cell contract plus
   wiring the capability off the `InMemoryLedgerRepository` fixture
   onto the real read path. Until then, expected figures in tests
   come from the fixture, fenced as untrusted DATA.

## 9. P5 interaction summary (fences every contract obeys)

- **UNTRUSTED_CONTENT:** Gmail bodies, Sheets cells, and legacy
  result files are DATA-only (P5-12 rows 6–8; 56-combo suite).
- **Secrets redaction:** credentials (Sheets service-account JSON,
  S3 creds) never enter audit rows, spans, or logs (`_audit`
  redact map, tracer sanitize, `scrub_text`, CI secret-literal
  gate). Failure paths log codes and hashes, never secret bytes.
- **Approval pinning:** only Slack `APPROVE` pinned to the exact
  `proposal_hash` advances `PROPOSED → APPROVED`; Gmail text never
  approves; double-approve is rejected.
- **Isolation:** `company_id = meridian` + environment on every row,
  API context (never client-supplied), S3 prefix, RLS, and
  `CompanyIsolationError` (alias of `TenantIsolationError`).
- **Determinism:** money in Decimal Python only; idempotency on
  `(company_id, proposal_hash, batch_id)` for execution and on
  `(provider, refund_id)` / `(batch_id, sequence)` for inputs.
