# Variance

## Business Meaning

A **Variance** is the difference between an actual financial outcome and a reference value (budget, forecast, or prior period). Variance analysis is the core analytical process in FinSight — it identifies where actual performance deviates from expectations, quantifies the deviation, and enables investigation into root causes. Variances drive the entire commentary pipeline from materiality assessment through root cause analysis to actionable recommendations.

## Variance Types

### Price Variance

The difference between actual and budgeted unit prices, multiplied by actual volume. Captures changes in pricing power, discounting behavior, or input cost movements.

```
Price Variance = (Actual Price - Budget Price) × Actual Volume
```

**Direction**: Favorable when actual price > budget price (revenue) or actual price < budget price (costs).

### Volume Variance

The difference between actual and budgeted volume, multiplied by the budgeted unit price. Captures changes in sales quantity or production volume.

```
Volume Variance = (Actual Volume - Budget Volume) × Budget Price
```

**Direction**: Favorable when actual volume > budget volume.

### Mix Variance

The residual variance after isolating price and volume effects. Captures changes in the composition of revenue or cost (e.g., selling more low-margin products than planned).

```
Mix Variance = Total Variance - Price Variance - Volume Variance - FX Variance
```

**Direction**: Favorable when the actual product/service mix has higher margins than budgeted.

### FX Variance

The difference attributed to changes in foreign exchange rates between budget and actual periods.

```
FX Variance = (Actual FX Rate - Budget FX Rate) × Actual Amount in Foreign Currency
```

**Direction**: Depends on whether the company is net long or short in the foreign currency.

### Spending Variance

For cost accounts, the difference between actual cost and budgeted cost at actual volume. Captures pure cost efficiency/inefficiency.

```
Spending Variance = Actual Cost - (Budget Rate × Actual Volume)
```

**Direction**: Favorable when actual cost is lower than the flexible budget.

## Calculation Methods

### Absolute Variance

```
Variance Amount = Actual - Reference
```

The raw monetary difference. Used to understand the dollar impact of the variance.

### Percentage Variance

```
Variance Percentage = (Actual - Reference) / |Reference| × 100
```

The relative difference. Used to understand the proportional significance. The reference value is taken as absolute to handle negative budgets correctly.

### Cumulative Variance (YTD)

```
YTD Variance = Sum(Period 1..N Actuals) - Sum(Period 1..N Budget)
```

The year-to-date aggregated variance. Used for period-to-date reporting.

## Favorable vs. Adverse Direction

Variance direction depends on the account type and context:

| Account Type | Favorable | Adverse |
|-------------|-----------|---------|
| **Revenue** | Actual > Budget (positive) | Actual < Budget (negative) |
| **COGS** | Actual < Budget (negative) | Actual > Budget (positive) |
| **OpEx** | Actual < Budget (negative) | Actual > Budget (positive) |
| **Other Income** | Actual > Budget (positive) | Actual < Budget (negative) |
| **Other Expense** | Actual < Budget (negative) | Actual > Budget (positive) |

The variance engine applies account-type direction logic when computing `Variance.variance_amount` and `Variance.variance_pct`. Sign alone is not sufficient to determine favorability — context-aware interpretation is required.

## Materiality Thresholds

A variance is classified as **material** when it exceeds configurable thresholds. The materiality engine uses a tiered approach with sensitivity levels (CRITICAL, HIGH, MEDIUM, LOW) and two threshold dimensions:

- **Percentage threshold**: Exceeded when `|variance_pct| > pct_threshold`.
- **Absolute threshold**: Exceeded when `|variance_amount| > abs_threshold`.

The combined rule (`"any"` or `"both"`) determines whether one or both thresholds must be exceeded.

See **[materiality.md](./materiality.md)** for detailed threshold configuration.

## Variance Analysis Waterfall

The variance waterfall (or bridge analysis) decomposes a total variance into its constituent components, ensuring the sum of components equals the total variance (within a small reconciliation tolerance).

### Revenue Bridge Flow

```
Total Revenue Variance
├── Price Effect       — (Actual Price - Budget Price) × Actual Volume
├── Volume Effect      — (Actual Volume - Budget Volume) × Budget Price
├── Mix Effect         — Residual after Price and Volume
└── FX Effect          — Exchange rate movement impact
```

### Cost Bridge Flow

```
Total Cost Variance
├── One-Time Effect    — Non-recurring items (legal settlements, restructuring)
├── Timing Effect      — Expenses shifted between periods
├── Scope Effect       — Changes in project scope or headcount
└── Rate Effect        — Pure cost rate changes (residual)
```

### Reconciliation

The bridge is considered **reconciled** when the sum of component variances equals the total variance within \$1.00 (configurable tolerance). When the bridge does not reconcile:

- The overall confidence score is reduced by 30%.
- A degraded mode flag is raised.
- Component descriptions note the reconciliation gap.

## Edge Cases

### Zero Budget

When the budget amount is zero for an account:

- Percentage variance is mathematically undefined (division by zero).
- The variance engine returns an effectively infinite percentage (represented as `0` — see materiality handling).
- The absolute threshold is the only usable materiality criterion.
- Commentary notes that the account had no budget allocation.

### Negative Budget

When the budget amount is negative (e.g., budgeted loss, negative interest income):

- Percentage variance uses `|budget|` in the denominator to produce meaningful direction.
- A variance from a negative budget to a less negative actual is **favorable** (the outcome is better than expected).
- Materiality assessment uses absolute variance for threshold comparison.

### Mix of Favorable and Adverse

When an account has sub-accounts with mixed variance directions:

- **Net variance** may be small, masking significant individual variances.
- The materiality engine flags each sub-account independently.
- Aggregate commentary includes a note about mixed direction — "Revenue was \$50K favorable on Product A but \$40K adverse on Product B, net favorable \$10K."
- Root cause analysis investigates both directions separately.

### Zero Variance

When actual equals budget exactly (zero variance):

- The variance is **not material** (fails both thresholds).
- Bridge analysis returns an empty component list.
- Commentary may reference the account as "on plan" or "at budget."
- Zero variance is not exempt from investigation if the account had material variances in prior periods.

### Partial Period Data

When only partial actuals are available for a period:

- The variance may be misleading (appears favorable if actuals are incomplete).
- A data quality check flags periods with incomplete actuals.
- Commentary notes the data completeness issue.
- Confidence scoring is reduced for partial-period variances.
