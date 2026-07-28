# Financial Glossary

Terms used throughout FinSight's codebase, documentation, and domain logic.

---

## A–C

| Term | Definition | Usage in FinSight |
|------|------------|-------------------|
| **Actuals** | Recorded financial results for a period — what actually happened. | Primary input to the variance pipeline. Stored in `Actual` model (`shared/models/database.py`). Compared against budget and forecast. |
| **ARR** | Annual Recurring Revenue. The annualized value of subscription revenue from customers. | KPI computed by the formula engine. Used for SaaS FP&A scenarios. |
| **Budget** | Planned financial targets for a period, set before the period begins. | Stored in `BudgetLine` model. Compared against actuals to compute variances. |
| **Burn Rate** | The rate at which a company consumes cash, typically expressed per month. | Used in runway analysis and forecast engine. Computed from operating cash outflows. |
| **CAPEX** | Capital Expenditure. Funds used to acquire or upgrade physical assets (property, equipment, infrastructure). | Account classification in the chart of accounts. Has different variance treatment than OPEX. |
| **Chart of Accounts** | A structured list of all accounts used by an organization to record financial transactions. | Defines the account hierarchy used for variance grouping and materiality tiering. |
| **COGS** | Cost of Goods Sold. Direct costs attributable to the production of goods sold. | Account category mapped to HIGH sensitivity tier in materiality rules. |
| **Cost Center** | A department or unit within an organization that incurs costs but does not directly generate revenue. | Used for variance grouping and departmental reporting. |

---

## D–F

| Term | Definition | Usage in FinSight |
|------|------------|-------------------|
| **Department** | Organizational unit used for reporting and budgeting. | Each variance is attributed to a department. Used in context building and commentary grouping. |
| **Driver** | A variable or factor that influences financial performance (e.g., headcount, sales volume, pricing). | Foundation of the driver tree analysis. The driver engine (`finance/driver_engine/`) decomposes variances into component drivers. |
| **EBITDA** | Earnings Before Interest, Taxes, Depreciation, and Amortization. A measure of operating profitability. | Computed by the formula engine as a ratio-type KPI. |
| **FP&A** | Financial Planning & Analysis. The practice of budgeting, forecasting, and analyzing financial performance to support business decisions. | The entire domain that FinSight operates within. |
| **Forecast** | A projection of future financial performance, typically updated more frequently than the budget. | Used in the forecast engine (`finance/forecast_engine/`) for what-if analysis and rolling forecasts. |
| **Favorable Variance** | A variance that benefits the organization: revenue higher than budget, or costs lower than budget. | Classification in the variance engine. Positive revenue variance and negative cost variance are both favorable. |

---

## G–M

| Term | Definition | Usage in FinSight |
|------|------------|-------------------|
| **GL** | General Ledger. The complete record of all financial transactions over a company's lifecycle. | Source of truth for actuals data. The `GLAccount` model maps to the chart of accounts. |
| **Gross Margin** | (Revenue − COGS) / Revenue × 100. The percentage of revenue retained after direct costs. | Margin-type KPI computed by the formula engine. |
| **Materiality** | A threshold determining whether a variance is significant enough to warrant investigation. | Core concept in the variance pipeline. Configured via `MaterialityConfig` with tiered sensitivity levels (CRITICAL, HIGH, MEDIUM, LOW). |
| **MRR** | Monthly Recurring Revenue. The normalized monthly subscription revenue. | KPI computed by the formula engine. Used for SaaS FP&A. |
| **MoM** | Month-over-Month. Period-over-period comparison between consecutive months. | Growth calculation type in the formula engine. |
| **Net Margin** | Net Income / Revenue × 100. The percentage of revenue that becomes profit after all expenses. | Margin-type KPI computed by the formula engine. |

---

## O–R

| Term | Definition | Usage in FinSight |
|------|------------|-------------------|
| **OPEX** | Operating Expenditure. Day-to-day expenses required to run the business (salaries, rent, utilities). | Account classification mapped to MEDIUM sensitivity tier. |
| **Operating Margin** | Operating Income / Revenue × 100. Profitability from core operations, excluding financing and taxes. | Margin-type KPI computed by the formula engine. |
| **QoQ** | Quarter-over-Quarter. Period-over-period comparison between consecutive quarters. | Growth calculation type in the formula engine. |
| **Rolling Forecast** | A forecast that extends forward continuously (e.g., always looking 12 months ahead), updated each period. | Planning model supported by the forecast engine. Distinct from static annual budgets. |
| **Run Rate** | The extrapolation of current financial performance to project annual figures. | Analysis type: "If we continue this pace, what's the annual result?" Used in commentary. |
| **Runway** | The amount of time a company can continue operating before running out of cash, given its current burn rate. | Computed from burn rate and cash balance. Used in going-concern analysis. |
| **Revenue** | Income generated from the sale of goods or services. | Primary account category mapped to CRITICAL sensitivity tier in materiality rules. |

---

## S–Z

| Term | Definition | Usage in FinSight |
|------|------------|-------------------|
| **Scenario** | A what-if model that applies adjustments to base financial data to explore alternative outcomes. | Managed by the scenario engine (`finance/scenario_engine/`). Used for sensitivity and what-if analysis. |
| **Sensitivity Analysis** | A technique that varies one driver at a time to measure the impact on outcomes. | Scenario subtype. The scenario engine supports applying individual adjustments to measure sensitivity. |
| **Unfavorable Variance (Adverse)** | A variance that harms the organization: revenue lower than budget, or costs higher than budget. | Classification in the variance engine triggers deeper investigation. |
| **Variance** | The difference between two values (actual vs budget, actual vs forecast, current vs prior period). | Central concept. Computed deterministically by the variance engine. |
| **Waterfall Analysis** | A decomposition of total variance into component parts, showing how each driver contributes to the net difference. | Implemented in `finance/driver_engine/bridge_analysis.py` as bridge decomposition (price, volume, mix, FX). |
| **YTD** | Year-to-Date. The cumulative period from the start of the fiscal year to the current date. | Period aggregation type. Used in reporting and context building. |
| **YoY** | Year-over-Year. Period-over-period comparison between the same period across different years. | Growth calculation type in the formula engine. |
| **ZBB** | Zero-Based Budgeting. A budgeting method where every expense must be justified for each new period, starting from zero. | Budgeting methodology that affects how budget data is structured and analyzed. |
