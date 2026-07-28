# Success Metrics

## Key Performance Indicators

The following metrics were defined at engagement kick-off and tracked throughout the delivery. They fall into three categories: **business outcomes**, **engineering quality**, and **evaluation rigour**.

---

## Business Outcome Metrics

### Cycle Time Reduction

| Metric | Baseline (Manual) | Target | Current |
|--------|-------------------|--------|---------|
| Variance analysis (full cycle) | 3 days | 30 minutes | ~4 minutes (deterministic engine) |
| Root cause investigation | 2 days | 2 hours | 15 minutes (LLM-guided, read-only tools) |
| Commentary generation | 1 day | 30 minutes | 30 seconds (LLM rendering from assertions) |
| Data quality assessment | 4 hours | 5 minutes | < 10 seconds (6 checks, batch) |

**Measurement method:** Pipeline execution timestamps captured by `ReasoningTelemetry`. Each node execution records start time, end time, and duration in milliseconds as structured JSON.

### Accuracy

| Metric | Target | Rationale |
|--------|--------|-----------|
| Calculation error rate | **0%** | All financial math is deterministic Python with `Decimal` precision. No LLM involved in computation. |
| Variance accuracy | **100%** | Formula engine uses `FormulaRegistry.evaluate_all()` with topological dependency resolution. |
| KPI accuracy | **100%** | KPI engine evaluates registered formulas against `Decimal` inputs. |
| Bridge reconciliation | **100%** | Bridge components must sum to total variance — enforced at model level. |

**Measurement method:** Deterministic by construction. Verified by 83+ tests across formula engine, materiality, calendar, and decimal layer. Enforced by `mypy` strict mode and `ruff` linting.

### Coverage

| Metric | Target | Notes |
|--------|--------|-------|
| Assertion verification rate | **95%+** | Fraction of assertions reaching `VERIFIED` or `PROBABLE` support level |
| Evidence coverage | **≥1 evidence item per assertion** | Every assertion must cite at least one source record |
| Data quality check pass rate | **Variable by tier** | CRITICAL checks must pass 100%; warnings acceptable for LOW severity |

**Measurement method:** `UnsupportedClaimRate` and `EvidenceCoverage` metrics in the evaluation suite. Captured per dataset in `EvaluationReport`.

### Adoption

| Metric | Target | Notes |
|--------|--------|-------|
| Time to configure new accounts | **< 15 minutes** | Account discovery from GL, materiality rule configuration, KPI registration |
| Time to onboard new tenant | **< 1 hour** | Database setup, seed data, materiality defaults |
| Pipeline run (full cycle) | **< 5 minutes** | Including LLM commentary generation |

---

## Engineering Quality Metrics

### Code Quality

| Metric | Standard | Enforcement |
|--------|----------|-------------|
| Type coverage | Strict mode | `mypy .` — zero errors |
| Linting | PEP 8, 100-char line limit | `ruff check .` — zero warnings |
| Monetary values | `Decimal` only | `MoneyDecimal` Pydantic validator rejects `float` |
| Test count | 83+ | `python -m pytest` — all passing |
| Test coverage | Unit + integration + agent | Three layers covering all engines, nodes, and pipelines |

### Architecture Compliance

| Metric | Standard | Enforcement |
|--------|----------|-------------|
| Dependency direction | `apps → agents → finance → shared` | Code review enforcement |
| No reverse imports | `shared` never imports `apps/agents/finance` | Code review + import checker |
| No LLM in finance layer | Finance is 100% deterministic | Architecture freeze after Phase 3 |

---

## Evaluation Rigour Metrics

### Golden Dataset Coverage

| Category | Count | What It Measures |
|----------|-------|------------------|
| Financial logic | 7 datasets | Core computation correctness (variances, KPIs, margins, growth, seasonality, zero/negative values) |
| Data quality | 5 datasets | Robustness to malformed, missing, duplicated, or mismatched input |
| Runtime behaviour | 4 datasets | Agent loop correctness (retries, replanning, evidence gaps, unsupported assertions) |
| Governance | 4 datasets | Policy compliance, forbidden claims, contradictions, low-confidence handling |
| Built-in (supplementary) | 2 datasets | Simple revenue and seasonal pattern checks for unit test integration |
| **Total** | **22 datasets** | |

### Business Metrics

| Metric | Definition | Threshold (warn / break) |
|--------|------------|--------------------------|
| `VarianceAccuracy` | Fraction of variance records matching expected values | 0.95 / 0.85 |
| `KPIAccuracy` | Fraction of KPI values matching expected values (with tolerance) | 0.95 / 0.85 |
| `ReportCoverage` | Fraction of expected report sections present in output | 0.90 / 0.80 |
| `UnsupportedClaimRate` | Proportion of assertions with `VERIFIED` or `PROBABLE` support | 0.90 / 0.80 |
| `EvidenceCoverage` | Average evidence items per assertion (normalised to target) | 0.80 / 0.60 |
| `PolicyCompliance` | Fraction of assertions respecting `max_allowed_action` | 0.95 / 0.90 |

### Runtime Metrics

| Metric | Definition | Threshold (warn / break) |
|--------|------------|--------------------------|
| `PlanningAccuracy` | Required intents present; forbidden intents absent | 0.95 / 0.85 |
| `ReplanningFrequency` | Actual replan count vs expected max replans | 0.10 / 0.20 |
| `ActionSuccessRate` | Fraction of actions completed successfully | 0.90 / 0.80 |
| `RetryRate` | Average retries per action (inverse score) | 0.10 / 0.20 |
| `AverageLatency` | Mean action latency within budget | 0.80 / 0.60 |
| `ToolFailureRate` | Fraction of tool calls that failed | 0.05 / 0.10 |

### Regression Detection

| Component | Behaviour |
|-----------|-----------|
| **Comparison** | Current evaluation report vs stored baseline |
| **Delta detection** | Per-metric deltas with signed values |
| **Breaking change** | Any metric delta below `break_` threshold |
| **Warning** | Any metric delta below `warn` threshold |
| **Report** | `RegressionReport` with summary, deltas, new/resolved failures, breaking changes |

---

## Metrics Dashboard (Verbatim from Regression Harness)

```
RegressionReport
├── summary: "PASS" | "MINOR_REGRESSION" | "REGRESSION_DETECTED"
├── runtime_metrics: {planning_accuracy, replanning_frequency, action_success_rate, ...}
├── business_metrics: {variance_accuracy, kpi_accuracy, report_coverage, ...}
├── deltas: {runtime.planning_accuracy: -0.02, business.variance_accuracy: 0.0, ...}
├── new_failures: ["dataset_ids_present_in_current_but_not_baseline"]
├── resolved_failures: ["dataset_ids_present_in_baseline_but_not_current"]
└── breaking_changes: ["metrics_that_exceeded_break_threshold"]
```

---

## Measurement Infrastructure

All metrics are computed by the `finance/evaluation/` module:

- **`finance/evaluation/metrics.py`** — 12 metric classes (6 business + 6 runtime) plus `OverallScore` aggregator
- **`finance/evaluation/runner.py`** — `EvaluationRunner` that drives metrics against `HarnessResult` and produces `EvaluationReport`
- **`finance/evaluation/regression.py`** — `Comparator` for baseline comparison, `RegressionRunner` for CI integration
- **`finance/evaluation/thresholds/`** — YAML threshold files per metric group (`business.yaml`, `runtime.yaml`)
- **`finance/evaluation/datasets/`** — 22 golden dataset JSON files organised by category

The infrastructure is designed to run in CI pipelines, producing a pass/fail verdict for each PR.
