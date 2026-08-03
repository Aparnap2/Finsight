# Regression Harness

## Purpose

The regression harness detects regressions across evaluation runs. It compares a current evaluation report set against a stored baseline, identifies breaking changes, and produces a structured report.

## Pipeline

```
  Baseline (stored)         Current (fresh run)
        │                         │
        └──────────┬──────────────┘
                   │
                   ▼
             Comparator
                   │
                   ▼
           RegressionReport
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
   Summary     Deltas    Breaking
                         Changes
```

## Components

### Comparator (`finance/evaluation/regression.py`)
Accepts baseline and current `list[EvaluationReport]`, compares them by `dataset_id`, computes metric deltas, and flags breaking changes.

```python
comparator = Comparator()
report = comparator.compare(baseline, current)
```

### RegressionReport
```python
class RegressionReport(BaseModel):
    baseline_id: str
    current_id: str
    summary: str          # PASS | MINOR_REGRESSION | REGRESSION_DETECTED
    runtime_metrics: dict
    business_metrics: dict
    deltas: dict          # metric → current - baseline
    new_failures: list    # datasets only in current
    resolved_failures: list  # datasets only in baseline
    breaking_changes: list   # metrics exceeding break thresholds
    score: float
```

### RegressionRunner
Manages baseline persistence and the compare cycle:

```python
runner = RegressionRunner(baseline_dir=".regression_baseline")

# First run (no baseline yet) — saves baseline, returns None
report = runner.run_and_compare(current_reports)

# Second run — compares against stored baseline
report = runner.run_and_compare(new_reports)
```

## Threshold Files

### `runtime.yaml`
```yaml
planning_accuracy:      warn: 0.95, break: 0.85
action_success_rate:    warn: 0.90, break: 0.80
replanning_frequency:   warn: 0.10, break: 0.20
retry_rate:             warn: 0.10, break: 0.20
average_latency:        warn: 0.80, break: 0.60
tool_failure_rate:      warn: 0.05, break: 0.10
```

### `business.yaml`
```yaml
variance_accuracy:      warn: 0.95, break: 0.85
kpi_accuracy:           warn: 0.95, break: 0.85
report_coverage:        warn: 0.90, break: 0.80
unsupported_claim_rate: warn: 0.90, break: 0.80
evidence_coverage:      warn: 0.80, break: 0.60
policy_compliance:      warn: 0.95, break: 0.90
```

## CI Integration

The regression runner is designed for CI pipelines:
- First commit on a branch creates the baseline
- Subsequent commits compare against baseline
- Breaking changes fail the CI step
- Regression reports are persisted as CI artefacts
