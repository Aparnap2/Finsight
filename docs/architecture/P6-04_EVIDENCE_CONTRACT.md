# P6-04 Evidence Correlation Contract — Meridian Commerce

**Status:** Draft spec for P6-04 on
`feat/finsight-p6-04-evidence-correlation`.
**Base:** `e6140e2` (P6-03 merge). P6-02 lifecycle and P6-03
detection semantics are FROZEN.
**Scope:** Single company (`company_id = meridian`, INR,
Decimal-only money).
**Sources:** `docs/domain/meridian-process-model.md` (§1 entities,
§4 FS-231),
`docs/architecture/P6-03_RECONCILIATION_CONTRACT.md` (facts,
verdicts, creation),
`docs/architecture/P6-01_INTEGRATION_CONTRACTS.md` (six systems).
**Type:** DOC-ONLY. No code, no agent changes, no P1 edits, no
new services.

Conventions: `tenant_id` in older code/docs means
`company_id = meridian` plus `environment` (dev / staging /
prod). All money is `Decimal` with 2 dp; `float` is forbidden.
FinSight owns reasoning state; source systems own facts. There
is NO LLM usage anywhere in this slice: correlation is
deterministic Python over frozen inputs, and hypothesis
generation belongs to a later slice.

## 0. Frozen inputs (normative, consumed as given)

P6-02 lifecycle states are FROZEN (§0 of P6-03): this spec
defines no new lifecycle states and redefines none. P6-03
detection semantics are FROZEN: canonical fact shapes (§1),
equations (§2), classification triggers (§3), and creation
rules (§4) are consumed exactly as written. This spec defines
no new discrepancy math.

This slice consumes three frozen inputs as given:

1. `FinancialSituation` (process model §1.6): the case the
   evidence package binds to, by `id` plus `company_id`.
2. `DetectionVerdict`: the P6-03 §3 classification code plus
   its trigger arithmetic, cited verbatim, never recomputed.
3. Canonical facts: P6-03 §1.1–§1.6 fact shapes with their
   `provenance`, `source_version`, and `source_hash` fields.

Correlation links evidence items to these inputs. It never
re-decides the verdict, never resizes the variance, and never
backfills a missing fact.

## 1. Requirements

Every normative statement below carries an `E-number` for
test traceability. "Refuse" means: drop the item, emit the
named code/marker, and continue deterministically with the
remaining inputs. Silently dropping, silently fixing, or
silently promoting data is forbidden everywhere.

### 1.1 Immutable provenance per evidence item (proof point 1)

- **E1.** Every evidence item carries write-once provenance:
  `source_system`, `external_id`, `source_version`,
  `content_hash` (sha256, 64-char lowercase hex),
  `retrieved_at` (tz-aware), adapter/reader identity, and
  the ingest correlation/run id. An item missing any of
  these fields is refused with code `PROVENANCE_MISSING`
  and never enters a package.
- **E2.** Provenance is immutable after collection. Any
  correction arrives as a NEW item id that supersedes by
  explicit reference; in-place edits of provenance or
  content are forbidden and rejected with
  `PROVENANCE_MUTATION`.
- **E3.** `content_hash` is computed over canonical bytes
  of the source record at ingest. A hash mismatch on
  re-read quarantines the item with marker
  `HASH_MISMATCH`; the quarantined bytes never enter the
  chain (§1.7) and the mismatch is named in the package.
- **E4.** Naive (tz-unaware) `retrieved_at` or source
  timestamps are refused with `NAIVE_TIMESTAMP`. Adapters
  must attach the source timezone before handoff, per
  P6-03 §1.7.

### 1.2 Scoping to the FinancialSituation (proof point 2)

- **E5.** Every item is bound at collection to the triple
  (`company_id`, `environment`, `situation_id`). Binding
  is part of the hashed payload (§1.7), not envelope
  metadata.
- **E6.** Cross-case attachment is refused: an item bound
  to situation FS-A is never attached to the package of
  FS-B. The attempt is refused with `CROSS_CASE_REFUSED`
  and logged with ids and hashes only (no content bytes).
