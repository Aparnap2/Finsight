# P6-06 Policy Approval and Execution Authorization Contract — Meridian

**Status:** Draft spec for P6-06 on
`feat/finsight-p6-06-policy-approval`.
**Base:** `d75cef3` (P6-05 merge). P6-02 lifecycle and P6-05
verdict semantics are FROZEN.
**Scope:** Single company (`company_id = meridian`, INR,
Decimal-only money).
**Sources:** `docs/domain/meridian-process-model.md` (§1.7
ResolutionProposal, §1.8 Approval, §1.8.1 Authority Boundary,
§2 lifecycle), `docs/architecture/P6-05_INVESTIGATION_CONTRACT.md`
(§2 proposal type V5/V9, §5 boundary), and
`finance/business_rules/meridian.py` (refund tiers,
legacy-always-approval, closed-period rule).
**Type:** DOC-ONLY. No code, no agent changes, no P1 edits,
no new services.

Conventions: `tenant_id` in older code/docs means
`company_id = meridian` plus `environment` (dev / staging /
prod). All money is `Decimal` with 2 dp; `float` is
forbidden. FinSight owns reasoning state; source systems
own facts. "Refuse" means: stop the chain at the current
gate, emit the named code, record an audit entry, and
change no state. Silent drops and silent fixes are
forbidden.

## 0. Frozen inputs (normative, consumed as given)

- **A1. P6-02 lifecycle is frozen.** The `PROPOSED` state,
  the `PROPOSED -> APPROVED` and `PROPOSED -> REJECTED`
  transitions, and the `ApprovalGate` outcomes are consumed
  exactly as written in the process model (§2) and P6-05.
  This spec defines no new lifecycle states, renames none,
  and authorizes no transitions; it only gates them.
- **A2. P6-05 verdict semantics are frozen.** The
  `RESOLUTION_PROPOSAL` shape (V5), the kind-tag rules
  (V10), and `PROPOSAL != AUTHORIZATION` (V9) are consumed
  as given. A proposal carrying approval, authorization,
  execution, or lifecycle-write fields is refused before
  any gate runs (see A13).

## 1. Core invariant (normative)

- **A3. Recommendation is not authorization.** Approval and
  authorization live only in this contract, never inside a
  proposal object:

> a valid proposal is evidence of what FinSight recommends; it is never evidence that FinSight is authorized to do it.

  No gate, decision, or token in this spec mutates a
  proposal. No proposal field confers authority. Execution
  (P6-07) must present a G7 authorization; a proposal alone
  authorizes nothing.

## 2. Authorization chain (normative)

- **A4. Ordered gates, first refusal wins.** Every approval
  and every execution authorization evaluates gates
  G1–G7 in fixed order. The first gate that refuses stops
  the chain; later gates never run. Each gate records an
  audit entry (gate id, inputs digest, permit/refuse,
  code). Gate order is part of the contract and is not
  configurable.

```text
G1 actor authentication -> G2 RBAC -> G3 case scope
  -> G4 business policy -> G5 proposal validation
  -> G6 approval decision -> G7 execution authorization
```

## 3. Gate specifications (normative)

### G1 — Actor authentication

- **A5. Claims are recorded, identity is verified
  upstream.** Inputs: `actor_id`, `claimed_role`, and an
  authentication proof reference. Outputs: a verified
  claim handle, or refusal `UNAUTHENTICATED_ACTOR` when the
  proof is missing, invalid, or expired. Per D7 (process
  model §1.8.1), in-domain actor values are recorded
  claims; authentication is enforced upstream (API boundary
  and approval transport). No gate in this contract mints
  identity, and no audit entry proves who a human is, only
  what was claimed and verified when.

### G2 — RBAC (role vs action)

- **A6. Role/action matrix.** Inputs: verified claim (G1)
  plus requested action (`propose`, `read`, `approve`).
  Outputs: permit, or refusal `APPROVE_RIGHT_DENIED`.
  The matrix is:

