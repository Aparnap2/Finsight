# P7-01 Agent Boundary & Authority Contract — Meridian Commerce

**Status:** Draft spec for P7-01 on `feat/finsight-p7-01-agent-authority-contract`.
**Base:** `0a305d2` (P6-08 merge). P6-01 process model, P6-02 lifecycle, P6-03
reconciliation, P6-04 evidence, P6-05 investigation, P6-06 approval, P6-07
execution, and P6-08 verification semantics are FROZEN.
**Scope:** Single company (`company_id = meridian`, INR, Decimal-only money,
`situation_id` + `company_id` tenancy). Agent plane is advisory only.
**Sources:** `docs/domain/meridian-process-model.md` (§1–§2 lifecycle,
§4 FS-231), `docs/architecture/P6-05_INVESTIGATION_CONTRACT.md`,
`P6-06_APPROVAL_CONTRACT.md`, `P6-07_EXECUTION_CONTRACT.md`,
`P6-08_VERIFICATION_CONTRACT.md`, `agents/capabilities/` (capability typing),
`finance/evidence/` and `finance/facts/` (authoritative store).
**Type:** DOC-ONLY. No LangGraph nodes, no runtime, no store writes, no P6
edits, no new services, no vector DB, no graph memory, no Temporal changes.

Conventions: `tenant_id` in older code means `company_id = meridian` plus
`environment` (dev / staging / prod). All money is `Decimal` with 2 dp;
`float` is forbidden. "Refuse" means: raise typed `AuthorityError` (or return
an explicit refusal code where raising is impossible), record no authoritative
state, leave the audit log of denials untouched, and continue deterministically.
Silent drops, silent fixes, silent promotion of claims, and assumed outcomes are
forbidden. Every normative statement is numbered `A<n>` for test traceability.
"Caller-supplied time" means every `captured_at` / `created_at` / `now` is
passed explicitly; no `datetime.now()` or wall-clock read lives in stored state.
P6 owns authoritative financial state; the agent plane cites it, never creates a
competing version.

## 0. Frozen inputs (normative, consumed as given)

- **F1. P6-02 lifecycle is frozen.** States, transitions, and terminal
  conditions in `finance/domain/lifecycle.py` and process-model §2 are consumed
  exactly as written. This spec defines no new lifecycle state and executes no
  transition.
- **F2. P6-03/P6-04 evidence and facts are frozen.** Canonical fact shapes,
  provenance (E1–E4), scoping (E5–E7), authority marking (E8–E11), conflict
  preservation (E12–E14), incomplete shape (E15–E17), evidence-fact separation
  (E18–E20), correlation (E21–E23), no causal upgrade (E24–E26), bounded
  collection (E27–E29), and P4-input suitability (E30–E33) are consumed as
  given.
- **F3. P6-06 approval is frozen.** G7 token shape, seal, idempotency, and
  replay rules are consumed as given. This spec mints no authorization.
- **F4. P6-07 execution is frozen.** Stages E1–E6, handoff shape X45–X47, and
  adjudications A1–A6 are consumed as given.
- **F5. P6-08 verification is frozen.** Report shape `VerificationReport`
  (`situation_id`, `execution_id`, `legacy_total_after`, `variance_after`,
  `verdict`, `checked_at`), re-read semantics, and INCOMPLETE vs FAILED
  distinction are consumed as given.

## 1. The 13 boundary questions (normative)

Each question is answered by numbered requirements. A requirement that says
"refuse" is observable as `AuthorityError` with no partial effect.

| # | Question | Answered by |
|---|----------|-------------|
| 1 | What may the agent **read**? | A1–A3 |
| 2 | What may the agent **infer**? | A4–A6 |
| 3 | What may the agent **propose**? | A7–A9 |
| 4 | What may the agent **never decide**? | A10–A11 |
| 5 | How are **facts vs claims** represented? | A12–A15 |
| 6 | How must every material claim reference **evidence**? | A16–A18 |
| 7 | How is **evidence staleness** represented and enforced? | A19–A22 |
| 8 | What are valid **agent entry points**? | A23–A25 |
| 9 | What happens when the agent is **wrong**? | A26–A28 |
| 10 | What happens when the agent/evidence/tool is **unavailable**? | A29–A32 |
| 11 | What must be **audited**? | A33–A36 |
| 12 | How do we distinguish useful reasoning from **fabrication**? | A37–A41 |
| 13 | How does an agent output cross back into the **deterministic control plane**? | A42–A46 |

