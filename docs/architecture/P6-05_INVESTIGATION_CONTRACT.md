# P6-05 Investigation Verdict and Proposal Contract — Meridian Commerce

**Status:** Draft spec for P6-05 on
`feat/finsight-p6-05-investigation-proposal`.
**Base:** `7d7b8f1` (P6-04 merge). P6-02 lifecycle, P6-03
detection, and P6-04 evidence semantics are FROZEN.
**Scope:** Single company (`company_id = meridian`, INR,
Decimal-only money).
**Sources:** `docs/architecture/P6-04_EVIDENCE_CONTRACT.md`
(E1–E33, package shape, CORRELATED_WITH-only rule),
`docs/domain/meridian-process-model.md` (§1.7
ResolutionProposal, §1.8 Approval, §2 lifecycle, §4 FS-231),
`finance/domain/lifecycle.py`
(`require_evidence_for_proposal`: the D3 gate P6-05
must satisfy).
**Type:** DOC-ONLY. No code, no agent changes, no P1 edits,
no new services.

Conventions: `tenant_id` in older code/docs means
`company_id = meridian` plus `environment` (dev / staging /
prod). All money is `Decimal` with 2 dp; `float` is
forbidden. FinSight owns reasoning state; source systems
own facts. P6-05 defines the SEMANTIC OBJECT a future LLM
may propose; it does not introduce the LLM itself.

## 0. Frozen inputs (normative, consumed as given)

P6-02 lifecycle states and transitions are FROZEN: this
spec defines no new states and redefines none. P6-03
detection semantics are FROZEN: canonical fact shapes,
equations, classification triggers, and creation rules are
consumed exactly as written; this spec defines no new
discrepancy math. P6-04 evidence semantics are FROZEN:
provenance (E1–E4), scoping (E5–E7), authority marking
(E8–E11), conflict preservation (E12–E14), incomplete
shape (E15–E17), evidence-fact separation (E18–E20),
deterministic correlation (E21–E23), no causal upgrade
(E24–E26), bounded idempotent collection (E27–E29), and
P4-input suitability (E30–E33) are consumed as given.

This slice consumes three frozen inputs as given:

1. `FinancialSituation` (process model §1.6): the case the
   verdict binds to, by `id` plus `company_id`.
2. `DetectionVerdict`: the P6-03 classification code plus
   its trigger arithmetic, cited verbatim, never
   recomputed.
3. `EvidencePackage`: the P6-04 correlated package with
   its chain, head hash, `CORRELATED_WITH`-only edges,
   conflict markers, and `COMPLETE` / `INCOMPLETE`
   header.

"Refuse" means: drop the item, emit the named code, and
continue deterministically with the remaining inputs.
Silently dropping, silently fixing, or silently promoting
data is forbidden everywhere.

## 1. Design question: fact, correlation, causation (normative)

This section answers the design question before any other
specification, because no implementation may answer it
retroactively.

**Q1. What constitutes sufficient evidence for a
FACTUAL_FINDING?** A statement is a factual finding if and
only if (a) it quotes a value verbatim from a canonical
fact consumed under P6-03, (b) it cites at least one
AUTHORITATIVE evidence id (E8, E11) whose reference
quadruple resolves (E18) and whose content hash verifies
(E3), and (c) it asserts nothing beyond what the cited
record states (no interpolation, no cross-record join
presented as a single record). A finding grounded in
ADVISORY (`sheets`) or CONTEXT (`gmail`, `slack`) items
alone is never factual; such items ride as investigation
context only (E11, E20).

**Q2. What constitutes merely CORRELATION?** A statement
is a correlation if and only if it links two or more
evidence ids or findings by co-occurrence for
investigation, labeled exactly `CORRELATED_WITH` (E24),
carrying the P6-04 no-causality banner (E26). Correlation
requires edge refs, not quoted authoritative values
asserted as one record. Correlation never decides the
verdict, never resizes the variance, and never backfills
a missing fact.