- **E7.** Out-of-scope reads use a uniform miss signal:
  a scope miss (wrong `company_id` or `environment`) is
  refused as `OUT_OF_SCOPE` with no existence oracle —
  the response reveals nothing about whether the record
  exists elsewhere, per the C-QUICKBOOKS fence in P6-01.

### 1.3 Authoritative vs non-authoritative marking (proof point 3)

Authority follows the P6-01 matrix exactly; this spec adds
no new authorities.

- **E8.** Authoritative items come from exactly three
  sources: `razorpay` (provider capture/fee/refund/
  adjustment), `quickbooks` (accounting journals/balance/
  period), and `cobol_legacy` (per-batch accepted totals
  and per-record `AC`/`RJ`/`DU` with verbatim reason).
  Only these sources may ground amounts and coverage.
- **E9.** Non-authoritative items are: `sheets`
  (expected settlement: ADVISORY business view, never
  overriding provider/accounting/legacy legs), `gmail`
  (CONTEXT only: refund/fee notes, never facts), and
  `slack` (approval SIGNAL only: never amount evidence,
  never coverage evidence).
- **E10.** Gmail content and Sheets notes/cells are NEVER
  authoritative. An item from `gmail` or `sheets` that
  claims ledger authority (amount finality, posting
  proof, approval power) is re-marked to its ceiling
  (`CONTEXT` / `ADVISORY`) with marker
  `AUTHORITY_STRIPPED`, and the spoofed claim is
  recorded, never honored.
- **E11.** Every item carries `trust_class`:
  `AUTHORITATIVE` | `ADVISORY` | `CONTEXT`, derived
  solely from `source_system` per E8–E9. Coverage (§1.5)
  counts AUTHORITATIVE items only; ADVISORY/CONTEXT
  items ride as investigation context.

### 1.4 Conflict preservation (proof point 4)

- **E12.** Contradictory items coexist. When the same
  `external_id` arrives with a different body (amount,
  disposition, or hash), BOTH bodies stay in the package
  with their hashes. Overwrite, merge, and
  last-write-wins are forbidden.
- **E13.** Every contradiction carries an explicit
  conflict marker: `CONFLICTING_EVIDENCE` naming the
  colliding item ids, the differing fields, and both
  content hashes. A package with an unmarked
  contradiction is malformed.
- **E14.** Silent resolution is forbidden: no
  majority-vote, no newest-wins, no
  authoritative-auto-overwrite inside this slice.
  Resolution belongs to investigation and a new
  proposal version (P6-03 §4.4); this slice only
  preserves and marks.

### 1.5 Incomplete result shape (proof point 5)

- **E15.** When required evidence is missing (absent
  leg, rejected fact per P6-03 §1.7, unreadable result
  file), the package is emitted as `INCOMPLETE` with a
  named `missing` set: each entry gives
  (`source_system`, `external_id` or window key, reason
  code). Missing legs are never left unnamed.
- **E16.** No silent partials: the package header
  carries `completeness: COMPLETE | INCOMPLETE`, and an
  `INCOMPLETE` package lists both present item ids and
  the `missing` set. A package without the header is
  malformed.
- **E17.** An `INCOMPLETE` package is held from
  P4-input suitability (§1.10) until coverage
  completes. Partial data is never promoted into a
  case-ready chain with a guessed or interpolated leg.

### 1.6 Evidence-fact separation (proof point 6)

- **E18.** Evidence REFERENCES facts; it never
  manufactures them. An item links to its fact via the
  (`source_system`, `external_id`, `source_version`,
  `source_hash`) quadruple from P6-03 §4.2. An item
  whose reference resolves to no consumed fact is
  refused with `DANGLING_REFERENCE`.
- **E19.** Amounts live ONLY in `finance/facts`
  canonical fact shapes (provider, books, expected,
  legacy). No evidence item carries an `amount` of its
  own; amount-like strings quoted from context (Gmail
  body, Sheets note) stay quoted text and never enter
  deterministic comparison.
- **E20.** Any amount-like string inside an ADVISORY or
  CONTEXT item carries flag `GROUNDING_REQUIRED` and is
  excluded from coverage counts, variance context, and
  chain ordering keys. Treating quoted text as a
  posting is refused with `AMOUNT_INVENTION`.

