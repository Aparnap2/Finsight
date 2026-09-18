# P6-07 Deterministic Execution and Legacy Boundary Contract — Meridian

**Status:** Draft spec for P6-07 on
`feat/finsight-p6-07-execution-legacy`.
**Base:** `acf9afd` (P6-06 merge). P6-02 lifecycle,
P6-05 verdict, and P6-06 approval semantics are FROZEN.
**Scope:** Single company (`company_id = meridian`, INR,
Decimal-only money, S3 file transport only).
**Sources:** `docs/architecture/LEGACY_BATCH_PROTOCOL.md`
(fixed-width schema, OUTBOUND→RESULT, control totals,
accepted/rejected, duplicates, partials),
`docs/architecture/P6-06_APPROVAL_CONTRACT.md` (G7 token
shape, idempotency key, replay semantics),
`docs/domain/meridian-process-model.md` (§4 FS-231,
§legacy correction flow, §1.9 ExecutionRecord, §1.10
VerificationReport), and
`finance/approval/authorization.py` (token fields,
`verify_authorization`, seal).
**Type:** DOC-ONLY. No code, no agent changes, no P1
edits, no new services, no new infra.

Conventions: `tenant_id` in older code/docs means
`company_id = meridian` plus `environment` (dev /
staging / prod). All money is `Decimal` with 2 dp;
`float` is forbidden. "Refuse" means: stop the chain
at the current stage, emit the named code, record an
audit entry, and change no further state. Silent drops,
silent fixes, silent retries of rejected records, and
assumed outcomes are forbidden. Every normative
statement is numbered `Xn` for test traceability.
"Replay-read" means: return the recorded outcome
without re-executing transport or legacy effects.

## 0. Frozen inputs (normative, consumed as given)

- **X1. P6-02 lifecycle is frozen.** The `APPROVED ->
  EXECUTING -> VERIFYING` chain, the `EXECUTING` state,
  and the banned transitions (`PROPOSED -> EXECUTING`,
  `INVESTIGATING -> EXECUTING`) are consumed exactly as
  written in the process model (§2). This spec defines
  no new lifecycle states, renames none, and executes
  no transitions itself; it only defines what happens
  inside `EXECUTING` once entry is granted.
- **X2. P6-05 verdict semantics are frozen.** The
  `RESOLUTION_PROPOSAL` shape, kind-tag rules, and
  `PROPOSAL != AUTHORIZATION` are consumed as given.
  A proposal alone authorizes nothing here; only a G7
  token opens the execution chain.
- **X3. P6-06 G7 token shape is frozen.** The
  `AuthorizationToken` fields (`authorization_id`,
  `proposal_hash`, `proposal_version`, `company_id`,
  `situation_id`, `action`, `amount_exact`,
  `account_code`, `idempotency_key`, `issued_at`,
  `expires_at`, `amount_ceiling`, `scope_batch`,
  `binding_digest`, `auth_mac`), the deterministic
  `idempotency_key` in (`company_id`, `proposal_hash`,
  `proposal_version`), and the G7 refusal codes are
  consumed verbatim from `authorization.py` and A17–A19.
  This spec mints no tokens and redefines no fields.
- **X4. No LLM write authority anywhere in this
  slice.** No prompt, completion, ranking, confidence
  rule, or agent judgment supplies amounts, account
  codes, batch ids, totals, hashes, or outcome labels.
  The LLM plane, if present, is read-only context; it
  never steers execution, transport, or ingestion.
- **X5. Ordering is part of the contract.** Stages run
  E1 → E2 → E3 → E4 → E5 → E6 in fixed order. The
  first stage that refuses stops the chain; later
  stages never run. Stage order is not configurable.
- **X6. Audit spine.** Every stage records one audit
  entry: stage id, inputs digest (hashes, never money
  in clear beyond 2-dp totals), permit/refuse, code,
  and resulting artifact hashes. Entries are
  append-only and hash-chained where the spine
  supports it.

## 1. Stage E1 — Authorization consumption (normative)

Purpose: decide whether this execution attempt may
proceed at all. No artifact, transport, or legacy
effect exists before E1 permits.

Signature (conceptual, no code):

```text
E1(token, presented_context, seal_context, at)
  -> PERMIT(execution_id) | REFUSE(code) | REPLAY(recorded_outcome)
```

- **X7. Inputs.** `token`: the caller-presented G7
  `AuthorizationToken` byte-identical to mint.
  `presented_context`: (`company_id`,
  `situation_id`, `proposal_hash`,
  `proposal_version`, `action`, `amount_exact`,
  `account_code`, `scope_batch`) asserted by the
  caller for this attempt. `seal_context`: the
  server-held seal key supplied by the hosting
  runtime for this verification call. `at`: the
  caller-supplied tz-aware use time (no clock read).
- **X8. Seal context is caller-supplied, never
  embedded.** The seal key is never a token field,
  never persisted beside the token, never logged,
  and never defaulted. Verification recomputes the
  HMAC-SHA256 seal over the canonical binding with
  the supplied key and compares with
  `hmac.compare_digest`. A public-digest
  recomputation alone never passes. Missing or
  empty seal context refuses before any other check
  with `TOKEN_FORGED`.
