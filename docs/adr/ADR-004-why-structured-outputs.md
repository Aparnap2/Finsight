# ADR-004: Why Structured Outputs — LLM Responses Must Conform to Pydantic Schemas

**Status:** Accepted  
**Date:** 2026-07-28  
**Deciders:** Architecture Team  

---

## Context

LLMs produce free text. Financial analysis requires structured, typed, validated data. Every LLM interaction in FinSight (root-cause investigation, commentary rendering, scenario generation) must produce outputs that the system can process deterministically — not text that needs fragile parsing.

In early prototypes, we attempted to parse LLM responses with:
- Regex extraction of monetary figures → missed values, extracted wrong numbers
- JSON parsing of instruction-following → malformed JSON on ~15% of calls
- Keyword matching for causal claims → false positives from negated statements
- Free-text commentary → hallucinated `$` figures that differed from source data

Each parsing failure was silent — the system either used `None` defaults or skipped the figure entirely. No error was surfaced to the user. This is unacceptable for financial software where every number must be accounted for.

## Decision

All LLM responses must conform to **strict Pydantic schemas** defined in advance. The LLM client (`shared/utils/llm_client.py`) enforces this contract:

### Schema-First Design

Every LLM interaction defines its expected output structure as a Pydantic `BaseModel` **before** the prompt is written:

```python
class RootCauseResponse(BaseModel):
    """Structured output from the root-cause investigation agent."""
    variance_id: str
    summary: str
    assertions: list[Assertion]        # Typed assertions, not free text
    evidence: list[EvidenceItem]       # Structured evidence references
    confidence_score: float            # 0.0–1.0
    alternative_hypotheses: list[Assertion]
    data_gaps: list[str]
```

### Enforcement Flow

```
Prompt + Schema ──→ LLM ──→ Raw Response ──→ Pydantic Validation
                                                    │
                                          ┌─────────┴──────────┐
                                          ▼                    ▼
                                     Valid ✓             Invalid ✗
                                          │                    │
                                          ▼                    ▼
                                    Use directly       Retry (up to 3×)
                                                            │
                                                   ┌────────┴────────┐
                                                   ▼                 ▼
                                              Succeeds          All retries fail
                                                  │                    │
                                                  ▼                    ▼
                                            Use directly      Degraded mode:
                                                           route_for_review
```

### Rules

1. **`response_model` always.** Every LLM call uses `llm_client.call(response_model=…)`. No exception for any agent.
2. **No free-text parsing of LLM output.** Regex is never used to extract structured data from LLM responses. Regex is allowed only in `claim_validator.py` for *post-rendering cross-checking* of human-authored commentary — a secondary validation, not a primary parsing path.
3. **No `json.loads()` on LLM output.** The raw text from the LLM is never passed to `json.loads()`. All structured parsing goes through Pydantic `model_validate()`.
4. **Retry on schema failure.** If Pydantic validation fails, the LLM client retries the call (up to 3 times) with the same prompt but including the previous attempt's validation error as feedback. This gives the LLM a chance to self-correct.
5. **Persistent failure = degraded mode.** After 3 retries, the system enters a degraded mode (e.g., `INSUFFICIENT_CAUSAL_EVIDENCE`), and the pipeline routes the step to human review. The LLM output is discarded — no partial data is used.
6. **Fields are always present.** No `Optional` field is allowed in an LLM response schema unless the absence conveys specific meaning (e.g., `data_gaps` being an empty list means no gaps found — it should not be `None`).

### What This Enables

- **Deterministic downstream processing.** Every consumer of LLM output receives a validated, typed object — never raw text.
- **Automatic error surfacing.** A retry-failed LLM call produces a structured degraded-mode event that propagates through the pipeline.
- **Unit-testable LLM contracts.** Agent unit tests can create fixture `RootCauseResponse` objects without ever calling an LLM.
- **Observability.** Schema validation failures are logged with the raw LLM response for debugging — without passing user-tainted data to downstream logic.

## Consequences

### Positive

- **Zero silent LLM data corruption.** Every value from the LLM passes through Pydantic validation. Malformed responses either self-correct or fail safely.
- **Types guarantee downstream safety.** The consuming code knows that `confidence_score` is a `float` in `[0.0, 1.0]`, not a string or a decimal or `None`.
- **Simpler agent implementation.** Agent code never parses or cleans LLM output — it receives ready-to-use typed objects.
- **Schema-as-documentation.** The Pydantic models define the interface contract for every agent. Reviewers can understand what an agent produces without reading its prompt.

### Negative

- **LLM calls cost more (retries).** 3 retries on a failed schema call triples the token cost for that interaction. In practice, retry rates are ~3–5% (depending on model), so the average cost increase is ~6–10%.
- **Schema rigidity.** Adding a new field to an LLM response schema requires careful migration — older deployed models may not populate it. The `version` field on `CommentaryDraft` exists specifically to handle schema evolution.
- **Latency from retries.** Each retry adds the full LLM response time. For a 10-second LLM call, 3 retries means up to 30 seconds of wall-clock time before degraded-mode fallback.

## Compliance

1. **Every agent node uses `response_model`.** Code review rejects any LLM call that does not pass a Pydantic `BaseModel` as `response_model`.
2. **No `json.loads()` on LLM output.** Search the codebase for `json.loads` where the source is an LLM response. Such patterns are banned.
3. **Retry counter is observable.** Every LLM call logs: `retry_attempt`, `validation_error` (if failed), and `final_status` (success | degraded).
4. **Degraded mode on persistent failure.** Any LLM interaction that fails schema validation after 3 retries must produce a `DegradedMode` entry in the pipeline state. Silent fallback is not allowed.
5. **Test coverage for schemas.** Every LLM response schema has a corresponding unit test that constructs a valid instance from fixture data and tests for structural completeness.