### 1.7 Deterministic correlation (proof point 7)

- **E21.** Same inputs yield the same chain. Chain order
  is canonical sort over (`source_system`,
  `external_id`, `source_version`, `content_hash`) —
  never wall-clock, never ingest arrival order — so
  redelivery and clock skew cannot reorder the chain.
- **E22.** The chain is hash-pinned: each link commits
  to `content_hash` of its item plus the previous link
  hash (`prev_hash`), and the package records the head
  hash. Dropping, reordering, or editing any link
  changes the head; verification recomputes it.
- **E23.** Correlation reruns over identical inputs
  yield byte-identical chains. Run/session ids live in
  the package envelope, EXCLUDED from chain hashes, so
  reruns differ only in envelope metadata, never in
  chain content or head hash.

### 1.8 No causal upgrade (proof point 8)

- **E24.** Correlation edges are labeled exactly
  `CORRELATED_WITH` (co-occurrence for investigation).
  The label `CAUSED_BY` is forbidden in this slice, as
  is any equivalent (`PROVES`, `ROOT_CAUSE`,
  `EXPLAINED_BY`).
- **E25.** Causal claims about the case are forbidden
  in package content: no item note, edge label, or
  package summary may assert what caused the variance.
  A candidate package containing causal wording is
  rejected with `CAUSAL_UPGRADE` before emission.
- **E26.** Every package carries the no-causality
  banner: "Correlation is co-occurrence for
  investigation, not a verdict. Causation is undecided
  in this slice." Removing the banner malforms the
  package.

### 1.9 Bounded idempotent collection (proof point 9)

- **E27.** Collection is per-source capped per
  situation: `razorpay` ≤ 2048 items, `quickbooks` ≤
  2048, `cobol_legacy` ≤ 2048, `sheets` reads ≤ 16,
  `gmail` ≤ 32, `slack` ≤ 4. Caps are slice constants,
  enforced before chaining.
- **E28.** Collection is redelivery-safe: delivering
  the same batch twice yields the same package.
  Dedupe key is (`source_system`, `external_id`,
  `content_hash`); an identical redelivery adds no new
  item, no new link, and no head-hash drift.
- **E29.** Overflow is deterministic and loud: beyond
  the cap, items are truncated in canonical order
  (first-N survive), the package is marked
  `CAP_EXCEEDED` naming the source and the dropped
  count, and completeness follows §1.5 (truncated
  required legs yield `INCOMPLETE`).

### 1.10 P4-input suitability (proof point 10)

This slice defines the package the existing P4 agent
boundary consumes. It does NOT redesign that boundary
and defines no agent behavior. Boundary modules,
cited as-is:

- `agents/investigation/request.py`
  (`InvestigationRequest.evidence_ids`: verified-only,
  bounded, unique ids assembled before any LLM call).
- `agents/investigation/plan.py`
  (`InvestigationPlan.evidence_required`: non-blank,
  bounded, unique ids; hypothesis stays unproven).
- `finance/evidence/models.py` (`EvidenceItem` with
  `tenant_id`, `content_hash`, `retrieved_at`,
  `provenance`; `EvidenceProvenance` adapter/endpoint/
  correlation triple).

- **E30.** A P4-suitable package exposes exactly these
  fields per item: evidence id, `content_hash`,
  `trust_class` (E11), and full provenance (E1). No
  other per-item field is required for suitability;
  no P4-bound field is renamed or reshaped here.
- **E31.** Suitability predicate (all required):
  header `COMPLETE` (E16), every item hash-verified
  (E3), every reference resolving (E18), scope triple
  intact (E5), chain head recomputed equal (E22), and
  the no-causality banner present (E26).
- **E32.** Conflict markers (E13) and ADVISORY/CONTEXT
  items (E11) ride along explicitly and do NOT block
  suitability: the P4 boundary investigates them. A
  missing `missing` set (E15) DOES block it.
- **E33.** Suitability is reported as a boolean plus
  the failing E-numbers on `false`. A `false` package
  is held with reasons; it is never silently repaired
  into `true` (no auto-fill, no auto-trim of the
  `missing` set).

## 2. Proof-point traceability

