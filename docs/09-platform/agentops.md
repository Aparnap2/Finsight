# AgentOps — Orchestration Layer

**Discipline:** AgentOps  
**Boundary:** Orchestration, not AI  
**Code locations:** `finance/cognition/`, `finance/evaluation/`

---

## Purpose

AgentOps is the orchestration layer of the FinSight Finance Operations OS. It owns **the who, the when, and the what** of every analysis run — not the *how*. AgentOps decides what to compute, which engine to call, whether to retry a failed action, when to request a human-in-the-loop, and whether the output is good enough to finalise. It does not own model inference, data pipelines, or security controls. Those belong to LLMOps, DataOps, and DevSecOps respectively.

Concretely: AgentOps is `ReasoningHarness` in `finance/cognition/harness.py`. It takes a natural-language query and drives a five-node pipeline — Planner → Retriever → Executor → Verifier → Reflection — with an iteration loop (max 5), per-action retry logic, escalation gates, and structured telemetry dumped to `.reasoning_traces/`.

---

## What AgentOps Decides

| Decision | Owned By | Why Not Another Layer |
|---|---|---|
| What actions to take | **Planner node** (AgentOps) | Planning is orchestration, not generation. The LLM decomposes goals—it never computes numbers. LLMOps owns the model; AgentOps owns the plan. |
| Which engine to call per action | **Executor node** (AgentOps) | Keyword-based dispatch (`variance` → `MaterialityEngine`, `kpi` → `FormulaEvaluator`, etc.) is a routing decision, not a model or data decision. |
| Retry a failed action? | **Executor node** (AgentOps) | `Action.retry_count` is a runtime field. AgentOps decides when to retry based on failure mode. MLOps owns the engine being retried. |
| Request human-in-the-loop? | **Reflection node** (AgentOps) | Policy enforcement (`max_allowed_action: escalate`) triggers escalation. The escalation channel is AgentOps; the human review is a human process. |
| Notify finance / open ERP transaction? | **Reflection node** → **escalation** | AgentOps decides *whether* to act. The actual notification or ERP integration is handled by the integration layer (not yet built). |
| Finalize or revise output? | **Reflection node** (AgentOps) | Based on confidence threshold (≥ 0.7), gap analysis, and remaining iterations. This is a workflow decision, not a model quality decision. |
| Abort the workflow? | **ReasoningHarness** (AgentOps) | If `loop_decision` remains "continue" after max iterations, the harness stops the run and marks it incomplete. Safety valve, not model behaviour. |
| What data to retrieve? | **Retriever node** (AgentOps) | The ActionPlan drives data selection. The retriever decides which spreadsheet ranges to read. DataOps owns the data's correctness; AgentOps owns the retrieval scope. |
| Is evidence sufficient? | **Verifier node** (AgentOps) | Rule-based checks against `SupportLevel`, `confidence`, and `evidence_ids`. Deterministic scoring, no AI involved. LLMOps has no say here. |

---

## Key Capabilities

- **Workflow planning (ActionPlan decomposition).** The Planner node translates a natural-language query into a structured `ActionPlan` — a list of `Action` objects with `objective`, `status`, `inputs`, `outputs`, `tool`, `latency_ms`, `retry_count`, and `evidence_ids`. Every action is typed through `finance/cognition/state/action.py`. No free text leaks from the planner.

- **Five-node pipeline orchestration.** `ReasoningHarness.run()` walks the registered pipeline in order: Planner → Retriever → Executor → Verifier → Reflection. Each node implements the `CognitiveNode` protocol (`finance/cognition/state/node.py`): `execute(ReasoningState) -> NodeResult`. The pipeline is configurable via `NodeRegistry.configure_pipeline()`.

- **Iteration loop with max-iterations guard.** After the Reflection node emits a `loop_decision`, the harness either loops back ("revise") or terminates ("finalize"). Capped at `min(state.max_iterations, self._max_iterations)` — default 5. Prevents runaway workflows.

- **State management via `ReasoningState`.** A single Pydantic model (`finance/cognition/state/models.py`) carries the query, execution `trace` (ordered `TraceEntry` records), aggregated `assertions`, a `context` dict for cross-node data, `action_plan`, `plan_history` (tracking all iterations), `overall_confidence`, and `loop_decision`. Immutable trace entries; mutable context.

