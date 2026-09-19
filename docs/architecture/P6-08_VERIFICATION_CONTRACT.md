# P6-08 Independent Post-Execution Verification Contract — Meridian

**Status:** Draft spec for P6-08 on
`feat/finsight-p6-08-verification`.
**Base:** `f2e197d` (P6-07 merge). P6-02 lifecycle,
P6-06 approval, and P6-07 execution semantics are FROZEN.
**Scope:** Single company (`company_id = meridian`, INR,
Decimal-only money, S3 read seams only).
**Sources:** `docs/architecture/P6-07_EXECUTION_CONTRACT.md`
§8 (X45–X47 handoff shape, the only P6-08 contract text),
`finance/domain/verification.py` (`VerificationReport`,
`VerificationVerdict`, `is_accepted`),
`finance/domain/lifecycle.py`
(`require_verification_for_close`,
`validate_persistable_state`), and
`docs/domain/meridian-process-model.md` (§4 FS-231,
§1.9 ExecutionRecord, §1.10 VerificationReport, §2).
**Type:** DOC-ONLY. No code, no agent changes, no P1
edits, no new services, no new infra.

Conventions: all money is `Decimal` with 2 dp; `float`
is forbidden. "Refuse" means: stop verification for
this handoff, emit the named reason code, record one
audit entry, mint no report on the incomplete path, and
change no external state. Silent drops, silent fixes,
assumed outcomes, and partial-verified verdicts are
forbidden. Every normative statement is numbered `Fn`
for test traceability. "Re-read" means: a fresh GET
from the authoritative source observed at verify time,
never a reuse of executor-supplied bytes or labels.
Tolerance is `CompanyConfiguration().tolerance_minor`
(`Decimal("100")`), consumed as given, never redefined.

## 0. Frozen inputs (normative, consumed as given)

- **F1. P6-02 lifecycle is frozen.** The
`APPROVED -> EXECUTING -> VERIFYING -> CLOSED` chain,
the `VERIFYING -> INVESTIGATING` reopen path, the
banned transitions, and the terminal states are
consumed exactly as written in the process model §2
and `lifecycle.py`. This spec defines no new states,
renames none, and executes no transitions itself.
- **F2. P6-06 approval semantics are frozen.** G7 token
shape, seal, idempotency key, and replay rules are
consumed as given. This spec mints no authorization
and redefines no approval field; it only checks that
an authorization binding is present (F36).
- **F3. P6-07 execution semantics are frozen.** Stages
E1–E6, the §8 handoff shape (X45–X47), the UNKNOWN
outcome, and the A1–A6 adjudications are consumed as
given. This spec redefines no execution stage and
recomputes no execution input.
- **F4. D1 report model is frozen.** The normative
report is `finance/domain/verification.py`
`VerificationReport` with exactly six fields
(`situation_id`, `execution_id`,
`legacy_total_after`, `variance_after`, `verdict`,
`checked_at`). §4 mints exactly this shape; the
process-model §1.10 row (`report_id`,
`company_id`, `EXECUTION_VERIFIED`) is read through
the code model: `VERIFIED` is the verdict string and
no extra field is minted.
- **F5. D1 close gate is frozen.** `CLOSED` requires
`require_verification_for_close` to accept: bound
`situation_id`, tz-aware `at`, and
`is_accepted(tolerance)` (verdict `VERIFIED` with
`abs(variance_after) <= tolerance`). Persistence
additionally requires `verified_total` present and
equal to `legacy_total_after`
(`validate_persistable_state`). This spec produces
reports that pass that gate with zero adaptation.
- **F6. Audit spine.** Every verification run records
one audit entry: handoff digest, re-read digests,
permit/refuse or VERIFIED/FAILED, reason code, and
report hash when minted. Entries are append-only.
Money appears only as 2-dp totals, never raw PII.

## 1. Central boundary (normative)

