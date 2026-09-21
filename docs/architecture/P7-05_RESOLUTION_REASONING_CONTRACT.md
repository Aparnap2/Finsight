# P7-05 Resolution Reasoning Contract — Advisory Interpretation over Discovery

**Status:** Draft spec for P7-05 on `feat/finsight-p7-05-resolution-reasoning`.
**Base:** `88a5014` (P7-04 merge). P6 lifecycle/evidence/approval/execution/verification frozen; P7-01 authority, P7-02 runtime, P7-03 tools, P7-04 discovery frozen.
**Scope:** Single company (`company_id = meridian`, `situation_id` tenancy, INR Decimal, `now` tz-aware caller-supplied). Transforms a valid bounded `DiscoveryResult` into typed advisory `ReasoningResult`; never financial truth.
**Sources:** `docs/architecture/P7-01_AGENT_AUTHORITY_CONTRACT.md` (A1–A46), `agents/authority/` (HMAC-bound refs, `AuthorityError`), `agents/runtime/` (factory-bound `RuntimeContext`/`RuntimeHandoff`), `agents/tools/` (P7-03 typed tools), `agents/discovery/` (`DiscoveryRequest`/`DiscoveryResult`/`discover`), `docs/domain/meridian-process-model.md` (§2 lifecycle, FS-231).
**Type:** DOC-ONLY. No LangGraph nodes, no runtime writes, no store/policy/verdict engine, no P6 edits, no vector DB, no Temporal, no LLM provider/prompt changes.

Conventions: `Refuse` = raise `AuthorityError` or return typed `ReasoningFailure` with no authoritative side effect. `Caller-supplied time` = every `captured_at`/`now`/`created_at` is explicit; no `datetime.now()` inside stored state. Discovery is the sole evidence source; reasoning never invents evidence/scope/now/fact. `tier = "reasoning"` for success, `tier = "reasoning_failure"` for typed failures. Confidence ∈ [0,1); `1.0` is refused.

## 0. Frozen inputs (normative, consumed as given)

- **F1.** P7-01 authority frozen: 13 deny-list verbs, HMAC-bound `EvidenceReference`/`AuthoritativeFact`, `AuthorityBoundary`, `AgentCapability` (READ/CORRELATE/HYPOTHESIZE/PROPOSE/EXPLAIN), advisory vs authoritative tier, `validate_claim/proposal_dict` semantics.
- **F2.** P7-02 runtime frozen: factory-bound `RuntimeContext` (HMAC of `situation_id:company_id:now`), `RuntimeHandoff` advisory-only, `AgentRuntime` capability-gated dispatch, deterministic envelope wins, no second authority.
- **F3.** P7-03 tools frozen: `EvidenceLookup`/`Correlation`/`Explanation` typed request→result via `EvidenceRegistry` HMAC, context-bound, scope-checked, freshness-enforced.
- **F4.** P7-04 discovery frozen: `DiscoveryRequest` (situation/company/now/scope/objective/capabilities) immutable, `DiscoveryResult` (success + refs/observations/hypotheses OR failure + code/detail), `discover()` advisory only, scope-locked, no financial mutation.

## 1. Boundary and mission (normative)

```
  DiscoveryResult (bounded, HMAC-bound refs, caller-supplied now)
        │
        ▼
  ┌─────────────┐
  │  Reasoning  │  candidate interpretation, conflicting evidence,
  │  (advisory) │  uncertainty, rationale, unresolved — never verdict
  └──────┬──────┘
         │ advisory ReasoningResult
         ▼
  Typed Advisory Resolution ──► Deterministic Gate ──► Policy→Approval→Execute→Verify
         (proposal, refs, provenance)   accept/reject   (P6 pipeline, no bypass)
```

Mission: translate a **valid** `DiscoveryResult` into a **typed advisory resolution** (interpretation + evidence refs + preserved contradictions + uncertainty + rationale + unresolved questions + advisory proposal). It must not create financial truth, authoritative status, or execution intent.

## 2. Gate A–I normative requirements (A1–A22, test-traceable)

### A. Input authority — only valid bounded DiscoveryResult (A1–A3)

- **A1.** Reasoning accepts only a `DiscoveryResult` where `success == True`, `situation_id`/`company_id`/`now` non-blank and tz-aware, `company_id == "meridian"`, `evidence_refs` is a non-empty tuple of HMAC-bound `EvidenceReference`, and `now` equals the bound `RuntimeContext.now`. Any other shape (`success == False`, `failure` present, empty/blank fields, naive `now`, wrong company, unissued refs, scope-expanded refs) is `INVALID_DISCOVERY_RESULT` typed failure or `AuthorityError` — never a plausible resolution.
- **A2.** Scope is bounded by the discovery result's `allowed_evidence_ids` provenance. Reasoning must not invent `evidence_id`/`source_id`/`captured_at`/`digest`/`provenance`/`ttl_seconds`, must not expand scope beyond the discovery's `evidence_ids`, must not invent `situation_id`/`company_id`/`now`, and must not mint a competing `AuthoritativeFact`. Any invented field is refused.
- **A3.** `now` is caller-supplied and replay-stable. No `datetime.now()`/`utcnow()`/`time.time()` read lives in reasoning state. Stale handling is explicit via `is_stale(now)` against caller-supplied `now`; stale is not auto-refreshed.

