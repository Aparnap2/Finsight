# Budget

## Business Meaning

A **Budget** is a financial plan for a defined period, typically a fiscal year, that establishes the expected revenues, costs, and expenditures against which actual performance is measured. Budgets serve as the primary benchmark for variance analysis and financial control within FinSight. The system supports multiple budget versions to accommodate the evolving nature of financial planning throughout the fiscal year.

## Budget Versions

### Original Budget

The baseline financial plan approved at the start of the fiscal year. The original budget:

- Is established before the fiscal year begins.
- Serves as the anchor for all variance analysis unless superseded by a revised budget.
- Remains immutable once the fiscal year starts — it is never modified after the first day of the fiscal year.
- Is the default comparison target in the variance engine.

### Revised Budget

An updated version of the budget that reflects approved changes to the original plan. Revisions occur when:

- **Organic growth/contraction**: Revenue targets are adjusted based on new market intelligence.
- **Cost restructuring**: Department budgets are reallocated.
- **Scope changes**: New business lines are added or existing ones discontinued.

Key rules:

- Each revision increments the version number.
- The revision reason and approver are recorded in the audit trail.
- The original budget remains visible alongside revisions for comparison.
- Variance analysis can be run against either the original or revised budget (default: most recent revised).

### Adjusted Budget

The original or revised budget adjusted for:

- **Actual volume** (flexible budgeting): Revenue and variable cost targets are recalculated using actual volumes.
- **Calendar differences**: Adjustments for the number of working days in a period.
- **FX rates**: Budget restated at actual exchange rates.

The adjusted budget is used for **volume-independent variance analysis** — when the goal is to isolate price, efficiency, and mix effects from volume effects.

## Periods

### Period Granularity

| Period Type | Granularity | Used For |
|-------------|-------------|----------|
| **Monthly** | Individual calendar/fiscal months | Operational reporting, detailed variance tracking |
| **Quarterly** | Fiscal quarters | Executive reporting, investor communications |
| **Annual** | Full fiscal year | Strategic planning, annual performance assessment |

### Period Accumulation

Budget values roll up hierarchically:

```
Annual Budget = Sum(Q1 + Q2 + Q3 + Q4)
Quarterly Budget = Sum(Month1 + Month2 + Month3)
```

Period boundaries are defined by the company's `FiscalCalendar`. A budget can be created at annual granularity and automatically distributed to monthly periods, or built from monthly components that roll up to quarterly and annual totals.

## Allocation Rules

Budget allocation distributes annual budget targets across periods and departments. Supported allocation methods:

| Method | Description | Use Case |
|--------|-------------|----------|
| **Straight-Line** | Even distribution across all periods | Fixed costs, rent |
| **Weighted** | Distribution based on weighting factors (e.g., seasonal patterns) | Revenue, marketing spend |
| **Driver-Based** | Distribution proportional to driver values (e.g., headcount, units) | Variable costs, COGS |
| **Manual** | Period-by-period entry | Ad-hoc or project-based budgets |
| **Prior Year** | Scaled from prior year actuals | Stable, recurring expenses |

## Budget vs. Actual Comparison

### Standard Comparison

```
Variance Amount = Actual - Budget
Variance Percentage = (Actual - Budget) / |Budget| × 100
```

A positive variance is **favorable** for revenue accounts (actual > budget) and **adverse** for cost accounts (actual > budget). Direction is determined by the account type configuration.

### Flexible Budget Comparison (Volume-Adjusted)

When comparing against an adjusted (flexible) budget:

```
Flexible Budget = Budgeted Rate × Actual Volume
Variance = Actual - Flexible Budget
```

This isolates **price/efficiency** variance from **volume** variance (which is absorbed by the flexible budget adjustment).

## Edge Cases

### Mid-Year Reforecast

When a mid-year reforecast occurs (e.g., at Q2):

1. A new **Revised Budget** version is created.
2. The remaining periods (H2) are reforecasted with updated assumptions.
3. Historical periods (H1) retain their original budget values.
4. The variance engine uses the revised budget for future periods while comparing actuals against the original budget for closed periods.
5. Commentary notes the revision date and reason.

### Zero-Based Budget

When a budget allocates zero to an account:

1. Any actual spend against that account generates a 100% variance (since budget is zero).
2. The variance engine detects the zero-budget condition and flags it.
3. Materiality assessment for zero-budget variances uses only the absolute threshold (percentage threshold is effectively infinite).
4. The commentary pipeline treats zero-budget variances with higher scrutiny, as they may indicate unplanned spend or budget omissions.
5. A degraded mode flag (`ZERO_BUDGET_VARIANCE`) is raised.

### Budget Carry-Forward

When unspent budget from one period is carried forward to a subsequent period:

1. The carry-forward amount is recorded as an adjustment to the target period's budget.
2. Both the original budget and the adjusted budget (with carry-forward) are tracked.
3. Variance analysis can be run against either version.
4. Carry-forward amounts are attributed to the original period's variance narrative.

### Multi-Currency Budget

When a budget is set in one currency but actuals arrive in another:

1. The budget is converted using the budgeted exchange rate (set at budget creation time).
2. FX variance is calculated as: `(Actual Rate - Budget Rate) × Actual Volume`.
3. The FX component is separated from volume and price variances in the bridge analysis.

### Department Reorganization

When departments are restructured mid-year:

1. Budget allocations are transferred from old to new departments via a budget adjustment.
2. The adjustment records the before-and-after department structure.
3. Variance analysis at the company level is unaffected; department-level analysis shows the reorganization.
4. Commentary for reorganized departments includes a note about the structural change.
