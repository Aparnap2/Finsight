# ADR-0002: Structured Assertion Model — Typed, Scored, Traced

**Status:** Accepted  
**Deciders:** Architecture Team  

---

## Context

Financial analysis produces claims. "Revenue increased 7.14%." "Marketing is 25% under budget." "The variance is driven by volume decline in Enterprise." In a manual FP&A process, each claim has a cell reference — the analyst can point to the spreadsheet row that produced it.

In an AI-driven system, claims can be:

- **Fabricated:** The LLM invents a number that looks plausible but has no source.
- **Misattributed:** The number is real but sourced from the wrong period or account.
- **Overconfident:** A weak hypothesis is presented as a verified fact.
- **Contradictory:** Two claims in the same report conflict, but the system doesn't flag it.

The existing codebase already had partial models — `EvidenceItem` in `shared/models/state.py` and `Assertion` in `shared/models/assertions.py` — but these were not enforced as the *only* way to make claims. Raw data could bypass the assertion pipeline and reach the commentary agent directly, making the system vulnerable to hallucination.

The requirement emerged: every claim must carry its provenance, confidence, and support level. No claim is valid without evidence.

## Decision

Every truth-claim in the system must be a **typed, scored, and traced `Assertion` object**. Unstructured claims are not permitted.

### The Assertion Model

```python
class Assertion(BaseModel):
    id: str                          # Unique identifier (e.g., "ast-001")
    type: AssertionType              # NUMERIC | COMPARATIVE | CAUSAL | HYPOTHESIS | ACTION
    text: str                        # Human-readable claim
    value: Decimal | None            # Monetary value (if applicable)
    evidence_ids: list[str]          # References to EvidenceItem IDs
    support_level: SupportLevel      # VERIFIED | PROBABLE | WEAK | INSUFFICIENT
    confidence: float                # 0.0–1.0 (deterministic, not LLM-assigned)
    contradictions: list[str]        # Evidence that conflicts with this claim
    missing_evidence: list[str]      # What evidence would strengthen this claim
    source: str                      # "deterministic" | "llm_analysis" | "human"
    max_allowed_action: str = "route_for_review"  # Policy constraint
```

### Five Assertion Types

| Type | Example | Max Support Level | Evidence Requirement |
|------|---------|-------------------|---------------------|
| **NUMERIC** | "Revenue variance is $100,000" | VERIFIED | At least 1 `EvidenceItem` |
| **COMPARATIVE** | "Marketing has the largest variance" | VERIFIED | Candidate set of ≥2 values |
| **CAUSAL** | "Decline driven by volume loss" | PROBABLE | ≥2 evidence classes |
| **HYPOTHESIS** | "Possibly due to FX impact" | WEAK | At least 1 supporting indicator |
| **ACTION** | "Recommend reducing cloud spend" | N/A | Cites a validated CAUSAL or NUMERIC assertion |

### Support Levels

| Level | Meaning | Numeric Score | Max Confidence Cap |
|-------|---------|---------------|-------------------|
| VERIFIED | Proven by direct evidence | 1.0 | 1.0 |
| PROBABLE | Strongly indicated but not directly proven | 0.7 | 0.85 |
| WEAK | Some evidence, alternative explanations remain | 0.4 | 0.6 |
| INSUFFICIENT | Cannot be supported with available data | 0.0 | 0.3 |

### Deterministic Confidence Computation

Confidence is computed by `shared/utils/confidence.py` as a weighted function — never assigned by the LLM:

| Factor | Weight | Logic |
|--------|--------|-------|
| Support level | 0.4 | VERIFIED=1.0, PROBABLE=0.7, WEAK=0.4, INSUFFICIENT=0.0 |
| Evidence count | 0.2 | ≥3 items=1.0, 2=0.7, 1=0.4, 0=0.0 |
| Evidence diversity | 0.2 | ≥2 source tables=1.0, 1=0.5 |
| Data quality | 0.1 | `DataQualityReport.overall_score` |
| Contradictions | 0.1 | None=1.0, any=0.3 |

### The Evidence Contract

Every `EvidenceItem` is immutable (Pydantic `frozen=True`) and sourced from deterministic data only:

```python
class EvidenceItem(BaseModel, frozen=True):
    source_table: str    # e.g., "gl_accounts", "budget_lines"
    record_id: str       # Primary key of the source record
    field: str           # e.g., "amount", "variance_pct"
    value: Decimal       # Exact value from source
    period: str          # Fiscal period identifier
    description: str     # Human-readable context
```

**Rule:** No `EvidenceItem` can have `source_table="llm"`. Evidence always traces to a deterministic source.

## Consequences

### Positive

- **Every claim traceable to evidence.** From commentary to assertion to evidence item to source record. Full audit trail.
- **Hallucination resistance.** The post-rendering claim validator cross-checks every `$` figure. Unmatched figures produce validation failures.
- **Confidence that reflects evidence quality.** Not an LLM's self-assessment — a deterministic function of evidence depth and diversity.
- **Contradiction-aware.** The `contradictions` field surfaces conflicting evidence explicitly rather than hiding it.
- **Policy-enforceable.** `max_allowed_action` gates how each assertion can be used downstream.

### Negative

- **Storage overhead.** A pipeline run covering 500 accounts across 12 periods can produce tens of thousands of evidence records.
- **Enforcement complexity.** Ensuring no assertion is created without evidence requires runtime checks in the assertion pipeline and code review discipline.
- **LLM agent prompt engineering.** The root-cause agent prompt must instruct the LLM to cite evidence IDs explicitly — and the structured output schema must enforce `evidence_ids` as required.
- **Evidence for "negative" findings.** Proving absence (e.g., "no unusual activity") requires tool results that explicitly record "no matches found."

## Compliance

1. **Every `Assertion` has non-empty `evidence_ids`.** The assertion pipeline validates this at construction. Any assertion without evidence is discarded.
2. **LLM agents return evidence IDs, not evidence values.** The LLM cannot return an `EvidenceItem` — only references to existing evidence. This prevents LLM fabrication of evidence.
3. **Causal assertions are never `VERIFIED`.** They are at most `PROBABLE`, only when backed by ≥2 evidence classes.
4. **Confidence computation is deterministic.** The `confidence.py` module has oracle tests: given fixed evidence, it always produces the same score.
5. **Evidence immutability is tested.** Unit tests verify that `EvidenceItem` objects cannot be mutated after creation (frozen config).