- **Per-action retry with telemetry.** Each `Action` carries a `retry_count` field. The `ExecutorNode` catches exceptions per action, marks `ActionStatus.FAILED`, and records the error in the action trace. Downstream nodes (Verifier, Reflection) can detect failures and trigger a revise iteration. The `RetryRate` metric tracks retries across the run.

- **Human-in-the-loop escalation gates.** Policy assertions carry a `max_allowed_action` field (`route_for_review`, `block`, `escalate`). The `ReflectionNode` inspects these when making its loop decision. Escalation is signalled through the state; the integration layer (future) consumes it.

- **Long-running workflow tracking via plan_history.** `ReasoningState.plan_history` appends the ActionPlan at each iteration. `ReasoningTelemetry.capture()` serialises the full plan history into the trace JSON. This enables post-hoc analysis of planning drift across revisions.

- **Structured telemetry to `.reasoning_traces/`.** Every `ReasoningHarness.run()` call writes a JSON file to a configurable output directory (default `.reasoning_traces/`). The trace includes `run_id`, `timestamp`, `step_count`, `iteration_count`, `overall_confidence`, `loop_decision`, the ordered `trace` of node executions, all `assertions`, `context_keys`, `action_traces`, and the full `plan_history`. Debuggable by file inspection.

- **Configurable pipeline and registry.** `NodeRegistry` (`finance/cognition/registry.py`) allows registering custom nodes, reordering the pipeline, or injecting engine dependencies (e.g., `MaterialityEngine`, `FormulaEvaluator`, `EvidenceEngine`, `ValidationSuite`). The default pipeline is `planner → retriever → executor → verifier → reflection`.

- **Evaluation harness for regression testing.** `EvaluationRunner` (`finance/evaluation/runner.py`) runs metrics against golden datasets. It accepts `HarnessResult` directly, computes runtime metrics and business metrics separately, and produces a structured `EvaluationReport`.

---

## Implementation Map

| Component | File | Responsibility |
|---|---|---|
| ReasoningHarness | `finance/cognition/harness.py` | Top-level orchestrator; iteration loop; telemetry capture |
| ReasoningState | `finance/cognition/state/models.py` | Central shared state; trace recording; assertion aggregation |
| ActionPlan / Action | `finance/cognition/state/action.py` | Action data model with status (PENDING/SUCCESS/FAILED/SKIPPED), latency, retries, evidence |
| CognitiveNode protocol | `finance/cognition/state/node.py` | Contract: `execute(ReasoningState) -> NodeResult` |
| NodeResult | `finance/cognition/state/node.py` | Structured output: state_updates, new_assertions, confidence, message |
| NodeRegistry | `finance/cognition/registry.py` | Node lifecycle; pipeline ordering; engine injection |
| PlannerNode | `finance/cognition/nodes/planner.py` | Query → ActionPlan decomposition (keyword-based) |
| RetrieverNode | `finance/cognition/nodes/retriever.py` | Data retrieval via SpreadsheetProvider |
| ExecutorNode | `finance/cognition/nodes/executor.py` | Action dispatch to deterministic engines; action traces |
| VerifierNode | `finance/cognition/nodes/verifier.py` | Assertion scoring; action verification |
| ReflectionNode | `finance/cognition/nodes/reflection.py` | Gap analysis; loop_decision (finalize / revise) |
| ToolRouterNode | `finance/cognition/nodes/tool_router.py` | Legacy; replaced by ExecutorNode (maintained for compat) |
| ReasoningTelemetry | `finance/cognition/telemetry.py` | Structured trace capture to `.reasoning_traces/{run_id}.json` |
| EvaluationRunner | `finance/evaluation/runner.py` | Golden-dataset evaluation; metric computation |
| Evaluation metrics | `finance/evaluation/metrics.py` | 12 metric classes (runtime + business) |

---

## Pipeline Flow