| Role | Propose | Read | Approve |
|------|---------|------|---------|
| analyst | yes | yes | never |
| payment-ops | yes | yes | never |
| manager | yes | yes | only `<= 50000`, never legacy `> 50000` |
| director | yes | yes | any amount, all legacy corrections |
| auditor | never | yes | never (read-only) |
| agent (service identity) | candidates only | yes | never |

  An auditor approval attempt and an agent approval attempt
  are both refused with `APPROVE_RIGHT_DENIED`; the audit
  entry records which role attempted it. The agent identity
  may assemble proposal candidates and read evidence; it
  may never approve and never mints authorization.
- **A7. Separation of duties (explicit rule).** A proposer
  cannot approve their own proposal, even when they hold a
  role with approve rights: `proposal.proposed_by ==
  decision.approver` is refused with `SELF_APPROVAL_DENIED`.
  A different holder of the required tier must decide.
  Delegation does not waive this rule.

### G3 — Case scope

- **A8. Actor bound to company plus case.** Inputs:
  verified claim plus `company_id` and `situation_id`.
  Outputs: permit only when `company_id == meridian` and
  the actor is bound to the cited case. A decision or
  authorization presented against a different case, or any
  non-`meridian` company, is refused with
  `CROSS_CASE_REFUSED`. Scope is checked again at G7
  against the token (see A18).

### G4 — Business policy

G4 consumes `finance/business_rules/meridian.py`
verbatim; on conflict the code wins and this spec is
amended, never silently reinterpreted.

- **A9. Refund-tier routing.** Inputs: proposal `amount`
  (`Decimal`, INR). The approving tier is `AUTO` below
  `5000`, `MANAGER` from `5000` to `50000` inclusive, and
  `DIRECTOR` above `50000`. A decision below the required
  tier (for example a manager deciding `60000`) is refused
  with `OVER_TIER_AMOUNT`; the escalation path is a new
  decision by the required tier, never an upgrade of the
  refused decision. `AUTO` never bypasses G5 or G7.
- **A10. Legacy always needs a human; director above the
  band.** Every legacy correction requires a human approval
  decision regardless of amount (never `AUTO`). Legacy
  corrections at or below `50000` approve at the manager
  tier (FS-231 golden, §5); legacy corrections above
  `50000` require a director. A legacy correction decided
  without the required director is refused with
  `LEGACY_DIRECTOR_REQUIRED`.
- **A11. Closed periods never mutate.** When the
  correction entry's `period` is in `closed_periods`, the
  chain is refused with `CLOSED_PERIOD_BLOCKED`. There is
  no override, no escalation path, and no director waiver
  for a closed period.
- **A12. Valid account code required.** The proposal
  `account_code` must be present in the static
  `AccountMappings` set. A missing, blank, or unknown code
  is refused with `INVALID_ACCOUNT_CODE`. Verbatim COBOL
  reason strings (for example `INVALID_ACCOUNT_CODE`) are
  preserved in the audit entry.

### G5 — Proposal validation (P6-05 binding)

- **A13. Hash, version, amount, and evidence binding.**
  Inputs: the proposal object plus its evidence package.
  The gate recomputes `proposal_hash` over
  (`situation_id`, `action`, `amount`, `account_code`,
  `evidence_refs`, `hypothesis_ref`, `proposal_version`);
  checks `proposal_version` monotonicity per situation;
  checks `amount` equals the P6-05 bound amount absent a
  cited deterministic transform (V24); and checks every
  evidence ref resolves and hash-verifies (V35). Any
  failure is refused with `UNVALIDATED_PROPOSAL`. A
  proposal carrying approval/authorization/execution
  fields (V9) fails this gate. Any amount or evidence
  drift detected between validation and decision is
  refused with `PROPOSAL_DRIFT_REFUSED`.

### G6 — Approval decision

- **A14. Decision object shape.** A decision is a separate
  object, never a proposal field. Required fields:
  `decision_id`, `approver`, `approver_role`,
  `decision` (`APPROVE` or `REJECT`), `decided_at`
  (tz-aware; naive timestamps refused), `situation_id`,
  `company_id`, plus pinned `proposal_hash` and
  `proposal_version`. One decision per proposal hash; a
  second differing decision on the same hash is refused
  (see A16 for identical replays).
