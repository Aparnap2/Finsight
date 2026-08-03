# Business Glossary — FP&A Primer

> **Part of:** Business Knowledge Layer  
> **Scope:** 50 essential FP&A finance concepts  
> **Status:** Draft — pending business review  
> **Classification:** Internal  

This glossary defines the core financial concepts that FinSight models. Every term in this document should eventually have a corresponding entry in the machine-readable `BusinessGlossary` registry.

---

## Revenue Concepts

### 1. Net Revenue
Total revenue from operations after deducting returns, allowances, and discounts.

- **Formula:** `Gross Revenue − Returns − Allowances − Discounts`
- **Typical source system:** ERP (NetSuite, SAP, Oracle)
- **Aliases:** Revenue, Sales, Top Line, Net Sales
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 2. Gross Revenue
Total invoiced revenue before any deductions.

- **Formula:** `Sum of all invoices before adjustments`
- **Typical source system:** Billing system, ERP
- **Aliases:** Billings, Gross Sales
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 3. Recurring Revenue (ARR / MRR)
Annualized or monthly value of subscription revenue from customers.

- **Formula (ARR):** `MRR × 12`
- **Formula (MRR):** `Sum of monthly subscription fees`
- **Typical source system:** Subscription management (Stripe, Zuora)
- **Aliases:** Annual Recurring Revenue, Monthly Recurring Revenue
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 4. Revenue Growth Rate
Period-over-period percentage change in net revenue.

- **Formula:** `((Current Period Revenue − Prior Period Revenue) / Prior Period Revenue) × 100`
- **Typical source system:** Computed (formula engine)
- **Aliases:** Revenue Growth %, YoY Growth
- **Classification:** Internal
- **SOX-relevant:** Yes

### 5. Average Deal Size
Average revenue per closed deal or customer contract.

- **Formula:** `Total New Bookings / Number of Deals Closed`
- **Typical source system:** CRM (Salesforce, HubSpot)
- **Aliases:** ACV (Annual Contract Value), Deal Size
- **Classification:** Confidential
- **SOX-relevant:** No

### 6. Revenue per FTE
Net revenue divided by total headcount.

- **Formula:** `Net Revenue / Total Headcount (FTE)`
- **Typical source system:** Computed (cross-system)
- **Aliases:** Revenue per Employee
- **Classification:** Internal
- **SOX-relevant:** No

### 7. Deferred Revenue
Cash received for services not yet delivered. A liability on the balance sheet.

- **Formula:** `Sum of unearned revenue balances`
- **Typical source system:** ERP, billing system
- **Aliases:** Unearned Revenue, Unbilled Revenue (opposite)
- **Classification:** Confidential
- **SOX-relevant:** Yes

---

## Expense Concepts

### 8. Cost of Goods Sold (COGS)
Direct costs attributable to producing goods or services sold.

- **Formula:** `Direct Materials + Direct Labor + Manufacturing Overhead`
- **Typical source system:** ERP, inventory management
- **Aliases:** Cost of Sales
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 9. Operating Expenses (OPEX)
Expenses incurred through normal business operations, excluding COGS.

- **Formula:** `SG&A + R&D + Depreciation + Amortization`
- **Typical source system:** ERP
- **Aliases:** OpEx, Operating Costs
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 10. Selling, General & Administrative (SG&A)
Operating expenses related to sales and management functions.

- **Formula:** `Sales Expenses + Marketing + Administrative + Rent + Utilities`
- **Typical source system:** ERP
- **Aliases:** SG&A, Sales & Marketing (when split out)
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 11. Research & Development (R&D)
Expenses related to product development and innovation.

- **Formula:** `Engineering salaries + Prototyping + Lab expenses + Software tools`
- **Typical source system:** ERP, HR system
- **Aliases:** Product Development
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 12. Capital Expenditure (CAPEX)
Funds used to acquire or upgrade long-term physical assets.

- **Formula:** `Purchase price of asset + Installation + Transportation`
- **Typical source system:** ERP, fixed asset module
- **Aliases:** CapEx, Fixed Asset Investment
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 13. Employee Compensation
Total cost of employing staff, including salary, benefits, and taxes.