**Q3. What additional conditions permit a CAUSAL_CONCLUSION?**
None within this slice. No sufficient formulation exists:
the frozen inputs contain no interventional data, no
counterfactual control, and no mechanism proof; P6-04
E24–E26 forbid causal upgrade inside the package; and any
candidate sufficient condition (for example "single RJ
plus matching amount") would let a hypothesis silently
promote itself into a verified causal fact. Therefore the
default posture holds absolutely.

**Verdict: causal conclusions are FORBIDDEN in P6-05.**
The `CAUSAL_CONCLUSION` type exists only to be refused
(V4). A future slice may define sufficient conditions;
this slice must not, and no implementation may invent
them.

## 2. Semantic types (normative)

The five verdict types are distinct schemas with distinct
required fields and an immutable `kind` tag — not bare
strings, not interchangeable labels. Every normative
statement below carries a `V-number` for test
traceability.

- **V1. FACTUAL_FINDING.** Fields: `kind` (`FACTUAL_`
  `FINDING`), `situation_id`, `evidence_ids` (at least
  one AUTHORITATIVE id, hash-verified per E3, resolving
  per E18), `quoted_value` (verbatim amount, code, or
  disposition from the cited record), `source_system`.
  A finding with zero AUTHORITATIVE ids, with an
  unverified hash, with a dangling reference, or with a
  paraphrased (non-verbatim) value is refused.
- **V2. CORRELATION.** Fields: `kind` (`CORRELATION`),
  `situation_id`, `edge_refs` (at least two evidence or
  finding ids), `edge_label` (exactly
  `CORRELATED_WITH`), banner citation (E26 present).
  A correlation with fewer than two refs, with any
  other label, or without the banner is refused.
- **V3. HYPOTHESIS.** Fields: `kind` (`HYPOTHESIS`),
  `situation_id`, `text` (candidate explanation stated
  as candidate), `confidence` (required label: `LOW` |
  `MEDIUM` | `HIGH`), `basis_refs` (finding or edge
  ids it interprets). A hypothesis missing `confidence`,
  stated as established fact, or citing zero basis refs
  is refused.
- **V4. CAUSAL_CONCLUSION is forbidden.** Fields: none
  constructible. Any candidate carrying `kind`
  `CAUSAL_CONCLUSION`, or any wording listed under V7,
  is refused with `CAUSAL_UPGRADE` before emission. No
  sufficient conditions exist in this slice (§1, Q3);
  no implementation may add any.
- **V5. RESOLUTION_PROPOSAL.** Fields: `kind`
  (`RESOLUTION_PROPOSAL`), `situation_id`, `action`
  (for example `REPROCESS_LEGACY_RECORD`), `amount`
  (`Decimal`, INR, 2 dp), `account_code` (when the
  action needs one), `evidence_refs` (at least one
  AUTHORITATIVE finding id), `hypothesis_ref` (the
  hypothesis it follows), `policy_pointer` (the
  policy text it appeals to, quoted, never executed).
  A proposal with no `evidence_refs`, no
  `hypothesis_ref`, or no `policy_pointer` is refused.
  A proposal is never an authorization (V9).
- **V6. FACT ≠ CORRELATION.** A finding built only on
  edge refs (no AUTHORITATIVE id, no quoted value) is
  refused with `FINDING_WITHOUT_GROUNDING`; a
  correlation carrying a quoted authoritative value as
  its own assertion is refused with
  `CORRELATION_AS_FACT`. Validators check both
  directions.
- **V7. CORRELATION ≠ CAUSATION.** Edge labels and
  verdict text allow exactly `CORRELATED_WITH`. The
  tokens `CAUSED_BY`, `ROOT_CAUSE`, `PROVES`, and
  `EXPLAINED_BY` (any case, any hyphenation) are
  refused with `CAUSAL_UPGRADE`. Validators scan
  labels, summaries, and proposal rationales.
- **V8. HYPOTHESIS ≠ FACT.** A hypothesis cited as
  grounding for a finding or a proposal amount is
  refused with `HYPOTHESIS_AS_FACT`. A finding whose
  only basis is a hypothesis id is refused with the
  same code. Confidence labels never substitute for
  AUTHORITATIVE grounding.
- **V9. PROPOSAL ≠ AUTHORIZATION.** A proposal carrying
  any of `approval_id`, `decider`, `decision`,
  `decided_at`, `execution_id`, `s3_key`, or lifecycle
  write fields is refused with `PROPOSAL_AS_APPROVAL`.
  Approval (§1.8) pins a proposal hash later, in a
  later slice; it never rides inside the proposal.
- **V10. Kinds are schemas, not strings.** Every
  verdict object carries an immutable `kind` tag bound
  at construction. Re-tagging in place is forbidden;
  changing a verdict's kind constructs a NEW object
  with fresh validation. Serialization must preserve
  the tag (see V22).

## 3. FS-231 verdict walk (normative, golden)

Situation `FS-2026-0916-00231`, Meridian, INR. Variance
`10000` and classification `LEGACY_POSTING_MISSING` are
consumed from P6-03 as given — sized and decided there,
cited here, never recomputed. Evidence hops are consumed
from the P6-04 §3 chain as given.

- **V11. Provider-adjustment FACT.** `FACTUAL_FINDING`
  quoting signed adjustment `+10000` for the window,
  grounded in the AUTHORITATIVE `razorpay`
  SettlementFact evidence id (P6-04 §3 hop 1).
- **V12. QB-absence FACT.** `FACTUAL_FINDING` quoting
  the book leg expecting the `10000` posting, grounded
  in the AUTHORITATIVE `quickbooks`
  AccountingEntryFact evidence id (P6-04 §3 hop 2).
  Absence-of-posting is stated as ledger comparison
  from P6-03, never as invented content.
- **V13. Legacy-RJ FACT with code.** `FACTUAL_FINDING`
  quoting disposition `RJ`, verbatim reason
  `INVALID_ACCOUNT_CODE`, and code `4812` expected,
  grounded in the AUTHORITATIVE `cobol_legacy`
  LegacyPostingFact evidence id (P6-04 §3 hop 5).
- **V14. CORRELATION over the chain.** `CORRELATION`
  with edge refs to the V11, V12, and V13 findings,
  labeled `CORRELATED_WITH` only, carrying the E26
  banner. Causation is undecided here.
- **V15. Rejected-posting HYPOTHESIS.** `HYPOTHESIS`
  with text "legacy rejection of the `10000`
  correction leg under a wrong account code explains
  the residual", confidence `MEDIUM`, basis refs to
  the V14 edge and the V13 finding. Stated as
  candidate, never as fact.
- **V16. Legacy-correction PROPOSAL.** `RESOLUTION_`
  `PROPOSAL` with action `REPROCESS_LEGACY_RECORD`,
  amount `Decimal("10000")`, account code `4812`,
  evidence refs to the V11–V13 findings, hypothesis
  ref to V15, and a policy pointer quoting "legacy
  correction always needs human approval plus valid
  account code plus balanced batch" (process model
  §4.4). Never an authorization (V9).