```
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                         ReasoningHarness.run()                          │
  │                                                                          │
  │  ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌────────┐   ┌──────────┐ │
  │  │Planner  │──▶│Retriever │──▶│Executor  │──▶│Verifier│──▶│Reflection│ │
  │  └─────────┘   └──────────┘   └──────────┘   └────────┘   └──────────┘ │
  │       │              │              │             │             │        │
  │       ▼              ▼              ▼             ▼             ▼        │
  │   ActionPlan    Raw data       Engine        Assertion     loop_decision│
  │   (intents)     (spreadsheet)  results +     scores +      (finalize /  │
  │                                assertions    action_verif.  revise)     │
  │                                                                          │
  │          ┌────────────────────────────────────────────────────┐          │
  │          │  loop_decision == "revise"  AND  iterations < max? │          │
  │          └──────────────┬─────────────────────────────────────┘          │
  │                         │ YES                                           │
  │                         └─────▶ back to Planner (new iteration)          │
  │                         │ NO (finalize or max iterations)                │
  │                         ▼                                                │
  │                  Telemetry.capture()                                     │
  │                  return HarnessResult                                    │
  └─────────────────────────────────────────────────────────────────────────┘
```

### Stage-by-stage

**1. Planner** (`finance/cognition/nodes/planner.py`)

Receives the raw `query` from `ReasoningState`. Parses for keywords (variance, kpi, evidence) and produces an `ActionPlan` — an ordered list of `Action` objects. Each action carries an `objective` string that determines which engine the executor will route to.

*Keyword → action mapping:*
- `"variance"` in query → `determine_revenue_variance`
- `"kpi"` or `"performance"` → `compute_key_performance_indicators`
- `"evidence"` or `"support"` → `collect_supporting_evidence`
- No match → default plan covering all three

Output is written to `state.action_plan` and `state.context["plan"]`. Confidence is a static 0.5 (placeholder for future LLM-based planning).

**2. Retriever** (`finance/cognition/nodes/retriever.py`)

Reads the ActionPlan to determine what data to fetch. When a `SpreadsheetProvider` is injected, it reads the configured range (`spreadsheet_id`, `range` from `state.context`). Without a provider, returns stub data (empty variances, KPIs, evidence items) for backward compatibility.

Populates `state.context["sources"]` with the data origin (e.g., `gl_accounts`, `budget`, `forecast`, `spreadsheet:default`). Confidence: 0.8.

**3. Executor** (`finance/cognition/nodes/executor.py`)

The heart of the deterministic runtime. Iterates over every action in the ActionPlan and dispatches based on keyword matching in the action objective:

| Objective contains | Engine | Produces |
|---|---|---|
| `"variance"` | `MaterialityEngine` | Materiality assessments → `Assertion` objects with `support_level=VERIFIED` |
| `"kpi"` or `"performance"` | `FormulaEvaluator` | KPI results → `Assertion` objects with `support_level=VERIFIED`, source `deterministic` |
| `"evidence"` or `"supporting"` | `EvidenceEngine` | Evidence items → linked via `evidence_ids` |
| (any action) | `ValidationSuite` | Validation results → failed validators create `Assertion` objects with `support_level=INSUFFICIENT` |

Each action records: `action_id`, `objective`, `tool` name, `status`, `latency_ms` (from `perf_counter`), `retries`, `assertion_count`, `evidence_count`, `validation_status`, and `error` (on failure). Exceptions are caught per action — one failing action does not crash the pipeline.

Output: `state.context["action_traces"]` and `state.context["plan_status"]` (all_succeeded / some_failed / no_actions). New assertions are appended to `state.assertions`.

**4. Verifier** (`finance/cognition/nodes/verifier.py`)

Scans every assertion in the state and classifies:
- **Low confidence:** `confidence < 0.5`
- **Unsupported:** `support_level in (WEAK, INSUFFICIENT)`
- **Missing evidence:** non-empty `missing_evidence`
- **Contradicted:** non-empty `contradictions`

Also verifies each action in the ActionPlan: an action passes if `status == SUCCESS` AND it has either outputs or evidence.

Aggregate outputs: `needs_revision` (boolean), `overall_confidence` (mean across assertions), counts of verified / low-confidence / unsupported / missing-evidence / contradicted assertions. Action verifications are written to `state.context["action_verifications"]`.

**5. Reflection** (`finance/cognition/nodes/reflection.py`)

