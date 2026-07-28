# ADR-009: Seven-Stage Validation Harness — No Stage Skip

**Status:** Accepted  
**Date:** 2026-07-28  
**Deciders:** Architecture Team  

---

## Context

Financial analysis output has many failure modes:
- A number could be wrong (calculation error)
- A number could be right but sourced from unreliable data (stale, low-coverage)
- A causal claim could lack supporting evidence (unsubstantiated hypothesis)
- An LLM-generated narrative could contain numbers that don't match the source (hallucination)
- A recommendation could violate policy (autonomy exceeded)

FinSight's existing system already has validation checks scattered across the pipeline:
- Schema validation at API boundaries (Pydantic)
- Financial validation in `finance/validation/`
- Data quality checks in `finance/validation/data_quality.py`
- Claim validation in `shared/utils/validators/claim_validator.py`
- Policy evaluation in `shared/utils/policy.py`

But these checks are not coordinated into a single validation framework. A failure in one stage could be compensated by a skip in another. Worse, a pipeline could complete without any validation at all if the orchestrator takes a shortcut path.

## Decision

Introduce a **Seven-Stage Validation Harness** — a structured pipeline that every piece of output passes through. **No stage can be skipped.** Each stage must either pass or produce a `DegradedMode` that propagates to the policy engine.

### The Seven Stages

```
Stage 1: Schema Validation    (Pydantic boundary enforcement)
Stage 2: Financial Validation (Domain rule enforcement)
Stage 3: Business Rule Check  (Policy and constraint enforcement)
Stage 4: Evidence Validation  (Every claim has evidence)
Stage 5: Hallucination Check  (Post-rendering claims vs source)
Stage 6: Recommendation Gate  (Action taxonomy and policy)
Stage 7: Executive Summary    (Final report integrity)
```

### Stage Details

#### Stage 1 — Schema Validation

**Owner:** `shared/` (Pydantic models)  
**Timing:** Every time data crosses a boundary (API, tool result, assertion creation)  
**What it checks:**
- All fields present with correct types
- Monetary fields are `Decimal` (not `float`)
- Enums are valid members
- Required fields are non-null
- Field constraints (e.g., `confidence` in `[0.0, 1.0]`)

**Failure mode:** `ValidationError` — hard failure, pipeline stops. Data must be fixed at source.

**Existing implementation:** Pydantic v2 `field_validator` on every model. The `MoneyDecimal` alias with `reject_float` validator.

#### Stage 2 — Financial Validation

**Owner:** `finance/validation/`  
**Timing:** After ingestion, before variance computation  
**What it checks:**
- Fiscal period consistency (no overlapping periods, no gaps)
- Period lifecycle validity (correct state transitions: OPEN → CLOSING → VALIDATING → ANALYZING → REVIEWING → COMPLETED → LOCKED)
- Chart of accounts integrity (no orphan transactions, valid account codes)
- Trial balance balances (debits = credits)
- Date arithmetic (start before end, contiguous periods)

**Failure mode:** `PeriodValidationResult` with `errors` list. Errors block pipeline; warnings produce degraded mode.

**Existing implementation:** `PeriodValidator.validate_period()`, `check_gaps()`, `check_overlapping()`.

#### Stage 3 — Business Rule Check

**Owner:** `shared/utils/policy.py` + `finance/assertion_pipeline.py`  
**Timing:** After assertions are built, before commentary rendering  
**What it checks:**
- Assertion confidence meets minimum thresholds per type
- Action assertions map to approved taxonomy
- Comparative assertions have ≥2 candidates in the candidate set
- Causal assertions cite validated driver tree edges or evidence classes
- No assertion type mismatch (e.g., NUMERIC used where CAUSAL required)

**Failure mode:** Route to higher autonomy level (e.g., ANALYST_IN_THE_LOOP → MANAGER_APPROVAL). Produces `DegradedMode` for the policy engine.

**Existing implementation:** `Assertion` types and `PolicyEngine.evaluate_policy()`.

#### Stage 4 — Evidence Validation

**Owner:** `finance/assertion_pipeline.py` + `shared/models/assertions.py`  
**Timing:** After assertion construction, before policy evaluation  
**What it checks:**
- Every `Assertion` has non-empty `evidence_ids`
- Every `evidence_id` references an existing `EvidenceItem`
- Evidence sources are valid and traceable
- Evidence diversity — at least one non-LLM source per assertion
- Contradictions are recorded if evidence conflicts

**Failure mode:** Assertion without evidence is discarded. Assertion with contradictory evidence gets `support_level=WEAK` and a `contradictions` list. No assertion passes Stage 4 without at least one evidence reference.

**Existing implementation:** `EvidenceItem` model, `evidence_ids` field on `Assertion`, `contradictions` field.

#### Stage 5 — Hallucination Check

**Owner:** `shared/utils/validators/claim_validator.py`  
**Timing:** After LLM commentary rendering, before policy evaluation  
**What it checks:**
- Every `$` figure in rendered commentary maps to a source assertion value (within 5% tolerance)
- Every comparative keyword ("largest", "biggest", "primary") is verified against a deterministic candidate set
- Every causal phrase ("driven by", "due to", "because of") is backed by a validated CAUSAL assertion or driver tree edge
- Every action phrase ("should", "recommend", "propose") maps to the approved taxonomy

