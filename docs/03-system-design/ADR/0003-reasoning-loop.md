# ADR-0003: Iterative Reasoning Loop — Plan → Execute → Verify → Reflect

**Status:** Accepted  
**Deciders:** Architecture Team  

---

## Context

Complex financial questions rarely yield a correct answer on the first attempt. An initial plan may:

- **Miss accounts** that should be analysed (e.g., forgets to check SG&A when revenue is over budget).
- **Misprioritise intents** (e.g., computes KPIs before collecting evidence needed for those KPIs).
- **Produce low-confidence assertions** that require re-execution with better input data.
- **Encounter tool failures** (e.g., a data source is temporarily unavailable).

A single-pass pipeline — plan once, execute once, return results — cannot recover from these failures. The system would produce incomplete or incorrect output with no mechanism for self-correction.

Additionally, the LLM planner is non-deterministic. Different calls may produce different `ActionPlan` structures for the same query. Without iteration, the system cannot detect or correct a poor plan.

## Decision

The cognitive runtime runs an **iterative loop** with a hard iteration limit:

```
                    ┌──────────────────┐
                    │     Planner       │
                    │  (AI: decompose)  │
                    └────────┬─────────┘
                             │ ActionPlan
                             ▼
                    ┌──────────────────┐
                    │    Retriever      │
                    │  (gather data)    │
                    └────────┬─────────┘
                             │ Evidence
                             ▼
                    ┌──────────────────┐
                    │    Executor       │
                    │  (deterministic)  │
                    └────────┬─────────┘
                             │ Assertions + traces
                             ▼
                    ┌──────────────────┐
                    │    Verifier       │
                    │  (rule-based)     │
                    └────────┬─────────┘
                             │ Scores + issues
                             ▼
                    ┌──────────────────┐
                    │   Reflection      │
                    │  (evaluate loop)  │
                    └────────┬─────────┘
                             │ "revise" or "finalize"
                             │
              ┌──────────────┘
              ▼
     ┌──────────────┐      ┌──────────────────┐
     │  "finalize"   │ ──→ │  Telemetry +      │
     │               │     │  HarnessResult    │
     └──────────────┘      └──────────────────┘
              │
     ┌──────────────┐
     │  "revise"     │ ──→ Back to Planner (if iterations remain)
     └──────────────┘
```

### Key Parameters

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `max_iterations` | 5 | Hard cap on loop iterations |
| `CONFIDENCE_THRESHOLD` | 0.7 | Minimum confidence to finalize |
| `MIN_CONFIDENCE_THRESHOLD` | 0.5 | Verifier threshold for low-confidence flag |

### When the Loop Revises

Reflection triggers a "revise" decision when:

1. **Validation checks failed:** The validation report shows failed checks.
2. **Unsupported assertions exist:** Any assertions are WEAK or INSUFFICIENT.
3. **Missing evidence:** No evidence items collected by the executor.
4. **Action verification failed:** A completed action has no outputs or evidence.
5. **Coverage gaps:** The action plan is missing expected analyses (e.g., no KPI or variance intents).
6. **Overall confidence below threshold:** `overall_confidence < 0.7`.

The loop continues until `loop_decision == "finalize"` or `iteration_count >= max_iterations`.

### Loop Implementation

```python
class ReasoningHarness:
    """Orchestrates the cognitive reasoning loop."""

    def __init__(self, registry, max_iterations=5, telemetry_dir=None):
        self._registry = registry or NodeRegistry()
        self._max_iterations = max_iterations
        self._telemetry = ReasoningTelemetry(output_dir=telemetry_dir or ".reasoning_traces")

    def run(self, state: ReasoningState) -> HarnessResult:
        pipeline = self._registry.get_pipeline()

        while state.iteration_count < min(state.max_iterations, self._max_iterations):
            state.iteration_count += 1

            for node_name in pipeline:
                node = self._registry.get(node_name)
                result = node.execute(state)
                # Records trace entry, aggregates assertions, updates state

            if state.loop_decision == "finalize":
                break

        self._telemetry.capture(run_id=run_id, state=state)
        return HarnessResult(state=state, run_id=run_id, success=True)
```

### Telemetry Capture

Every pipeline run records a structured telemetry trace:

```json
{
  "run_id": "run_a1b2c3d4e5f6",
  "step_count": 12,
  "iteration_count": 2,
  "overall_confidence": 0.85,
  "loop_decision": "finalize",
  "trace": [
    {"node_name": "planner", "execution_order": 1, "confidence": 0.5},
    {"node_name": "retriever", "execution_order": 2, "confidence": 0.8},
    {"node_name": "executor", "execution_order": 3, "confidence": 0.9},
    {"node_name": "verifier", "execution_order": 4, "confidence": 0.85},
    {"node_name": "reflection", "execution_order": 5, "confidence": 0.85, "result": {"loop_decision": "revise"}},
    {"node_name": "planner", "execution_order": 6, "confidence": 0.6},
    ...
  ],
  "assertions": [...],
  "plan_history": [...]
}
```

## Consequences

### Positive

- **Self-correcting.** The system recovers from plan failures and low-confidence assertions by revising and re-executing.
- **Hard termination prevents infinite loops.** The `max_iterations` cap ensures bounded execution.
- **Traceable iteration history.** `plan_history` records every plan version. Telemetry reports the full iteration tree.
- **Graceful degradation.** When iterations are exhausted with unresolved issues, the system finalizes with what it has rather than failing entirely.

### Negative

- **Increased latency.** Each iteration runs all 5 pipeline nodes. Two iterations = 10 node executions.
- **Non-deterministic iteration count.** Planner improvements may change the average iteration count, making latency unpredictable.
- **Plan history drift.** A revised plan may differ substantially from the original. Comparing plan versions requires semantic analysis.
- **Potential for oscillation.** The planner could produce a plan, fail verification, and produce a near-identical plan again. The current loop does not detect plan stability.

## Compliance

1. **`max_iterations` is enforced at two levels.** The `ReasoningState.max_iterations` field and the `ReasoningHarness._max_iterations` parameter. Both must agree.
2. **`loop_decision` is set only by the reflection node.** No other node modifies this field.
3. **Telemetry captures every iteration.** A run with 0 iterations (if `max_iterations=0` is set) still produces a telemetry trace.
4. **`plan_history` is append-only.** Previous plans are never modified. New iterations append to the list.
5. **CI tests verify iteration behaviour.** At least one test dataset expects `max_replans > 0` to confirm the loop mechanism works.
