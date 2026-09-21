# P7-06 Human Resolution Brief Contract — Advisory Human-Readable Package over Reasoning

**Status:** Draft spec for P7-06 on `feat/finsight-p7-06-human-resolution-brief`.
**Base:** `a906f68` (P7-05 merge). P6 lifecycle/evidence/approval/execution/verification frozen; P7-01 authority, P7-02 runtime, P7-03 tools, P7-04 discovery, P7-05 reasoning frozen.
**Scope:** Single company (`company_id = meridian`, `situation_id` tenancy, INR Decimal, `now` tz-aware caller-supplied). Transforms a valid advisory `ReasoningResult` into a typed human-readable advisory `HumanResolutionBrief`; never a decision artifact or approval.
**Sources:** `docs/architecture/P7-01_AGENT_AUTHORITY_CONTRACT.md` (A1–A46), `agents/authority/` (HMAC-bound refs, `AuthorityError`), `agents/runtime/` (factory-bound `RuntimeContext`/`RuntimeHandoff`), `agents/tools/` (P7-03 typed tools), `agents/discovery/` (`DiscoveryRequest`/`DiscoveryResult`/`discover`), `agents/reasoning/resolution.py` (`ReasoningResult`/`ReasoningFailure`/`reason`), `docs/domain/meridian-process-model.md` (§2 lifecycle, FS-231).
**Type:** DOC-ONLY. No LangGraph nodes, no runtime writes, no store/policy/verdict engine, no P6 edits, no vector DB, no graph memory, no Temporal, no LLM provider/prompt changes, no financial mutation.

Conventions: `Refuse` = raise `AuthorityError` or return typed `BriefFailure` with no authoritative side effect. `Caller-supplied time` = every `captured_at`/`now`/`created_at` is explicit; no `datetime.now()` inside stored state. Reasoning is the sole interpretation source; brief never invents evidence/scope/now/fact/decision. `tier = "brief"` for success, `tier = "brief_failure"` for typed failures. Brief is advisory and human-readable; readability never implies authority. Four-perspective convergence: engineering (minimal typed surface), product (human must be able to act without mistaking advice for decision), design (scannable sections, no status theatre), business-auditor (outcome-first: nothing lost, prematurely closed, misrepresented, or bypassed).

## 0. Frozen inputs (normative, consumed as given)

- **F1.** P7-01 authority frozen: 13 deny-list verbs, HMAC-bound `EvidenceReference`/`AuthoritativeFact`, `AuthorityBoundary`, `AgentCapability` (READ/CORRELATE/HYPOTHESIZE/PROPOSE/EXPLAIN), advisory vs authoritative tier, `validate_claim/proposal_dict` semantics.
- **F2.** P7-02 runtime frozen: factory-bound `RuntimeContext` (HMAC of `situation_id:company_id:now`), `RuntimeHandoff` advisory-only, `AgentRuntime` capability-gated dispatch, deterministic envelope wins, no second authority.
- **F3.** P7-03 tools frozen: `EvidenceLookup`/`Correlation`/`Explanation` typed request→result via `EvidenceRegistry` HMAC, context-bound, scope-checked, freshness-enforced.
- **F4.** P7-04 discovery frozen: `DiscoveryRequest` (situation/company/now/scope/objective/capabilities) immutable, `DiscoveryResult` (success + refs/observations/hypotheses OR failure + code/detail), `discover()` advisory only, scope-locked, no financial mutation.
- **F5.** P7-05 reasoning frozen: `ReasoningResult` (success + `candidate_interpretation`/`conflicting_evidence`/`uncertainty`/`rationale`/`unresolved_questions`/`advisory_proposal`, tier `reasoning`, no `status`/`verdict`/`decision`/`amount`/`VERIFIED`) and `ReasoningFailure` (6 codes), `reason(discovery, context)` advisory only, provenance-preserving, no second authority, no wall-clock.

## 1. Boundary and mission (normative)