- **X9. Fixed check order, first refusal wins.**
  E1 evaluates in this order and stops at the first
  failure: (1) authenticity (seal recomputation),
  (2) integrity (binding digest), (3) case binding
  (`company_id`, `situation_id`), (4) hash/version
  pin, (5) expiry (`at > expires_at`), (6) scope
  (`action`, `amount_exact`, `amount_ceiling`,
  `account_code`, `scope_batch`). Order matches
  `verify_authorization` and is not configurable.
- **X10. Refusal codes.** Authenticity or integrity
  break → `TOKEN_FORGED`. Case escape →
  `CROSS_CASE_REFUSED`. Version mismatch →
  `PROPOSAL_VERSION_SWAPPED`. Same-version hash
  skew → `PIN_SKEW_HASH`. Past expiry →
  `AUTHORIZATION_EXPIRED`. Any scope-field escape
  (different action, amount, ceiling breach,
  account code, or batch/window) →
  `AUTHORIZATION_SCOPE_ESCAPE`. Naive `at`
  refuses as input hygiene with `TOKEN_FORGED`.
- **X11. Outputs.** On permit: `execution_id`
  (defined as the token's `idempotency_key`; §7),
  bound for all later stages. On refuse: the code
  from X10 plus an audit entry; no state changes.
  On replay (X12): the recorded outcome, byte-
  identical to the first recording.
- **X12. Single-use effect, replay-read outcome.**
  The first permitted presentation for an
  `execution_id` owns the single allowed effect
  (one OUTBOUND artifact, one legacy processing).
  Every later presentation of the same
  authorization is a replay-read: E1 returns the
  recorded outcome verbatim and no later stage
  re-runs. A caller demanding a second effect is
  refused with `AUTHORIZATION_REPLAYED`.
- **X13. No minting, no renewal, no upgrade.**
  E1 never mints, extends, re-scopes, or repairs a
  token. Expiry renewal is a fresh G1–G6 decision
  plus G7 mint under P6-06; presenting an edited
  copy (new expiry, same seal) refuses with
  `TOKEN_FORGED`.

## 2. Stage E2 — Execution intent (normative)

Purpose: derive the single deterministic correction
intent from token fields only. No new amounts are
computed and no LLM input is accepted.

```text
E2(execution_id, token) -> PERMIT(intent) | REFUSE(code)
```

- **X14. Derivation is a projection, not a
  computation.** `intent` is copied field-for-field
  from the permitted token: `action`,
  `amount_exact` (Decimal, 2 dp, unchanged),
  `account_code`, `company_id`, `situation_id`,
  `scope_batch`, `idempotency_key`. No arithmetic,
  no rounding, no fee/refund re-derivation, no
  evidence re-read, no proposal re-fetch. Any
  value not present in the token is absent from
  the intent.
- **X15. Closed vocabulary.** `action` must equal
  the token's bound action (for FS-231:
  `REPROCESS_LEGACY_RECORD`). `amount_exact` must
  equal the token amount to the cent; `1` paise of
  drift refuses. `account_code` must equal the
  token code exactly. Mismatch on any of the three
  refuses with `AUTHORIZATION_SCOPE_ESCAPE` (scope
  escape at the intent gate, before any artifact).
- **X16. No LLM input, no human input, no
  enrichment.** Suggestive text, email context,
  chat transcripts, and model completions are not
  inputs to E2. If the token binds it, it executes;
  if it does not, it refuses. E2 records the
  intent digest in the audit entry.
- **X17. Batch scope pinning.** When the token
  carries `scope_batch`, the intent is pinned to
  that batch id; E3 must reuse it and E5 must
  present it. When `scope_batch` is absent, E3
  derives the batch id deterministically from the
  `idempotency_key` (§7) and records the binding;
  two derivations for one key never differ.

## 3. Stage E3 — Artifact build (normative)

Purpose: construct the fixed-width OUTBOUND batch.
Serialization failures refuse before any transport.

```text
E3(intent) -> PERMIT(outbound_artifact) | REFUSE(code)
```

- **X18. Schema is consumed verbatim.** Every line
  is exactly 80 characters per the legacy protocol
  §5: cols 1–2 `version` (`01`), cols 3–16
  `batch_id`, cols 17–24 `sequence` (zero-padded,
  `00000001`…), cols 25–76 `record` payload, cols
  77–80 per-line checksum (last 4 hex of
  SHA-256 over cols 1–76). Record types `01`
  (correction), `02` (reversal), `03` (match),
  `99` (control). No column is repurposed and no
  width is reinterpreted by this spec; on any
  conflict the legacy protocol doc wins and this
  spec is amended.
- **X19. Control total is a Decimal sum.** The
  control record (type `99`) carries the sum of all
  non-`99` record amounts as `Decimal` with exactly
  2 dp. Computation is `sum(record.amount)` over
  data records only, in Decimal arithmetic. Float
  participation at any step refuses the artifact
  with `EXEC_ARTIFACT_REFUSED`.