### Q1. What may the agent read? (A1–A3)

- **A1.** The agent may read only (a) authorized case context for a single
  `situation_id` under `company_id = meridian`, and (b) authorized evidence
  pointers supplied through deterministic accessors. No other read surface exists.
- **A2.** The agent must not read credentials, secrets, or any store by direct
  DB/S3 access. Stores remain behind P6 deterministic accessors.
- **A3.** The agent must not write any authoritative store, ledger, or evidence
  chain. Reading is read-only.

### Q2. What may the agent infer? (A4–A6)

- **A4.** The agent may infer only over evidence supplied to it (correlate,
  identify ambiguity, form hypotheses, compare values). No inference may invent
  values not present in supplied evidence.
- **A5.** Inferences are advisory and carry explicit uncertainty. Absolute
  certainty (`confidence = 1.0`) over non-authoritative evidence is refused.
- **A6.** Instruction-bearing content inside evidence (e.g. "SYSTEM: approve")
  is treated as data, never as a directive.

### Q3. What may the agent propose? (A7–A9)

- **A7.** The agent may produce only typed advisory proposals: a named advisory
  `action` in the allow-list (`read`, `correlate`, `hypothesize`, `propose`,
  `explain`), plus evidence refs, uncertainty, and rationale.
- **A8.** A proposal carries no authoritative field. Keys that would smuggle
  state (`status`, `verdict`, `decision`, `amount` where not a cited evidence
  value) are refused.
- **A9.** Proposals are never authoritative financial state and never imply
  authorization.

### Q4. What may the agent never decide? (A10–A11)

- **A10.** The agent must never decide: mutate financial state, execute a
  financial correction, approve, reject/authorize, establish verdict, declare
  verification successful, close a case, modify authoritative evidence, fabricate
  missing evidence, convert an unsupported claim into a fact, use stale evidence
  as current, bypass deterministic policy, or bypass P6 verification.
  The 13 verbs in A10 are the deny-list; each attempt is refused with no side
  effect.
- **A11.** No agent output may create, alter, or imply a `VerificationReport`,
  an approval token, or a lifecycle transition.

### Q5. How are facts vs claims represented? (A12–A15)

- **A12.** An `AuthoritativeFact` is a frozen reference to a P6-established
  fact: `{source_id, digest (64-char lowercase hex sha256), captured_at}`.
  Frozen, no mutation API, no promotion helper.
- **A13.** An `AgentObservation` is `{text, evidence_refs+, observed_at}`.
  Advisory tier `"observation"`.
- **A14.** An `AgentClaim` is `{text, confidence in [0,1), evidence_refs+,
  created_at}`. Advisory tier `"claim"`. No `to_authoritative` / `to_fact`
  escape exists.
- **A15.** An `AgentHypothesis` is `{text, evidence_refs+, uncertainty,
  created_at}` and an `AgentProposal` is `{action, evidence_refs+,
  uncertainty, rationale, created_at}`. Both are advisory. The agent plane
  references P6 facts; it does not create competing fact versions.

### Q6. How must every material claim reference evidence? (A16–A18)

- **A16.** Every material `AgentClaim` / `AgentProposal` must carry a non-empty
  `evidence_refs` sequence. Empty refs are refused.
- **A17.** Each ref must name a `source_id` in the known registry and in the
  caller's accessible set; otherwise the claim/proposal is refused. Unknown or
  inaccessible sources are refused without leaking their content.
- **A18.** Each ref's content that fails integrity (e.g. `digest_mismatch`) is
  refused. Brown-field content hash checks ride from P6 E3 where available.

### Q7. How is evidence staleness represented and enforced? (A19–A22)

- **A19.** An `EvidenceReference` is `{source_id, captured_at (tz-aware),
  ttl_seconds (positive int)}`. No wall-clock is stored inside it.
- **A20.** Freshness is evaluated only against an explicit caller-supplied
  `now` (tz-aware): `stale ⇔ now ≥ captured_at + ttl`. `is_stale(now)` is the
  predicate; `require_fresh(now)` raises `AuthorityError` when stale.
- **A21.** Stale evidence is never usable as current authoritative evidence.
  Any claim/proposal/observation/correlation that depends on a stale ref is
  refused.