- **Formula:** `Base Salary + Benefits + Payroll Taxes + Bonuses + Equity`
- **Typical source system:** HRIS / Payroll (Workday, ADP)
- **Aliases:** Total Rewards, Total Compensation
- **Classification:** Restricted (PII)
- **SOX-relevant:** No

### 14. Depreciation & Amortization (D&A)
Non-cash expense allocating the cost of assets over their useful lives.

- **Formula:** `(Asset Cost − Salvage Value) / Useful Life`
- **Typical source system:** Fixed asset ledger
- **Aliases:** D&A, Depreciation, Amortization
- **Classification:** Confidential
- **SOX-relevant:** Yes

---

## Profitability Metrics

### 15. Gross Profit
Revenue remaining after deducting COGS.

- **Formula:** `Net Revenue − COGS`
- **Typical source system:** Computed (formula engine)
- **Aliases:** Gross Income
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 16. Gross Margin
Gross profit expressed as a percentage of revenue.

- **Formula:** `(Net Revenue − COGS) / Net Revenue × 100`
- **Typical source system:** Computed (formula engine)
- **Aliases:** Gross Margin %
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 17. EBITDA
Earnings Before Interest, Taxes, Depreciation, and Amortization.

- **Formula:** `Net Income + Interest + Taxes + D&A`
- **Typical source system:** Computed (formula engine)
- **Aliases:** Operating Cash Flow Proxy
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 18. EBIT
Earnings Before Interest and Taxes (operating profit).

- **Formula:** `Revenue − COGS − OPEX`
- **Typical source system:** Computed (formula engine)
- **Aliases:** Operating Income, Operating Profit
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 19. Net Income
The bottom line: total revenue minus all expenses, taxes, and interest.

- **Formula:** `EBIT − Interest − Taxes`
- **Typical source system:** Computed (formula engine)
- **Aliases:** Net Profit, Net Earnings, The Bottom Line
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 20. Net Profit Margin
Net income as a percentage of revenue.

- **Formula:** `Net Income / Net Revenue × 100`
- **Typical source system:** Computed (formula engine)
- **Aliases:** Net Margin, Return on Sales
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 21. Operating Margin
Operating income (EBIT) as a percentage of revenue.

- **Formula:** `EBIT / Net Revenue × 100`
- **Typical source system:** Computed (formula engine)
- **Aliases:** Operating Profit Margin
- **Classification:** Confidential
- **SOX-relevant:** Yes

---

## Balance Sheet Items

### 22. Cash & Cash Equivalents
Liquid assets including cash on hand, bank deposits, and short-term investments.

- **Formula:** `Cash + Bank Balances + Marketable Securities (< 90 days)`
- **Typical source system:** Treasury system, ERP
- **Aliases:** Cash, Liquid Assets
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 23. Accounts Receivable (AR)
Money owed by customers for delivered goods or services.

- **Formula:** `Sum of unpaid customer invoices`
- **Typical source system:** ERP, AR sub-ledger
- **Aliases:** Receivables, Trade Debtors
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 24. Accounts Payable (AP)
Money owed to vendors for received goods or services.

- **Formula:** `Sum of unpaid vendor invoices`
- **Typical source system:** ERP, AP sub-ledger
- **Aliases:** Payables, Trade Creditors
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 25. Inventory
Value of raw materials, work-in-progress, and finished goods.

- **Formula:** `Raw Materials + WIP + Finished Goods (at cost)`
- **Typical source system:** Inventory management, ERP
- **Aliases:** Stock, Merchandise Inventory
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 26. Shareholders' Equity
Residual interest in assets after deducting liabilities.

- **Formula:** `Total Assets − Total Liabilities`
- **Typical source system:** ERP, equity management
- **Aliases:** Equity, Net Worth, Stockholders' Equity
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 27. Working Capital
Measure of short-term liquidity and operational efficiency.

- **Formula:** `Current Assets − Current Liabilities`
- **Typical source system:** Computed (balance sheet)
- **Aliases:** Net Working Capital
- **Classification:** Confidential
- **SOX-relevant:** Yes

---

## Cash Flow Concepts

### 28. Operating Cash Flow (OCF)
Cash generated from core business operations.