- **X20. Whole-file SHA-256.** E3 computes
  `outbound_sha256 = SHA-256(file bytes)` over the
  exact bytes to be uploaded (LF line endings, no
  trailing whitespace beyond the 80-char body, one
  terminal newline). The digest is recorded in the
  audit entry and the execution record; it is the
  read-back comparator for E4 and the provenance
  hash for the §8 handoff.
- **X21. Batch identity and idempotency embedding.**
  `batch_id` format `LEGACY-YYYYMMDD-NNNN` is
  consumed as given. The 80-char lines carry no new
  fields: the `idempotency_key` is embedded at the
  artifact envelope level — (a) `execution_id`
  equals the key, (b) `batch_id` is bound to the
  key (pinned `scope_batch` reused, else
  deterministic derivation recorded at E2/X17),
  and (c) the key travels in the execution record
  and the S3 envelope (key prefix + manifest
  entry). Same key always resolves to the same
  `batch_id`; a second `batch_id` for one key is
  forbidden.
- **X22. Refuse-before-transport.** Any of these
  refuses with `EXEC_ARTIFACT_REFUSED` and uploads
  nothing: line != 80 chars, illegal record type,
  sequence gap or duplication within the batch,
  per-line checksum failure on self-verify,
  control total mismatch on self-verify, non-2-dp
  Decimal, empty batch (zero data records), or
  oversized batch (record count above the
  configured legacy ceiling, default 99999999
  sequence space and operational cap recorded in
  the manifest). The refusal names the first bad
  line/field.
- **X23. Output.** On permit: `outbound_artifact`
  (exact bytes, `batch_id`, `record_count`,
  `control_total`, `outbound_sha256`,
  `execution_id`). The bytes E3 permits are the
  bytes E4 uploads; no stage re-serializes between
  E3 and E4.

## 4. Stage E4 — S3 transport (normative)

Purpose: move bytes without mutating financial
meaning. Transport is a courier, never an author.

```text
E4(outbound_artifact) -> PERMIT(transport_receipt) | REFUSE(code)
```

- **X24. Fixed seam.** Buckets
  `finsight-legacy-outbound` (write) and
  `finsight-legacy-result` (read) are the only
  transport path; there is no HTTP interface.
  OUTBOUND key:
  `{company_id}/{batch_id}/CORRECTION_YYYYMMDD_231.DAT`
  (e.g.
  `meridian/LEGACY-20260916-0043/CORRECTION_20260916_231.DAT`).
  `company_id` in the key must equal the token's
  bound company; any cross-company key refuses
  with `EXEC_PREFIX_ESCAPE` before any network
  call (maps to `TenantIsolationError` semantics).
- **X25. Put with read-back verification.** After
  PUT, E4 reads the object back and compares
  `SHA-256(read bytes)` to `outbound_sha256`. Match
  yields `transport_receipt` (key, sha256, byte
  count, timestamp). Mismatch refuses with
  `EXEC_HASH_MISMATCH`: the object is left for
  operator triage, nothing proceeds to E5, and no
  silent re-PUT rewrites financial meaning.
- **X26. Retry budget, then stop.** S3 upload
  failure retries at most 3 times with backoff
  (1s, 2s, 4s) per the legacy protocol §12. Reads
  time out at 10s per object. Exhaustion refuses
  with `EXEC_TRANSPORT_REFUSED` (maps to
  `LegacyUploadError` / `LegacyTimeoutError`).
  Retries resend identical bytes only; re-
  serialization during retry is forbidden.
- **X27. Transport never mutates meaning.** E4
  performs no amount, code, total, sequence, or
  checksum edits. Byte inequality between E3
  output and uploaded bytes is a refusal
  (X25/X26), never a fix-up.
- **X28. Output.** On permit: `transport_receipt`
  bound to (`execution_id`, `batch_id`, key,
  sha256). The receipt is the sole precondition
  for E5 observation; legacy polling never starts
  without it.

## 5. Stage E5 — Legacy batch processing (normative)

Purpose: observe COBOL-ledger semantics as facts.
FinSight does not reimplement the ledger; it
records what the ledger reports.

- **X29. Per-record results consumed as given.**
  The ledger reports one result line per input
  line with the same sequence number and a code
  at cols 25–26: `AC` (accepted), `RJ`
  (rejected, with verbatim reason in cols 27–76),
  `DU` (duplicate, already processed). E5 never
  invents, upgrades, or downgrades a code.
- **X30. Rejection handling.** `INVALID_ACCOUNT_CODE`
  and any other `RJ` reason are preserved verbatim
  with the offending sequence and code. Rejected
  records are never auto-retried by this chain;
  they queue for human review outside this spec.
  Partial batches (some `AC`, some `RJ`) are
  preserved as partial; partial acceptance is
  allowed and expected (legacy protocol §9).
- **X31. Control-total mismatch fails closed.**
  When the result's control total does not match
  the recomputed Decimal total, the batch outcome
  is `REJECTED` in full: no partial acceptance is
  recorded for a control-total mismatch (legacy
  protocol §6). Refusal/state code:
  `EXEC_CONTROL_TOTAL_MISMATCH` (maps to
  `LegacyControlTotalError` semantics).
