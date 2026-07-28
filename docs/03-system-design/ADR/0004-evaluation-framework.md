# ADR-0004: Evaluation Framework — Golden Datasets, Dual Metrics, Regression

**Status:** Accepted  
**Deciders:** Architecture Team  

---

## Context

Unit tests verify that individual functions produce correct outputs. For a cognitive reasoning system, unit tests are insufficient:

- **Planner correctness** cannot be tested with a simple assertion — the planner must produce an `ActionPlan` with the right intents and avoid forbidden ones.
- **Multi-step pipeline accuracy** requires comparing the full pipeline output (variances, KPIs, report sections) against known-correct values.
- **Runtime behaviour** (retry handling, replanning, latency) is invisible to unit tests but critical for reliability.
- **Regression detection** across releases requires comparing current results against a stored baseline with configurable thresholds.

The system needed an evaluation framework that:

1. Tests both **financial accuracy** (are the numbers right?) and **runtime behaviour** (did the system handle failures gracefully?).
2. Uses **golden datasets** with structured expectations across all pipeline stages (planning, execution, verification, reflection, output).
3. Produces **comparable results** across runs to detect regression.
4. Runs in **CI pipelines** with pass/fail gates.

## Decision

Build an evaluation framework organised around three components: **GoldenDataset** as the test specification, **EvaluationRunner** as the executor, and **Comparator/RegressionRunner** as the regression detector.

### GoldenDataset Structure

Each golden dataset is a JSON file that defines input and expected behaviour across all five pipeline stages:

```python
class GoldenDataset(BaseModel):
    metadata: DatasetMetadata    # id, name, category, difficulty, tags
    input: DatasetInput          # query, context accounts, spreadsheet data
    expected: ExpectedBehaviour  # Expectations for all 5 stages
    
class ExpectedBehaviour(BaseModel):
    planning: PlanningExpectation     # required/forbidden intents, min/max actions, max replans
    execution: ExecutionExpectation   # min success rate, max retries, max failures
    verification: VerificationExpectation  # max unsupported/contradictory/low-confidence assertions
    reflection: ReflectionExpectation      # expected decision, max gaps
    output: OutputExpectation              # exact variances, KPIs, report sections, claims
```

### Dual Metric Groups

The framework computes 12 metrics in two independent groups:

**Business Metrics (6):** Measure financial accuracy and output quality.

| Metric | What It Measures |
|--------|-----------------|
| `VarianceAccuracy` | Fraction of variance records matching expected values |
| `KPIAccuracy` | Fraction of KPI values matching expected values (with optional tolerance) |
| `ReportCoverage` | Fraction of expected report substrings present in output |
| `UnsupportedClaimRate` | Proportion of assertions with VERIFIED or PROBABLE support |
| `EvidenceCoverage` | Average evidence items per assertion, normalised to target |
| `PolicyCompliance` | Fraction of assertions respecting `max_allowed_action` |

**Runtime Metrics (6):** Measure pipeline execution quality.

| Metric | What It Measures |
|--------|-----------------|
| `PlanningAccuracy` | Required intents present; forbidden intents absent |
| `ReplanningFrequency` | Actual replanning count vs expected max |
| `ActionSuccessRate` | Fraction of actions completed successfully |
| `RetryRate` | Average retries per action (inverse score) |
| `AverageLatency` | Mean action latency within budget |
| `ToolFailureRate` | Fraction of action executions that failed |

### Regression Detection

The `Comparator` compares current evaluation reports against a stored baseline:

1. **Thresholds per metric** in YAML (`runtime.yaml`, `business.yaml`) with `warn` and `break_` values.
2. **Deltas computed** as `current - baseline` for every metric.
3. **Breaking changes** flagged when a delta exceeds the `break_` threshold.
4. **Summary verdict:** `PASS`, `MINOR_REGRESSION`, or `REGRESSION_DETECTED`.

```yaml
# runtime.yaml
planning_accuracy:
  warn: 0.95
  break: 0.85
action_success_rate:
  warn: 0.90
  break: 0.80
```

### Evaluation Runner

```python
class EvaluationRunner:
    def run(self, dataset: GoldenDataset, result: HarnessResult) -> EvaluationReport:
        # Compute business metrics from state.assertions and state.context
        # Compute runtime metrics from action_plan.actions and plan_history
        # Aggregate into overall score (pass >= 0.7)
        return EvaluationReport(
            dataset_id=dataset.metadata.id,
            overall_score=...,
            runtime_metrics={...},
            business_metrics={...},
            passed=overall >= 0.7,
        )
```

## Consequences

### Positive

- **Clear separation of concerns.** Business metrics measure financial quality; runtime metrics measure system health. A change that improves accuracy but degrades latency is visible in both groups.
- **CI-integratable.** `RegressionRunner.run_and_compare()` stores the first run as baseline and compares subsequent runs. Breaking changes fail the build.
- **Structured expectations.** Each golden dataset specifies exactly what the planner should (and should not) produce — enabling targeted planning regression tests.
- **Configurable thresholds.** Per-metric thresholds can be tuned for different deployment environments (development vs production vs audit).

### Negative

- **Golden dataset maintenance.** 22 datasets must be kept in sync with any changes to engine behaviour. A formula change can invalidate multiple datasets.
- **Baseline drift risk.** If baseline is updated without review, regressions can be silently accepted. Mitigated by requiring PR review for baseline updates.
- **Metric noise.** Some metrics (e.g., `AverageLatency`) are environment-dependent. CI runners must run on consistent hardware for reproducible results.

## Compliance

1. **Every PR must pass evaluation on all 22 golden datasets.** `RegressionRunner.run_and_compare()` is part of the CI pipeline.
2. **Threshold files are version-controlled.** Changes to `warn`/`break` thresholds require team review.
3. **New metrics must be registered in both `metrics.py` and the threshold YAML.** Missing threshold entries default to `warn=0.0, break=0.0` (no gating).
4. **Golden datasets are immutable after release.** Corrections create new dataset versions.
5. **Business and runtime metrics are computed independently.** A change cannot inflate one group at the expense of the other.