Performs gap analysis against multiple axes:

- **Validation failures:** checks `validation_report.failed_count > 0`
- **Unsupported assertions:** counts those with `WEAK` or `INSUFFICIENT` support
- **Missing evidence:** checks `missing_evidence` lists
- **Contradictions:** checks `contradictions` lists
- **Evidence existence:** warns when no evidence items were collected
- **Action verification:** flags actions that did not pass
- **Plan coverage:** warns if the plan lacks KPI or variance analysis

Decision logic:
- No gaps AND `overall_confidence >= 0.7` → **finalize**
- Gaps exist AND iterations remain → **revise**
- No iterations remaining → **finalize** (forced termination)

Output: `loop_decision` (finalize / revise), `gaps` list, `reflection_confidence`.

---

## Decision Ownership

| Decision | Node | Logic | Threshold / Criteria |
|---|---|---|---|
| What actions to take | Planner | Keyword-based decomposition from query | Static (future: LLM-based) |
| Which engine to route to | Executor | Objective keyword matching | `"variance"` → MaterialityEngine, etc. |
| Retry a failed action | Executor | Catches exception, sets `FAILED` status, increments `retry_count` | Per-action; no global retry limit |
| Mark action succeeded | Executor | Successful engine invocation | Engine returns without exception |
| Finalize or revise | Reflection | Gap count + confidence score | `overall_confidence >= 0.7` AND zero gaps → finalize |
| Escalate to human | Reflection | Policy assertion `max_allowed_action` | `"escalate"` or `"block"` in assertion |
| Abort workflow | ReasoningHarness | Max-iterations guard | `iteration_count >= max(max_iterations, 5)` |
| Accept output | ReasoningHarness | `loop_decision == "finalize"`, telemetry written | Always writes telemetry regardless |

---

## Integration with Other Layers

```
                    AgentOps
                        │
          ┌─────────────┼─────────────┐
          │             │             │
          ▼             ▼             ▼
       LLMOps         MLOps         DataOps
    (PlannerNode)  (RiskProvider)  (Validated data)
```

**AgentOps → LLMOps.** The **PlannerNode** is the sole LLM touchpoint in the pipeline. It consumes an LLM-generated ActionPlan (currently keyword-based; planned LLM integration via `finance/cognition/nodes/planner.py`). AgentOps invokes the model, but the model does not escape the planner boundary. No other node calls an LLM.

**AgentOps → MLOps.** The **ExecutorNode** routes the `variance` action to `MaterialityEngine` (`finance/variance_engine/materiality.py`). This is a deterministic engine that MLOps may supplement with ML-based risk models in future. The boundary: AgentOps calls the engine; MLOps owns the engine's correctness and performance characteristics.

**AgentOps → DataOps.** The **RetrieverNode** fetches raw data via `SpreadsheetProvider` (`finance/integration/spreadsheet_provider.py`). DataOps owns the data's freshness, schema conformance, and source connectivity. AgentOps owns the retrieval scope — what ranges to read, which accounts to pull. The `ValidationSuite` run by the executor also exercises DataOps' validation rules.

**AgentOps → DevSecOps.** The policy engine (`shared/models/policy.py` — `max_allowed_action`) enforces what AgentOps is permitted to do. DevSecOps defines the policy rules; AgentOps reads them from the state and honours them during the Reflection decision. DevSecOps also owns the deployment and secrets management for the harness.

**AgentOps → Evaluation (internal).** The `EvaluationRunner` (`finance/evaluation/runner.py`) is AgentOps' own regression testing layer. It consumes `HarnessResult` objects and computes metrics. This is not a separate ops layer — it is a quality gate within AgentOps.

---

## Operational Metrics

All metrics are computed by `finance/evaluation/runner.py` using metric classes in `finance/evaluation/metrics.py`. Each returns a float in `[0.0, 1.0]`.

### Runtime Metrics (Agent Behaviour)