- **X32. Duplicate batch detection.** A second
  submission of the same `batch_id` is never
  reprocessed: the ledger returns `DU` for the
  batch and E5 records the already-recorded
  outcome (replay-read path, §7). FinSight-side,
  attempting a second `batch_id` for one
  `execution_id` (violating X21) refuses with
  `AUTHORIZATION_REPLAYED` before any PUT.
- **X33. Sequence discipline.** Sequences are
  monotonically increasing within the batch and
  namespaced by `batch_id`; reuse across batches
  is allowed. Gaps or intra-batch duplicates
  found at ingestion refuse with
  `EXEC_RESULT_CORRUPT`, never patched.
- **X34. Observation only.** E5 performs no ledger
  writes except the single E4 PUT that already
  happened. COBOL polling cadence and ledger-side
  timing are consumed as facts; this spec sets no
  ledger behavior.

## 6. Stage E6 — Result ingestion (normative)

Purpose: read the RESULT file, verify it, and record
the outcome. Late or missing results yield an
explicit UNKNOWN state — never an assumed verdict.

```text
E6(transport_receipt) -> RECORDED(outcome) | RECORDED(unknown)
```

- **X35. Fixed RESULT seam and shape.** RESULT key:
  `{company_id}/{batch_id}/…` under
  `finsight-legacy-result`. Structure mirrors the
  outbound file per legacy protocol §11: cols 1–2
  `version` (must match input), cols 3–16
  `batch_id` (must match input), cols 17–24
  `sequence` (must match input), cols 25–26
  `result_code` (`AC`/`RJ`/`DU`), cols 27–76
  `detail`, cols 77–80 checksum. Version, batch,
  or sequence skew refuses with
  `EXEC_RESULT_CORRUPT`.
- **X36. Hash verification first.** E6 verifies
  every result line checksum (SHA-256 of cols
  1–76, last 4 hex) and records
  `result_sha256 = SHA-256(result file bytes)`.
  Any checksum failure refuses with
  `EXEC_RESULT_CORRUPT` (maps to
  `LegacyChecksumError` / `LegacyParseError`
  semantics): raw bytes are logged, no outcome is
  recorded, no retry is attempted against corrupt
  data. Non-80-char lines or unparseable fields
  refuse identically.
- **X37. Control-total cross-check.** E6 recomputes
  the Decimal control total from accepted-record
  semantics and cross-checks it against both the
  OUTBOUND control total (X19) and the RESULT
  control total. Mismatch records `REJECTED` in
  full with `EXEC_CONTROL_TOTAL_MISMATCH` (X31);
  partial acceptance is forbidden on this path.
- **X38. Per-record outcome recording.** On clean
  verification, E6 records per-sequence outcomes
  (`AC`/`RJ`/`DU` + verbatim detail), accepted and
  rejected counts and totals (Decimal, 2 dp), and
  the batch outcome label `ACCEPTED` (all `AC`),
  `PARTIAL` (mixed), or `REJECTED` (none `AC` or
  X37 fired). `DU` lines resolve to the original
  line's recorded outcome and never double-count
  amounts.
- **X39. UNKNOWN is explicit and timeout-bounded.**
  E6 polls for the RESULT up to 30 minutes (every
  60s) per legacy protocol §12. If no verifiable
  RESULT arrives in window, E6 records outcome
  `UNKNOWN` with reason `EXEC_RESULT_UNKNOWN`,
  the poll window, and `unknown_flag = true`. UNKNOWN
  is a recorded outcome, not a refusal and not a
  verdict: it asserts nothing about success or
  failure and it never auto-transitions the case.
- **X40. Late results reconcile, never rewrite
  silently.** A RESULT arriving after UNKNOWN is
  ingested under X35–X38 as a new recording event
  linked to the same `execution_id`; the UNKNOWN
  entry is preserved in history and superseded by
  pointer, never edited or deleted. Replay
  presentations during UNKNOWN return the UNKNOWN
  record until reconciliation completes (§7).

## 7. Idempotency end-to-end (normative)

- **X41. Exactly-once effect, repeatable reads.**
  One `execution_id` (one `idempotency_key`, one
  authorization) produces at most one OUTBOUND PUT
  and one legacy processing. Any number of
  presentations returns the same recorded outcome
  (byte-identical handoff, §8). Effect
  deduplication key is
  (`company_id`, `proposal_hash`,
  `proposal_version`) carried as `execution_id`;
  batch namespace key adds `batch_id` per the
  process model §1.9.
- **X42. Same authorization twice.** First
  presentation runs E1 → E2 → E3 → E4, then E6
  records the outcome. Second presentation stops
  at E1/X12: returns the recorded outcome,
  re-runs nothing, emits `AUTHORIZATION_REPLAYED`
  in the audit trail as the reason no second
  effect ran (not as an error to the caller
  expecting the outcome; the outcome itself is
  returned).
- **X43. Same batch id twice (ledger DU).** The
  ledger reports `DU`; E5/E6 resolve to the
  original outcome without reprocessing and
  without double-counting amounts in any total.