- **V17. No silent promotion.** The V15 hypothesis MUST
  NOT silently become a verified causal fact. The
  prevention mechanism is type-tag preservation plus
  promotion refusal: `kind` is immutable (V10); any
  re-ingest of a `HYPOTHESIS` as `FACTUAL_FINDING` or
  `CAUSAL_CONCLUSION` is refused with
  `PROMOTION_REFUSED`; no upgrade path exists in this
  slice. A future slice may construct a NEW object
  from NEW evidence; it may never mutate `kind` in
  place.

## 4. Acceptance criteria: 14 RED scenarios (normative)

Each scenario is a numbered acceptance criterion. Each
names the attack or edge, the required deterministic
outcome, and its tracing V-numbers.

- **R1 (V18). FS-231 full walk.** Assemble V11–V16 in
  order over the frozen FS-231 inputs. Required: all
  six objects validate; proposal amount equals
  `Decimal("10000")`; head-hash-linked evidence refs
  resolve; verdict set serializes with kinds intact.
- **R2 (V19). Unsupported causal claim rejected.**
  Candidate text says the `RJ` "caused" the variance,
  "proves" the root cause, or names a `ROOT_CAUSE`.
  Required: refuse with `CAUSAL_UPGRADE`; keep the
  `CORRELATED_WITH` edge and the banner. Traces to
  V4, V7.
- **R3 (V20). Missing-evidence proposal refused.** The
  package header is `INCOMPLETE` (E15–E17) with the
  legacy leg named in `missing`. Required: hold the
  proposal; emit `EVIDENCE_INCOMPLETE` naming the
  missing leg. Never guess the leg. Traces to V5.
- **R4 (V21). Conflicting-authoritative stalemate
  preserved.** Two AUTHORITATIVE items collide with a
  `CONFLICTING_EVIDENCE` marker (E12–E14). Required:
  preserve the stalemate; no proposal may pick a
  winner silently (`RECORD_SHOPPING` refused). A
  proposal may proceed only by citing the conflict
  marker explicitly and holding amount finality, or
  the verdict terminates UNRESOLVED per V31.
- **R5 (V22). Hypothesis-vs-fact serialization
  distinction.** Serialize a `HYPOTHESIS` and a
  `FACTUAL_FINDING`, then round-trip. Required: the
  `kind` tag, `confidence` (hypothesis only), and
  `quoted_value` (finding only) survive byte-equal;
  a swapped or dropped tag fails validation with
  `KIND_MISMATCH`. Traces to V10, V1, V3.