- **F7. Central boundary (verbatim).** P6-08
independently verifies external/post-execution
financial state by re-reading authoritative sources.
It never trusts the executor's reported success,
never recomputes execution inputs, and never becomes
a second execution or reconciliation engine.
- **F8. Never trusts reported success.** Handoff
`outcome` (`ACCEPTED`/`PARTIAL`/`REJECTED`/`UNKNOWN`),
counts, totals, and digests are claims to be
re-observed, never facts. No `VERIFIED` verdict is
minted on handoff labels alone; every verdict needs
the §3 re-reads to agree.
- **F9. Never recomputes execution inputs.** Intent
projection, artifact serialization, control-total
derivation, transport, and ledger polling are P6-07
owned. P6-08 performs no E1–E6 step, builds no
OUTBOUND bytes, and re-derives no amount, code, or
batch id from the token.
- **F10. Never a second execution or reconciler.**
P6-08 writes no ledger, PUTs no S3 object, mints no
proposal or approval, opens no investigation, and
generates no hypothesis. It reads external state and
mints at most one `VerificationReport` per run.

## 2. Verification inputs (normative)

The §8 (X45–X47) handoff is the only input. F11
splits its fields into carried bindings versus
cross-checked claims.

- **F11. Handoff consumed whole, trusted in no
part.** Every run takes the recorded §8 handoff for
one `execution_id` (`execution_id`,
`authorization_id`, `proposal_hash`,
`proposal_version`, `company_id`, `situation_id`,
`batch_id`, `s3_outbound_key`, `outbound_sha256`,
`control_total`, `record_count`, `accepted_count`,
`rejected_count`, `accepted_total`,
`rejected_total`, `per_record`, `result_key`,
`result_sha256`, `outcome`, `unknown_flag`,
`recorded_at`). Absent RESULT data leaves result
fields null with `unknown_flag = true` (X46).
- **F12. Carried bindings (locators, never
proof).** `execution_id`, `authorization_id`,
`proposal_hash`, `proposal_version`, `company_id`,
`situation_id`, `batch_id`, `s3_outbound_key`,
`result_key`, and `recorded_at` are carried verbatim
as the identity of what is being verified. They
locate re-reads; agreement with a locator never
proves financial truth.
- **F13. Cross-checked claims (proof required).**
`outbound_sha256`, `result_sha256`,
`control_total`, `record_count`, `accepted_count`,
`rejected_count`, `accepted_total`,
`rejected_total`, `per_record`, `outcome`, and
`unknown_flag` are claims. Each must agree with a
fresh §3 re-read before any `VERIFIED` verdict.
- **F14. Entry gate: UNKNOWN never verifies.**
A handoff with `outcome = UNKNOWN` (or
`unknown_flag = true`, null `result_key` /
`result_sha256`) is not verifiable: verification
records `VERIFY_RESULT_MISSING` and mints no report
(F34). UNKNOWN is an execution outcome label, not a
lifecycle state and not a FAILED verdict.
- **F15. Entry gate: case and company binding.**
Runs refuse before any re-read when `company_id !=
meridian` or `situation_id` is blank: reason codes
`VERIFY_CASE_SKEW` / `VERIFY_PREFIX_ESCAPE`. No
cross-company or unbound verification ever runs.
- **F16. Entry gate: Decimal hygiene.** Any handoff
total not Decimal 2-dp (float participation, wrong
scale) invalidates the handoff with
`VERIFY_HANDOFF_CORRUPT`; no re-read runs on a
corrupt handoff.
- **F17. No input beyond handoff plus re-reads.**
No prompt, completion, email text, chat context, or
human edit supplies amounts, totals, hashes, codes,
or verdicts. The LLM plane, if present, is read-only
context and never steers verification.

## 3. Independent re-reads (normative)

Every re-read is a fresh external observation made at
verify time. Reusing handoff bytes, labels, or digests
as the observation itself is forbidden.