| # | Proof point | Requirements |
|---|-------------|--------------|
| 1 | Immutable provenance | E1, E2, E3, E4 |
| 2 | Situation scoping | E5, E6, E7 |
| 3 | Authority marking | E8, E9, E10, E11 |
| 4 | Conflict preservation | E12, E13, E14 |
| 5 | Incomplete shape | E15, E16, E17 |
| 6 | Evidence-fact separation | E18, E19, E20 |
| 7 | Deterministic correlation | E21, E22, E23 |
| 8 | No causal upgrade | E24, E25, E26 |
| 9 | Bounded idempotent collection | E27, E28, E29 |
| 10 | P4-input suitability | E30, E31, E32, E33 |

## 3. FS-231 evidence chain (golden walk)

Situation `FS-2026-0916-00231`, Meridian, INR. Variance
(`10000`) and classification (`LEGACY_POSTING_MISSING`)
are consumed from P6-03 §2.2/§3.6 as given — sized and
decided there, cited here. The chain below shows the
required item at each hop and what marks it
authoritative. Edge labels are `CORRELATED_WITH` only.

Hop 1 — SettlementFact: signed adjustment `+10000`
for the window (C-RAZORPAY). Trust: AUTHORITATIVE.
Provider owns adjustment truth (P6-01 §1).

Hop 2 — AccountingEntryFact: book leg expecting the
`10000` posting (C-QUICKBOOKS). Trust: AUTHORITATIVE.
Books own journals; debits equal credits (P6-01 §2).

Hop 3 — Batch item: `LEGACY-20260916-0042` control
record, 500 sent (C-LEGACY). Trust: AUTHORITATIVE.
Legacy owns per-batch truth; control fail-closed
(P6-01 §6).

Hop 4 — 499 `LegacyPostingFact` items, disposition `AC`
(C-LEGACY). Trust: AUTHORITATIVE. Result-file
dispositions are legacy truth (P6-01 §6).

Hop 5 — 1 `LegacyPostingFact`, disposition `RJ`,
verbatim `INVALID_ACCOUNT_CODE`, code `4812` expected
(C-LEGACY). Trust: AUTHORITATIVE. Verbatim reason +
code; rejections are human-review, never auto-retry
(P6-01 §6).

Hop 6 — ExpectedSettlementFact: expected `1000000`
(C-SHEETS stub, fixture-fenced). Trust: ADVISORY.
Business view only; never overrides legs (P6-01 §3).

Hop 7 — Gmail context items: refund-request /
fee-change notes, snippet-capped (C-GMAIL). Trust:
CONTEXT. Untrusted DATA; approvals never accepted
(P6-01 §4).

Hop 8 — Chain links: hop 5 `CORRELATED_WITH` hop 2
`CORRELATED_WITH` hop 1; hops 6–7 attached as context
edges. Per E24 correlation only; causation undecided
(E26 banner).

Golden acceptance: the package header is `COMPLETE`,
head hash verifies (E22), all five AUTHORITATIVE hops
hash-verify (E3), the `RJ` item keeps its verbatim
reason (E8), Gmail/Sheets items carry their ceiling
(E10–E11), no edge says `CAUSED_BY` (E24–E25), and the
suitability report is `true` per E31.

## 4. Adversarial scenarios (normative)

Each scenario names the attack, the required deterministic
outcome, and the tracing E-numbers. "Refused" always
means: drop/deny the item, emit the code/marker, keep the
rest of the package deterministic.

- **A1. Cross-case smuggling.** Item bound to FS-229 is
  submitted into the FS-231 package. Required: refuse
  with `CROSS_CASE_REFUSED`; FS-231 head hash unchanged.
  Traces to E5, E6.
- **A2. Forged provenance.** Item arrives with a copied
  adapter id but no matching run/ingest path.
  Required: refuse with `PROVENANCE_MISSING`; never
  admit anonymous facts. Traces to E1.
- **A3. Authoritative-spoofing via Gmail.** A Gmail item
  claims "ledger confirms posting of `10000`".
  Required: re-mark `CONTEXT`, emit
  `AUTHORITY_STRIPPED`, keep the note as quoted text
  with `GROUNDING_REQUIRED`. Traces to E10, E11, E20.
