# Company

## Business Meaning

A **Company** represents the legal entity being analyzed within the FinSight platform. It is the top-level organizational anchor — all financial data, budgets, forecasts, variances, and commentary are scoped to a single company context. Every analysis run, every assertion, and every recommendation originates from and belongs to exactly one company.

In multi-entity deployments, each legal entity is modeled as an independent company. Consolidation across entities is handled at the reporting layer, not by merging company records.

## Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `id` | `str` | Unique tenant identifier (e.g., `"CF001"`). Used to scope all pipeline operations. |
| `name` | `str` | Legal entity name for display and reporting purposes. |
| `currency` | `str` | Base reporting currency (ISO 4217 code, e.g., `"USD"`, `"EUR"`). |
| `fiscal_year_start` | `date` | Start date of the fiscal year (month and day). Determines fiscal period boundaries. |
| `base_currency` | `str` | Immutable base currency established at company creation. All monetary values stored in this currency. |

## Relationships

```
Company
├── has one ChartOfAccounts      — defines the account structure
├── has many Departments         — organizational units for cost/revenue allocation
├── has one FiscalCalendar       — defines all fiscal periods (monthly/quarterly/annual)
├── has many BudgetVersions      — original, revised, and adjusted budgets
├── has many Forecasts           — rolling, driver-based, and scenario forecasts
├── has many VarianceAnalyses    — period-over-period and actual-vs-budget comparisons
└── has many MaterialityConfigs  — optional tenant-specific threshold overrides
```

### Key Relationship Details

- **ChartOfAccounts**: A company has exactly one active chart of accounts. Account codes are unique within this chart.
- **Departments**: Departments are child entities that consume and generate financial data. A department belongs to exactly one company.
- **FiscalCalendar**: The calendar defines period boundaries for the fiscal year. All transactions are posted to specific fiscal periods.

## Rules

### One Active Fiscal Year

A company can have only one active fiscal year at any time. When transitioning between fiscal years (e.g., moving from FY2025 to FY2026), the prior year must be closed before the new year becomes active. This ensures period-over-period comparisons reference stable time boundaries.

### Base Currency Is Immutable

The `base_currency` is set at company creation and **cannot be changed**. This constraint exists because:

- All monetary values in the system are stored in the base currency.
- Historical financial data would require revaluation if the base currency changed.
- Foreign currency transactions are converted to the base currency at the transaction date using prevailing exchange rates.

Attempting to modify `base_currency` after creation is rejected at the domain validation layer.

## Edge Cases

### Multi-Entity Consolidation

When analyzing a group of legal entities (e.g., a parent company with subsidiaries), each entity is modeled as a separate Company record. Consolidation is performed at the reporting layer:

1. **Intercompany eliminations** must be processed before consolidation.
2. **Currency conversion** applies to entities with different base currencies.
3. **Minority interests** and **non-controlling interests** are calculated during consolidation, not stored per-entity.
4. **Consolidated commentary** references individual entity analyses but may adjust conclusions for eliminations.

The FinSight pipeline operates on one company at a time. Cross-entity consolidation is an orchestration concern handled upstream of the per-company pipeline.

### Currency Conversion

When actual data arrives in a foreign currency:

1. The ingestion layer converts amounts to the company's base currency using the spot rate for the transaction date (or period-end rate for accruals).
2. The variance engine can analyze FX impact as a separate variance component via the bridge analysis engine (`BridgeComponent.FX`).
3. FX variance is decomposed as: `(current_rate - prior_rate) × current_amount / current_rate`.
4. A **degraded mode** flag is raised if FX rate data is missing or stale.

### Company Deactivation

When a company is deactivated (e.g., divestiture, dissolution):

1. No new pipeline runs are permitted.
2. Existing analyses and commentary remain readable.
3. Historical data is preserved for audit and compliance purposes.
4. The company record's status transitions to `inactive` — it is never hard-deleted.

### Fiscal Year Changes

If a company changes its fiscal year start date (e.g., shifting from a calendar year to a fiscal year):

1. A transitional "stub" period is created for the gap.
2. All existing fiscal periods are re-indexed.
3. Prior-year comparisons for the transition year use the stub period as the anchor point.
4. The change is recorded in the company's audit trail.