- **A15. Approval pinning voids on swap.** An approval
  pins exactly one (`proposal_hash`, `proposal_version`).
  Approving v1 then proposing v2 voids any authorization
  derived from v1: presenting the v1 authorization against
  v2 (hash/version mismatch) is refused with
  `PROPOSAL_VERSION_SWAPPED`. v2 requires a fresh G1–G6
  pass and a new decision.
- **A16. Double-approval is idempotent-safe.** Replaying
  the identical decision (same `decision_id`, hash, and
  version) returns the same authorization, never a second
  one. The authorization carries the `idempotency_key` it
  will use (see A17). Duplicate-effect suppression itself
  is P6-07; this contract guarantees the authorization
  layer never multiplies (one approved version yields at
  most one authorization id).

### G7 — Execution authorization

- **A17. Non-forgeable single-version token.** G7 mints an
  authorization only after G1–G6 all permit. The token is
  opaque to callers and bound to exactly one approved
  proposal version. Required fields: `authorization_id`,
  `proposal_hash`, `proposal_version`, `company_id`,
  `situation_id`, `action`, `amount_exact` (`Decimal`),
  `account_code`, `idempotency_key` (deterministic in
  (`company_id`, `proposal_hash`, `proposal_version`)),
  `issued_at` (tz-aware), `expires_at` (tz-aware), and
  scope limits (company, case, action, amount ceiling,
  account code, batch/window when applicable). Mint and
  verify mechanics, transport, and effect belong to P6-07;
  the shape and binding rules here are normative for it.
- **A18. Expiry, replay, and scope enforcement.** Use
  after `expires_at` is refused with
  `AUTHORIZATION_EXPIRED`. Presenting an already-consumed
  authorization for a second effect is refused with
  `AUTHORIZATION_REPLAYED` (effect enforcement is P6-07;
  the code is defined here). Presenting the token outside
  its scope limits (different batch, case, action,
  amount, or account code) is refused with
  `AUTHORIZATION_SCOPE_ESCAPE`.

## 4. Refusal matrix (normative)

- **A19. Exact codes.** The table is normative. Order of
  evaluation follows gate order (A4); the first matching
  row wins and later rows are not evaluated.

| Condition | Gate | Refusal code |
|-----------|------|--------------|
| Unauthenticated actor | G1 | `UNAUTHENTICATED_ACTOR` |
| Role without approve right | G2 | `APPROVE_RIGHT_DENIED` |
| Self-approval | G2 | `SELF_APPROVAL_DENIED` |
| Cross-case approval | G3 | `CROSS_CASE_REFUSED` |
| Over-tier amount | G4 | `OVER_TIER_AMOUNT` |
| Legacy without director | G4 | `LEGACY_DIRECTOR_REQUIRED` |
| Closed period | G4 | `CLOSED_PERIOD_BLOCKED` |
| Invalid account | G4 | `INVALID_ACCOUNT_CODE` |
| Unvalidated proposal | G5 | `UNVALIDATED_PROPOSAL` |
| Amount/evidence drift | G5/G6 | `PROPOSAL_DRIFT_REFUSED` |
| Swapped proposal version | G6/G7 | `PROPOSAL_VERSION_SWAPPED` |
| Expired authorization | G7 | `AUTHORIZATION_EXPIRED` |
| Replayed authorization | G7 | `AUTHORIZATION_REPLAYED` |
| Authorization scope escape | G7 | `AUTHORIZATION_SCOPE_ESCAPE` |

## 5. FS-231 walk (normative, golden)

