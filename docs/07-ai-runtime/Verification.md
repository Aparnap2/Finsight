# Verification

## Purpose

The verifier evaluates every assertion produced during execution and scores it against its supporting evidence. This is not an LLM judgment — it is a deterministic rule-based scoring system.

## Assertion Model

```python
class Assertion(BaseModel):
    id: str
    type: AssertionType  # numeric, comparative, causal, hypothesis, action
    text: str
    value: Decimal | None
    evidence_ids: list[str]
    support_level: SupportLevel  # verified, probable, weak, insufficient
    confidence: float
    contradictions: list[str]
    missing_evidence: list[str]
    source: str  # deterministic, llm_analysis, human
```

## Scoring Criteria

The verifier checks:

1. **Evidence exists**: Does the assertion have at least one `evidence_id`?
2. **Support level**: Is the evidence sufficient to support the assertion type?
3. **Contradictions**: Are there any contradictions recorded?
4. **Confidence threshold**: Does the confidence score meet the minimum?
5. **Source reliability**: Is the source deterministic or LLM-derived?

### Support Level Assignment

| Condition | Support Level |
|-----------|--------------|
| Direct evidence from deterministic engine | verified |
| Indirect evidence, plausible | probable |
| Single source, low confidence | weak |
| No evidence or contradictory | insufficient |

## Verification Output

The verifier updates each assertion's `support_level` and `confidence` field. It also records any `missing_evidence` paths and `contradictions` discovered. These fields are used by the reflection node to decide whether the plan needs revision.
