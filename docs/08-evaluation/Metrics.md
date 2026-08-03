# Metrics

## Overview

Metrics are divided into two groups: **business metrics** measure financial correctness; **runtime metrics** measure the cognitive agent's behaviour. Each metric returns a float in `[0.0, 1.0]`.

## Business Metrics

### VarianceAccuracy
Compares expected variance records to actual pipeline output by `account_id`. A record matches when both `variance_amount` and `variance_pct` are equal.

### KPIAccuracy
Compares expected KPI records to actual output by `name`. Supports optional tolerance for fuzzy matching.

### ReportCoverage
Checks that expected substrings appear in actual report sections. Case-insensitive.

### UnsupportedClaimRate
Measures the proportion of assertions with `support_level` other than `verified` or `probable`. A score of 1.0 means all claims are supported. Renamed from "hallucination rate" because the runtime is deterministic — this measures unsupported claims, not model hallucination.

### EvidenceCoverage
Average number of evidence items per assertion, normalised to a configurable target (default 1). Capped at 1.0.

### PolicyCompliance
Fraction of assertions whose `max_allowed_action` was not `block` or `escalate`.

## Runtime Metrics

### PlanningAccuracy
Checks whether the planner produced all required intents and avoided all forbidden intents. Average of required and forbidden scores.

### ReplanningFrequency
Compares actual replanning count to expected `max_replans`. 1.0 = no replanning needed, 0.0 = exceeded limit.

### ActionSuccessRate
Fraction of actions that completed with `status = SUCCESS`.

### RetryRate
Total retries across all actions divided by action count. 1.0 = zero retries, 0.0 = every action retried once.

### AverageLatency
Mean action latency in ms, compared against a configurable budget (default 1000ms). 1.0 if at or under budget, 0.0 at 2x budget, linear degradation between.

### ToolFailureRate
Fraction of actions with `status = FAILED`. 1.0 = no failures.

## Thresholds

Thresholds are defined in YAML with warn and break levels:

```yaml
# runtime.yaml
action_success_rate:
  warn: 0.90
  break: 0.80

# business.yaml
variance_accuracy:
  warn: 0.95
  break: 0.85
```

The comparator uses break thresholds for breaking change detection and warn thresholds for advisory notices.

## OverallScore

The arithmetic mean of all metric scores. A run is considered passing when `overall >= 0.7`.
