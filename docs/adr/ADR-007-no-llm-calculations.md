# ADR-007: No LLM Calculations — Deterministic Code Owns All Math

**Status:** Accepted  
**Date:** 2026-07-28  
**Deciders:** Architecture Team  

---

## Context

Large Language Models are not calculators. Despite advances in reasoning models, LLMs exhibit well-documented failures with arithmetic:

- **Inconsistent precision:** The same calculation (e.g., `484464 - 472038`) can produce different results in different calls, or even different results in the same call
- **Decimal place errors:** LLMs routinely misplace decimal points, especially with large numbers — `$1,234,567` becomes `$123,456.7` or `$12,345,670`
- **Percentage miscalculation:** "What is 5% of $2.1M?" produces answers ranging from `$105,000` to `$10,500,000` depending on the model and prompt phrasing
- **Unit confusion:** Mixing thousands separators, currency symbols, and number formats across locales causes parsing and generation errors
- **Rounding inconsistency:** Different models (and even the same model across calls) apply different rounding rules

For an FP&A intelligence system, any of these errors destroys trust in the entire analysis. A single miscalculated variance percentage undermines every downstream assertion.

## Decision

**The LLM never performs arithmetic.** Not for simple calculations. Not for complex ones. Never.

### What the LLM Never Does

```
❌ Addition                    "What is 484464 + 472038?"
❌ Subtraction                 "What is the difference between actual and budget?"
❌ Multiplication              "Calculate 15% of $2.1M"
❌ Division                    "What is the ratio?"
❌ Percentage computation      "What is the variance as a percentage?"
❌ Aggregation                 "What is the total of all accounts?"
❌ Averaging                   "What is the average variance across departments?"
❌ Trend computation           "What is the 3-month rolling average?"
❌ Growth rate                 "What is the YoY growth rate?"
❌ Forecast extrapolation      "If trend continues, what is next quarter's value?"
```

### What Owns the Math

| Calculation | Owner | Evidence |
|-------------|-------|----------|
| Formula evaluation | `finance/formula_engine/` | `FormulaRegistry.evaluate()` |
| Variance amount | `agents/variance/variance_agent.py` | `compute_variances()` |
| Variance percentage | `agents/variance/variance_agent.py` | `compute_variances()` |
| Materiality assessment | `finance/variance_engine/materiality.py` | `MaterialityEngine.assess()` |
| Bridge decomposition | `finance/driver_engine/bridge_analysis.py` | `decompose_bridge()` |
| KPI computation | `finance/kpi_engine/` | Formula execution |
| Scenario projection | `finance/scenario_engine/` | Deterministic projection |
| Confidence scoring | `shared/utils/confidence.py` | Weighted factor computation |
| Data quality scoring | `finance/validation/data_quality.py` | 6 deterministic checks |

### The LLM's Role (No Math)

The LLM does three things, none of which involve arithmetic:

1. **Hypothesis generation:** "Given these material variances, what could explain the difference?" (Root-cause agent)
2. **Narrative rendering:** "Arrange these validated assertions into a coherent board report." (Commentary agent)
3. **Scenario framing:** "What parameters should we adjust for a best-case projection?" (Scenario agent — the projection math is done by `finance/scenario_engine/`)

In all three cases, every number the LLM references has been pre-computed by deterministic code and provided as a string in the Context Pack. The LLM arranges, summarises, and explains — it never calculates.

### Pipeline Sequence (Enforced by Orchestrator)

```python
# agents/orchestrator.py — the pipeline sequence enforces no LLM math
# Each deterministic step completes BEFORE any LLM step
# LLM steps are read-only: they consume deterministic outputs

pipeline_steps = [
    "ingestion",            # Deterministic: read data
    "variance_detection",   # Deterministic: compute variances + materiality
    "data_quality",         # Deterministic: 6 quality checks
    "assertion_pipeline",   # Deterministic: build typed assertions
    "root_cause",           # LLM: hypothesis generation (no math)
    "commentary",           # LLM: narrative rendering (no math)
    "policy_evaluation",    # Deterministic: route based on confidence
]
```

### What About the Scenario Agent's Hybrid Role?

The scenario agent is marked as "hybrid" because it does two things:
1. **LLM proposes scenario parameters** (e.g., "what if revenue growth is 8% instead of 5%?")
2. **`finance/scenario_engine/` runs the projection** using deterministic formulas

The LLM never computes the projection — it only proposes the input parameters. The projection engine is a deterministic calculator.

## Consequences

### Positive

- **Every number is correct.** Not "probably correct" or "within tolerance" — exactly correct, every time, as verified by unit tests with oracle assertions.
- **LLM output is decorrelated from arithmetic.** If the LLM hallucinates, it hallucinates in the narrative, not in the numbers. Post-rendering claim validation catches numerical inconsistencies.
- **Simpler LLM prompts.** Prompts contain no arithmetic instructions, no "calculate this" steps, no "what percentage" sub-questions. The LLM's task is purely linguistic.
- **Deterministic output for numerical endpoints.** API endpoints like `GET /variances/{period}` return numbers computed by deterministic code — never LLM-generated values.

### Negative

- **Strict pipeline ordering.** Deterministic engines must run before any LLM step. This increases end-to-end latency compared to a parallel approach.
- **Engine coverage must be complete.** Every calculation the system needs must have a deterministic implementation. The formula registry (`finance/formula_engine/formula_registry.py`) must be maintained as the single source of truth for all financial formulas.
- **No LLM-based data imputation.** If a data point is missing, the LLM cannot estimate it. The deterministic engine must either compute from available data or flag it as a data gap.
- **Harder to add "quick" calculations.** A new "what's our burn rate?" calculation requires implementing a deterministic formula, registering it, and testing it — not just asking the LLM.

## Compliance

1. **Zero arithmetic tokens in LLM prompts.** All prompt templates are audited for arithmetic keywords: "calculate", "sum", "subtract", "multiply", "divide", "percentage", "ratio", "average", "total". None are allowed.
2. **No LLM-written numbers in `CommentaryDraft` without evidence.** Every `$` figure in a commentary section must reference a pre-computed assertion. Enforced by `validate_commentary_claims()`.
3. **Variance agent is deterministic.** The `agents/variance/variance_agent.py` module must never call an LLM. It receives data, computes, and returns. Enforced by dependency rules — `agents/variance/` has no `llm_client` import.
4. **Formula registry is the math authority.** Any new calculation must be registered in `finance/formula_engine/formula_registry.py` or an equivalent deterministic engine. No LLM is consulted for formula definition.
5. **CI arithmetic gate.** A CI step scans all prompt template files and LLM call sites for arithmetic keywords. Matches fail the build.