- **X44. Replay matrix (normative).** Each row is
  required behavior; tests trace each row.

| # | Replay event | Required behavior |
|---|--------------|-------------------|
| R-1 | Same token, pre-PUT replay | One PUT total; replay returns outcome |
| R-2 | Same token, post-PUT replay | No second PUT; returns receipt/outcome |
| R-3 | Same batch id resubmitted | Ledger `DU`; original outcome stands |
| R-4 | Same token, new batch attempted | Refuse `AUTHORIZATION_REPLAYED` pre-PUT |
| R-5 | Late RESULT after UNKNOWN | Reconcile per X40; history preserved |
| R-6 | Replay during UNKNOWN window | Return UNKNOWN record; keep polling |
| R-7 | Same token, drifted amount/code | Refuse `AUTHORIZATION_SCOPE_ESCAPE` |
| R-8 | Same token after expiry | Refuse `AUTHORIZATION_EXPIRED` |

## 8. Verification handoff (normative)

Purpose: define the exact artifact P6-08 consumes to
prove the outcome. This section defines the handoff
shape only; verification judgments belong to P6-08.

- **X45. Handoff is data, not a verdict.** The
  handoff asserts what happened (bytes, codes,
  totals, hashes); it never asserts
  `EXECUTION_VERIFIED` or `FAILED`, never closes
  the case, and never computes residual variance.
- **X46. Required handoff fields.** Every recorded
  outcome (including UNKNOWN) emits all fields;
  absent RESULT data leaves result fields null
  with `unknown_flag = true`, never zero-filled:

| Field | Type | Notes |
|-------|------|-------|
| `execution_id` | `str` | Token `idempotency_key` |
| `authorization_id` | `str` | Bound G7 token id |
| `proposal_hash` | `str` | Pinned hash |
| `proposal_version` | `int` | Pinned version |
| `company_id` | `str` | `meridian` |
| `situation_id` | `str` | Parent case |
| `batch_id` | `str` | `LEGACY-YYYYMMDD-NNNN` |
| `s3_outbound_key` | `str` | Full OUTBOUND key |
| `outbound_sha256` | `str` | X20 file digest |
| `control_total` | `Decimal` | 2-dp batch total |
| `record_count` | `int` | Data records excl. `99` |
| `accepted_count` | `int` | `AC` lines |
| `rejected_count` | `int` | `RJ` lines |
| `accepted_total` | `Decimal` | 2-dp accepted sum |
| `rejected_total` | `Decimal` | 2-dp rejected sum |
| `per_record` | `list` | Per sequence: code+detail |
| `result_key` | `str\|null` | RESULT key or null |
| `result_sha256` | `str\|null` | X36 digest or null |
| `outcome` | `str` | `ACCEPTED/PARTIAL/REJECTED/UNKNOWN` |
| `unknown_flag` | `bool` | True only with UNKNOWN |
| `recorded_at` | `datetime` | Tz-aware record time |

- **X47. Integrity of the handoff.** The handoff
  carries `outbound_sha256` and (when present)
  `result_sha256` so P6-08 can re-verify bytes
  without trusting this chain's labels. Totals
  are Decimal 2-dp; floats anywhere invalidate
  the handoff (`EXEC_ARTIFACT_REFUSED`).

## 9. FS-231 walk (normative, golden)

Situation `FS-2026-0916-00231`, `company_id =
meridian`, INR, Decimal only. Token binds
(`REPROCESS_LEGACY_RECORD`, `Decimal("10000")`,
code `4812`, scope FS-231) with G7 `idempotency_key`
from P6-06/A20.

- **X48. Historical context (evidence, not this
  execution).** Legacy batch `LEGACY-20260916-0042`:
  500 records sent, 499 accepted, 1 rejected with
  verbatim reason `INVALID_ACCOUNT_CODE` (the
  pre-existing bad code that motivated the fix).
  This batch is consumed as P6-04/P6-05 evidence;
  P6-07 never reprocesses, repairs, or retries it.
- **X49. New correction batch.** E1 permits the
  FS-231 token (seal verifies, binding/expiry/scope
  hold); E2 projects the intent (`10000`, `4812`).
  E3 builds a new OUTBOUND batch (new `batch_id`
  for the new `execution_id`, e.g.
  `LEGACY-20260916-0043`) whose control total is
  `Decimal("10000.00")`; file name
  `CORRECTION_20260916_231.DAT` under
  `meridian/{batch_id}/` in
  `finsight-legacy-outbound`. E3 records
  `outbound_sha256`.
- **X50. Transport and processing.** E4 PUTs the
  exact E3 bytes and read-back-verifies the hash.
  The ledger processes the correction leg: result
  line `AC` for the `10000` posting under code
  `4812` (the historical 499/1 split is not
  replayed onto this batch; this batch carries the
  new correction only).
