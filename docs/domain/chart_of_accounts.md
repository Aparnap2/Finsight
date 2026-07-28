# Chart of Accounts

## Business Meaning

The **Chart of Accounts (COA)** defines the structured hierarchy of financial accounts used to classify and organize all financial transactions within a company. It is the foundational taxonomy upon which budgeting, forecasting, variance analysis, and financial commentary are built. Every financial datum in FinSight — every actual, budget, and forecast value — is tagged to an account from the chart.

## Structure

Accounts are organized in a hierarchical tree structure by type. The hierarchy follows standard accounting conventions:

```
ChartOfAccounts
├── Revenue (4xxx)
│   ├── Product Revenue (4100)
│   ├── Service Revenue (4200)
│   └── Other Revenue (4300)
├── Cost of Goods Sold (5xxx)
│   ├── Direct Materials (5100)
│   ├── Direct Labor (5200)
│   └── Manufacturing Overhead (5300)
├── Operating Expenses (6xxx)
│   ├── Sales & Marketing (6100)
│   ├── Research & Development (6200)
│   ├── General & Administrative (6300)
│   └── Depreciation & Amortization (6400)
├── Other Income/Expenses (7xxx)
│   ├── Interest Income (7100)
│   ├── Interest Expense (7200)
│   └── Foreign Exchange (7300)
├── Balance Sheet (8xxx)
│   ├── Current Assets (8100)
│   ├── Fixed Assets (8200)
│   ├── Current Liabilities (8300)
│   └── Equity (8400)
└── Statistical / Non-Financial (9xxx)
    ├── Headcount (9100)
    └── Square Footage (9200)
```

### Account Levels

| Level | Description | Example |
|-------|-------------|---------|
| **Group** | Top-level classification | `4xxx` — Revenue |
| **Category** | Mid-level grouping | `41xx` — Product Revenue |
| **Account** | Individual ledger account | `4100` — Software Licenses |
| **Sub-account** | Granular breakdown (optional) | `4101` — SaaS Subscriptions |

## Account Types

### Revenue (4xxx)
Income from primary business activities. Includes product sales, service fees, subscription revenue, and licensing income. Revenue accounts are **credit-normal** — credits increase the balance.

### Cost of Goods Sold (5xxx)
Direct costs attributable to producing goods or delivering services. Includes materials, labor, and manufacturing overhead. COGS accounts are **debit-normal** — debits increase the balance.

### Operating Expenses (6xxx)
Indirect costs required to run the business. Includes sales & marketing, R&D, G&A, and depreciation. OpEx accounts are **debit-normal**.

### Other Income/Expenses (7xxx)
Non-operating income and expenses such as interest, FX gains/losses, and one-time items. The sensitivity tier defaults to **LOW** for these accounts.

### Balance Sheet (8xxx)
Asset, liability, and equity accounts. Balance sheet accounts are **not typically variance-analyzed** through the standard pipeline but may be included for cash flow analysis or working capital commentary.

### Statistical / Non-Financial (9xxx)
Non-monetary measures such as headcount (FTE), square footage, and units sold. These accounts use integer or decimal values rather than monetary amounts.

## Account Code Conventions

Account codes are 4-digit numeric codes organized by range:

| Range | Category | Sensitivity Tier |
|-------|----------|-----------------|
| 4xxx | Revenue | CRITICAL |
| 5xxx | Cost of Goods Sold | HIGH |
| 6xxx | Operating Expenses | MEDIUM |
| 7xxx | Other Income/Expenses | LOW |
| 8xxx | Balance Sheet | LOW |
| 9xxx | Statistical / Non-Financial | LOW |

This range convention drives the **default materiality tier mapping** (`DEFAULT_TIER_MAP` in the Materiality Engine). Accounts matching `4*` are classified as CRITICAL, `5*` as HIGH, `6*` as MEDIUM, and all others as LOW.

## Rules

### Unique Account Codes

Every account must have a unique code within the company's chart of accounts. Duplicate codes are rejected at the domain validation layer. This uniqueness constraint ensures that variance analysis can unambiguously match budget and actual records to a single account.

### Standard Account Ranges

New accounts must be created within the standard numeric ranges defined above. Creating an account outside these ranges (e.g., an account code of `1000`) is permitted but triggers a **degraded mode** notification in the materiality engine, as the account will default to MEDIUM tier classification via pattern fallback.

### Account Deactivation

Accounts cannot be deleted — they can only be **deactivated**. Deactivation rules:

1. Deactivated accounts are excluded from new budget and forecast creation.
2. Existing historical data linked to deactivated accounts remains accessible.
3. Variance analysis may include deactivated accounts if the comparison period contains data for them.
4. Re-activating an account restores it to full functionality.

## Edge Cases

### New Account Creation

When a new account is created:

1. It must have a valid 4-digit numeric code.
2. It must fall within an existing account range (or be explicitly assigned a tier).
3. If the code matches a default pattern (e.g., `4*`), the materiality engine automatically assigns the corresponding tier.
4. No historical data exists for the account — variance analysis produces "no prior year" or "new account" labels rather than numerical variances.
5. Budget and forecast entries for the new account start empty until populated.

### Account Deactivation

When an account is deactivated mid-fiscal-year:

1. Budgets already allocated to the account remain in the system for variance tracking.
2. Actuals posted to the account before deactivation remain valid.
3. Future pipeline runs include deactivated accounts only if the comparison period has data for them.
4. The deactivation reason and date are recorded in the account's audit trail.

### Account Reclassification

When an account's code changes (e.g., renumbering from `5100` to `5200`):

1. The account retains its historical data under the old code.
2. New data is posted under the new code.
3. Variance analysis across the change point shows a break in the time series — the commentary pipeline flags this as a **data quality note**.

### Merged Accounts

When two accounts are merged:

1. Both source accounts are deactivated.
2. A new account is created (or an existing one is reused).
3. Historical data remains queryable against the original accounts.
4. The recommendation engine may flag merged accounts as a data quality consideration during trend analysis.