```
  DiscoveryResult (bounded, HMAC-bound refs, caller-supplied now)
        │
        ▼
  ┌───────────┐
  │ Reasoning │  candidate interpretation, conflicting evidence,
  │ (advisory)│  uncertainty, rationale, unresolved  (P7-05)
  └─────┬─────┘
        │ advisory ReasoningResult (tier=reasoning)
        ▼
  ┌────────────┐
  │   Brief    │  human-readable advisory package: situation/context,
  │ (advisory) │  what was observed, reasoning summary, supporting
  │            │  evidence, conflicting evidence, uncertainty, unresolved
  │            │  questions, advisory next-step/proposal — never decision
  └─────┬──────┘
        │ HumanResolutionBrief (tier=brief)  ──►  Human (reads, decides outside)
        │                                              │
        │                                              ▼
        │                                    Deterministic Gate ──► Policy→Approval→Execute→Verify
        │                                      (P6, no bypass; brief never bypasses)
```

Mission: translate a **valid** `ReasoningResult` (itself derived from a valid bounded `DiscoveryResult`) into a **typed human-readable advisory brief** that a human can act on without mistaking advice for decision, authority, or financial truth. It must preserve situation, provenance, scope, now, every material evidence link, every contradiction, every uncertainty, and every unresolved question.

Business-auditor invariant: the brief answers one question — *can the system represent and control the business situation without losing, prematurely closing, misrepresenting, or bypassing it?*  Losing = dropping situation/company/now/provenance. Premature closure = resolving contradictions or missing evidence with prose. Misrepresentation = inventing evidence, expanding scope, or using authoritative language (`VERIFIED`/`APPROVED`/status/verdict). Bypass = hidden approval, executable command, or second authority.

## 2. Gate A–I normative requirements (A1–A27, test-traceable)

### A. Input integrity — only successful, valid ReasoningResult (A1–A4)

- **A1.** Brief accepts only a `ReasoningResult` where `success == True`, `failure is None`, `situation_id`/`company_id`/`now` non-blank and tz-aware, `company_id == "meridian"`, `now` equals the bound `RuntimeContext.now`, `evidence_refs` is a non-empty tuple of HMAC-bound `EvidenceReference`, `candidate_interpretation`/`uncertainty`/`rationale` non-blank, `tier == "reasoning"`, and `confidence` in `[0,1)`. Any other shape (`success == False`, `failure` present, empty/blank fields, naive `now`, wrong company, `confidence == 1.0`, `status`/`verdict` keys, unissued refs) is a typed brief-generation failure — never a plausible brief.
- **A2.** Scope is bounded by the reasoning result's `evidence_refs` provenance and the discovery scope it preserves. Brief must not invent `evidence_id`/`source_id`/`captured_at`/`digest`/`provenance`/`ttl_seconds`, must not expand evidence scope beyond the reasoning's `evidence_ids`, must not invent `situation_id`/`company_id`/`now`, and must not mint a competing `AuthoritativeFact`. Any invented field is refused as `INVALID_REASONING_INPUT` or `SCOPE_MISMATCH`.
- **A3.** `now` is caller-supplied and replay-stable. No `datetime.now()`/`utcnow()`/`time.time()` read lives in brief state. Freshness is evaluated via `is_stale(now)` against caller-supplied `now`; stale is typed failure, not auto-refreshed prose.
- **A4.** Only the reasoning result and the bound `RuntimeContext` are inputs. Brief has no other evidence source, no registry factory, no wall-clock, and no LLM/prompt/vector memory/graph memory/Temporal/DB/API/ERP path.

### B. Evidence linkage — every material statement maps to supplied evidence (A5–A8)