- **X51. Ingestion to ACCEPTED.** E6 verifies the
  RESULT (checksums, batch/sequence match,
  control-total cross-check `10000.00`), records
  outcome `ACCEPTED` with `accepted_total`
  `Decimal("10000.00")`, `rejected_count` 0, and
  `result_sha256`, then emits the §8 handoff with
  `unknown_flag = false`. No verdict is asserted;
  P6-08 proves it from this handoff.

## 10. Adversarial scenarios (normative, at least 12)

Each scenario names setup, action, and the required
outcome + code. "No effect" means no PUT, no second
PUT, or no ledger reprocessing as applicable.

- **X52/D1. Forged token at execution.** Setup:
  token bytes edited (amount `10000` → `12000`)
  or sealed with the wrong key. Action: present
  for execution. Required: E1 refuses with
  `TOKEN_FORGED`; no intent, artifact, or PUT.
- **X53/D2. Expired token.** Setup: valid token,
  `at` past `expires_at`. Action: present for
  execution. Required: refuse with
  `AUTHORIZATION_EXPIRED`; renewal is a fresh
  P6-06 decision, never an edit.
- **X54/D3. Wrong-batch token reuse.** Setup:
  token with `scope_batch =
  LEGACY-20260916-0043` presented for batch
  `…-0044`. Action: attempt execution. Required:
  refuse with `AUTHORIZATION_SCOPE_ESCAPE` at
  E1 (X10) or E2 (X15); first refusal wins.
- **X55/D4. Tampered artifact in flight.** Setup:
  E3 bytes altered between build and read-back
  (bit flip, truncation, re-serialization).
  Action: E4 read-back. Required: refuse with
  `EXEC_HASH_MISMATCH`; nothing proceeds to E5;
  no silent re-PUT.
- **X56/D5. Duplicate batch submission.** Setup:
  same `batch_id` submitted twice (retry storm or
  operator double-click). Action: second PUT
  attempt. Required: no second effect; ledger
  `DU` resolves to the original outcome (X43);
  FinSight-side second batch for one key refuses
  with `AUTHORIZATION_REPLAYED`.
- **X57/D6. Partial result with missing records.**
  Setup: RESULT omits sequences present in the
  OUTBOUND. Action: E6 ingest. Required: refuse
  with `EXEC_RESULT_CORRUPT` (sequence skew);
  nothing recorded as partial success; raw bytes
  logged for triage.
- **X58/D7. Late result after UNKNOWN timeout.**
  Setup: RESULT arrives after the 30-min window
  already recorded UNKNOWN. Action: late ingest.
  Required: reconcile per X40 (new event, same
  `execution_id`, history preserved); never edit
  the UNKNOWN entry; replays during the gap must
  have returned UNKNOWN (R-6).
- **X59/D8. Control total mismatch.** Setup:
  RESULT control total differs from recomputed
  Decimal total by any amount. Action: E6 cross-
  check. Required: record `REJECTED` in full with
  `EXEC_CONTROL_TOTAL_MISMATCH`; no partial
  acceptance on this path (X31/X37).
- **X60/D9. Double-execution of one
  authorization.** Setup: permitted token
  presented, executed, then presented again
  demanding a second correction. Action: second
  presentation. Required: E1 replay-read returns
  the recorded outcome; audit notes
  `AUTHORIZATION_REPLAYED`; exactly one PUT and
  one processing exist (X41/X42).
- **X61/D10. S3 prefix escape.** Setup: asserted
  key `otherco/{batch}/…` or `meridian/../…`
  against a `meridian`-bound token. Action: E4
  key check. Required: refuse with
  `EXEC_PREFIX_ESCAPE` before any network call;
  no cross-company read or write occurs.
- **X62/D11. Oversized batch.** Setup: record
  count above the configured legacy ceiling.
  Action: E3 build. Required: refuse with
  `EXEC_ARTIFACT_REFUSED` before transport;
  refusal names the ceiling and the count.
- **X63/D12. Empty batch.** Setup: zero data
  records (control record only or nothing).
  Action: E3 build. Required: refuse with
  `EXEC_ARTIFACT_REFUSED`; empty corrections
  never reach S3.
- **X64/D13. Corrupt result line.** Setup: RESULT
  line != 80 chars or any line checksum fails.
  Action: E6 ingest. Required: refuse with
  `EXEC_RESULT_CORRUPT`; raw bytes logged; no
  outcome recorded; no retry against corrupt
  data (legacy protocol §12).

## 11. Explicit non-goals (normative)

- **X65. No approval minting (P6-06 owned).** No
  G1–G7 gates, no decisions, no tokens, no seals,
  no expiry edits, no tier or role rules. Token
  mechanics beyond consumption are out of scope.
- **X66. No verification judgments (P6-08).** No
  `EXECUTION_VERIFIED` / `FAILED` verdicts, no
  residual-variance math, no close decisions. P6-08
  consumes the §8 handoff; it is defined elsewhere.
- **X67. No LLM anywhere.** No prompts,
  completions, rankings, confidences, or steered
  parameters at any stage (X4, X16). Deterministic
  code paths only.
- **X68. No new lifecycle states.** No states
  added, renamed, or redefined; no transitions
  executed by this spec (X1). `EXECUTING` and
  `UNKNOWN` (an execution outcome label, not a
  lifecycle state) keep their defined meanings.