- **R6 (V23). Proposal-without-evidence refused.** A
  proposal cites zero evidence ids (D3 gate in
  `require_evidence_for_proposal`). Required: refuse
  with `PROPOSAL_WITHOUT_EVIDENCE`. A hypothesis
  alone never satisfies the gate. Traces to V5, V34.
- **R7 (V24). Proposal-amount-must-equal-discrepancy.**
  The cited variance is `10000`; the proposal claims
  any other amount (for example `12000` or `17500`)
  with no cited transform. Required: refuse with
  `AMOUNT_MISMATCH`. Another amount passes only with
  an explicit deterministic transformation (named
  legs plus arithmetic, e.g. fee split or multi-leg
  sum) recomputable in `Decimal`.
- **R8 (V25). Proposal-calculation subordinated to
  domain arithmetic.** A probabilistic or LLM-shaped
  amount (estimate, rounded guess, model completion)
  is offered as authoritative. Required: refuse with
  `PROBABILISTIC_AMOUNT`; amounts are authoritative
  only from deterministic domain arithmetic over
  frozen facts. Traces to V1, V5.
- **R9 (V26). Proposal-is-not-approval.** A proposal
  arrives carrying approval fields or stamps
  (`approval_id`, `decider`, `decision`,
  `decided_at`, hash pins). Required: refuse with
  `PROPOSAL_AS_APPROVAL`; strip nothing silently,
  honor nothing. Traces to V9.
- **R10 (V27). No lifecycle mutation.** A verdict set
  claims to yield `APPROVED`, `EXECUTING`, `VERIFYING`,
  or `CLOSED`, or carries a lifecycle write.
  Required: refuse with `LIFECYCLE_WRITE_REFUSED`.
  P6-05 construction is limited to PROPOSED-bound
  outputs (findings, edges, hypotheses, one
  proposal); transitions belong to the domain owner.
- **R11 (V28). Wrong-situation evidence refused.** An
  evidence id bound to another situation (per E5–E6)
  is cited by a finding or proposal for FS-231.
  Required: refuse with `CROSS_CASE_REFUSED`; the
  citing object fails validation. Traces to V1, V5.
- **R12 (V29). Double assembly fingerprint-stable.**
  Assemble the same verdict set twice from identical
  inputs. Required: byte-identical verdict bytes and
  identical proposal hash; run/session ids live in
  the envelope, excluded from the hash (mirroring
  E23). Any drift fails the criterion.
- **R13 (V30). LLM-shaped input quarantined.** Input
  shaped `{"root_cause": ...}` (or equivalent causal
  shape) arrives from outside. Required: quarantine
  as `HYPOTHESIS` at best, confidence at most `LOW`,
  flagged `LLM_SHAPED_QUARANTINED`; never promote to
  finding or causal conclusion (`PROMOTION_REFUSED`
  on any such attempt). Traces to V3, V4, V8.
- **R14 (V31). No-viable-resolution terminates
  UNRESOLVED.** No hypothesis supports a proposal
  (persistent conflict, empty evidence, or held
  package). Required: terminate as `UNRESOLVED`,
  escalation-ready, with reasons cited; inventing a
  proposal to fill the void is refused with
  `PROPOSAL_INVENTED`.

## 5. P4 / agent boundary preservation (normative)

P6-05 defines the semantic object plane. It defines no
agent behavior, no prompts, and no LLM calls. The future
LLM plane consumes verdicts through this exact handoff;
anything outside it is out of contract.

- **V32. Handoff fields (exact).** The future LLM plane
  consumes exactly: finding ids with their quoted
  values and evidence ids; correlation edge refs with
  `CORRELATED_WITH` labels; hypothesis text plus its
  `confidence` label; and the proposal object (action,
  amount, account code, evidence refs, hypothesis
  ref, policy pointer). No other verdict field is
  part of the handoff.
- **V33. Never pre-authorized.** The LLM plane is never
  handed, and never receives as pre-authorized: any
  approval (`approval_id`, `decider`, `decision`,
  hash pins), any execution handle (`execution_id`,
  `s3_key`, batch keys), or any lifecycle write
  capability (transitions, status stamps, close
  proofs). A handoff containing any of these is
  refused with `PREAUTHORIZED_HANDOFF`.
- **V34. D3 gate satisfaction.** A proposal satisfies
  the `require_evidence_for_proposal` gate only with
  at least one evidence id recorded and
  `hypothesis_count >= 1`: in P6-05 terms, at least
  one AUTHORITATIVE finding id in `evidence_refs`
  (V1, V5) and at least one validated `HYPOTHESIS`
  (V3) referenced by `hypothesis_ref`. A proposal
  meeting less is unproposable by construction.