- **A20. Ten-thousand-rupee legacy correction.** Situation
  `FS-2026-0916-00231`, `company_id = meridian`. The P6-05
  proposal v1 (`REPROCESS_LEGACY_RECORD`, amount
  `Decimal("10000")`, account code `4812`, evidence-bound
  per V16) enters G1–G5 and validates. G4 routes tier
  `MANAGER` (`10000 <= 50000`); the legacy rule (A10)
  keeps the human-approval requirement at the manager
  tier. A manager (not the proposer, per A7) records an
  `APPROVE` decision pinning hash v1. G7 mints one
  authorization bound to (`proposal_hash` v1,
  `proposal_version` 1, amount `10000`, code `4812`,
  scope FS-231) with `idempotency_key` and `expires_at`.
  The case is now ready for P6-07 execution, which is
  explicitly out of scope here: no S3 upload, no Slack
  send, and no state transition is performed by this
  contract.

## 6. RED scenarios (normative, at least 12)

Each scenario names setup, action, required outcome, and
trace. "Authorization void" means no minted token survives
for the superseded version.

- **R1 (A21). Self-approval refused.** The v1 proposer,
  holding a manager role, records `APPROVE` on their own
  v1. Required: refuse with `SELF_APPROVAL_DENIED`; no
  decision stored; a different manager may then decide.
- **R2 (A22). Tier escalation.** A manager attempts
  `APPROVE` on a `Decimal("60000")` non-legacy proposal.
  Required: refuse with `OVER_TIER_AMOUNT`; the director
  path is a fresh decision by a director, never an edit
  of the refused decision.
- **R3 (A23). Stale proposal approval void.** v1 is
  approved and authorized; v2 is then proposed for the
  same situation. Required: the v1 authorization is void
  for v2; presenting it is refused with
  `PROPOSAL_VERSION_SWAPPED`; v2 needs a fresh G1–G6
  pass.
- **R4 (A24). Replayed approval decision.** The identical
  `APPROVE` decision (same id, hash, version) is
  delivered twice. Required: one authorization returned
  both times; no second `authorization_id`; refused
  duplication code is never needed because no second
  object is created.
- **R5 (A25). Expired authorization use.** A valid token
  is presented after `expires_at`. Required: refuse with
  `AUTHORIZATION_EXPIRED`; renewal is a fresh G6 decision
  plus G7 mint, never an expiry edit.
- **R6 (A26). Cross-case authorization reuse.** A token
  minted for FS-231 is presented for FS-232. Required:
  refuse with `CROSS_CASE_REFUSED` at G3 and
  `AUTHORIZATION_SCOPE_ESCAPE` recorded at G7 scoping;
  the first refusal emitted is `CROSS_CASE_REFUSED`.
- **R7 (A27). Closed-period correction attempt.** A
  correction targets a period in `closed_periods`, with a
  director willing to approve. Required: refuse with
  `CLOSED_PERIOD_BLOCKED`; director approval does not
  waive it.
- **R8 (A28). Legacy correction without director.** A
  `Decimal("60000")` legacy correction is presented to a
  manager. Required: refuse with
  `LEGACY_DIRECTOR_REQUIRED` (tier breach also recorded
  as `OVER_TIER_AMOUNT`); only a director decision
  proceeds.
- **R9 (A29). Auditor approval attempt.** An auditor
  records `APPROVE` on a validated v1. Required: refuse
  with `APPROVE_RIGHT_DENIED`; auditor remains
  read-only; the proposal stays `PROPOSED`.
- **R10 (A30). Agent approval attempt.** The FinSight
  service identity records `APPROVE` on its own candidate.
  Required: refuse with `APPROVE_RIGHT_DENIED`; agents
  never approve and never mint authorization.
- **R11 (A31). Amount/evidence drift.** v1 validates at
  `10000`; before decision the amount becomes `12000` or
  an evidence ref is swapped with the hash unchanged.
  Required: hash recomputation fails or drift is
  detected; refuse with `PROPOSAL_DRIFT_REFUSED` (or
  `UNVALIDATED_PROPOSAL` when the hash no longer
  verifies); no decision is recorded.
- **R12 (A32). Authorization scope escape.** A batch
  authorization for `LEGACY-20260916-0042` is presented
  for a different batch. Required: refuse with
  `AUTHORIZATION_SCOPE_ESCAPE`; authorizations never
  cover more than their stated scope.