- **X69. No edits to frozen contracts.** No P1,
  P6-02, P6-03, P6-04, P6-05, or P6-06 changes; no
  legacy-protocol reinterpretation. Conflicts
  resolve in favor of the frozen source plus
  `finance/business_rules/meridian.py` and
  `finance/approval/authorization.py`.
- **X70. No Temporal, queues, streams, or new
  infra.** No workers, schedulers, or AWS services
  beyond the existing S3 OUTBOUND→RESULT seam
  (two buckets, key conventions, retry/timeout
  budgets consumed as given).

## 12. Requirement index

| Requirement | Section | Statement |
|-------------|---------|-----------|
| X1 | §0 | Lifecycle frozen, EXECUTING consumed |
| X2 | §0 | P6-05 verdict frozen |
| X3 | §0 | G7 token shape frozen |
| X4 | §0 | No LLM write authority |
| X5 | §0 | Fixed stage order E1–E6 |
| X6 | §0 | Audit spine entry per stage |
| X7 | §1 E1 | Consumption inputs |
| X8 | §1 E1 | Seal caller-supplied, never embedded |
| X9 | §1 E1 | Fixed check order |
| X10 | §1 E1 | Refusal codes |
| X11 | §1 E1 | Permit/refuse/replay outputs |
| X12 | §1 E1 | Single-use effect, replay-read |
| X13 | §1 E1 | No minting/renewal/upgrade |
| X14 | §2 E2 | Projection, no computation |
| X15 | §2 E2 | Closed vocabulary, drift refuses |
| X16 | §2 E2 | No LLM/human/enrichment input |
| X17 | §2 E2 | Batch scope pinning |
| X18 | §3 E3 | Schema consumed verbatim |
| X19 | §3 E3 | Decimal control total |
| X20 | §3 E3 | Whole-file SHA-256 |
| X21 | §3 E3 | Batch identity, key embedding |
| X22 | §3 E3 | Refuse-before-transport |
| X23 | §3 E3 | Artifact output is PUT bytes |
| X24 | §4 E4 | Fixed S3 seam, prefix check |
| X25 | §4 E4 | PUT with read-back verify |
| X26 | §4 E4 | Retry budget, then stop |
| X27 | §4 E4 | Transport never mutates meaning |
| X28 | §4 E4 | Receipt preconditions E5 |
| X29 | §5 E5 | Per-record results as given |
| X30 | §5 E5 | Rejections verbatim, no retry |
| X31 | §5 E5 | Control mismatch fails closed |
| X32 | §5 E5 | Duplicate batch, no reprocess |
| X33 | §5 E5 | Sequence discipline |
| X34 | §5 E5 | Observation only |
| X35 | §6 E6 | RESULT seam and shape |
| X36 | §6 E6 | Hash verification first |
| X37 | §6 E6 | Control-total cross-check |
| X38 | §6 E6 | Per-record recording |
| X39 | §6 E6 | UNKNOWN explicit, bounded |
| X40 | §6 E6 | Late results reconcile |
| X41 | §7 | Exactly-once effect |
| X42 | §7 | Same authorization twice |
| X43 | §7 | Duplicate batch id (DU) |
| X44 | §7 | Replay matrix R-1–R-8 |
| X45 | §8 | Handoff is data, not verdict |
| X46 | §8 | Handoff fields |
| X47 | §8 | Handoff integrity |
| X48 | §9 | FS-231 historical context |
| X49 | §9 | FS-231 correction batch |
| X50 | §9 | FS-231 transport+processing |
| X51 | §9 | FS-231 ingestion to ACCEPTED |
| X52 | §10 D1 | Forged token refused |
| X53 | §10 D2 | Expired token refused |
| X54 | §10 D3 | Wrong-batch reuse refused |
| X55 | §10 D4 | Tampered artifact refused |
| X56 | §10 D5 | Duplicate batch, no reprocess |
| X57 | §10 D6 | Missing records corrupt |
| X58 | §10 D7 | Late result reconciles |
| X59 | §10 D8 | Control mismatch rejected |
| X60 | §10 D9 | Double-execution replay-read |
| X61 | §10 D10 | Prefix escape refused |
| X62 | §10 D11 | Oversized batch refused |
| X63 | §10 D12 | Empty batch refused |
| X64 | §10 D13 | Corrupt result refused |
| X65 | §11 | No approval minting |
| X66 | §11 | No verification judgments |
| X67 | §11 | No LLM anywhere |
| X68 | §11 | No new lifecycle states |
| X69 | §11 | No frozen-contract edits |
| X70 | §11 | No new infra |

---

*P6-07 deterministic execution and legacy boundary
contract. Tokens authorize; stages execute once;
hashes prove; UNKNOWN stays explicit; P6-08 verifies.*

## 12. Contract adjudications, review round 1 (normative)

Review of `eaca4fd` held the engine wave on five
contract-level gaps. Each adjudication below is a
frozen decision the engine must implement; where an
adjudication narrows an X-item, the adjudication
wins and the X-item is read through it. No frozen
protocol, domain, or approval document is edited by
this section — P6-07 pins its own consumption of
those contracts.