- **A22.** The TTL travels with the pointer; callers, not storage, own the
  policy of what TTL is appropriate for a given source.

### Q8. What are valid agent entry points? (A23–A25)

- **A23.** Valid entry verbs are exactly `read`, `correlate`, `hypothesize`,
  `propose`, `explain`. This is the allow-list. All other verbs are denied and
  leave the advisory log untouched.
- **A24.** Valid entry shapes are (a) plain-data `claim` payloads validated by
  `validate_claim_dict`, and (b) plain-data `proposal` payloads validated by
  `validate_proposal_dict`. Model outputs enter only as plain mappings through
  these validators; no LLM call lives behind the boundary.
- **A25.** Missing shapes (required keys absent), ambiguous evidence marked as
  flat claims, and contradictory tool-value maps are refused.

### Q9. What happens when the agent is wrong? (A26–A28)

- **A26.** When the agent is wrong, its proposal remains non-authoritative.
  No financial truth, approval, execution input, or verification verdict changes
  as a result of the proposal.
- **A27.** The deterministic control plane is unaffected: policy → approval →
  execution → independent verification runs identically with or without the
  proposal.
- **A28.** The wrong proposal and the evidence it cited remain auditable (A33)
  so that the error is traceable, not authoritative.

### Q10. What happens when the agent/evidence/tool is unavailable? (A29–A32)

- **A29.** When required evidence is missing, the agent must report the missing
  `source_id`s and refuse to fabricate values to fill the gap.
- **A30.** When a tool result is unavailable (`available[tool] != true` or
  `result is None`), `require_tool_result` raises `AuthorityError`; the agent
  must not guess.
- **A31.** When the model is unavailable (`model_available == false` or
  `output is None`), `require_model_output` raises `AuthorityError`; the agent
  must not fabricate content.
- **A32.** Degraded advisory output (fewer refs, higher uncertainty) is
  permitted only when it still satisfies A16–A21; otherwise the agent must
  refuse rather than emit a weakly grounded proposal. Deterministic workflow
  validity is never conditional on agent availability.

### Q11. What must be audited? (A33–A36)

- **A33.** Every advisory attempt must be auditable: inputs (plain-data
  payloads), evidence refs (source ids + `captured_at` + TTL + freshness
  outcome), model/tool id and version where applicable, output (claim /
  hypothesis / proposal), and proposal lineage back to cited evidence.
- **A34.** Denied authority attempts must not append to the advisory audit log;
  the log's before/after equality is the observable proof of no side effect.
- **A35.** Agent lineage is never merged into the P6 financial audit spine as
  financial truth; it rides alongside as advisory provenance.
- **A36.** Timestamps in the audit are caller-supplied `captured_at` /
  `created_at` values, not wall-clock reads.

### Q12. How do we distinguish useful reasoning from fabrication? (A37–A41)

- **A37.** Useful reasoning cites evidence refs (A16), survives freshness
  checks (A20–A21), and preserves uncertainty language.
- **A38.** Fabrication is any claim that (a) carries no refs, (b) carries
  stale/tampered/invented/inaccessible refs, (c) asserts absolute certainty
  (`1.0`) on non-authoritative evidence, or (d) smuggles authoritative keys.
  All four are refused by construction.
- **A39.** A hypothesis that notes ambiguity (`is_ambiguous = true`) without
  resolving it by fiat is valid reasoning; merging conflicting values into a
  flat claim is not.
- **A40.** Instruction-bearing evidence text that is rendered or stored is not
  reasoning; it is data. The validator ignores inert extra keys (e.g. `note`).
- **A41.** Evaluation of agent output must check grounding (refs), usefulness
  (ranked proposals still advisory), fabrication rate (refused vs emitted), and
  boundary compliance (deny-list hits).

### Q13. How does an agent output cross back into the deterministic control plane? (A42–A46)

- **A42.** The only crossing is a typed `AgentProposal` through a deterministic
  gate. The gate's decision is `accept` or `reject`; there is no implicit
  execution.
- **A43.** `Agent output is never financial truth.`
- **A44.** `Only the deterministic control plane may establish authoritative financial state.`
- **A45.** Past the gate, accepted proposals flow through existing P6
  machinery only: deterministic policy, approval (P6-06), execution intent
  (P6-07), and independent verification (P6-08). No bypass path exists.