- **A4. Conflict suppression attempt.** Second body for
  an `external_id` arrives and the collector is asked
  to "keep only the latest". Required: keep BOTH,
  emit `CONFLICTING_EVIDENCE` with both hashes; reject
  the keep-latest instruction. Traces to E12, E13, E14.
- **A5. Missing-leg silence.** The legacy result file
  is unreadable; the collector is asked to emit a
  clean package anyway. Required: emit `INCOMPLETE`
  with the legacy leg named in `missing`; suitability
  `false` citing E15. Traces to E15, E16, E17, E33.
- **A6. Amount invention via evidence text.** A Sheets
  note reads "looks like `12000`"; downstream asks to
  treat it as the posting. Required: refuse with
  `AMOUNT_INVENTION`; the string stays quoted
  `GROUNDING_REQUIRED` text. Traces to E18, E19, E20.
- **A7. Causal-upgrade wording.** A package summary
  draft says the `RJ` "caused" the variance / "proves"
  the root cause. Required: reject with
  `CAUSAL_UPGRADE`; edges stay `CORRELATED_WITH` with
  the banner intact. Traces to E24, E25, E26.
- **A8. Unbounded collection (10k-item flood).** 10,000
  Gmail items arrive for one situation. Required:
  keep first 32 in canonical order, mark
  `CAP_EXCEEDED` with dropped count 9968; required
  legs unaffected stay intact. Traces to E27, E29.
- **A9. Duplicate batch delivery.** The 500-record
  legacy batch is delivered twice with identical
  hashes. Required: absorb; same items, same chain,
  same head hash; no new links. Traces to E28, E23.
- **A10. Tampered content hash.** Re-read bytes for an
  `AC` record no longer match its `content_hash`.
  Required: quarantine with `HASH_MISMATCH`, name it
  in the package, exclude it from the chain; coverage
  recomputed without it. Traces to E3, E15.
- **A11. Backdated timestamps.** An item arrives with
  `retrieved_at` earlier than its source timestamp.
  Required: flag `TIMESTAMP_SUSPECT`, keep chain order
  by canonical sort (clocks never order the chain);
  exclude the item from coverage until re-attested.
  Traces to E4, E21.
- **A12. Scope escape (tenant-b evidence).** An item
  bound to another company/environment is submitted
  into the meridian case. Required: refuse with
  `OUT_OF_SCOPE` via the uniform miss signal; reveal
  nothing about the foreign record. Traces to E5, E7.
- **A13. Slack approval quoted as evidence.** A Slack
  `APPROVE` signal is offered as proof of the `10000`
  amount. Required: refuse as amount/coverage
  evidence; Slack items are approval SIGNAL only and
  never ground money. Traces to E9, E11.

## 5. Explicit non-goals

1. No LLM or hypothesis generation anywhere in this
   slice. No prompts, no completions, no ranking, no
   narrative. Hypothesis work belongs to a later slice
   through the cited P4 boundary, unchanged here.
2. No causal inference. Correlation edges never become
   causal claims; root-cause verdicts are out of scope.
3. No execution and no approval semantics. Proposal
   hashing, Slack HITL tiers, S3 correction upload,
   and verification verdicts belong to P6-05+; this
   spec stops at the correlated evidence package.
4. No new lifecycle states and no state redefinitions.
   P6-02 §2 stays frozen; `COMPLETE` / `INCOMPLETE`
   are package header labels, not states, and an
   `INCOMPLETE` package creates no new case or
   transition.
5. No edits to P1, P6-02, or P6-03. Canonical facts,
   equations, triggers, and creation rules are
   consumed verbatim; any conflict between this spec
   and those contracts resolves in favor of the
   frozen contract.
6. No Temporal, queues, streams, new AWS services, or
   live transports beyond the P6-01 matrix. S3 stays
   transport-only for legacy batches; the C-SHEETS
   and C-SLACK stubs stay stubs until their owning
   steps land.

---

*P6-04 evidence correlation contract. Correlation links
frozen facts to a frozen case, deterministically, without
invention and without causation; investigation decides
what the links mean.*