- **V35. Grounding quality.** Proposal `evidence_refs`
  must resolve (E18), hash-verify (E3), come from
  AUTHORITATIVE sources (E8), and sit inside a
  `COMPLETE` package whose head recomputes equal
  (E22, E31). ADVISORY/CONTEXT items never ground a
  proposal amount (E11, E20).

## 6. Explicit non-goals (normative)

- **V36. No LLM integration.** No prompts, no
  completions, no tool calls, no model selection, no
  temperature or sampling rules. P6-05 defines the
  object a future LLM may propose, not the LLM.
- **V37. No hypothesis ranking or selection.** No
  scoring, no 1-of-N choice, no "best hypothesis"
  rule. Ranking belongs to a later slice; P6-05
  carries hypotheses with confidence labels only.
- **V38. No execution or approval transport.** No
  Slack HITL, no S3 correction upload, no proposal
  hashing transport, no verification verdicts. Per
  V9 and V33, approval and execution handles must
  not appear in this slice at all.
- **V39. No new lifecycle states.** No states added,
  renamed, or redefined; no transitions authorized.
  `UNRESOLVED` (V31) is a termination label for the
  verdict, not a lifecycle state; `COMPLETE` /
  `INCOMPLETE` remain package header labels (E16).
- **V40. No P1 / P6-02 / P6-03 / P6-04 edits.**
  Canonical facts, equations, triggers, creation
  rules, lifecycle tables, and evidence semantics are
  consumed verbatim; any conflict resolves in favor
  of the frozen contract.
- **V41. No Temporal, queues, streams, or new infra.**
  No workers, no schedulers, no new AWS services, no
  transports beyond the P6-01 matrix. S3 stays
  transport-only for legacy batches in later slices.

## 7. Requirement index

| Requirement | Section | Statement |
|-------------|---------|-----------|
| V1 | §2 | FACTUAL_FINDING shape |
| V2 | §2 | CORRELATION shape |
| V3 | §2 | HYPOTHESIS shape |
| V4 | §2 | CAUSAL_CONCLUSION forbidden |
| V5 | §2 | RESOLUTION_PROPOSAL shape |
| V6 | §2 | FACT ≠ CORRELATION |
| V7 | §2 | CORRELATION ≠ CAUSATION |
| V8 | §2 | HYPOTHESIS ≠ FACT |
| V9 | §2 | PROPOSAL ≠ AUTHORIZATION |
| V10 | §2 | Kinds are schemas, not strings |
| V11 | §3 | Provider-adjustment FACT |
| V12 | §3 | QB-absence FACT |
| V13 | §3 | Legacy-RJ FACT with code |
| V14 | §3 | CORRELATION over the chain |
| V15 | §3 | Rejected-posting HYPOTHESIS |
| V16 | §3 | Legacy-correction PROPOSAL |
| V17 | §3 | No silent promotion mechanism |
| V18 | §4 R1 | FS-231 full walk |
| V19 | §4 R2 | Causal claim rejected |
| V20 | §4 R3 | Missing-evidence hold |
| V21 | §4 R4 | Stalemate preserved |
| V22 | §4 R5 | Serialization keeps kind tag |
| V23 | §4 R6 | Proposal-without-evidence refused |
| V24 | §4 R7 | Amount equals discrepancy |
| V25 | §4 R8 | Probabilistic amount refused |
| V26 | §4 R9 | Proposal is not approval |
| V27 | §4 R10 | No lifecycle mutation |
| V28 | §4 R11 | Wrong-situation refused |
| V29 | §4 R12 | Fingerprint-stable assembly |
| V30 | §4 R13 | LLM-shaped input quarantined |
| V31 | §4 R14 | UNRESOLVED termination |
| V32 | §5 | Exact handoff fields |
| V33 | §5 | Never pre-authorized |
| V34 | §5 | D3 gate satisfaction |
| V35 | §5 | Grounding quality |
| V36 | §6 | No LLM integration |
| V37 | §6 | No hypothesis ranking |
| V38 | §6 | No execution/approval transport |
| V39 | §6 | No new lifecycle states |
| V40 | §6 | No frozen-contract edits |
| V41 | §6 | No Temporal/queue/infra |

---

*P6-05 investigation verdict and proposal contract. Facts
are quoted, links are correlation, hypotheses stay
candidates, causation is forbidden, and proposals suggest
without authorizing.*
