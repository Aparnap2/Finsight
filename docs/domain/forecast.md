# Forecast

## Business Meaning

A **Forecast** is a forward-looking estimate of financial performance for future periods. Unlike a budget — which represents a target or commitment — a forecast represents the most current expectation of what will actually happen. Forecasts are updated more frequently than budgets (often monthly or quarterly) and incorporate the latest business intelligence, market conditions, and operational data.

## Forecast Methods

### Rolling Forecast

A continuously updated projection that extends forward by a fixed number of periods (typically 12-18 months). As each period closes, it is dropped from the forecast window and a new future period is added.

Key characteristics:

- **Fixed horizon**: Always shows N periods ahead (e.g., 12-month rolling forecast).
- **Regular updates**: Recast monthly or quarterly as new actuals become available.
- **Eliminates fiscal year bias**: Focuses on a forward-looking time window rather than remaining budget periods.
- **Best for**: Companies with long sales cycles or subscription revenue models.

### Driver-Based Forecast

A forecast built by modeling the relationship between business drivers (e.g., headcount, ARR, units sold) and financial outcomes. Changes to driver assumptions automatically propagate through the financial model.

Key characteristics:

- **Causal relationships**: Revenue is a function of headcount × productivity; COGS is a function of units × unit cost.
- **Sensitivity-ready**: Changing a single driver (e.g., "reduce headcount growth by 10%") recalculates all dependent accounts.
- **Best for**: Companies with well-understood operational drivers and historical data to calibrate relationships.

### Trend-Based Forecast

A statistical forecast that projects historical patterns into future periods using time-series analysis. Common techniques include moving averages, exponential smoothing, and linear regression.

Key characteristics:

- **Data-driven**: Relies entirely on historical patterns without causal modeling.
- **Low setup cost**: Does not require building driver hierarchies.
- **Best for**: Mature, stable business lines with predictable seasonality.

## Forecast Periods

Forecasts can be created at any granularity defined by the company's FiscalCalendar:

| Period Type | Forecast Horizon | Update Cadence |
|-------------|-----------------|----------------|
| **Monthly** | 3-18 months forward | Monthly |
| **Quarterly** | 4-8 quarters forward | Quarterly |
| **Annual** | 1-3 years forward | Semi-annually |

## Scenarios

### Base Case

The most likely outcome based on current business conditions and management assumptions. The base case is the default forecast used for variance analysis and comparison against the budget.

### Optimistic Case

An upside scenario modeling favorable conditions:

- Higher revenue growth rate (+5-15% over base case).
- Faster customer acquisition.
- Lower than expected cost inflation.
- Favorable FX movements.

### Pessimistic Case

A downside scenario modeling adverse conditions:

- Lower revenue growth or contraction.
- Customer churn increases.
- Cost inflation above expectations.
- Adverse FX movements.
- Supply chain disruptions.

### Scenario Governance

- Each scenario has documented assumptions that explain deviation from the base case.
- Scenarios are versioned and immutable once created.
- Scenario probabilities are assessed (e.g., Base: 60%, Optimistic: 20%, Pessimistic: 20%).
- Weighted average across scenarios produces the **expected value forecast**.

## Forecast vs. Budget Comparison

The forecast vs. budget comparison is distinct from the standard budget vs. actual comparison:

```
Forecast vs Budget = Forecast Amount - Budget Amount
Forecast Variance % = (Forecast - Budget) / |Budget| × 100
```

This comparison serves as an **early warning signal** — if the forecast is significantly different from the budget, management has time to adjust plans before the variance materializes.

### Use Cases

| Scenario | Insight |
|----------|---------|
| Forecast > Budget | Upside risk — potential overperformance |
| Forecast < Budget | Downside risk — potential shortfall |
| Forecast = Budget | On track to meet targets |
| Forecast trending away from budget | Systematic deviation — investigate root causes |

## Edge Cases

### Partial Year Forecast

When creating a forecast partway through the fiscal year (e.g., a Q3 forecast for Q3-Q4 and the next fiscal year):

1. **Closed periods**: Actuals replace forecast values for already-completed periods.
2. **Current period**: The in-flight period may use a blend of actuals-to-date and forecast for the remainder.
3. **Remaining periods**: Pure forecast for future periods.
4. **YTD comparison**: The forecast includes actuals for closed periods + forecast for remaining.
5. Commentary must clearly distinguish between actuals, actuals+forecast blends, and pure forecast ranges.

### New Business Line

When a new business line (e.g., a new product category) has no historical data:

1. **No trend baseline**: Trend-based forecasting is not available — use driver-based or benchmark-based methods.
2. **Assumption-heavy**: Forecasts rely on management assumptions about ramp-up curves, market penetration, and unit economics.
3. **Wider confidence intervals**: Forecast uncertainty is higher due to the absence of historical calibration.
4. **Comparison period**: If no prior-year budget exists, the forecast is compared to zero or to industry benchmarks.
5. Commentary notes the lack of historical data as a **data quality consideration**.

### Forecast Horizon Extension

When extending the forecast horizon (e.g., from 12 to 18 months):

1. The reliability of forecast values decreases with distance from the present.
2. Extended-horizon periods use higher-level assumptions and broader ranges.
3. Commentary for extended periods notes the decreased confidence.
4. Confidence scoring for extended periods is proportionally reduced.

### Merger or Acquisition Impact

When a company undergoes an M&A event during the forecast period:

1. The acquired entity's financials are incorporated as a new business line.
2. Historical data for the acquired entity may not exist in the company's system.
3. Forecast assumptions explicitly document the acquisition impact and integration timeline.
4. A separate "pro-forma" scenario may be created to show performance excluding the acquisition.