- **Formula:** `Net Income + Non-Cash Charges − Change in Working Capital`
- **Typical source system:** Cash flow statement, ERP
- **Aliases:** Cash from Operations, CFO
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 29. Free Cash Flow (FCF)
Cash available after capital expenditures.

- **Formula:** `Operating Cash Flow − CAPEX`
- **Typical source system:** Computed (cash flow)
- **Aliases:** FCF, Free Cash
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 30. Burn Rate
Rate at which a company consumes cash, typically monthly.

- **Formula:** `Monthly Operating Cash Outflows − Monthly Operating Cash Inflows`
- **Typical source system:** Computed (cash flow)
- **Aliases:** Cash Burn, Net Burn
- **Classification:** Confidential
- **SOX-relevant:** No

### 31. Cash Runway
Number of months before cash is exhausted at current burn rate.

- **Formula:** `Current Cash Balance / Monthly Burn Rate`
- **Typical source system:** Computed (cash flow)
- **Aliases:** Runway, Cash Runway (Months)
- **Classification:** Confidential
- **SOX-relevant:** No

### 32. Days Sales Outstanding (DSO)
Average number of days to collect payment after a sale.

- **Formula:** `(Accounts Receivable / Net Revenue) × Number of Days`
- **Typical source system:** Computed (AR analysis)
- **Aliases:** DSO, Collection Period
- **Classification:** Internal
- **SOX-relevant:** Yes

---

## Budgeting Concepts

### 33. Budget
Planned financial targets for a period, set before the period begins.

- **Definition:** A financial plan approved by management that allocates resources and sets performance targets.
- **Typical source system:** FP&A tool, spreadsheet, ERP budgeting module
- **Aliases:** Operating Budget, Financial Plan
- **Classification:** Confidential
- **SOX-relevant:** No

### 34. Original Budget
The initial budget approved at the start of the fiscal year.

- **Definition:** The baseline budget against which actuals are compared. Changes only through formal reforecast.
- **Typical source system:** FP&A tool
- **Aliases:** Baseline Budget, Approved Budget
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 35. Revised Budget
An updated budget reflecting approved changes during the year.

- **Definition:** The current working budget that incorporates reforecasts, reallocations, and approved adjustments.
- **Typical source system:** FP&A tool
- **Aliases:** Current Budget, Reforecast
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 36. Zero-Based Budgeting (ZBB)
Budgeting methodology requiring every expense to be justified each period.

- **Definition:** A budgeting process where all expenses must be justified from zero, rather than incrementing from prior periods.
- **Typical source system:** FP&A tool
- **Aliases:** ZBB, Zero-Base Budgeting
- **Classification:** Internal
- **SOX-relevant:** No

### 37. Budget Attainment Rate
Percentage of budgeted amount that was actually achieved.

- **Formula:** `(Actual Amount / Budget Amount) × 100`
- **Typical source system:** Computed (variance analysis)
- **Aliases:** Budget Utilization, Budget Achievement
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 38. Budget Cycle
The annual process of creating, reviewing, approving, and monitoring the budget.

- **Definition:** The end-to-end timeline from budget preparation through final approval and periodic review.
- **Typical source system:** Process / calendar
- **Aliases:** Planning Cycle, Budget Season
- **Classification:** Internal
- **SOX-relevant:** No

### 39. Reforecast
An updated forecast that replaces the budget for remaining periods.

- **Definition:** A mid-cycle update to financial projections, typically more frequent than the annual budget cycle.
- **Typical source system:** FP&A tool
- **Aliases:** Rolling Forecast, Updated Forecast
- **Classification:** Confidential
- **SOX-relevant:** No

---

## Variance Analysis

### 40. Variance
The difference between actual results and the budget or forecast.

- **Formula:** `Actual Amount − Budget Amount`
- **Typical source system:** Computed (variance engine)
- **Aliases:** Budget Variance, Actual vs. Budget
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 41. Favorable Variance
A variance that benefits the organization.

- **Definition:** Revenue higher than budget, or costs lower than budget. Takes the sign convention: positive revenue variance is favorable; negative cost variance is favorable.
- **Typical source system:** Computed (variance engine)
- **Aliases:** Favourable Variance, Positive Variance
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 42. Unfavorable Variance
A variance that harms the organization.