| Metric | Class | Formula | Interpretation |
|---|---|---|---|
| **PlanningAccuracy** | `PlanningAccuracy` | Average of required-intent recall and forbidden-intent avoidance | 1.0 = planner produced every required intent and no forbidden intents |
| **ReplanningFrequency** | `ReplanningFrequency` | `1.0 - (replan_count / (max_replans + 1))` | 1.0 = no replanning needed; 0.0 = exceeded max replans |
| **ActionSuccessRate** | `ActionSuccessRate` | `successful_actions / total_actions` | 1.0 = every action completed successfully |
| **RetryRate** | `RetryRate` | `1.0 - (total_retries / total_actions)` | 1.0 = zero retries across all actions |
| **AverageLatency** | `AverageLatency` | Linear degradation from budget_ms to 2× budget | 1.0 = within budget (default 1000 ms); 0.0 ≥ 2× budget |
| **ToolFailureRate** | `ToolFailureRate` | `1.0 - (failed_actions / total_actions)` | 1.0 = zero tool failures |

### Business Metrics (Output Correctness)

| Metric | Class | What It Measures |
|---|---|---|
| VarianceAccuracy | `VarianceAccuracy` | Proportion of expected variance records correctly computed (matched by `account_id`) |
| KPIAccuracy | `KPIAccuracy` | Proportion of expected KPIs correctly computed (matched by `name`) |
| ReportCoverage | `ReportCoverage` | Proportion of expected report sections present in output |
| UnsupportedClaimRate | `UnsupportedClaimRate` | Proportion of assertions with `support_level` VERIFIED or PROBABLE |
| EvidenceCoverage | `EvidenceCoverage` | Average evidence items per assertion, normalised to target (default 1) |
| PolicyCompliance | `PolicyCompliance` | Fraction of assertions whose `max_allowed_action` was not blocked or escalated |

### Aggregation

`OverallScore` computes the arithmetic mean of all runtime and business metrics. A run **passes** when the overall score is **≥ 0.7**.

```python
# finance/evaluation/metrics.py — line 279
@staticmethod
def compute(scores: dict[str, float]) -> dict[str, Any]:
    overall = round(sum(scores.values()) / len(scores), 10)
    passed = overall >= 0.7
    return {"overall": overall, "passed": passed}
```

---

## Failure Modes

### Infinite loop (stalled workflow)

**Symptoms:** `loop_decision` remains "revise" indefinitely. The Reflection node finds gaps (e.g., unsupported assertions, missing evidence), but each revision either does not address them or introduces new gaps.

**Current protection:** The max-iterations guard (`min(state.max_iterations, self._max_iterations)`, default 5) forces a "finalize" decision. `ReasoningState.plan_history` grows unboundedly until the guard triggers.

**Remaining risk:** A workflow that genuinely oscillates between two states (e.g., Planner keeps adding evidence actions, Executor keeps failing them, Reflection keeps requesting revision) consumes iterations productively but never converges. The system produces an output — but one that likely has unresolved gaps.

**Recommendation:** Add a plan-stability check in the harness: detect when the last N plan_history entries are identical and force-terminate with a "stalled" status.

### Stalled data retrieval

**Symptoms:** RetrieverNode returns empty data (no provider, or provider raises). Executor runs with empty inputs — variances list is `[]`, so MaterialityEngine produces zero assessments. Verifier reports zero verified assertions. Reflection sees "no evidence" and requests revision. Planner replans identically. Loop repeats until max iterations.

**Current protection:** The stub-data path in RetrieverNode provides empty lists rather than crashing, but the Reflection node does not distinguish "no data available" from "all data verified." The workflow burns through iterations on a problem no amount of replanning can fix.

**Recommendation:** Add a data-availability flag to `ReasoningState`. Reflection should check this flag before requesting revision. If data was unavailable on the first pass, it will be unavailable on the fifth — escalate immediately.

### Unhandled escalation

**Symptoms:** An assertion carries `max_allowed_action: "escalate"`. The Reflection node correctly passes it through, but there is no integration layer to receive the escalation signal. The decision is recorded in the telemetry JSON and then discarded.

**Current state:** The pipeline does not block on escalation — it continues to finalize. The `max_allowed_action` field is populated and serialised, but no downstream consumer exists.

**Recommendation:** Before returning `HarnessResult`, the harness should check for any assertion with `max_allowed_action` in `{"escalate", "block"}` and at minimum log a warning. Future: integrate with a notification service (email, Slack, ERP webhook).