### B. Output — advisory interpretation only (A4–A6)

- **A4.** Success output is `ReasoningResult` with: `situation_id`, `company_id`, `now` (each preserved), `evidence_refs` (HMAC-bound subset), `candidate_interpretation` (non-blank text), `conflicting_evidence` (tuple of evidence_ids that remain conflicting, may be empty), `uncertainty` (non-blank text, never empty), `rationale` (non-blank grounding text), `unresolved_questions` (tuple of non-blank strings, may be empty), `advisory_proposal` (typed advisory intent from `_ADVISORY_PROPOSAL_TYPES` or `None`), `tier == "reasoning"`. All fields are frozen/extra-forbid/strict.
- **A5.** Output must never contain authoritative markers: keys or substrings `status`, `verdict`, `decision`, `amount`, `VERIFIED`, `FAILED`, `APPROVED`, `EXECUTED`, `SETTLED`, `FACT`. `to_dict()` and any advisory text must be free of these. A proposal's intent is disjoint from capability verbs and deny-list verbs.
- **A6.** On failure, output is typed `ReasoningFailure` with `code` in `INSUFFICIENT_EVIDENCE`|`CONTRADICTORY_EVIDENCE`|`STALE_EVIDENCE`|`SCOPE_MISMATCH`|`INVALID_DISCOVERY_RESULT`|`REASONING_FAILED` and non-blank `detail`; success never carries failure and failure never carries success payload.

### C. Evidence-grounded (A7–A9)

- **A7.** Every conclusion (`candidate_interpretation`, `conflicting_evidence` entries, `rationale`, `unresolved_questions`, `advisory_proposal`) must be traceable to at least one `evidence_id` in the input discovery's `evidence_refs`. No orphan conclusion.
- **A8.** Unsupported assertion (claim with no cited ref, ref not in discovery scope, unissued/HMAC-invalid ref, or invented value) is refused — either `AuthorityError` or `REASONING_FAILED`/`INVALID_DISCOVERY_RESULT` typed failure, never a silent success.
- **A9.** Evidence refs are resolved through the deterministic `EvidenceRegistry` bound to `RuntimeContext`; caller-supplied metadata that disagrees with the registry's record (`source_id`/`digest`/`provenance`/`ttl_seconds`/`captured_at`) is fabrication and refused.

### D. Uncertainty preservation (A10–A12)

- **A10.** Contradictory evidence must remain flagged in `conflicting_evidence` and acknowledged in `uncertainty`; it must not be collapsed into a single flat claim or merged value.
- **A11.** Missing evidence (`present_ids ⊂ required_ids`) must remain in `unresolved_questions`; reasoning must not fabricate values to fill the gap. `uncertainty` must name the missing dimension.
- **A12.** Stale (`is_stale(now) == True`), inaccessible, or ambiguous evidence must remain flagged; high `confidence` (e.g. `0.99`) or persuasive prose must not resolve it. Confidence and prose never promote uncertainty to certainty.

### E. Capability boundary — advisory only (A13–A14)

- **A13.** Reasoning has no capability to `WRITE`/`EXECUTE`/`APPROVE`/`VERIFY`/mutate ledger/bypass policy/verdict/closure. It is advisory; it may only produce `ReasoningResult` (tier `reasoning`) for handoff. Any attempt to perform a denied verb is `AuthorityError`.
- **A14.** No financial mutation attribute (`mutate`, `execute`, `write`, `update`, `delete`, `commit`, `approve`, `verify`) exists on the reasoning engine or result. `discover→reason` never writes P6 state.

### F. No second authority (A15–A16)

- **A15.** Reasoning must not introduce a registry, boundary, store, policy engine, verdict engine, or `EvidenceRegistry`/`AuthorityBoundary` factory. The sole authority remains P6's `EvidenceRegistry` bound to `RuntimeContext`. Any `to_authoritative`/`to_fact`/`registry`/`boundary` injection is refused.
- **A16.** No direct DB/S3/API/ERP (`httpx`/`requests`/`boto3`/`psycopg`/`openai`/`temporalio`) import lives in reasoning; no `EvidenceRegistry(` instantiation lives in `agents/reasoning/`. Evidence path is only via HMAC-bound refs from discovery + `RuntimeContext`.

### G. Deterministic/probabilistic separation (A17–A18)

- **A17.** `confidence` (if present) is a probabilistic score in `[0,1)`; it never implies `VERIFIED`. A result with `confidence == 0.99` must still have `tier == "reasoning"` and must still carry `VERIFIED not in to_dict()`.
- **A18.** Absolute certainty `1.0` on non-authoritative evidence is refused. Authoritative language (`VERIFIED`/`FACT`/`DECISION`/`APPROVED`) is forbidden in advisory output regardless of confidence.

### H. Replay/context integrity (A19–A20)