- **F18. R1 — RESULT re-read by key.** Verification
GETs `result_key` from `finsight-legacy-result`
(fresh read, 10s timeout per object) and computes
`SHA-256(result bytes)` over the exact bytes
returned. The recomputed digest must equal handoff
`result_sha256`; line checksums, version, batch id,
and sequence skew are re-checked per X35–X36 shape
rules before any total is read.
- **F19. R2 — books-side legacy total re-read.**
Verification re-reads the authoritative legacy
accepted total for the situation (`legacy_total_after`
source of truth, not handoff `accepted_total`).
Post-execution expectation for FS-231: legacy before
`982500` plus correction `10000` equals legacy after
`992500` (Decimal 2-dp). R2 is the sole provenance
of the report's `legacy_total_after` (F26).
- **F20. R3 — expectation re-read.** Verification
re-reads the expected settlement total and any
recognised pending timing item from their
authoritative sources (never from the handoff).
Residual is `expected - legacy_total_after -
pending` in Decimal arithmetic. For FS-231:
`1000000 - 992500 - 7500 = 0`.
- **F21. Freshness rule.** R1, R2, and R3 each run
inside the verification run against live sources.
Cached executor output, handoff-embedded bytes, or a
prior verification's observations never satisfy a
re-read. A re-read failure (timeout, missing key,
unparseable bytes) is recorded, never retried into
a new meaning, and never papered over.
- **F22. Digest agreement is byte-exact.**
`SHA-256(re-read RESULT bytes) == result_sha256`
to the hex digit; one bit of drift fails the run
(F34). Outbound bytes are not re-PUT or rebuilt;
`outbound_sha256` is preserved as provenance only
and is not re-derived by P6-08 (F9).
- **F23. Count reconciliation.** Re-read per-record
codes must reconcile: `accepted_count +
rejected_count` covers every non-control sequence,
`DU` lines resolve to their original outcome with
no double-count, and `record_count` matches the
re-read line population. Any skew fails the run
with `VERIFY_COUNT_SKEW` (F35).
- **F24. Batch binding on the wire.** The re-read
RESULT header `batch_id` (compact wire form per
P6-07/A1 expanded before compare) must equal
handoff `batch_id`. Skew fails with
`VERIFY_BATCH_SKEW`, even when totals coincidentally
match (F35).
- **F25. Read-only transport.** Re-reads use the
existing S3 read seams only (`finsight-legacy-
result` RESULT GET plus the established books/
expectation reads). No PUT, no new bucket, no
queue, no Temporal, no new infra.

## 4. Report minting (normative)

- **F26. Exactly six fields, each with provenance.**
Minted reports carry exactly the D1 model fields,
no more and no fewer: `situation_id` ← handoff
binding (after F15/F36 pass); `execution_id` ←
handoff `execution_id` (non-blank, model-enforced);
`legacy_total_after` ← R2 observation only (F19);
`variance_after` ← R3 residual math only (F20);
`verdict` ← F27 conjunction only; `checked_at` ←
verification run time, tz-aware (F29). No field is
copied from a handoff financial claim.
- **F27. VERIFIED is a three-way conjunction.**
Verdict `VERIFIED` mints only when all three hold:
(a) residual `abs(variance_after) <= tolerance`
(`Decimal("100")`); (b) R1 digest agrees with
`result_sha256` and header/sequence checks pass
(F22/F24); (c) counts reconcile per F23 and every
re-read control total cross-checks in Decimal. One
failure anywhere mints `FAILED`, never VERIFIED.
- **F28. FAILED carries a reason code, never
silence.** Every `FAILED` report records exactly
one primary reason code from the registry:
`VERIFY_DIGEST_MISMATCH`, `VERIFY_RESULT_MUTATED`,
`VERIFY_BATCH_SKEW`, `VERIFY_COUNT_SKEW`,
`VERIFY_CONTROL_SKEW`, `VERIFY_TOLERANCE_EXCEEDED`,
`VERIFY_CASE_SKEW`, `VERIFY_UNAUTHORIZED_EXECUTION`,
`VERIFY_CLOCK_SKEW`. Failed runs still record R1–R3
observations made so far plus the code; there is no
silent FAILED and no code-less FAILED.
- **F29. `checked_at` discipline.** `checked_at` is
the tz-aware verification run time supplied by the
caller (no auto-stamp inside the model). Naive
`checked_at` mints nothing (Pydantic refuses);
backdated `checked_at` earlier than handoff
`recorded_at` mints `FAILED` with
`VERIFY_CLOCK_SKEW`; future skew beyond the 5-minute
budget mints `FAILED` with `VERIFY_CLOCK_SKEW`.
- **F30. No partial-verified.** The verdict enum has
exactly two members (`VERIFIED`, `FAILED`). There
is no `PARTIAL_VERIFIED`, no `MOSTLY_VERIFIED`, and
no confidence score. Partial agreement across R1–R3
mints `FAILED` with the first failing code.
- **F31. Deterministic idempotent mint.** The mint
key is (`situation_id`, `execution_id`,
`result_sha256`, `legacy_total_after`,
`variance_after`). Re-running verification for the
same handoff with unchanged re-reads yields a
byte-identical report (same verdict, same fields
except a fresh `checked_at` is forbidden from
altering identity: replays reuse the recorded
report per F40). A second run never double-writes
external state; verification has no external side
effects to duplicate.
- **F32. FAILED reopens, never closes.** A `FAILED`
report is consumable only by the
`VERIFYING -> INVESTIGATING` path. Presenting it on
the `CLOSED` path refuses inside
`require_verification_for_close`
(`is_accepted` false). Verification itself executes
no transition.
- **F33. Close-ready shape.** A `VERIFIED` report
with residual within tolerance passes
`require_verification_for_close` and
`validate_persistable_state` with zero adaptation
when stored with `verified_total ==
legacy_total_after` and a tz-aware close `at`. The
spec adds no adapter field and no wrapper object.