- **A1. Logical vs wire batch identity.** The
  logical id `LEGACY-YYYYMMDD-NNNN` (21 chars)
  cannot occupy wire cols 3–16 (`CHAR(14)`). The
  legacy protocol's own codec resolves this:
  wire form is the compact `LEGYYMMDD-NNNN`
  (14 chars) via the existing
  `_batch_id_to_compact` / `_compact_to_batch_id`
  functions, which the engine wraps and never
  reimplements (century prefix `20` is recorded
  behavior, not engine logic). Frozen rule:
  logical form everywhere except the 80-char
  lines; compact form on the wire only. X18/X21
  are read through this rule: "schema consumed
  verbatim" means the compact id in cols 3–16,
  and self-verify expands it back before any
  comparison with logical ids (keys, records,
  audit, handoff). A line carrying a 21-char id
  in cols 3–16 refuses with
  `EXEC_ARTIFACT_REFUSED`.
- **A2. Durable execution reservation (CAS).**
  Exactly-once effect requires a durable commit
  point before any artifact work, or two workers
  (and crash recovery) can both perform the
  single PUT. Frozen order inside E1, after the
  token checks pass: `atomic claim(execution_id)`
  inserts a reservation row keyed by
  `execution_id` (= `idempotency_key`) carrying
  the authorization binding digest, company,
  case, and state `RESERVED`. Exactly one
  claimant wins; every concurrent loser reads
  the winner's row and follows the replay-read
  path (`AUTHORIZATION_REPLAYED` recorded, never
  re-executed). A crash between `RESERVED` and a
  recorded receipt recovers by resuming from the
  row, but a missing receipt alone never
  authorizes a re-PUT: the outbound key is
  deterministic, so recovery first performs a
  bounded S3 read of that exact key (existing
  read capability; no `HeadObject`, no new
  infrastructure). If the object exists and its
  bytes hash exactly to `outbound_sha256`, the
  transport receipt is durably recorded from the
  observation and NO second PUT occurs. If the
  object is absent, PUT the exact E3 bytes once.
  If the object exists with differing bytes,
  refuse (integrity/collision semantics win over
  retransmission) and escalate; no recovery path
  may reserialize. This closes the crash window
  between a completed external PUT and the
  persisted receipt, preserving X41's "at most
  one OUTBOUND PUT" literally. The row uses
  existing persistence patterns (conditional
  insert-or-read, predicated UPDATE on
  `(execution_id, state)`); no queues, Temporal,
  workers, or new infrastructure. State
  transitions on the row (`RESERVED` → receipt →
  terminal outcome) are recorded, never edited.
- **A3. Where DU may legitimately enter.** Three
  cases, only two of which are legal: (a)
  FinSight replay — same execution presented
  again: NO second PUT by construction (A2
  reservation); the recorded outcome returns
  (X42). A same-execution second PUT is a
  contract violation, not a DU source. (b)
  Ledger-side duplicate — the ledger processed
  OUR batch twice on its side and reports `DU`
  for already-seen sequences: recorded verbatim,
  resolves to the original outcome, no FinSight
  re-PUT (nothing left to PUT). (c)
  Pre-existing batch collision — our `batch_id`
  collides with a legacy-side batch predating us:
  S3 transport succeeds (PUT is not the DU
  source), then legacy observes the already-known
  batch and its RESULT reports `DU`. E5/E6 record
  the `DU` outcome and escalate per policy; never
  auto-retry under a new id (X21 forbids a second
  `batch_id` for one key; a new id needs a new
  authorization cycle). X43 covers (b); X56/D5
  covers (b)-style observation and (c); the
  forbidden (a)-as-PUT path is closed by A2.
  `DU` is a legacy observation vocabulary item,
  never an S3 transport response.
- **A4. Retry budget frozen.** One initial
  attempt plus up to three retries: at most four
  PUT+read-back-verify cycles per execution, with
  backoffs 1s, 2s, 4s before retries 1, 2, 3.
  Each cycle resends byte-identical E3 output;
  re-serialization between cycles is forbidden.
  Read timeout stays 10s per object. X26 is read
  through this rule wherever it says "at most 3
  times".
- **A5. Generic artifact naming.** The rule is
  `CORRECTION_<YYYYMMDD>_<SEQ>.DAT` where `SEQ`
  is the last three digits of the owning
  situation's sequence component (`FS-…-00231`
  → `231`). `CORRECTION_20260916_231.DAT` is the
  FS-231 instantiation, not the rule. The engine
  derives `SEQ` from the situation id and must
  never hard-code `231`; S3 key prefixes stay
  batch-scoped (`{company_id}/{batch_id}/`) per
  X24. X24/X49 examples are read as
  instantiations of this rule.

| A1 | §12 | Logical vs wire batch identity |
| A2 | §12 | Durable reservation (CAS) |
| A3 | §12 | DU entry points vs replay |
| A4 | §12 | Retry budget: 1+3 attempts |
| A5 | §12 | Generic artifact naming rule |