- **R13 (A33). Input hygiene trio.** (a) No auth proof
  presented: refuse `UNAUTHENTICATED_ACTOR` at G1. (b)
  Unknown account code `9999`: refuse
  `INVALID_ACCOUNT_CODE` at G4. (c) Proposal with no
  evidence refs: refuse `UNVALIDATED_PROPOSAL` at G5.
  Each stops its chain at the named gate.

## 7. Explicit non-goals (normative)

- **A34. No execution transport (P6-07).** No S3 upload,
  no result polling, no idempotent-effect implementation,
  no verification verdicts. P6-07 consumes G7 tokens; it
  is defined elsewhere.
- **A35. No Slack integration code.** No message shapes,
  no button handlers, no webhook receivers. Slack is the
  upstream approval transport; this contract only defines
  what a decision must contain (A14).
- **A36. No LLM behavior.** No prompts, no completions,
  no ranking, no confidence rules. The future LLM plane
  may propose candidates; it never approves (A6).
- **A37. No new lifecycle states.** No states added,
  renamed, or redefined; no transitions executed here.
  `PROPOSED`, `APPROVED`, `REJECTED`, and `ESCALATED`
  keep their P6-02 meanings.
- **A38. No edits to frozen contracts.** No P1, P6-02,
  P6-03, P6-04, or P6-05 changes. Conflicts resolve in
  favor of the frozen contract plus
  `finance/business_rules/meridian.py`.
- **A39. No Temporal, queues, streams, or new infra.** No
  workers, schedulers, retries, or AWS services. G7 mint
  storage mechanics are P6-07 business, not this slice.

## 8. Requirement index

| Requirement | Section | Statement |
|-------------|---------|-----------|
| A1 | §0 | Lifecycle frozen, PROPOSED consumed |
| A2 | §0 | P6-05 semantics frozen, V9 holds |
| A3 | §1 | Recommendation is not authorization |
| A4 | §2 | Ordered gates, first refusal wins |
| A5 | §3 G1 | Claim recorded, verified upstream |
| A6 | §3 G2 | Role/action matrix |
| A7 | §3 G2 | No self-approval |
| A8 | §3 G3 | Company plus case binding |
| A9 | §3 G4 | Refund-tier routing |
| A10 | §3 G4 | Legacy human + director rule |
| A11 | §3 G4 | Closed periods never mutate |
| A12 | §3 G4 | Valid account code required |
| A13 | §3 G5 | Proposal binding validation |
| A14 | §3 G6 | Decision object shape |
| A15 | §3 G6 | Pinning voids on swap |
| A16 | §3 G6 | Double-approval idempotent-safe |
| A17 | §3 G7 | Single-version token shape |
| A18 | §3 G7 | Expiry, replay, scope refusal |
| A19 | §4 | Exact refusal codes |
| A20 | §5 | FS-231 golden walk |
| A21 | §6 R1 | Self-approval refused |
| A22 | §6 R2 | Tier escalation refused |
| A23 | §6 R3 | Stale version void |
| A24 | §6 R4 | Replay returns same token |
| A25 | §6 R5 | Expiry refused |
| A26 | §6 R6 | Cross-case reuse refused |
| A27 | §6 R7 | Closed period refused |
| A28 | §6 R8 | Legacy needs director |
| A29 | §6 R9 | Auditor cannot approve |
| A30 | §6 R10 | Agent cannot approve |
| A31 | §6 R11 | Drift refused |
| A32 | §6 R12 | Scope escape refused |
| A33 | §6 R13 | Input hygiene trio |
| A34 | §7 | No execution transport |
| A35 | §7 | No Slack code |
| A36 | §7 | No LLM behavior |
| A37 | §7 | No new lifecycle states |
| A38 | §7 | No frozen-contract edits |
| A39 | §7 | No Temporal/queue/infra |

---

*P6-06 policy approval and execution authorization contract.*
*Proposals recommend; gates authorize; tokens bind one*
*version; execution belongs to P6-07.*