## 5. Refusal and negative cases (normative)

Incomplete runs (re-reads unavailable) mint no report;
completed runs with failed checks mint FAILED (F28).
Both record an audit entry with the code.

- **F34. Digest mismatch and late mutation.**
`SHA-256(R1 bytes) != result_sha256`, any RESULT
line-checksum failure, or RESULT bytes differing
from the handoff digest (tamper or late mutation
after handoff) mint `FAILED` with
`VERIFY_DIGEST_MISMATCH` (tamper-evident case:
`VERIFY_RESULT_MUTATED`). Raw re-read bytes are
logged for triage; nothing is repaired.
- **F35. Wrong-batch and count skew.** RESULT header
`batch_id` != handoff `batch_id` mints `FAILED`
with `VERIFY_BATCH_SKEW`. Accepted/rejected counts
or control totals disagreeing with the R1 re-read
mint `FAILED` with `VERIFY_COUNT_SKEW` /
`VERIFY_CONTROL_SKEW`. Coincidental total equality
never overrides a binding skew.
- **F36. Missing RESULT is incomplete, not FAILED.**
Null `result_key`, absent S3 key at verify time, or
an UNKNOWN handoff means verification cannot
complete: mint no report, record
`VERIFY_RESULT_MISSING` with the poll window. This
is distinct from execution UNKNOWN (which is the
handoff's own outcome label) and distinct from a
FAILED verdict (which needs completed re-reads).
- **F37. Tolerance exceeded mints FAILED.** Completed
re-reads with `abs(variance_after) > tolerance`
mint `FAILED` with `VERIFY_TOLERANCE_EXCEEDED`,
even when digests agree and counts reconcile. The
boundary is inclusive: residual exactly `100.00`
accepts; `100.01` fails (Decimal compare, F20).
- **F38. Wrong-situation handoff mints nothing.**
Handoff `situation_id` != case under verification
mints no report and records `VERIFY_CASE_SKEW`.
Cross-case report presentation additionally refuses
inside `require_verification_for_close` (bound-to-
another-situation rule, frozen).
- **F39. Unapproved execution mints nothing.** A
handoff with blank `authorization_id` (no G7
binding present) mints no report and records
`VERIFY_UNAUTHORIZED_EXECUTION`. Verification never
launders an unapproved execution into a closeable
report.
- **F40. Stale handoff replay is idempotent.** A
second verification run for an already-verified
(`situation_id`, `execution_id`) pair returns the
recorded report byte-identically and records
`VERIFY_STALE_REPLAY` in audit as the reason no new
mint occurred. Replays never mint a second report
and never alter the first.

## 6. FS-231 walk (normative, golden)

Situation `FS-2026-0916-00231`, `company_id =
meridian`, INR, Decimal only. Tolerance `100.00`.

- **F41. Handoff in (ACCEPTED, 992500-bound).**
P6-07 emits the §8 handoff with outcome `ACCEPTED`,
`accepted_total Decimal("10000.00")`,
`rejected_count 0`, `unknown_flag = false`, bound
to FS-231 and the correction execution
(`idempotency_key` = `execution_id`). The walk
consumes this handoff as claims only (F8).
- **F42. Re-reads out.** R1 GETs the correction
RESULT by `result_key` and matches `result_sha256`
with header batch `LEGACY-20260916-0043` (wire
compact expanded per A1) and one `AC` line for the
`10000` posting under code `4812`. R2 observes
legacy `992500` (`982500 + 10000`). R3 observes
expected `1000000` and pending `7500`.
- **F43. Residual zero.** `variance_after =
1000000 - 992500 - 7500 = Decimal("0.00")`,
so `abs(0) <= 100` holds with digests agreeing and
counts reconciling. The run mints `VERIFIED` with
`legacy_total_after Decimal("992500.00")`,
situation `FS-2026-0916-00231`, and the correction
`execution_id`.
- **F44. Zero-adaptation close.** The report passes
`require_verification_for_close` with a tz-aware
close `at` and tolerance `100`: same
`situation_id`, `is_accepted` true. Persisting with
`verified_total == legacy_total_after`
(`992500.00`) and tz-aware `closed_at` passes
`validate_persistable_state`. No adapter needed.
- **F45. Historical batch untouched.** Legacy batch
`LEGACY-20260916-0042` (499/1 split,
`INVALID_ACCOUNT_CODE`) stays evidence only. The
walk never reprocesses, repairs, or retries it;
only the new correction batch verifies.

## 7. Adversarial scenarios (normative, V1–V10)

Each scenario names setup, action, and the required
outcome plus code. "No report" means nothing is
minted and the audit entry carries the code.

- **F46/V1. Executor lies about success.** Setup:
handoff claims `ACCEPTED` but no RESULT exists at
`result_key`. Action: verify. Required: no report;
record `VERIFY_RESULT_MISSING`. Never mint
`VERIFIED` from labels alone (F8/F36).
- **F47/V2. Tampered RESULT post-handoff.** Setup:
RESULT bytes altered after handoff (bit flip,
truncation, re-serialization). Action: R1 compare.
Required: mint `FAILED` with
`VERIFY_RESULT_MUTATED`; raw bytes logged; no
repair, no retry into new meaning (F34).
- **F48/V3. Replayed stale handoff.** Setup: same
handoff verified twice (operator double-click,
retry storm). Action: second run. Required: return
the recorded report byte-identically; audit notes
`VERIFY_STALE_REPLAY`; no second mint and no side
effects (F40/F31).
- **F49/V4. Wrong-situation handoff.** Setup:
handoff bound to FS-231 presented for another case.
Action: verify. Required: no report; record
`VERIFY_CASE_SKEW`. A smuggled report would
additionally refuse at the D1 gate (F38).
- **F50/V5. Near-tolerance residual gaming.**
Setup: digests agree, counts reconcile, residual
`100.00` vs `100.01` vs `101.00`. Action: verdict.
Required: `100.00` mints `VERIFIED`;
`100.01` and `101.00` mint `FAILED` with
`VERIFY_TOLERANCE_EXCEEDED`. Boundary is `<=`
in Decimal, never float (F27/F37).
- **F51/V6. Backdated `checked_at`.** Setup:
`checked_at` earlier than handoff `recorded_at`.
Action: mint. Required: mint `FAILED` with
`VERIFY_CLOCK_SKEW`. Naive `checked_at` mints
nothing (model refuses). No backdated VERIFIED
ever closes (F29).
- **F52/V7. Cross-case verification reuse.** Setup:
VERIFIED report for FS-231 presented to close
another situation. Action: close path. Required:
`require_verification_for_close` refuses
(bound-to-another-situation, frozen F5). P6-08
never rebinds a report to a new situation (F26).
- **F53/V8. Unapproved execution.** Setup: handoff
with blank `authorization_id` (no G7 binding).
Action: verify. Required: no report; record
`VERIFY_UNAUTHORIZED_EXECUTION`. Verification never
creates closeability for unapproved work (F39).
- **F54/V9. Double-mint with different verdicts.**
Setup: second run for the same
(`situation_id`, `execution_id`) would conclude
differently (ledger drifted between runs). Action:
second mint attempt. Required: refuse the second
mint; the first recorded report stands; audit notes
`VERIFY_DOUBLE_MINT_REFUSED` with both
observations. Reports are recorded, never edited.
- **F55/V10. Clock-skewed timestamps.** Setup:
naive close `at`, or `at`/`checked_at` skewed
beyond the 5-minute future budget. Action: close.
Required: naive `at` refuses at the D1 gate
(frozen F5); skewed `checked_at` mints `FAILED`
with `VERIFY_CLOCK_SKEW` (F29). No clock skew
ever manufactures VERIFIED.

## 8. Explicit non-goals (normative)

- **F56. No execution transport.** No E1–E6 logic, no
OUTBOUND build, no S3 PUT, no read-back verify, no
polling cadence, no UNKNOWN recording, no retry
budget. P6-07 owns all of it (F3/F9).
- **F57. No approval minting.** No G1–G7 gates, no
tokens, no seals, no expiry edits, no tier or role
rules. Presence of the binding is checked (F39);
its manufacture belongs to P6-06.
- **F58. No reconciliation engine.** No variance
detection, no correlation, no evidence collection,
no control-total derivation for execution. Residual
math here (F20) serves the verdict only and never
re-derives an execution input.
- **F59. No hypothesis generation.** No hypotheses,
no ranking, no explanations, no proposals. A FAILED
verdict routes to re-investigation via the frozen
lifecycle; it does not diagnose the cause.
- **F60. No LLM anywhere.** No prompts, completions,
rankings, confidences, or steered parameters (F17).
Deterministic Decimal code paths only.
- **F61. No new lifecycle states.** No states added,
renamed, or redefined; no transitions executed by
this spec (F1). `VERIFYING`, `CLOSED`, and
`INVESTIGATING` keep their frozen meanings.
- **F62. No edits to frozen contracts.** No P1,
P6-02, P6-03, P6-04, P6-05, P6-06, or P6-07
changes; no legacy-protocol reinterpretation.
Conflicts resolve in favor of the frozen source.
- **F63. No Temporal, queues, streams, or new
infra.** No workers, schedulers, or AWS services
beyond the existing S3 read seams and the
established books/expectation reads (F25).

## 9. Requirement index

| Requirement | Section | Statement |
|-------------|---------|-----------|
| F1 | §0 | Lifecycle frozen, consumed |
| F2 | §0 | Approval frozen, minting excluded |
| F3 | §0 | Execution frozen, §8 consumed |
| F4 | §0 | D1 report model frozen, six fields |
| F5 | §0 | D1 close gate frozen, zero adaptation |
| F6 | §0 | Audit spine entry per run |
| F7 | §1 | Central boundary verbatim |
| F8 | §1 | Reported success never trusted |
| F9 | §1 | Execution inputs never recomputed |
| F10 | §1 | No second execution or reconciler |
| F11 | §2 | Handoff consumed whole, trusted none |
| F12 | §2 | Carried bindings are locators |
| F13 | §2 | Claims need proof |
| F14 | §2 | UNKNOWN never verifies |
| F15 | §2 | Case and company binding gate |
| F16 | §2 | Decimal hygiene gate |
| F17 | §2 | No input beyond handoff plus re-reads |
| F18 | §3 | R1 RESULT re-read by key |
| F19 | §3 | R2 legacy total re-read, 992500 |
| F20 | §3 | R3 expectation re-read, residual math |
| F21 | §3 | Freshness rule, no reuse |
| F22 | §3 | Byte-exact digest agreement |
| F23 | §3 | Count reconciliation, DU no double |
| F24 | §3 | Batch binding on the wire |
| F25 | §3 | Read-only transport, existing seams |
| F26 | §4 | Six fields, each with provenance |
| F27 | §4 | VERIFIED three-way conjunction |
| F28 | §4 | FAILED carries one reason code |
| F29 | §4 | checked_at discipline |
| F30 | §4 | No partial-verified |
| F31 | §4 | Deterministic idempotent mint |
| F32 | §4 | FAILED reopens, never closes |
| F33 | §4 | Close-ready shape, zero adaptation |
| F34 | §5 | Digest mismatch, late mutation FAILED |
| F35 | §5 | Wrong-batch and count skew FAILED |
| F36 | §5 | Missing RESULT incomplete, no report |
| F37 | §5 | Tolerance exceeded FAILED |
| F38 | §5 | Wrong-situation handoff, no report |
| F39 | §5 | Unapproved execution, no report |
| F40 | §5 | Stale replay returns recorded report |
| F41 | §6 | FS-231 handoff in, ACCEPTED claims |
| F42 | §6 | FS-231 re-reads out |
| F43 | §6 | FS-231 residual zero, VERIFIED |
| F44 | §6 | FS-231 zero-adaptation close |
| F45 | §6 | Historical batch untouched |
| F46 | §7 V1 | Executor lies, missing result |
| F47 | §7 V2 | Tampered RESULT post-handoff |
| F48 | §7 V3 | Replayed stale handoff idempotent |
| F49 | §7 V4 | Wrong-situation handoff refused |
| F50 | §7 V5 | Near-tolerance boundary 100 vs 101 |
| F51 | §7 V6 | Backdated checked_at FAILED |
| F52 | §7 V7 | Cross-case reuse refused at gate |
| F53 | §7 V8 | Unapproved execution, no report |
| F54 | §7 V9 | Double-mint refused, first stands |
| F55 | §7 V10 | Clock-skewed timestamps refused |
| F56 | §8 | No execution transport |
| F57 | §8 | No approval minting |
| F58 | §8 | No reconciliation engine |
| F59 | §8 | No hypothesis generation |
| F60 | §8 | No LLM anywhere |
| F61 | §8 | No new lifecycle states |
| F62 | §8 | No frozen-contract edits |
| F63 | §8 | No new infra |
| F64 | §10 | Double-mint registry invariant |
| F65 | §10 | R2 seam named, handoff-independent |
| F66 | §10 | R3 seams named, handoff-independent |

---

*P6-08 independent post-execution verification contract.
Re-reads prove; handoffs claim; digests agree; residual
decides; the D1 gate closes.*

## 10. Pre-implementation adjudications (normative)

Adjudication 1 and 2 below clear the contract into
the engine-design gate. They add requirements
(F64–F66); they change no frozen contract and no
existing F-item.

- **F64. Double-mint registry invariant.**
`VERIFY_DOUBLE_MINT_REFUSED` joins the F28 reason
registry as a frozen code (closed world: the
minter emits no code outside the registry).
Mint key is `execution_id`: a second mint with
the same key and byte-identical report inputs
returns the identical report (idempotent replay,
mirroring the A6 handoff rule); the same key
with any differing report content refuses with
`VERIFY_DOUBLE_MINT_REFUSED`, first record
stands, and no second verification identity is
created. One execution holds at most one
terminal verification identity. A deterministic
test is required (same-key-different-report
refuses; same-key-identical-report returns
identical). No second terminal proof can ever
exist for one execution.
- **F65. R2 seam named (legacy total).** R2 reads
no handoff value field, ever. Sources: (a) the
RESULT object bytes from the same fresh S3 GET
that serves R1 — R1 proves integrity (digest
agreement) and R2 derives semantics (frozen
codec parse → accepted sum, Decimal 2-dp) only
from digest-verified bytes; handoff
`accepted_total` is a comparison target, never
an input. (b) The pre-correction legacy total
(FS-231: `982500`) arrives as a caller-supplied
run input tagged with its provenance (detection
fact, never handoff — handoff carries no prior
total). `legacy_total_after` = prior total +
fresh accepted sum. Adapter: existing S3 read
seam (`ObjectStorePort.get_object`) + frozen
codec; no new port. Identity: handoff
`result_key`. Normalization: codec parse,
Decimal 2-dp, INR-only. Failure: missing bytes
→ incomplete run (F36 family); digest/staleness
handled at R1 first. Contradiction: derived sum
vs handoff `accepted_total` mismatch →
`VERIFY_COUNT_SKEW`; vs OUTBOUND control →
`VERIFY_CONTROL_SKEW`.
- **F66. R3 seams named (expectation + pending).**
R3 reads no handoff value field, ever. Two
minimal read ports, defined in the verification
package before any re-reader is written (ports
are interfaces; tests bind fakes; production
adapters bind later; no new infrastructure):
(a) expected-settlement read — source system
per the P6-01 matrix (Sheets), case key,
Decimal total, as-of timestamp; (b)
provider-pending read — source system per the
matrix (Razorpay), batch key, Decimal pending
total, as-of timestamp. Residual =
`expected - legacy_total_after - pending` in
Decimal (FS-231: `1000000 - 992500 - 7500 =
0`). Timestamps: `observed_at` is verify-run
time; source as-of recorded when provided,
staleness beyond the run window → incomplete.
Normalization: Decimal 2-dp, INR-only.
Failure: either source missing/unreadable →
incomplete run (never FAILED, never zero-fill).
Contradiction: residual beyond tolerance →
`VERIFY_TOLERANCE_EXCEEDED`; currency mismatch
→ `FAILED` under the closest existing code
(engine maps, no new codes beyond F64).