**Failure mode:** Unmatched `$` figure → validation failure → commentary rejected → pipeline enters `INSUFFICIENT_CAUSAL_EVIDENCE` degraded mode. The LLM may re-render (up to 2 retries) or the pipeline escalates to human review.

**Existing implementation:** `validate_commentary_claims()` with `MonetaryClaim`, `CausalClaim`, `ActionClaim`, and the four validator functions.

#### Stage 6 — Recommendation Gate

**Owner:** `shared/utils/policy.py` + `shared/models/action.py`  
**Timing:** After commentary, before response assembly  
**What it checks:**
- Action assertions map to approved `ActionDomain`/action pairs (20 approved pairs)
- Each action clears 5 gates:
  1. **Taxonomy gate:** Action is in approved set
  2. **Cause gate:** Action cites a validated CAUSAL assertion
  3. **Policy gate:** Action is permitted at current autonomy level
  4. **Owner gate:** Owner type is identified
  5. **Impact gate:** Expected impact is quantified

**Failure mode:** Action that fails any gate is added to `PolicyDecision.blocked_actions`. The response includes warning but the action is not executed. Gate 3–5 failures escalate autonomy level.

**Existing implementation:** `ActionDomain` enum, `APPROVED_ACTION_TAXONOMY` set, `create_action()` gate enforcement.

#### Stage 7 — Executive Summary Validation

**Owner:** Integration orchestration in `agents/orchestrator.py`  
**Timing:** Before final response is returned  
**What it checks:**
- All previous 6 stages have completed (no skip)
- `DataQualityReport` is present and passed
- `PolicyDecision` is present
- Assertion → commentary coherence (all sections have cited assertions)
- No degraded mode without corresponding escalation
- Version metadata is populated

**Failure mode:** Incomplete validation chain → pipeline returns error. Response is not served until Stage 7 passes. This is the circuit-breaker.

**Existing implementation:** `PipelineState` fields (`data_quality`, `policy_decision`, `assertions`, `commentary_draft`) — the orchestrator checks presence of all required keys before final return.

### Stage Flow Control

```
Input ──→ Stage 1 ──→ Stage 2 ──→ Stage 3 ──→ Stage 4 ──→ Stage 5 ──→ Stage 6 ──→ Stage 7 ──→ Output
           │           │           │           │           │           │           │
           ▼           ▼           ▼           ▼           ▼           ▼           ▼
        Hard fail   Hard fail   Soft fail   Soft fail   Soft fail   Soft fail   Hard fail
        (stop)      (stop)      (route up)  (discard)   (retry)     (block)     (stop)
```

- **Hard fail:** Pipeline terminates. Error returned to user.
- **Soft fail:** Pipeline continues in degraded mode. Policy engine decides routing.

## Consequences

### Positive

- **No gap in validation.** Every output passes through all 7 stages. There is no "skip root cause → skip validation" path.
- **Failure mode clarity.** Each stage has a defined failure mode. Developers know exactly what happens when their change introduces a validation failure.
- **Degraded-mode propagation.** Soft failures produce `DegradedMode` entries that propagate through the pipeline and influence the policy engine's autonomy decision.
- **Auditable validation trail.** Each stage records its pass/fail status. The pipeline response includes a validation summary showing which stages passed, which degraded, and which failed.

### Negative

- **Pipeline latency.** 7 sequential validation stages add to end-to-end execution time. Stage 5 (Hallucination Check) is especially expensive as it re-examines the LLM's entire output.
- **Double validation.** Some checks overlap (e.g., Stage 1 enforces types, Stage 2 enforces domain rules — but a domain rule violation is also a type violation at the API boundary). We accept this redundancy in exchange for isolation.
- **Stage 5 retries are expensive.** If the LLM hallucinates, Stage 5 rejects and requests a re-render. Each re-render costs a full LLM call. Mitigated by making the re-render prompt highly specific about which figures were unmatched.
- **Adding a new stage is invasive.** A Stage 8 would require changes to the orchestrator, the pipeline state, the response schema, and all integration tests.

## Compliance

1. **No stage can be programmatically skipped.** The orchestrator (`agents/orchestrator.py`) must explicitly call each stage in sequence. A PR that removes a stage call is rejected.
2. **Each stage produces a typed result.** Stage results are recorded in `PipelineState` under `validation_results: dict[str, ValidationStageResult]`.
3. **Stage 7 checks stage completion.** The executive summary validator iterates the expected stage list and verifies each has a result entry. Missing stages produce an error.
4. **Integration tests run all 7 stages.** A golden-path integration test must execute all 7 stages and verify each result.
5. **Stage 5 (Hallucination Check) has a dedicated test suite.** The `validate_commentary_claims()` function is tested with golden data: known-good commentary, known-bad commentary (hallucinated numbers), and edge cases (commentary with no `$` figures).