- **A19.** Success must preserve `situation_id`/`company_id`/`now`/`evidence_ids`/`provenance` from the discovery result and bound context. Mismatch (`request.situation_id != context.situation_id`, etc.) is `SCOPE_MISMATCH`. No wall-clock read replaces caller-supplied `now`.
- **A20.** Provenance (`p6_evidence_store` etc.) travels with refs and is preserved in the result; `to_dict()` exposes `situation_id`/`company_id`/`now`/`evidence_ids`/`provenance` unchanged from discovery+context.

### I. Failure semantics — typed, not plausible (A21–A22)

- **A21.** Failure is typed `ReasoningFailure` with code ∈ {`INSUFFICIENT_EVIDENCE`, `CONTRADICTORY_EVIDENCE`, `STALE_EVIDENCE`, `SCOPE_MISMATCH`, `INVALID_DISCOVERY_RESULT`, `REASONING_FAILED`} and non-blank detail. `success == False` iff `failure is not None`; `success == True` iff `failure is None`. No other codes.
- **A22.** Failure never fabricates a plausible advisory resolution to hide the failure. A stale, contradictory, or insufficient input yields a typed failure, not a best-guess `candidate_interpretation` presented as success.

## 3. Semantic model (minimum, normative)

| Type | Shape | Tier | Notes |
|------|-------|------|-------|
| `ReasoningFailure` | `code∈{6 codes}, detail` | failure | Frozen, extra-forbid, strict |
| `ReasoningResult` | `situation_id, company_id, now, evidence_refs+, candidate_interpretation, conflicting_evidence, uncertainty, rationale, unresolved_questions, advisory_proposal?, tier="reasoning"` | advisory | HMAC refs preserved, no authoritative keys, frozen |
| `reason(discovery, *, context)` | `(DiscoveryResult, RuntimeContext) -> ReasoningResult` (or typed failure) | function | Only evidence path via discovery+context, no second authority |

`candidate_interpretation ≠ verdict`, `uncertainty ≠ resolved`, `confidence ≠ VERIFIED`, `proposal ≠ decision`, `advisory ≠ truth`.

## 4. Negative invariants (reuse; not re-tested as goals)

- No wall-clock, no network, no `Decimal` money in this slice (P6 Decimal re-enforced past gate).
- No promotion path from advisory to authoritative; no `to_authoritative`/`to_fact`.
- No evidence minting from agent data; only `EvidenceRegistry` (via discovery+context) issues HMAC pointers.

## 5. Non-goals (this slice)

LangGraph nodes, LLM provider/prompt/vector/graph/Temporal changes, policy redefinition, store mutations, financial execution intents, or P6 edits are non-goals. Reasoning composes frozen primitives only.

## 6. Verification shape (how the contract is tested)

- **Gate A:** valid discovery represented, blank/injected/stale/invented/mismatched now/scope/fact refused (`INVALID_DISCOVERY_RESULT`/`SCOPE_MISMATCH`/`STALE_EVIDENCE`), no wall-clock.
- **Gate B:** success carries required advisory fields, `to_dict()` free of `status`/`verdict`/`decision`/`amount`/`VERIFIED`/`FAILED`/`APPROVED`/`EXECUTED`/`SETTLED`, tier is `reasoning`.
- **Gate C:** orphan/unsupported/invented metadata refused, every conclusion maps to discovery evidence, registry mismatch refused.
- **Gate D:** contradictory/missing/stale/ambiguous remain flagged in `conflicting_evidence`/`unresolved_questions`/`uncertainty`, not resolved by `0.99` or prose.
- **Gate E:** no WRITE/EXECUTE/APPROVE/VERIFY/mutation attributes, remains advisory, handoff is `reasoning` not `verified`.
- **Gate F:** no second registry/boundary/store/policy/verdict engine, no direct external imports, no `EvidenceRegistry(` instantiation.
- **Gate G:** `0.99` still advisory, `1.0` refused, `VERIFIED` never appears even at high confidence.
- **Gate H:** preserves `situation_id`/`company_id`/`now`/`evidence_ids`/`provenance`, replay-stable, no wall-clock.
- **Gate I:** six typed failure codes only, failure shape strict, no plausible resolution on failure.
- All Gates must be RED before review, then GREEN after minimal implementation that sits inside the agent plane.

## 7. Review gate (normative)

```
P7-05 contract + RED tests (Gates A–I, ~22 invariants)
      ↓
business-contract review (this doc is the authority)
      ↓
reasoning-boundary review (no financial truth, no second authority)
      ↓
FREEZE
```

No reasoning implementation slice may start until this contract is frozen. Implementation must sit entirely inside the agent plane:

```
                AGENT PLANE
  DiscoveryResult ──► Reasoning (advisory) ──► ReasoningResult
                                              (candidate + refs + uncertainty)
                                                      │
                                              typed advisory handoff
                                                      ▼
                                               DETERMINISTIC GATE
                                                      │
                                           accept / reject
                                                      ▼
                                           Policy → Approval → Execute → Verify
                                                      (P6, no bypass)
```

See `agents/reasoning/` for the minimal boundary model and `tests/contract/test_p7_05_reasoning_red.py` for the RED suite that enforces it.
