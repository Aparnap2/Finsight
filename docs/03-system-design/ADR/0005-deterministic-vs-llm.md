# ADR-0005: Deterministic vs LLM Boundary — Separation of Concerns

**Status:** Accepted  
**Deciders:** Architecture Team  

---

## Context

FinSight must produce financial analysis that FP&A teams can act on. The fundamental architectural question is: **which parts of the pipeline use AI, and which parts use deterministic code?**

The finance industry has learned through hard experience that LLMs cannot be trusted for financial arithmetic:

- A single call to GPT-4o for "Calculate the variance between $484,464 and $472,038" can produce different results across API calls.
- Decimal place errors with large numbers are common — `$1,234,567` becomes `$123,456.70` or `$12,345,670`.
- Percentage calculations like "What is 5% of $2.1M?" produce answers ranging from `$105,000` to `$10,500,000` depending on model and prompt phrasing.

At the same time, pure deterministic systems cannot generate narrative commentary, propose causal hypotheses, or frame "what-if" scenarios. The FP&A team still needs the explanatory power that AI provides.

The challenge is defining a boundary where AI contributes its strengths without compromising the system's numerical integrity.

## Decision

**The LLM is restricted to language generation only.** All mathematical computation is deterministic Python. The boundary is absolute and enforced at multiple levels.

### The Boundary Definition

```
┌─────────────────────────────────────────────────────┐
│                   LLM DOMAIN                         │
│  • Query decomposition → ActionPlan (planner)        │
│  • Narrative rendering from assertions (commentary)  │
│  • Hypothesis generation (root cause investigation)  │
│  • Scenario parameter proposal (scenario agent)      │
│                                                      │
│  RESTRICTED TO: language, intent, structure          │
│  NEVER: arithmetic, computation, fact generation     │
└──────────────────────┬──────────────────────────────┘
                       │
              (ActionPlan + Assertions)
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│               DETERMINISTIC DOMAIN                    │
│  • Formula evaluation (FormulaRegistry)              │
│  • Variance computation (MaterialityEngine)          │
│  • KPI computation (FormulaEvaluator)                │
│  • Evidence collection (EvidenceEngine)              │
│  • Data quality checks (6 deterministic checks)      │
│  • Validation (ValidationSuite)                      │
│  • Confidence scoring (confidence.py)               │
│  • Policy evaluation (PolicyEngine)                  │
│  • Assertion verification (VerifierNode)             │
│  • Loop reflection (ReflectionNode)                  │
│                                                      │
│  GUARANTEED: 100% reproducible, Decimal precision    │
└─────────────────────────────────────────────────────┘
```

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
| Variance computation | `agents/variance/variance_agent.py` | `compute_variances()` |
| Variance percentage | `agents/variance/variance_agent.py` | `compute_variances()` |
| Materiality assessment | `finance/variance_engine/materiality.py` | `MaterialityEngine.assess()` |
| Bridge decomposition | `finance/driver_engine/bridge_analysis.py` | `decompose_bridge()` |
| KPI computation | `finance/kpi_engine/` | Formula execution |
| Scenario projection | `finance/scenario_engine/` | Deterministic projection |
| Confidence scoring | `shared/utils/confidence.py` | Weighted factor computation |
| Data quality scoring | `finance/validation/data_quality.py` | 6 deterministic checks |

### Pipeline Sequence (Enforced by Orchestrator)

```python
# The pipeline sequence enforces no LLM math
# Each deterministic step completes BEFORE any LLM step
# LLM steps are read-only: they consume deterministic outputs

pipeline_nodes = [
    "planner",      # LLM: decompose query → ActionPlan (no math)
    "retriever",    # Deterministic: gather context data
    "executor",     # Deterministic: run actions against engines
    "verifier",     # Deterministic: score assertions
    "reflection",   # Deterministic: evaluate loop outcome
]
```

### LLM Call Budget

A standard pipeline run makes exactly **two LLM calls**:

1. **Planner** — One call to decompose the query into an `ActionPlan`. Subsequent iterations may re-plan.
2. **Commentary agent** — One call (in the downstream pipeline) to render narrative from assertions.

The executor, verifier, and reflection nodes make zero LLM calls.

## Consequences

### Positive

- **Zero numerical hallucination.** Every `$` value originates from deterministic code. The LLM never computes.
- **Full audit trail.** Every number traces back to a deterministic engine call with a defined formula.
- **Deterministic output for numerical endpoints.** API endpoints like `GET /variances/{period}` return LLM-free numbers.
- **Simpler LLM prompts.** Prompts contain no arithmetic instructions, no "calculate this" steps. The LLM's task is purely linguistic.
- **LLM cost is bounded and predictable.** Approximately 2 LLM calls per pipeline run.

### Negative

- **Strict pipeline ordering.** Deterministic engines must run before any LLM step, increasing latency.
- **Engine coverage must be complete.** Every calculation the system needs must have a deterministic implementation. There is no "ask the LLM to estimate" fallback.
- **No LLM-based data imputation.** If a data point is missing, the LLM cannot estimate it. The deterministic engine must either compute from available data or flag a data gap.
- **Harder to add "quick" calculations.** A new calculation requires implementing a deterministic formula, registering it, and testing it — not just asking the LLM.

### The Scenario Agent Exception

The scenario agent is marked "hybrid" because it does two things:
1. **LLM proposes scenario parameters** (e.g., "what if revenue growth is 8% instead of 5%?")
2. **`finance/scenario_engine/` runs the projection** using deterministic formulas

The LLM never computes the projection — it only proposes input parameters. The projection engine is a deterministic calculator.

## Compliance

1. **Zero arithmetic tokens in LLM prompts.** All prompt templates are audited for arithmetic keywords: "calculate", "sum", "subtract", "multiply", "divide", "percentage", "ratio", "average", "total". None are allowed.
2. **No LLM-written numbers in commentary without evidence.** Every `$` figure must reference a pre-computed assertion. Enforced by `validate_commentary_claims()`.
3. **Finance layer is 100% deterministic.** `finance/` has no `llm_client` import and no LLM call originates from it.
4. **CI arithmetic gate.** A CI step scans all prompt template files and LLM call sites for arithmetic keywords. Matches fail the build.
5. **Count of LLM calls per pipeline run is telemetry-captured.** Unexpected increases trigger investigation.
