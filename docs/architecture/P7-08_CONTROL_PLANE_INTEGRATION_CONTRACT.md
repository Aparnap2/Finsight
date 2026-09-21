# P7-08 Deterministic Control Plane Integration Contract

**Status:** Gate 1 RED — contract frozen for implementation.
**Base:** `87fb8a842d319c56c9264bbaeb31fd64acad51a7` (P7-07 frozen).
**Branch:** `feat/finsight-p7-08-control-plane-integration`

## Purpose

Define the only legal seam between the frozen P7 advisory plane and the frozen P6 deterministic control plane.

```text
P7 Discovery / Reasoning / Human Brief
                |
                v
       DETERMINISTIC GATE
                |
        P6 proposal/policy
                |
          P6 approval
                |
        P6 authorization
                |
          P6 execution
                |
       P6 independent verify
```

P7-08 is an integration boundary, not an authority boundary. It MUST consume P7 artifacts as untrusted/advisory inputs and delegate authoritative decisions to existing P6 owners.

## Normative invariants

### I1 — No direct execution authority
P7 artifacts MUST NOT be accepted as execution commands, authorization tokens, approval records, or lifecycle transitions. No function in `agents/` may invoke P6 execution as a side effect of merely receiving an advisory result.

### I2 — Advisory ≠ approval
`advisory_proposal`, `advisory_next_step`, `candidate_interpretation`, reasoning confidence, and brief prose MUST remain advisory metadata. The integration MUST NOT synthesize `ApprovalDecision`, authorization tokens, approval commands, or approval state from these fields.

### I3 — Evidence does not cross an authority boundary by representation alone
P7 HMAC-bound evidence references MAY be carried forward, but integration MUST NOT mint new evidence authority, alter provenance, convert references into authoritative facts, or treat a P7 reference as a P6 `EVIDENCE_VERIFIED` record without the frozen P6 verification/proposal path.

### I4 — Confidence is never policy authority
Any P7 confidence value is non-authoritative. It MUST NOT select autonomy, approval tier, execution allowance, or verification status. Policy consumes its own frozen deterministic inputs.

### I5 — Contradiction and uncertainty survive integration
Conflicting evidence, unresolved questions, uncertainty, and discovery/reasoning/brief failures MUST remain explicit. The gate MUST fail closed or route to a non-executable outcome; it MUST NOT choose a winner by confidence, prose, or field precedence.

### I6 — Failed/incomplete agent work cannot enter execution
A failed or incomplete `DiscoveryResult`, `ReasoningResult`, or `HumanResolutionBrief` MUST NOT be transformed into an execution-ready P6 input. Missing required artifacts MUST be an explicit typed refusal/blocked outcome, never a plausible success.

### I7 — Context binding survives the seam
`situation_id`, `company_id`, caller-supplied `now`, and evidence scope MUST remain bound. Cross-situation/company/time-scope input MUST be refused. No wall-clock may replace the carried `now`.

### I8 — P6 owns proposal/policy/approval/execution/verification
The seam may validate P7 shape and establish a typed handoff into existing P6 APIs, but only frozen P6 modules may establish authoritative proposal/policy/approval/authorization/execution/verification outcomes. No wrapper may reimplement a policy, approval, authorization, or verification engine.

### I9 — Verification remains independent
P6-08 verification consumes the P6 execution handoff and independently determines VERIFIED/FAILED/INCOMPLETE. P7 output cannot assert or substitute for the verification report, and integration MUST NOT close a case from agent evidence alone.

### I10 — No second authority / no hidden side effects
No new `AuthorityBoundary`, `EvidenceRegistry`, runtime factory, policy engine, approval engine, authorization secret/seal, execution writer, verifier, DB/S3/API/network client, LLM provider, vector/graph memory, Temporal workflow, or queue may be introduced by P7-08.

## Admission model

The gate accepts only a complete, scope-consistent advisory bundle. Its legal output is one of:

- `BLOCKED` — P7 evidence/artifacts are missing, failed, contradictory, stale, or scope-invalid.
- `P6_HANDOFF` — a typed, non-authoritative handoff into an existing deterministic P6-owned path; this is not approval or authorization.

The seam MUST NOT emit `APPROVED`, `EXECUTING`, `VERIFIED`, `FAILED`, `CLOSED`, or an authorization token as its own authority result.

## Test classification

Gate 1 tests are deterministic and split into:

1. **Import/shape RED:** integration entry point is absent until implementation.
2. **Primitive boundary RED:** P7 artifacts cannot be promoted into P6 authority objects by the integration seam.
3. **Pipeline RED:** incomplete/contradictory/scope-skewed bundles cannot reach an execution-capable path.
4. **Static RED:** forbidden authority/I/O dependencies are absent from the integration package.

## Explicit non-goals

- No implementation in Gate 1.
- No LangGraph, LLM, vector DB, graph memory, Temporal, queue, API, ERP, or database integration.
- No changes to P6 or P7-01..P7-07 contracts.
- No new lifecycle states.
- No new authority or signing secret.

## Gate 1 DoD

- Contract committed on the P7-08 branch.
- RED test suite committed separately and fails because the integration boundary is not yet implemented.
- Frozen 256-test regression remains green.
- Ruff clean.
- No frozen-layer modifications.
- Working tree clean after commits.
- STOP: no GREEN implementation in Gate 1.
