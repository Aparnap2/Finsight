# Driver

## Business Meaning

A **Driver** is a measurable business factor that causally influences financial outcomes. Drivers form the foundation of driver-based planning, forecasting, and sensitivity analysis. By modeling the relationship between drivers and financial accounts, FinSight enables scenario modeling, what-if analysis, and root cause decomposition that goes beyond simple period-over-period comparison.

Drivers connect operational metrics (e.g., headcount, units sold, customer count) to financial outcomes (e.g., revenue, COGS, OpEx) through defined formulas and ratios.

## Business Driver Categories

### Revenue Drivers

| Driver | Definition | Impact on |
|--------|-----------|-----------|
| **Headcount (HC)** | Number of revenue-generating employees (e.g., sales reps, consultants) | Revenue capacity |
| **Annual Recurring Revenue (ARR)** | Normalized annual subscription revenue | SaaS revenue growth |
| **Average Revenue Per Unit (ARPU)** | Revenue per customer or unit | Revenue per volume |
| **Customer Count** | Total active customers | Subscription revenue |
| **Win Rate** | % of opportunities closed | Sales revenue |
| **Pricing Index** | Weighted average price index | Price variance |

### Cost Drivers

| Driver | Definition | Impact on |
|--------|-----------|-----------|
| **FTE (Full-Time Equivalent)** | Number of employees | Salary, benefits, occupancy |
| **Occupancy Cost per FTE** | Average facility cost per employee | Facility expenses |
| **Units Produced** | Production volume | Direct materials, labor |
| **Unit Cost** | Cost per unit of input | COGS |
| **Third-Party Spend** | External services and contractors | Professional services |
| **IT Cost per Employee** | Average IT infrastructure cost | IT expenses |

### Operational Drivers

| Driver | Definition | Impact on |
|--------|-----------|-----------|
| **Square Footage** | Office/facility space | Rent, utilities, maintenance |
| **Machine Hours** | Production equipment runtime | Manufacturing overhead |
| **Customer Churn Rate** | % of customers lost per period | Revenue retention |
| **Days Sales Outstanding (DSO)** | Average collection period | Working capital |

## Driver-Based Planning

Driver-based planning (DBP) builds financial plans by defining mathematical relationships between drivers and accounts:

```
Revenue (4100) = Sales Headcount (9101) × Quota per Rep × Win Rate × ASP
COGS (5100)   = Units Sold (9102) × Unit Material Cost (account level)
OpEx (6100)   = Total HC (9100) × Cost per FTE
```

### Formula Structure

Each driver-to-account relationship is defined as:

```
Account Value = Driver Value × Factor
```

Where:
- **Account Value**: The financial outcome to be budgeted or forecasted.
- **Driver Value**: The operational input from the driver engine.
- **Factor**: The conversion ratio (e.g., cost per FTE, quota per rep).

Factors can be:
- **Fixed**: Set as a constant (e.g., standard cost per unit).
- **Variable**: Function of another driver or time period (e.g., cost per FTE with inflation index).
- **Formula-based**: Complex expression involving multiple drivers.

## Driver Trees (Hierarchical Relationships)

Drivers can form hierarchical trees where high-level drivers decompose into sub-drivers:

```
Total Headcount
├── Revenue-Generating HC
│   ├── Sales HC
│   ├── Services HC
│   └── Customer Success HC
├── R&D HC
│   ├── Product HC
│   └── Engineering HC
└── G&A HC
    ├── Finance HC
    ├── HR HC
    └── Legal HC
```

### Tree Rules

1. **Top-down propagation**: Changes to a parent driver cascade to all children (e.g., reducing Total Headcount by 10% reduces all sub-categories).
2. **Bottom-up rollup**: Changes to child drivers roll up to the parent (e.g., adding 5 Sales HC increases Revenue HC increases Total HC).
3. **Consistency enforcement**: The sum of child driver values must equal the parent value (within a configurable tolerance).
4. **Override support**: Any node in the tree can be individually overridden, with the override being tracked and versioned.

## Sensitivity Analysis

Sensitivity analysis measures how changes in driver assumptions affect financial outcomes. The bridge analysis engine (`finance/driver_engine/bridge_analysis.py`) implements deterministic sensitivity decomposition.

### Revenue Sensitivity

For revenue accounts, sensitivity is expressed as:

```
Δ Revenue = Price Effect + Volume Effect + Mix Effect + FX Effect
```

Each effect is calculated by varying one driver while holding others constant (ceteris paribus analysis).

### Cost Sensitivity

For cost accounts:

```
Δ Cost = One-Time Effect + Timing Effect + Scope Effect + Rate Effect
```

### Confidence Scoring

Each sensitivity component carries a confidence score:

- **With driver data** (actual volume, actual rates): confidence = 0.85
- **Without driver data** (heuristic-based split): confidence = 0.50-0.60
- **When bridge does not reconcile**: confidence is reduced by 30%

## Edge Cases

### Driver Correlations

When two drivers are correlated (e.g., headcount and occupancy cost), changing one driver independently may produce misleading sensitivity results:

- The system flags correlated drivers during sensitivity analysis.
- Commentary notes potential correlation bias.
- Scenario modeling can group correlated drivers into "linked scenarios" where they move together.
- Correlation coefficients are computed from historical data when available.

### Non-Linear Drivers

Some driver-to-account relationships are non-linear:

- **Economies of scale**: Doubling production volume may increase COGS by only 80%.
- **Step costs**: Adding headcount may require a new floor of office space, creating a step change in occupancy costs.
- **Saturation effects**: Increasing marketing spend beyond a point yields diminishing returns.

Non-linear relationships are modeled using:
1. **Piecewise linear functions**: Different factors apply to different volume ranges.
2. **Formula-based expressions**: Custom mathematical expressions in the formula registry.
3. **Manual overrides**: For scenarios where the relationship changes fundamentally.

### Driver Data Gaps

When driver data is missing for a period:

1. The driver-based model falls back to trend-based extrapolation.
2. A degraded mode flag (`INSUFFICIENT_DRIVER_DATA`) is raised.
3. Confidence scoring for affected accounts is reduced.
4. Commentary notes the data gap and the extrapolation method used.

### New Drivers

When introducing a new driver (e.g., a new operational metric):

1. Historical data may not exist — calibration uses management estimates.
2. The driver is not included in trend-based forecasting until sufficient history accumulates.
3. Confidence scoring for the new driver starts at a lower baseline.
4. Driver relationships (factors) are flagged as unvalidated until verified against actual outcomes.