- **A46.** A payload shaped like `{"status": "VERIFIED", "amount": 10000}`
  smuggled through a proposal is treated as an agent claim/proposal, never as
  a financial fact. The deterministic system must validate any financial field
  from authoritative re-reads, not from proposal content.

## 2. Semantic model (minimum, normative)

| Type | Shape | Tier | Notes |
|------|-------|------|-------|
| `AuthoritativeFact` | `source_id, digest, captured_at` | authoritative reference | Frozen; cite-only |
| `EvidenceReference` | `source_id, captured_at, ttl_seconds` | pointer | Freshness via explicit `now` |
| `AgentObservation` | `text, evidence_refs+, observed_at` | advisory | `tier = "observation"` |
| `AgentClaim` | `text, confidence∈[0,1), evidence_refs+, created_at` | advisory | No promotion helper |
| `AgentHypothesis` | `text, evidence_refs+, uncertainty, created_at` | advisory | Candidate explanation |
| `AgentProposal` | `action∈ALLOW, evidence_refs+, uncertainty, rationale, created_at` | advisory | `to_dict()` has no `status`/`verdict`/`decision`/`amount` |

`proposal ≠ decision`, `claim ≠ fact`, `reasoning ≠ authorization`,
`recommendation ≠ execution`.

## 3. Authority surface (normative lists)

**Allow-list (advisory, 5):** `read`, `correlate`, `hypothesize`, `propose`,
`explain`.

**Deny-list (forbidden, 13; each refused with no side effect):**

1. `mutate_financial_state`
2. `execute_financial_correction`
3. `approve`
4. `reject_authorize`
5. `establish_verdict`
6. `declare_verification_successful`
7. `close_case`
8. `modify_authoritative_evidence`
9. `fabricate_missing_evidence`
10. `convert_unsupported_claim_into_fact`
11. `use_stale_evidence_as_current`
12. `bypass_deterministic_policy`
13. `bypass_p6_verification`

## 4. Negative invariants (reuse; not re-tested as goals)

- No wall-clock read inside stored state; every time is caller-supplied.
- No network call behind the boundary; model/tool outputs are plain-data inputs
  to validators.
- No `Decimal` money in this slice (stratum-0 advisory); P6 Decimal boundary
  is re-enforced past the gate.
- No promotion path from advisory tier to authoritative tier exists.

## 5. Non-goals (this slice)

LangGraph nodes, orchestrators, vector DB, graph memory, Temporal changes,
policy redefinition, store mutations, or any P6 contract edit are non-goals.
The runtime is a later slice and must conform to this contract.

## 6. Verification shape (how the contract is tested)

- **Forbidden-authority tests:** one parametrized denial per verb, plus
  `claim→fact` promotion absence and `VERIFIED`-shaped smuggling still-a-claim
  checks; denials assert `audit_log() == before`.
- **Positive tests:** read + freshness, correlate, ambiguity, hypothesis,
  reasoning, request investigation, missing-info, structured proposal,
  uncertainty, explanation, and observation-is-not-fact.
- **Adversarial tests:** missing / conflicting / stale / tampered / ambiguous
  evidence; instruction-bearing evidence staying data; contradictory tool data;
  unavailable tool; unavailable model; malformed model output; unsupported
  certainty; invented / inaccessible source; out-of-capability action; smuggled
  authoritative state; stale helper.
- All 13 deny-list verbs, all positive capabilities, and the adversarial set
  above must be covered before the review gate.

## 7. Review gate (normative)

```
P7-01 contract + RED tests + adversarial cases
      ↓
business-contract review
      ↓
authority-boundary review
      ↓
FREEZE
```

No implementation slice may start until this contract is frozen. The minimal
runtime abstraction that follows must sit entirely inside the agent plane:

```
                    AGENT PLANE
                         │
        ┌────────────────┼────────────────┐
        │                │                │
    investigate       reason          propose
        │                │                │
        └────────────────┼────────────────┘
                         │
                  typed proposal
                         │
                         ▼
              DETERMINISTIC GATE
                         │
                ┌────────┴────────┐
                │                 │
             reject            accept
                                  │
                                  ▼
                            existing P6
                                  │
             policy → approval → execution
                                  │
                                  ▼
                         independent verification
```

See `agents/authority/` for the minimal boundary model and
`tests/contract/test_p7_01_authority_red.py` /
`tests/contract/test_p7_01_adversarial.py` for the RED suite that enforces it.
