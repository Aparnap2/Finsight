# ADR-006: Evidence-Backed AI — Every Claim References Supporting Evidence

**Status:** Accepted  
**Date:** 2026-07-28  
**Deciders:** Architecture Team  

---

## Context

Financial commentary without source attribution is worthless. When an FP&A analyst reads "Revenue declined due to volume loss in the Enterprise segment," they need to know: which account? which period? what's the source? how confident is this claim?

In traditional financial analysis, every number in a commentary has a cell reference. In AI-generated analysis, claims can be fabricated (hallucinated), sourced from the wrong period, or based on stale data. Without evidence tracking, the system produces output that cannot be audited, trusted, or actioned.

The existing codebase already models evidence structures:
- `EvidenceItem` (`shared/models/state.py`): `source_table`, `record_id`, `field`, `value`, `period`, `description`
- `Assertion` (`shared/models/assertions.py`): `evidence_ids`, `support_level`, `confidence`, `contradictions`, `missing_evidence`, `source`

These models are defined but must be enforced as the **only** way claims are made.

## Decision

**Every claim produced by the system — whether by deterministic engines or LLM agents — must reference supporting evidence.** No claim is valid without evidence.

### Evidence Model

Every `EvidenceItem` captures:

```python
class EvidenceItem(BaseModel):
    source_table: str       # e.g., "gl_accounts", "budget_lines", "trial_balance"
    record_id: str          # Primary key of the source record
    field: str              # e.g., "amount", "variance_pct"
    value: Decimal          # Exact value from source
    period: str             # Fiscal period identifier
    description: str = ""   # Human-readable context
```

### Assertion → Evidence Chain

Every `Assertion` (the atomic unit of truth) carries:

```python
class Assertion(BaseModel):
    id: str
    type: AssertionType     # NUMERIC | COMPARATIVE | CAUSAL | HYPOTHESIS | ACTION
    text: str               # The claim itself
    value: Decimal | None   # Monetary value (if applicable)
    evidence_ids: list[str] # References to EvidenceItem IDs
    support_level: SupportLevel  # VERIFIED | PROBABLE | WEAK | INSUFFICIENT
    confidence: float       # 0.0–1.0 deterministic confidence
    contradictions: list[str]    # Evidence that contradicts this claim
    missing_evidence: list[str]  # What evidence would strengthen this
    source: str             # "deterministic" | "llm_analysis" | "human"
```

### Rules

1. **NUMERIC assertions require at least one `EvidenceItem`.** A monetary claim without a source record ID is invalid.
2. **COMPARATIVE assertions require a candidate set of ≥2 `EvidenceItem` values.** "Largest variance" must be provable by sorting the deterministic set.
3. **CAUSAL assertions are never `VERIFIED`.** They are at most `PROBABLE`, and only when backed by ≥2 evidence classes (driver-tree decomposition, trend analysis, operational data).
4. **HYPOTHESIS assertions are explicitly labelled.** The root-cause agent's alternative hypotheses carry `type=HYPOTHESIS` and `support_level=WEAK`. The commentary agent is prohibited from upgrading hypotheses to facts.
5. **ACTION assertions must cite a validated CAUSAL or NUMERIC assertion.** An action without a root cause is not permitted.
6. **Evidence is immutable.** Once created, an `EvidenceItem` is never modified. Updates create new evidence items.
7. **Evidence has no LLM provenance.** No `EvidenceItem` can have `source_table="llm"`. Evidence always traces back to a deterministic data source.

### Confidence Score Computation

Confidence is deterministic, not LLM-assigned. The `shared/utils/confidence.py` module computes confidence based on:

| Factor | Weight | Source |
|--------|--------|--------|
| Support level | 0.4 | `VERIFIED=1.0`, `PROBABLE=0.7`, `WEAK=0.4`, `INSUFFICIENT=0.0` |
| Evidence count | 0.2 | ≥3 items = 1.0, 2 = 0.7, 1 = 0.4, 0 = 0.0 |
| Evidence diversity | 0.2 | ≥2 source tables = 1.0, 1 = 0.5 |
| Data quality | 0.1 | `DataQualityReport.overall_score` |
| Contradictions | 0.1 | None = 1.0, any = 0.3 |

### Evidence Sources

| Source Type | Examples | Evidence Generator |
|-------------|----------|--------------------|
| **Ledger** | `trial_balance`, `gl_accounts` | `ingestion/ingestion_agent.py` |
| **Budget** | `budget_lines` | `ingestion/ingestion_agent.py` |
| **Computed** | Variance, KPI, Bridge | `variance_engine/`, `kpi_engine/`, `driver_engine/` |
| **Tool result** | Headcount, Vendor, RAG | `shared/utils/tools/` |
| **Human** | Manual override, context note | API endpoint `POST /pipeline/{id}/review` |

LLM agents **cannot** create evidence — they can only reference evidence created by deterministic sources.

## Consequences

### Positive

- **Fully auditable claims.** Every number in a commentary has a traceable source record. An FP&A analyst can click a number and see where it came from.
- **Confidence that means something.** Confidence is not an LLM's self-assessment ("I am 90% sure") — it's a deterministic function of evidence quality, diversity, and consistency.
- **Contradiction-aware analysis.** If evidence points in different directions, the system surfaces contradictions explicitly rather than picking one narrative.
- **Hallucination resistance.** Because every claim must cite evidence, an LLM agent cannot invent a number without the post-rendering claim validator catching the unsubstantiated `$` figure.

### Negative

- **Storage overhead.** Every evidence item is stored. For a pipeline run covering 500 accounts across 12 periods, evidence storage can reach tens of thousands of records.
- **Enforcement complexity.** Ensuring no assertion is created without evidence requires runtime checks in the assertion pipeline and code review discipline.
- **LLM agent prompt engineering burden.** The root-cause agent prompt must instruct the LLM to cite evidence IDs explicitly in its output — and the structured output schema must enforce `evidence_ids` as a required field.
- **Evidence for "negative" findings.** Proving the absence of something (e.g., "no unusual activity") requires evidence that a search was performed. The system handles this with tool results that explicitly record "no matches found."

## Compliance

1. **Every `Assertion` has non-empty `evidence_ids`.** The assertion pipeline validates this at construction. Any assertion without evidence is discarded.
2. **LLM agents return evidence IDs, not evidence values.** The LLM cannot return an `EvidenceItem` — only references to existing evidence via IDs. This prevents LLM fabrication of evidence.
3. **Commentary claim validator cross-checks citations.** After the LLM renders commentary, `validate_commentary_claims()` extracts every `$` figure and checks it against the evidence set. Unmatched figures produce a validation failure.
4. **Evidence immutability is tested.** Unit tests verify that `EvidenceItem` objects cannot be mutated after creation (frozen config).
5. **Confidence computation is deterministic.** The `confidence.py` module has oracle tests: given fixed evidence, it always produces the same confidence score.