- **A5.** Every material statement in the brief (every section's substantive sentences, every supporting/conflicting entry, every advisory sentence) must map to at least one `evidence_id` present in the input reasoning's `evidence_refs`. No orphan statement.
- **A6.** Unsupported assertion (statement with no cited ref, ref not in reasoning scope, unissued/HMAC-invalid ref, or invented digest/provenance value) is refused — typed brief failure, never a silent success with fabricated content.
- **A7.** No evidence-scope expansion: the brief's `evidence_ids` must be a subset of the reasoning's `evidence_ids`. Adding an `evidence_id` not present in the reasoning result is `SCOPE_MISMATCH` or `INVALID_REASONING_INPUT`. Evidence references remain opaque `EvidenceReference` issued by the deterministic `EvidenceRegistry`; brief never regenerates tokens or re-mints refs from raw fields.
- **A8.** Evidence references remain authoritative references, not regenerated tokens. Brief preserves the original `EvidenceReference` objects (including `_token`, `captured_at`, `digest`, `provenance`, `ttl_seconds`). Reconstructing a ref from string fields or minting a new HMAC outside `EvidenceRegistry` is fabrication and refused.

### C. Human readability — explicit sections (A9–A11)

- **A9.** Success output must expose explicit, non-blank, human-readable sections. Required sections (each a non-blank string or structured entry, never `None` or empty): `situation_context` (situation/company/now provenance and scope), `observed_summary` (what was observed via discovery), `reasoning_summary` (candidate interpretation grounded in evidence), `supporting_evidence` (evidence-backed supporting entries with refs), `conflicting_evidence` (preserved conflicts, may be empty only when reasoning has none), `uncertainty_section` (explicit uncertainty text), `unresolved_questions` (typed unresolved entries, may be empty only when reasoning has none), `advisory_next_step` (advisory proposal/next-step, never a command).
- **A10.** Sections must be human-readable prose/structured text, not raw dumps or opaque IDs alone. Each section must be scannable: non-blank, at least one complete sentence, no single-token or single-character filler. A brief that collapses all content into one blob or leaves any required section blank/whitespace is invalid.
- **A11.** Readability never implies authority. Formatting, headings, or emphasis (e.g. markdown `#`, `**`) must not introduce authoritative markers (`VERIFIED`/`FAILED`/`APPROVED` etc.) or create a visual decision artefact (e.g. a stamp-like `APPROVED` header).

### D. Uncertainty preservation — contradictions remain visible (A12–A15)

- **A12.** Contradictory evidence (`reasoning.conflicting_evidence` non-empty) must remain flagged in the brief's `conflicting_evidence` section and acknowledged in `uncertainty_section` and `reasoning_summary`. It must not be collapsed into a single flat claim, merged value, or resolved with persuasive prose.
- **A13.** Missing evidence (`reasoning.unresolved_questions` non-empty) must remain in the brief's `unresolved_questions` and be named in `uncertainty_section`. Brief must not fabricate values to fill the gap; `uncertainty_section` must name the missing dimension.
- **A14.** Stale, inaccessible, or ambiguous evidence (reasoning with `STALE_EVIDENCE`/`INSUFFICIENT_EVIDENCE`/`CONTRADICTORY_EVIDENCE` context, or refs where `is_stale(now) == True`) must remain flagged as uncertainty — never silently omitted or resolved. High-confidence prose or `confidence == 0.99` must not resolve it. The brief for a stale input must be a typed failure, not a best-guess package.
- **A15.** Unresolved reasoning (reasoning where `uncertainty` names unresolved dimensions) must propagate verbatim or with fidelity into the brief's `uncertainty_section` — paraphrasing that drops the unresolved dimension is a misrepresentation and is refused. The brief's advisory tone must preserve — not soften — the reasoning's uncertainty.

### E. Advisory semantics — never authoritative (A16–A18)

- **A16.** Brief output (every section, `to_dict()`, any prose, any heading) must never contain authoritative markers as substrings or keys: `VERIFIED`, `FAILED`, `APPROVED`, `EXECUTED`, `SETTLED`, `status`, `verdict`, `decision`, `FACT`, or `amount` where not a cited evidence value. Presence of any marker is a hard failure of the brief's advisory semantics.
- **A17.** Brief must not contain an authoritative amount as a direct financial assertion. Monetary values may appear only as cited evidence values with an accompanying `evidence_id` ref; a bare `amount: 123.45` or sentence `Amount is ...` without a ref is refused. Decimal handling remains P6's responsibility — brief cites, never establishes, amounts.
- **A18.** Brief's advisory proposal/next-step, if any, is disjoint from capability verbs and deny-list verbs. `advisory_next_step` must never be a capability verb (`read`, `correlate`, `hypothesize`, `propose`, `explain`) nor a deny-list verb (`approve`, `verify`, `execute`, `mutate_financial_state`, etc.). Tier remains advisory (`tier == "brief"` on success); confidence never implies `VERIFIED`.

### F. No hidden approval — recommendation is not a decision (A19–A20)

- **A19.** Human-readable recommendation/advisory text must not be represented as an approval request, approval decision, executable command, or authorization. Strings or keys such as `approval_request`, `approve`, `authorized`, `execute`, `command`, `run`, `perform_correction`, or any `decision = ...` field are forbidden in the brief. The brief is read-only advice; the deterministic approval/execution boundary (P6) remains the sole authority.
- **A20.** No status theatre: phrases that mimic decision artefacts (`Status: APPROVED`, `Decision: ...`, `Approved by`, `Executed`, `Settled`) are forbidden even as headings or emphasis. The brief must read as `Advisory`/`For review`/`Next step (advisory)` — never as a stamp.

### G. No second authority (A21–A23)

- **A21.** Brief must not introduce a registry, boundary, store, policy engine, verdict engine, execution interface, or `EvidenceRegistry`/`AuthorityBoundary` factory. The sole authority remains P6's `EvidenceRegistry` bound to `RuntimeContext`. Any `to_authoritative`/`to_fact`/`registry`/`boundary`/`policy`/`verdict`/`execute` injection is refused.
- **A22.** No direct DB/S3/API/ERP/LLM/vector/graph/Temporal import lives in brief: `httpx`, `requests`, `boto3`, `psycopg`, `openai`, `temporalio`, `langchain`, `langgraph`, `qdrant`, `redis`, `pydantic` beyond model definition, `prompts`, or `memory` scaffolding are forbidden in `agents/brief/`. Evidence path is only via HMAC-bound refs from reasoning + `RuntimeContext`.
- **A23.** Brief does not create, alter, or imply a `VerificationReport`, an approval token, a lifecycle transition, or an alternative evidence authority. No `EvidenceRegistry(` instantiation lives in `agents/brief/`.

### H. Failure behavior — typed, not fabricated (A24–A25)

- **A24.** Invalid reasoning input (failed reasoning `success == False`, blank/naive `now`, wrong `company_id`, invented scope, unissued refs, stale refs, `confidence == 1.0`, authoritative markers in reasoning) must produce a typed `BriefFailure` with `code` in `INVALID_REASONING_INPUT`|`STALE_EVIDENCE`|`SCOPE_MISMATCH`|`BRIEF_GENERATION_FAILED` and non-blank `detail`, with `success == False` and no plausible prose masquerading as a brief. No other codes.
- **A25.** Failure never fabricates human-readable prose to hide the failure. A stale, contradictory-outside-scope, or insufficient input yields a typed failure with empty/None sections, not a best-guess `situation_context` presented as success. `success == True` iff `failure is None`; `success == False` iff `failure is not None`.

### I. Replay/context integrity — situation/company/now/provenance/scope unchanged (A26–A27)

- **A26.** Success must preserve `situation_id`/`company_id`/`now`/`evidence_ids`/`provenance` from the reasoning result and bound context. Mismatch (`brief.situation_id != reasoning.situation_id`, `brief.company_id != context.company_id`, `brief.now != context.now`) is `SCOPE_MISMATCH`. No wall-clock read replaces caller-supplied `now`. `to_dict()` exposes `situation_id`/`company_id`/`now`/`evidence_ids`/`provenance` unchanged from reasoning+context.
- **A27.** Evidence provenance (`p6_evidence_store` etc.) and scope travel with refs and are preserved verbatim in the brief's `supporting_evidence` and `conflicting_evidence` entries and in `to_dict()`. Regenerating refs or altering `provenance`/`ttl_seconds`/`captured_at`/`digest` is fabrication.

## 3. Semantic model (minimum, normative)

| Type | Shape | Tier | Notes |
|------|-------|------|-------|
| `BriefFailure` | `code∈{INVALID_REASONING_INPUT, STALE_EVIDENCE, SCOPE_MISMATCH, BRIEF_GENERATION_FAILED}, detail` | failure | Frozen, extra-forbid, strict |
| `HumanResolutionBrief` | `situation_id, company_id, now, evidence_refs+, situation_context, observed_summary, reasoning_summary, supporting_evidence+, conflicting_evidence, uncertainty_section, unresolved_questions, advisory_next_step?, tier="brief", success, failure?` | advisory (human-readable) | HMAC refs preserved, 8 required sections non-blank (or empty only when reasoning has none for conflicting/unresolved), no authoritative keys/markers, frozen |
| `brief(reasoning, *, context)` | `(ReasoningResult, RuntimeContext) -> HumanResolutionBrief` (or typed failure) | function | Only evidence path via reasoning+context, no second authority, no wall-clock |

`brief ≠ decision`, `readable ≠ authoritative`, `advisory_next_step ≠ approval`, `confidence ≠ VERIFIED`, `human-readable ≠ machine-executable`.

## 4. Negative invariants (reuse; not re-tested as goals)

- No wall-clock, no network, no `Decimal` money assertion in this slice (P6 Decimal re-enforced past gate; brief cites amounts only via refs).
- No promotion path from advisory to authoritative; no `to_authoritative`/`to_fact`.
- No evidence minting from agent data; only `EvidenceRegistry` (via discovery→reasoning→brief chain) issues HMAC pointers.
- No approval/execution/verification side effects; brief is read-only.

## 5. Non-goals (this slice)

LangGraph nodes, LLM provider/prompt/vector/graph/Temporal changes, policy redefinition, store mutations, financial execution intents, ERP/API access, or P6 edits are non-goals. Brief composes frozen primitives only.

## 6. Verification shape (how the contract is tested)

- **Gate A:** valid reasoning represented, blank/injected/stale/invented/mismatched now/scope/fact/1.0 refused (`INVALID_REASONING_INPUT`/`SCOPE_MISMATCH`/`STALE_EVIDENCE`), no wall-clock, context-bound.
- **Gate B:** every material statement maps to reasoning evidence, orphan/invented/expanded scope refused, no regenerated tokens, `evidence_ids` subset preserved.
- **Gate C:** 8 required sections present and non-blank/scannable, not collapsed, headings free of authority markers.
- **Gate D:** contradictory/missing/stale/ambiguous remain flagged in `conflicting_evidence`/`unresolved_questions`/`uncertainty_section`, not resolved by `0.99` or prose, stale is typed failure.
- **Gate E:** `to_dict()` and every section free of `status`/`verdict`/`decision`/`amount`/`VERIFIED`/`FAILED`/`APPROVED`/`EXECUTED`/`SETTLED`/`FACT`, no authoritative amount without ref, tier is `brief`.
- **Gate F:** no `approval_request`/`approve`/`execute`/`command`/`authorized`/`decision` representation, no status theatre.
- **Gate G:** no second registry/boundary/store/policy/verdict engine, no direct external imports, no `EvidenceRegistry(` instantiation.
- **Gate H:** 4 typed failure codes only, failure shape strict, no plausible prose on failure.
- **Gate I:** preserves `situation_id`/`company_id`/`now`/`evidence_ids`/`provenance`, replay-stable, no wall-clock, no regenerated refs.
- All Gates must be RED before review, then GREEN after minimal implementation that sits inside the agent plane.

## 7. Review gate (normative)

```
P7-06 contract + RED tests (Gates A–I, ~24 invariants)
      ↓
four-perspective review (engineering · product · design · business-auditor)
      ↓
business-contract review (this doc is the authority)
      ↓
brief-boundary review (human-readable ≠ decision, no second authority)
      ↓
FREEZE
```

No brief implementation slice may start until this contract is frozen. Implementation must sit entirely inside the agent plane:

```
                AGENT PLANE (advisory, human-readable)
  DiscoveryResult ──► Reasoning (candidate + refs + uncertainty) ──► Brief (sections + refs + advisory next-step)
                                                                      (human reads, decides outside)
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

See `agents/brief/` for the minimal boundary model and `tests/contract/test_p7_06_human_resolution_brief_red.py` for the RED suite that enforces it.