### Telemetry directory write failure

**Symptoms:** `ReasoningTelemetry.capture()` attempts to write `.reasoning_traces/{run_id}.json` but the directory is not writable (permissions, disk full, read-only filesystem). The `Path.write_text()` call raises an unhandled `OSError`.

**Current protection:** None. The `mkdir(parents=True, exist_ok=True)` call in `__init__` may fail at construction time, but a runtime write failure is not caught.

**Recommendation:** Wrap the `capture()` call in the harness with a try-except that logs the failure and still returns the `HarnessResult`. Telemetry is valuable but must not block production analysis.

### Planner producing empty ActionPlan

**Symptoms:** No keywords match the query. PlannerNode generates the default plan (variance, KPI, evidence — three actions). This is benign. However, if a custom PlannerNode returns an `ActionPlan` with zero actions, the ExecutorNode returns "no_actions", the Verifier has nothing to verify, and the Reflection node sees no KPI/variance analysis in the plan.

**Current protection:** The ExecutorNode handles `plan.actions` being `None` or empty and returns a `plan_status: "no_actions"` result. The Verifier skips action verification. The Reflection node flags missing KPI and variance analysis as gaps — which may trigger a useless revision.

**Recommendation:** Treat an empty ActionPlan as an immediate escalation. No valid plan → no meaningful work can happen. The harness should skip the iteration loop entirely and produce a `HarnessResult` with `success=False`.

### Action exception not captured

**Symptoms:** An exception occurs during engine dispatch in the ExecutorNode — but outside the try-except block. Currently, the per-action `try/except Exception` wraps the keyword routing logic, and each route is separately try-wrapped. However, the validation suite call (line 192) and the assertion-building outside the try block are not guarded.

**Current protection:** The per-action `try/except Exception` wraps the core dispatch. However, the `perf_counter()` and action_trace construction at the bottom of the loop (latency calculation, line 214-221) execute after the try block. If these raise, the entire `execute()` method fails ungracefully.

**Recommendation:** Either extend the try block to cover the full loop body, or add a second catch at the `execute()` method level that returns a fallback NodeResult.

---

## Configuration Surface

| Parameter | Location | Default | Description |
|---|---|---|---|
| `max_iterations` | `ReasoningHarness.__init__` | `5` | Max pipeline iterations per run |
| `telemetry_dir` | `ReasoningHarness.__init__` | `".reasoning_traces"` | Output directory for run traces |
| pipeline order | `NodeRegistry.__init__` | `[planner, retriever, executor, verifier, reflection]` | Node execution order |
| `latency_budget_ms` | `EvaluationRunner.__init__` | `1000` | Latency budget for AverageLatency metric |
| `min_evidence_target` | `EvidenceCoverage.__init__` | `1` | Target evidence items per assertion |
| `CONFIDENCE_THRESHOLD` | `ReflectionNode` | `0.7` | Minimum confidence to allow finalize |
| `MIN_CONFIDENCE_THRESHOLD` | `VerifierNode` | `0.5` | Below this → low confidence flag |

---

## Running the Harness

```python
from finance.cognition.harness import ReasoningHarness
from finance.cognition.state.models import ReasoningState

state = ReasoningState(query="Analyse budget variances for Q1 2026")
harness = ReasoningHarness(max_iterations=5)
result = harness.run(state)

print(f"Run ID: {result.run_id}")
print(f"Success: {result.success}")
print(f"Iterations: {result.state.iteration_count}")
print(f"Decision: {result.state.loop_decision}")
print(f"Confidence: {result.state.overall_confidence}")
print(f"Trace written to: .reasoning_traces/{result.run_id}.json")
```

Evaluating against a golden dataset:

```python
from finance.evaluation.runner import EvaluationRunner
from finance.evaluation.dataset import GoldenDataset

runner = EvaluationRunner(latency_budget_ms=1000)
dataset = GoldenDataset(...)
report = runner.run(dataset, result)

print(f"Overall: {report.overall_score}")
print(f"Passed: {report.passed}")
print(f"Runtime: {report.runtime_metrics}")
print(f"Business: {report.business_metrics}")
```
