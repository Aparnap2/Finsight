# ADR-0001: Layered Cognitive Runtime Architecture

**Status:** Accepted  
**Deciders:** Architecture Team  

---

## Context

Financial analysis systems face a fundamental tension: they must produce numerically accurate results that FP&A teams can trust with budget decisions, while also generating the narrative explanations, causal hypotheses, and board-ready commentary that stakeholders depend on.

Large Language Models (LLMs) are excellent at language generation and causal reasoning from unstructured context, but they exhibit well-documented failures with arithmetic — inconsistent precision, decimal place errors, percentage miscalculations, and hallucinated figures. Pure deterministic systems produce correct numbers but cannot generate narrative output.

Early FinSight prototypes attempted end-to-end LLM pipelines with mixed results:

- **Variance calculations** produced different answers on successive runs for the same inputs.
- **Monetary figures** in commentary sections frequently contradicted the source data.
- **Audit trails** were impossible to construct because the LLM could not explain how it arrived at a number.
- **Debugging failures** required sifting through opaque LLM outputs with no intermediate state.

The core insight: LLMs should decide *what* to compute and *how to present* results, but should never perform the computation itself.

## Decision

Adopt a **layered cognitive architecture** with three semantically distinct layers:

```
                     ┌─────────────────────────────────────┐
                     │         Planner (AI Layer)           │
                     │  Decomposes query → ActionPlan       │
                     │  LLM generates intents, never facts   │
                     └────────────────┬────────────────────┘
                                      │
                                      ▼
                     ┌─────────────────────────────────────┐
                     │        Executor (Deterministic)      │
                     │  Routes actions → financial engines  │
                     │  100% pure Python, zero LLM calls    │
                     │  Produces typed assertions + evidence │
                     └────────────────┬────────────────────┘
                                      │
                                      ▼
                     ┌─────────────────────────────────────┐
                     │        Verifier (Rule-Based)         │
                     │  Scores assertions against evidence  │
                     │  Checks: support, confidence, gaps   │
                     │  Produces verdict with issues list   │
                     └────────────────┬────────────────────┘
                                      │
                                      ▼
                     ┌─────────────────────────────────────┐
                     │       Reflection (Meta-Layer)        │
                     │  Evaluates pipeline outcome          │
                     │  Decides: "finalize" or "revise"     │
                     └─────────────────────────────────────┘
```

### Layer 1: Planner (AI)

The planner receives a natural-language query and produces an `ActionPlan` — an ordered list of discrete actions. The LLM is restricted to decomposing the goal into intents. It never computes, never generates numbers, and never produces financial data.

**Input:** User query (e.g., "Analyse budget variances for Q1 2026")
**Output:** `ActionPlan` with actions like `["determine_revenue_variance", "compute_key_performance_indicators", "collect_supporting_evidence"]`
**Implementation:** `finance/cognition/nodes/planner.py` — `PlannerNode`

### Layer 2: Executor (Deterministic)

The executor reads the `ActionPlan` and routes each action to the appropriate deterministic engine:

| Engine | Route Keyword | Responsibility |
|--------|--------------|----------------|
| MaterialityEngine | `variance` | Variance computation + materiality assessment |
| FormulaEvaluator | `kpi`, `performance` | KPI formula evaluation |
| EvidenceEngine | `evidence`, `supporting` | Evidence collection from data sources |
| ValidationSuite | (all actions) | Schema + domain validation |

Each action records: `status`, `latency_ms`, `retry_count`, `evidence_ids`, and `outputs`. Every monetary value uses `decimal.Decimal`.

**Implementation:** `finance/cognition/nodes/executor.py` — `ExecutorNode`

### Layer 3: Verifier (Rule-Based)

The verifier scores every assertion in the state against deterministic criteria:

- **Support level:** Is the assertion VERIFIED, PROBABLE, WEAK, or INSUFFICIENT?
- **Confidence:** Does the assertion's confidence meet the threshold (> 0.5)?
- **Evidence:** Does the assertion have supporting evidence IDs?
- **Contradictions:** Are there contradictory findings?

Produces aggregate counts and a `needs_revision` flag for the reflection layer.

**Implementation:** `finance/cognition/nodes/verifier.py` — `VerifierNode`

## Consequences

### Positive

- **Zero hallucination on calculations.** The LLM never performs arithmetic. Every `$` value originates from deterministic code.
- **LLM cost reduced.** The planner makes approximately one LLM call per pipeline run. No LLM calls for computation, validation, or verification.
- **Full traceability.** Every action records latency, status, evidence, and outputs. The telemetry system captures structured traces for every run.
- **Testable by layer.** Each layer can be unit tested independently. The executor has oracle tests; the verifier has assertion-scoring tests.
- **Degraded-mode resilience.** When an action fails, the executor records `ActionStatus.FAILED` and continues. The verifier catches the gap; reflection decides whether to retry.

### Negative

- **Pipeline ordering is strict.** The executor must run before the verifier, which must run before reflection. This limits parallelism.
- **More code to maintain.** Three layers with explicit interfaces instead of an end-to-end LLM call.
- **Engine coverage must be complete.** Every computation the system needs must have a deterministic implementation. There is no "ask the LLM to estimate" fallback.
- **Interface contracts are critical.** `NodeResult`, `ActionPlan`, and `Assertion` become shared contracts across all layers.

## Compliance

1. **No LLM call originates from `finance/cognition/nodes/executor.py` or `verifier.py`.** The LLM boundary is strictly at the planner.
2. **Every action records `latency_ms` and `evidence_ids`.** The executor must produce these for every action. Missing evidence IDs cause verifier failures.
3. **`ActionStatus` transitions follow a strict state machine.** `PENDING → SUCCESS | FAILED | SKIPPED`. No other transitions.
4. **Verifier checks are deterministic.** No LLM scoring, no probabilistic models. All checks are rule-based comparisons against thresholds.
5. **CI gate validates layer isolation.** Any PR that adds an LLM import to the executor or verifier modules is automatically rejected.