- **Definition:** Revenue lower than budget, or costs higher than budget. Opposite of favorable.
- **Typical source system:** Computed (variance engine)
- **Aliases:** Adverse Variance, Negative Variance
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 43. Material Variance
A variance exceeding defined thresholds of significance.

- **Definition:** A variance that exceeds both an absolute threshold (e.g., $50K) and a percentage threshold (e.g., 10%). Material variances trigger review and commentary requirements.
- **Typical source system:** Computed (materiality engine)
- **Aliases:** Significant Variance, Exception
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 44. Variance Percentage
The variance expressed as a percentage of the budget/plan.

- **Formula:** `(Actual − Budget) / ABS(Budget) × 100`
- **Typical source system:** Computed (variance engine)
- **Aliases:** Variance %, Percent Variance
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 45. Volume Variance
The portion of variance attributable to changes in quantity/volume.

- **Formula:** `(Actual Volume − Budget Volume) × Budget Price`
- **Typical source system:** Computed (driver analysis)
- **Aliases:** Quantity Variance
- **Classification:** Confidential
- **SOX-relevant:** Yes

### 46. Price Variance
The portion of variance attributable to changes in price/rate.

- **Formula:** `(Actual Price − Budget Price) × Actual Volume`
- **Typical source system:** Computed (driver analysis)
- **Aliases:** Rate Variance, Spending Variance (for costs)
- **Classification:** Confidential
- **SOX-relevant:** Yes

---

## Forecasting Concepts

### 47. Rolling Forecast
A continuously updated forecast that extends a fixed number of periods into the future.

- **Definition:** A forecast methodology where each month/quarter a new period is added and the oldest is dropped, maintaining a constant forward-looking horizon.
- **Typical source system:** FP&A tool
- **Aliases:** Continuous Forecast, Rolling Projection
- **Classification:** Confidential
- **SOX-relevant:** No

### 48. Driver-Based Forecasting
A forecasting methodology using operational drivers to project financial outcomes.

- **Definition:** Financial projections built by modelling relationships between operational metrics (headcount, units sold) and financial outcomes, rather than extrapolating from history.
- **Typical source system:** FP&A tool, driver models
- **Aliases:** Driver Model, Driver Tree
- **Classification:** Confidential
- **SOX-relevant:** No

### 49. Forecast Accuracy
Measure of how closely the forecast matched actual results.

- **Formula (MAPE):** `Mean(|Actual − Forecast| / |Actual|) × 100`
- **Typical source system:** Computed (forecast engine)
- **Aliases:** Forecast Error, MAPE (Mean Absolute Percentage Error)
- **Classification:** Internal
- **SOX-relevant:** Yes

### 50. Scenario Analysis
Evaluation of financial outcomes under different assumptions.

- **Definition:** A modelling technique that evaluates financial performance under multiple sets of assumptions (base case, upside, downside) to understand range of possible outcomes.
- **Typical source system:** FP&A tool, scenario engine
- **Aliases:** What-If Analysis, Sensitivity Analysis
- **Classification:** Confidential
- **SOX-relevant:** No

---

## Appendix: Category Summary

| Category | Count | Entries |
|----------|-------|---------|
| Revenue Concepts | 7 | #1–7 |
| Expense Concepts | 7 | #8–14 |
| Profitability Metrics | 7 | #15–21 |
| Balance Sheet Items | 6 | #22–27 |
| Cash Flow Concepts | 5 | #28–32 |
| Budgeting Concepts | 7 | #33–39 |
| Variance Analysis | 7 | #40–46 |
| Forecasting Concepts | 4 | #47–50 |

## Appendix: Data Classification Distribution

| Classification | Count | Percentage |
|---------------|-------|------------|
| Public | 0 | 0% |
| Internal | 5 | 10% |
| Confidential | 40 | 80% |
| Restricted (PII) | 1 | 2% |
| Confidential + SOX | 32 | 64% |

---

*This glossary was compiled from US GAAP, common FP&A practice, and FinSight domain model audit. Every term should have a corresponding registry entry in the Business Knowledge Layer. Last updated: 2026-07-30.*
