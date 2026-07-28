# Benchmarks

## Overview

The evaluation framework includes 22 golden datasets organised into 4 categories. Each dataset specifies expectations across all 5 pipeline stages: planning, execution, verification, reflection, and output.

## Dataset Catalogue

### Financial Logic (7 datasets)

| Dataset | Difficulty | What It Tests |
|---------|-----------|---------------|
| `revenue_growth` | basic | Standard positive variance, basic KPI computation |
| `margin_decline` | intermediate | Revenue grew but costs grew faster, margin compression analysis |
| `budget_variance` | basic | Multi-account variance analysis across 5 accounts |
| `negative_revenue` | intermediate | Revenue reversal from returns/credits |
| `zero_budget` | intermediate | Accounts with zero budget allocation |
| `seasonality` | intermediate | Seasonal Q1 patterns affecting revenue |
| `fx_impact` | advanced | FX rate effects on international revenue |

### Data Quality (5 datasets)

| Dataset | Difficulty | What It Tests |
|---------|-----------|---------------|
| `missing_values` | intermediate | Null actual/budget values in some accounts |
| `duplicate_rows` | advanced | Same account appearing twice with conflicting values |
| `malformed_spreadsheet` | advanced | Invalid data types and missing required fields |
| `currency_mismatch` | advanced | Accounts with USD, EUR, GBP without FX rates |
| `invalid_periods` | advanced | Inconsistent fiscal period label formats |

### Runtime Behaviour (4 datasets)

| Dataset | Difficulty | What It Tests |
|---------|-----------|---------------|
| `retry_scenario` | intermediate | Complex inter-dependent accounts requiring retries |
| `replanning_scenario` | advanced | Missing data requiring plan revision |
| `missing_evidence` | intermediate | Mixed evidence quality across accounts |
| `unsupported_assertions` | advanced | Incomplete metadata leading to weak assertions |

### Governance (4 datasets)

| Dataset | Difficulty | What It Tests |
|---------|-----------|---------------|
| `policy_violation` | advanced | Cost-cutting action violating regulatory policy |
| `contradictory_evidence` | advanced | Different data sources with conflicting signals |
| `forbidden_claim` | advanced | Scenario designed to trigger false absolute claims |
| `low_confidence` | intermediate | Ambiguous data with wide estimate ranges |

## Runtime Expectations per Dataset

Each dataset specifies expectations for:
- **Planning**: required intents, forbidden intents, action count bounds, max replans
- **Execution**: minimum success rate, max retries, max failed actions, latency budget
- **Verification**: max unsupported, max contradictions, min evidence, min confidence
- **Reflection**: expected decision (finalize/revise), max gaps
- **Output**: expected variances, KPIs, report sections, required/forbidden claims
