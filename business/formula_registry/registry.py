"""Formula Registry — populated catalog of every derived financial metric.

This module builds the authoritative ``FormulaRegistry`` singleton and
registers every formula defined in the FP&A business glossary
(``docs/13-business-knowledge/glossary.md``) and proposal
(``docs/13-business-knowledge/proposal.md``).

Formulas are registered in dependency order — source metrics first, then
simple derivatives, then composite metrics. Dependencies between formulas
use stable ``formula_id`` references.
"""

from __future__ import annotations

from datetime import date

from business.formula_registry.models import (
    FormulaCategory,
    FormulaDefinition,
    FormulaRegistry,
)

# ---------------------------------------------------------------------------
# Shared metadata
# ---------------------------------------------------------------------------

_VALID_FROM = date(2026, 1, 1)
_FPA_OWNER = "FP&A Team"
_CONTROLLER = "Controller"
_TREASURY = "Treasury"
_FINANCE = "Finance"

# ===========================================================================
# REVENUE FORMULAS
# ===========================================================================

# -- source metrics ---------------------------------------------------------

GROSS_REVENUE = FormulaDefinition(
    formula_id="gross_revenue",
    name="Gross Revenue",
    description="Total invoiced revenue before any deductions.",
    expression="Sum of all invoices before adjustments",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.REVENUE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "source"],
    source="formula_engine",
    sox_relevant=True,
)

RETURNS = FormulaDefinition(
    formula_id="returns",
    name="Returns",
    description="Value of products returned by customers.",
    expression="Sum of product return amounts",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.REVENUE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "source"],
    source="formula_engine",
    sox_relevant=True,
)

ALLOWANCES = FormulaDefinition(
    formula_id="allowances",
    name="Allowances",
    description="Customer allowances granted after sale.",
    expression="Sum of customer allowance amounts",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.REVENUE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "source"],
    source="formula_engine",
    sox_relevant=True,
)

DISCOUNTS = FormulaDefinition(
    formula_id="discounts",
    name="Discounts",
    description="Customer discounts and trade discounts.",
    expression="Sum of customer discount amounts",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.REVENUE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "source"],
    source="formula_engine",
    sox_relevant=True,
)

MRR = FormulaDefinition(
    formula_id="mrr",
    name="Monthly Recurring Revenue",
    description="Normalized monthly subscription revenue from customers.",
    expression="Sum of monthly subscription fees",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.REVENUE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["saas", "subscription", "source"],
    source="kpi_engine",
    sox_relevant=True,
)

TOTAL_NEW_BOOKINGS = FormulaDefinition(
    formula_id="total_new_bookings",
    name="Total New Bookings",
    description="Total value of new contracts or bookings closed in the period.",
    expression="Sum of new contract values",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.REVENUE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["crm", "sales", "source"],
    source="kpi_engine",
    sox_relevant=True,
)

NUMBER_OF_DEALS = FormulaDefinition(
    formula_id="number_of_deals",
    name="Number of Deals",
    description="Count of closed won deals in the period.",
    expression="Count of closed won opportunities",
    depends_on=[],
    data_type="Count",
    category=FormulaCategory.REVENUE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["crm", "sales", "source"],
    source="kpi_engine",
    sox_relevant=False,
)

TOTAL_HEADCOUNT = FormulaDefinition(
    formula_id="total_headcount",
    name="Total Headcount (FTE)",
    description="Number of active full-time equivalent employees.",
    expression="Count of active FTEs at period end",
    depends_on=[],
    data_type="Count",
    category=FormulaCategory.REVENUE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["hr", "workforce", "source"],
    source="manual",
    sox_relevant=False,
)

# -- derived revenue --------------------------------------------------------

NET_REVENUE = FormulaDefinition(
    formula_id="net_revenue",
    name="Net Revenue",
    description="Total revenue from operations after deducting returns, "
    "allowances, and discounts.",
    expression="GrossRevenue - Returns - Allowances - Discounts",
    depends_on=["gross_revenue", "returns", "allowances", "discounts"],
    data_type="Money",
    category=FormulaCategory.REVENUE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "core"],
    source="formula_engine",
    sox_relevant=True,
)

REVENUE_GROWTH_RATE = FormulaDefinition(
    formula_id="revenue_growth_rate",
    name="Revenue Growth Rate",
    description="Period-over-period percentage change in net revenue.",
    expression="((CurrentPeriodRevenue - PriorPeriodRevenue) / "
    "PriorPeriodRevenue) * 100",
    depends_on=["net_revenue"],
    data_type="Percentage",
    category=FormulaCategory.REVENUE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "growth", "board_report"],
    source="formula_engine",
    sox_relevant=True,
)

ARR = FormulaDefinition(
    formula_id="arr",
    name="Annual Recurring Revenue",
    description="Annualized value of subscription revenue from customers.",
    expression="MRR * 12",
    depends_on=["mrr"],
    data_type="Money",
    category=FormulaCategory.REVENUE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["saas", "subscription", "board_report"],
    source="kpi_engine",
    sox_relevant=True,
)

AVG_DEAL_SIZE = FormulaDefinition(
    formula_id="avg_deal_size",
    name="Average Deal Size",
    description="Average revenue per closed deal or customer contract.",
    expression="TotalNewBookings / NumberOfDeals",
    depends_on=["total_new_bookings", "number_of_deals"],
    data_type="Money",
    category=FormulaCategory.REVENUE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["crm", "sales", "kpi"],
    source="kpi_engine",
    sox_relevant=False,
)

REVENUE_PER_FTE = FormulaDefinition(
    formula_id="revenue_per_fte",
    name="Revenue per FTE",
    description="Net revenue divided by total headcount.",
    expression="NetRevenue / TotalHeadcount",
    depends_on=["net_revenue", "total_headcount"],
    data_type="Money",
    category=FormulaCategory.REVENUE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["efficiency", "productivity", "board_report"],
    source="kpi_engine",
    sox_relevant=False,
)

# ===========================================================================
# EXPENSE FORMULAS
# ===========================================================================

# -- source metrics ---------------------------------------------------------

DIRECT_MATERIALS = FormulaDefinition(
    formula_id="direct_materials",
    name="Direct Materials",
    description="Cost of raw materials used in production.",
    expression="Sum of raw material costs",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.EXPENSE,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "cogs", "source"],
    source="formula_engine",
    sox_relevant=True,
)

DIRECT_LABOR = FormulaDefinition(
    formula_id="direct_labor",
    name="Direct Labor",
    description="Labor costs directly attributable to production.",
    expression="Sum of production wages and related costs",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.EXPENSE,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "cogs", "source"],
    source="formula_engine",
    sox_relevant=True,
)

MANUFACTURING_OVERHEAD = FormulaDefinition(
    formula_id="manufacturing_overhead",
    name="Manufacturing Overhead",
    description="Indirect costs of production not traceable to specific units.",
    expression="Sum of indirect production costs",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.EXPENSE,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "cogs", "source"],
    source="formula_engine",
    sox_relevant=True,
)

SG_AND_A = FormulaDefinition(
    formula_id="sg_and_a",
    name="Selling, General & Administrative (SG&A)",
    description="Operating expenses related to sales and management functions.",
    expression="SalesExpenses + Marketing + Administrative + Rent + Utilities",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.EXPENSE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "source"],
    source="formula_engine",
    sox_relevant=True,
)

R_AND_D = FormulaDefinition(
    formula_id="r_and_d",
    name="Research & Development (R&D)",
    description="Expenses related to product development and innovation.",
    expression="EngineeringSalaries + Prototyping + LabExpenses + SoftwareTools",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.EXPENSE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "source"],
    source="formula_engine",
    sox_relevant=True,
)

DEPRECIATION_AMORTIZATION = FormulaDefinition(
    formula_id="depreciation_amortization",
    name="Depreciation & Amortization (D&A)",
    description="Non-cash expense allocating cost of assets over useful lives.",
    expression="(AssetCost - SalvageValue) / UsefulLife",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.EXPENSE,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "noncash", "source"],
    source="formula_engine",
    sox_relevant=True,
)

CAPEX = FormulaDefinition(
    formula_id="capex",
    name="Capital Expenditure (CAPEX)",
    description="Funds used to acquire or upgrade long-term physical assets.",
    expression="PurchasePrice + Installation + Transportation",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.EXPENSE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "capex", "source"],
    source="formula_engine",
    sox_relevant=True,
)

EMPLOYEE_COMPENSATION = FormulaDefinition(
    formula_id="employee_compensation",
    name="Employee Compensation",
    description="Total cost of employing staff including salary and benefits.",
    expression="BaseSalary + Benefits + PayrollTaxes + Bonuses + Equity",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.EXPENSE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["hr", "compensation", "source"],
    source="manual",
    sox_relevant=False,
)

TOTAL_RECRUITING_COST = FormulaDefinition(
    formula_id="total_recruiting_cost",
    name="Total Recruiting Cost",
    description="Sum of all recruiting and hiring expenses.",
    expression="Sum of all recruiting expenses",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.EXPENSE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["hr", "recruiting", "source"],
    source="manual",
    sox_relevant=False,
)

NUMBER_OF_HIRES = FormulaDefinition(
    formula_id="number_of_hires",
    name="Number of Hires",
    description="Count of new hires in the period.",
    expression="Count of new hires",
    depends_on=[],
    data_type="Count",
    category=FormulaCategory.EXPENSE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["hr", "recruiting", "source"],
    source="manual",
    sox_relevant=False,
)

# -- derived expense --------------------------------------------------------

COGS = FormulaDefinition(
    formula_id="cogs",
    name="Cost of Goods Sold (COGS)",
    description="Direct costs attributable to producing goods or services sold.",
    expression="DirectMaterials + DirectLabor + ManufacturingOverhead",
    depends_on=["direct_materials", "direct_labor", "manufacturing_overhead"],
    data_type="Money",
    category=FormulaCategory.EXPENSE,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "core"],
    source="formula_engine",
    sox_relevant=True,
)

OPEX = FormulaDefinition(
    formula_id="opex",
    name="Operating Expenses (OPEX)",
    description="Expenses incurred through normal business operations, "
    "excluding COGS.",
    expression="SG&A + R&D + Depreciation + Amortization",
    depends_on=["sg_and_a", "r_and_d", "depreciation_amortization"],
    data_type="Money",
    category=FormulaCategory.EXPENSE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "core"],
    source="formula_engine",
    sox_relevant=True,
)

COST_PER_HIRE = FormulaDefinition(
    formula_id="cost_per_hire",
    name="Cost per Hire",
    description="Average cost incurred to hire a new employee.",
    expression="TotalRecruitingCost / NumberOfHires",
    depends_on=["total_recruiting_cost", "number_of_hires"],
    data_type="Money",
    category=FormulaCategory.EXPENSE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["hr", "recruiting", "efficiency"],
    source="kpi_engine",
    sox_relevant=False,
)

RD_AS_PCT_OF_REVENUE = FormulaDefinition(
    formula_id="rd_as_pct_of_revenue",
    name="R&D as % of Revenue",
    description="Research and development spending as a percentage of net revenue.",
    expression="(R_D / NetRevenue) * 100",
    depends_on=["r_and_d", "net_revenue"],
    data_type="Percentage",
    category=FormulaCategory.EXPENSE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "efficiency", "board_report"],
    source="kpi_engine",
    sox_relevant=True,
)

# ===========================================================================
# PROFITABILITY FORMULAS
# ===========================================================================

# -- source metrics ---------------------------------------------------------

INTEREST_EXPENSE = FormulaDefinition(
    formula_id="interest_expense",
    name="Interest Expense",
    description="Cost of borrowing money, including interest on debt.",
    expression="Sum of interest payments on outstanding debt",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.PROFITABILITY,
    owner=_TREASURY,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "source"],
    source="formula_engine",
    sox_relevant=True,
)

INCOME_TAX = FormulaDefinition(
    formula_id="income_tax",
    name="Income Tax",
    description="Income tax expense for the period.",
    expression="Sum of income tax provisions",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.PROFITABILITY,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "source"],
    source="formula_engine",
    sox_relevant=True,
)

# -- derived profitability --------------------------------------------------

GROSS_PROFIT = FormulaDefinition(
    formula_id="gross_profit",
    name="Gross Profit",
    description="Revenue remaining after deducting cost of goods sold.",
    expression="NetRevenue - COGS",
    depends_on=["net_revenue", "cogs"],
    data_type="Money",
    category=FormulaCategory.PROFITABILITY,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "core"],
    source="formula_engine",
    sox_relevant=True,
)

GROSS_MARGIN = FormulaDefinition(
    formula_id="gross_margin",
    name="Gross Margin",
    description="Gross profit expressed as a percentage of net revenue.",
    expression="(NetRevenue - COGS) / NetRevenue * 100",
    depends_on=["net_revenue", "cogs"],
    data_type="Percentage",
    category=FormulaCategory.PROFITABILITY,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "core", "board_report"],
    source="formula_engine",
    sox_relevant=True,
)

EBIT = FormulaDefinition(
    formula_id="ebit",
    name="EBIT (Operating Income)",
    description="Earnings before interest and taxes — operating profit.",
    expression="Revenue - COGS - OPEX",
    depends_on=["net_revenue", "cogs", "opex"],
    data_type="Money",
    category=FormulaCategory.PROFITABILITY,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "core", "board_report"],
    source="formula_engine",
    sox_relevant=True,
)

NET_INCOME = FormulaDefinition(
    formula_id="net_income",
    name="Net Income",
    description="The bottom line: total revenue minus all expenses, taxes, "
    "and interest.",
    expression="EBIT - Interest - Taxes",
    depends_on=["ebit", "interest_expense", "income_tax"],
    data_type="Money",
    category=FormulaCategory.PROFITABILITY,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "core", "board_report"],
    source="formula_engine",
    sox_relevant=True,
)

EBITDA = FormulaDefinition(
    formula_id="ebitda",
    name="EBITDA",
    description="Earnings before interest, taxes, depreciation, and amortization.",
    expression="NetIncome + Interest + Taxes + D&A",
    depends_on=["net_income", "interest_expense", "income_tax",
                "depreciation_amortization"],
    data_type="Money",
    category=FormulaCategory.PROFITABILITY,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "core", "board_report"],
    source="formula_engine",
    sox_relevant=True,
)

NET_PROFIT_MARGIN = FormulaDefinition(
    formula_id="net_profit_margin",
    name="Net Profit Margin",
    description="Net income as a percentage of net revenue.",
    expression="NetIncome / NetRevenue * 100",
    depends_on=["net_income", "net_revenue"],
    data_type="Percentage",
    category=FormulaCategory.PROFITABILITY,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "core", "board_report"],
    source="formula_engine",
    sox_relevant=True,
)

OPERATING_MARGIN = FormulaDefinition(
    formula_id="operating_margin",
    name="Operating Margin",
    description="Operating income (EBIT) as a percentage of net revenue.",
    expression="EBIT / NetRevenue * 100",
    depends_on=["ebit", "net_revenue"],
    data_type="Percentage",
    category=FormulaCategory.PROFITABILITY,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "p&l", "core", "board_report"],
    source="formula_engine",
    sox_relevant=True,
)

# ===========================================================================
# BALANCE SHEET FORMULAS
# ===========================================================================

# -- source metrics ---------------------------------------------------------

CURRENT_ASSETS = FormulaDefinition(
    formula_id="current_assets",
    name="Current Assets",
    description="Assets that are expected to be converted to cash within one year.",
    expression="CashAndEquivalents + AccountsReceivable + Inventory + "
    "PrepaidExpenses + ShortTermInvestments",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.BALANCE_SHEET,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "balance_sheet", "source"],
    source="formula_engine",
    sox_relevant=True,
)

CURRENT_LIABILITIES = FormulaDefinition(
    formula_id="current_liabilities",
    name="Current Liabilities",
    description="Obligations due within one year.",
    expression="AccountsPayable + ShortTermDebt + AccruedLiabilities + "
    "DeferredRevenue",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.BALANCE_SHEET,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "balance_sheet", "source"],
    source="formula_engine",
    sox_relevant=True,
)

ACCOUNTS_RECEIVABLE = FormulaDefinition(
    formula_id="accounts_receivable",
    name="Accounts Receivable (AR)",
    description="Money owed by customers for delivered goods or services.",
    expression="Sum of unpaid customer invoices and credit memos",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.BALANCE_SHEET,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "balance_sheet", "ar", "source"],
    source="formula_engine",
    sox_relevant=True,
)

ACCOUNTS_PAYABLE = FormulaDefinition(
    formula_id="accounts_payable",
    name="Accounts Payable (AP)",
    description="Money owed to vendors for received goods or services.",
    expression="Sum of unpaid vendor invoices",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.BALANCE_SHEET,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "balance_sheet", "ap", "source"],
    source="formula_engine",
    sox_relevant=True,
)

INVENTORY = FormulaDefinition(
    formula_id="inventory",
    name="Inventory",
    description="Value of raw materials, work-in-progress, and finished goods.",
    expression="RawMaterials + WIP + FinishedGoods (at cost)",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.BALANCE_SHEET,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "balance_sheet", "source"],
    source="formula_engine",
    sox_relevant=True,
)

CASH_AND_EQUIVALENTS = FormulaDefinition(
    formula_id="cash_and_equivalents",
    name="Cash & Cash Equivalents",
    description="Liquid assets including cash, bank deposits, and "
    "short-term investments.",
    expression="Cash + BankBalances + MarketableSecurities (< 90 days)",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.BALANCE_SHEET,
    owner=_TREASURY,
    valid_from=_VALID_FROM,
    tags=["gaap", "balance_sheet", "liquidity", "source"],
    source="formula_engine",
    sox_relevant=True,
)

TOTAL_ASSETS = FormulaDefinition(
    formula_id="total_assets",
    name="Total Assets",
    description="Sum of all assets owned by the entity.",
    expression="CurrentAssets + NonCurrentAssets",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.BALANCE_SHEET,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "balance_sheet", "source"],
    source="formula_engine",
    sox_relevant=True,
)

TOTAL_LIABILITIES = FormulaDefinition(
    formula_id="total_liabilities",
    name="Total Liabilities",
    description="Sum of all liabilities owed by the entity.",
    expression="CurrentLiabilities + NonCurrentLiabilities",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.BALANCE_SHEET,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "balance_sheet", "source"],
    source="formula_engine",
    sox_relevant=True,
)

# -- derived balance sheet --------------------------------------------------

WORKING_CAPITAL = FormulaDefinition(
    formula_id="working_capital",
    name="Working Capital",
    description="Measure of short-term liquidity and operational efficiency.",
    expression="CurrentAssets - CurrentLiabilities",
    depends_on=["current_assets", "current_liabilities"],
    data_type="Money",
    category=FormulaCategory.BALANCE_SHEET,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "liquidity", "core"],
    source="formula_engine",
    sox_relevant=True,
)

SHAREHOLDERS_EQUITY = FormulaDefinition(
    formula_id="shareholders_equity",
    name="Shareholders' Equity",
    description="Residual interest in assets after deducting liabilities.",
    expression="TotalAssets - TotalLiabilities",
    depends_on=["total_assets", "total_liabilities"],
    data_type="Money",
    category=FormulaCategory.BALANCE_SHEET,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "balance_sheet", "core"],
    source="formula_engine",
    sox_relevant=True,
)

# ===========================================================================
# LIQUIDITY FORMULAS
# ===========================================================================

CURRENT_RATIO = FormulaDefinition(
    formula_id="current_ratio",
    name="Current Ratio",
    description="Measure of ability to pay short-term obligations with "
    "short-term assets.",
    expression="CurrentAssets / CurrentLiabilities",
    depends_on=["current_assets", "current_liabilities"],
    data_type="Ratio",
    category=FormulaCategory.LIQUIDITY,
    owner=_TREASURY,
    valid_from=_VALID_FROM,
    tags=["gaap", "liquidity", "health"],
    source="formula_engine",
    sox_relevant=True,
)

QUICK_RATIO = FormulaDefinition(
    formula_id="quick_ratio",
    name="Quick Ratio (Acid-Test)",
    description="Measure of ability to pay short-term obligations with "
    "most liquid assets.",
    expression="(CurrentAssets - Inventory) / CurrentLiabilities",
    depends_on=["current_assets", "inventory", "current_liabilities"],
    data_type="Ratio",
    category=FormulaCategory.LIQUIDITY,
    owner=_TREASURY,
    valid_from=_VALID_FROM,
    tags=["gaap", "liquidity", "health"],
    source="formula_engine",
    sox_relevant=True,
)

DSO = FormulaDefinition(
    formula_id="dso",
    name="Days Sales Outstanding (DSO)",
    description="Average number of days to collect payment after a sale.",
    expression="(AccountsReceivable / NetRevenue) * NumberOfDays",
    depends_on=["accounts_receivable", "net_revenue"],
    data_type="Days",
    category=FormulaCategory.LIQUIDITY,
    owner=_TREASURY,
    valid_from=_VALID_FROM,
    tags=["gaap", "liquidity", "efficiency", "ar"],
    source="formula_engine",
    sox_relevant=True,
)

DPO = FormulaDefinition(
    formula_id="dpo",
    name="Days Payable Outstanding (DPO)",
    description="Average number of days to pay vendor invoices.",
    expression="(AccountsPayable / COGS) * NumberOfDays",
    depends_on=["accounts_payable", "cogs"],
    data_type="Days",
    category=FormulaCategory.LIQUIDITY,
    owner=_TREASURY,
    valid_from=_VALID_FROM,
    tags=["gaap", "liquidity", "efficiency", "ap"],
    source="formula_engine",
    sox_relevant=True,
)

DIO = FormulaDefinition(
    formula_id="dio",
    name="Days Inventory Outstanding (DIO)",
    description="Average number of days to sell inventory.",
    expression="(Inventory / COGS) * NumberOfDays",
    depends_on=["inventory", "cogs"],
    data_type="Days",
    category=FormulaCategory.LIQUIDITY,
    owner=_TREASURY,
    valid_from=_VALID_FROM,
    tags=["gaap", "liquidity", "efficiency", "inventory"],
    source="formula_engine",
    sox_relevant=True,
)

CASH_CONVERSION_CYCLE = FormulaDefinition(
    formula_id="cash_conversion_cycle",
    name="Cash Conversion Cycle (CCC)",
    description="Number of days cash is tied up in operations.",
    expression="DSO + DIO - DPO",
    depends_on=["dso", "dio", "dpo"],
    data_type="Days",
    category=FormulaCategory.LIQUIDITY,
    owner=_TREASURY,
    valid_from=_VALID_FROM,
    tags=["gaap", "liquidity", "efficiency", "board_report"],
    source="formula_engine",
    sox_relevant=True,
)

# ===========================================================================
# CASH FLOW FORMULAS
# ===========================================================================

# -- source metrics ---------------------------------------------------------

NON_CASH_CHARGES = FormulaDefinition(
    formula_id="non_cash_charges",
    name="Non-Cash Charges",
    description="Expenses recorded in the income statement that do not "
    "involve cash outflows.",
    expression="DepreciationAndAmortization + StockBasedCompensation + "
    "DeferredTaxes + ImpairmentCharges",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.CASH_FLOW,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "cash_flow", "source"],
    source="formula_engine",
    sox_relevant=True,
)

CHANGE_IN_WORKING_CAPITAL = FormulaDefinition(
    formula_id="change_in_working_capital",
    name="Change in Working Capital",
    description="Period-over-period change in net working capital.",
    expression="WorkingCapitalEndPeriod - WorkingCapitalStartPeriod",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.CASH_FLOW,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "cash_flow", "source"],
    source="formula_engine",
    sox_relevant=True,
)

MONTHLY_CASH_OUTFLOWS = FormulaDefinition(
    formula_id="monthly_cash_outflows",
    name="Monthly Cash Outflows",
    description="Total cash payments made in a month.",
    expression="Sum of all cash disbursements",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.CASH_FLOW,
    owner=_TREASURY,
    valid_from=_VALID_FROM,
    tags=["treasury", "liquidity", "source"],
    source="manual",
    sox_relevant=True,
)

MONTHLY_CASH_INFLOWS = FormulaDefinition(
    formula_id="monthly_cash_inflows",
    name="Monthly Cash Inflows",
    description="Total cash receipts collected in a month.",
    expression="Sum of all cash receipts",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.CASH_FLOW,
    owner=_TREASURY,
    valid_from=_VALID_FROM,
    tags=["treasury", "liquidity", "source"],
    source="manual",
    sox_relevant=True,
)

# -- derived cash flow ------------------------------------------------------

OPERATING_CASH_FLOW = FormulaDefinition(
    formula_id="operating_cash_flow",
    name="Operating Cash Flow (OCF)",
    description="Cash generated from core business operations.",
    expression="NetIncome + NonCashCharges - ChangeInWorkingCapital",
    depends_on=["net_income", "non_cash_charges", "change_in_working_capital"],
    data_type="Money",
    category=FormulaCategory.CASH_FLOW,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "cash_flow", "core", "board_report"],
    source="formula_engine",
    sox_relevant=True,
)

FREE_CASH_FLOW = FormulaDefinition(
    formula_id="free_cash_flow",
    name="Free Cash Flow (FCF)",
    description="Cash available after capital expenditures.",
    expression="OperatingCashFlow - CAPEX",
    depends_on=["operating_cash_flow", "capex"],
    data_type="Money",
    category=FormulaCategory.CASH_FLOW,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "cash_flow", "core", "board_report"],
    source="formula_engine",
    sox_relevant=True,
)

BURN_RATE = FormulaDefinition(
    formula_id="burn_rate",
    name="Burn Rate",
    description="Rate at which a company consumes cash, typically monthly.",
    expression="MonthlyCashOutflows - MonthlyCashInflows",
    depends_on=["monthly_cash_outflows", "monthly_cash_inflows"],
    data_type="Money",
    category=FormulaCategory.CASH_FLOW,
    owner=_TREASURY,
    valid_from=_VALID_FROM,
    tags=["treasury", "liquidity", "startup"],
    source="manual",
    sox_relevant=False,
)

CASH_RUNWAY = FormulaDefinition(
    formula_id="cash_runway",
    name="Cash Runway",
    description="Number of months before cash is exhausted at current "
    "burn rate.",
    expression="CurrentCashBalance / MonthlyBurnRate",
    depends_on=["cash_and_equivalents", "burn_rate"],
    data_type="Ratio",
    category=FormulaCategory.CASH_FLOW,
    owner=_TREASURY,
    valid_from=_VALID_FROM,
    tags=["treasury", "liquidity", "startup"],
    source="manual",
    sox_relevant=False,
)

# ===========================================================================
# EFFICIENCY FORMULAS
# ===========================================================================

# -- source metrics ---------------------------------------------------------

AVERAGE_INVENTORY = FormulaDefinition(
    formula_id="average_inventory",
    name="Average Inventory",
    description="Average inventory value over a period.",
    expression="(BeginningInventory + EndingInventory) / 2",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.EFFICIENCY,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "efficiency", "source"],
    source="formula_engine",
    sox_relevant=True,
)

# -- derived efficiency -----------------------------------------------------

ASSET_TURNOVER = FormulaDefinition(
    formula_id="asset_turnover",
    name="Asset Turnover",
    description="Efficiency measure of how effectively assets generate revenue.",
    expression="NetRevenue / TotalAssets",
    depends_on=["net_revenue", "total_assets"],
    data_type="Ratio",
    category=FormulaCategory.EFFICIENCY,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["gaap", "efficiency", "board_report"],
    source="formula_engine",
    sox_relevant=True,
)

INVENTORY_TURNS = FormulaDefinition(
    formula_id="inventory_turns",
    name="Inventory Turns",
    description="Number of times inventory is sold and replaced over a period.",
    expression="COGS / AverageInventory",
    depends_on=["cogs", "average_inventory"],
    data_type="Ratio",
    category=FormulaCategory.EFFICIENCY,
    owner=_CONTROLLER,
    valid_from=_VALID_FROM,
    tags=["gaap", "efficiency", "inventory"],
    source="formula_engine",
    sox_relevant=True,
)

# ===========================================================================
# BUDGETING FORMULAS
# ===========================================================================

BUDGET_ATTAINMENT_RATE = FormulaDefinition(
    formula_id="budget_attainment_rate",
    name="Budget Attainment Rate",
    description="Percentage of budgeted amount that was actually achieved.",
    expression="(ActualAmount / BudgetAmount) * 100",
    depends_on=[],
    data_type="Percentage",
    category=FormulaCategory.BUDGETING,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["budgeting", "variance", "core"],
    source="formula_engine",
    sox_relevant=True,
)

BUDGET_UTILIZATION_RATE = FormulaDefinition(
    formula_id="budget_utilization_rate",
    name="Budget Utilization Rate",
    description="Percentage of budget that has been spent or consumed.",
    expression="(SpentAmount / BudgetAmount) * 100",
    depends_on=[],
    data_type="Percentage",
    category=FormulaCategory.BUDGETING,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["budgeting", "spend", "core"],
    source="formula_engine",
    sox_relevant=True,
)

FORECAST_ACCURACY_MAPE = FormulaDefinition(
    formula_id="forecast_accuracy_mape",
    name="Forecast Accuracy (MAPE)",
    description="Measure of how closely the forecast matched actual results, "
    "expressed as Mean Absolute Percentage Error.",
    expression="Mean(|Actual - Forecast| / |Actual|) * 100",
    depends_on=[],
    data_type="Percentage",
    category=FormulaCategory.BUDGETING,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["forecasting", "accuracy", "kpi"],
    source="kpi_engine",
    sox_relevant=True,
)

# ===========================================================================
# VARIANCE FORMULAS
# ===========================================================================

VARIANCE_AMOUNT = FormulaDefinition(
    formula_id="variance_amount",
    name="Variance Amount",
    description="The absolute difference between actual results and the "
    "budget or forecast.",
    expression="Actual - Budget",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.VARIANCE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["variance", "core"],
    source="formula_engine",
    sox_relevant=True,
)

VARIANCE_PCT = FormulaDefinition(
    formula_id="variance_pct",
    name="Variance %",
    description="The variance expressed as a percentage of budget.",
    expression="(Actual - Budget) / ABS(Budget) * 100",
    depends_on=[],
    data_type="Percentage",
    category=FormulaCategory.VARIANCE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["variance", "core"],
    source="formula_engine",
    sox_relevant=True,
)

VOLUME_VARIANCE = FormulaDefinition(
    formula_id="volume_variance",
    name="Volume Variance",
    description="Portion of variance attributable to changes in quantity or volume.",
    expression="(ActualVolume - BudgetVolume) * BudgetPrice",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.VARIANCE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["variance", "driver_analysis"],
    source="formula_engine",
    sox_relevant=True,
)

PRICE_VARIANCE = FormulaDefinition(
    formula_id="price_variance",
    name="Price Variance",
    description="Portion of variance attributable to changes in price or rate.",
    expression="(ActualPrice - BudgetPrice) * ActualVolume",
    depends_on=[],
    data_type="Money",
    category=FormulaCategory.VARIANCE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["variance", "driver_analysis"],
    source="formula_engine",
    sox_relevant=True,
)

MATERIALITY_SCORE = FormulaDefinition(
    formula_id="materiality_score",
    name="Materiality Score",
    description="Composite score indicating whether a variance exceeds "
    "defined thresholds of significance.",
    expression="Computed from absolute and percentage thresholds",
    depends_on=["variance_amount"],
    data_type="Ratio",
    category=FormulaCategory.VARIANCE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["variance", "materiality", "governance"],
    source="formula_engine",
    sox_relevant=True,
)

TREND_SCORE = FormulaDefinition(
    formula_id="trend_score",
    name="Trend Score",
    description="Score indicating the direction and acceleration of "
    "a variance over consecutive periods.",
    expression="Computed from multi-period trend analysis",
    depends_on=[],
    data_type="Ratio",
    category=FormulaCategory.VARIANCE,
    owner=_FPA_OWNER,
    valid_from=_VALID_FROM,
    tags=["variance", "trend", "analytics"],
    source="kpi_engine",
    sox_relevant=False,
)

# ===========================================================================
# BUILD & EXPORT THE REGISTRY
# ===========================================================================

_ALL_FORMULAS: list[FormulaDefinition] = [
    # Revenue — source
    GROSS_REVENUE,
    RETURNS,
    ALLOWANCES,
    DISCOUNTS,
    MRR,
    TOTAL_NEW_BOOKINGS,
    NUMBER_OF_DEALS,
    TOTAL_HEADCOUNT,
    # Revenue — derived
    NET_REVENUE,
    REVENUE_GROWTH_RATE,
    ARR,
    AVG_DEAL_SIZE,
    REVENUE_PER_FTE,
    # Expense — source
    DIRECT_MATERIALS,
    DIRECT_LABOR,
    MANUFACTURING_OVERHEAD,
    SG_AND_A,
    R_AND_D,
    DEPRECIATION_AMORTIZATION,
    CAPEX,
    EMPLOYEE_COMPENSATION,
    TOTAL_RECRUITING_COST,
    NUMBER_OF_HIRES,
    # Expense — derived
    COGS,
    OPEX,
    COST_PER_HIRE,
    RD_AS_PCT_OF_REVENUE,
    # Profitability — source
    INTEREST_EXPENSE,
    INCOME_TAX,
    # Profitability — derived
    GROSS_PROFIT,
    GROSS_MARGIN,
    EBIT,
    NET_INCOME,
    EBITDA,
    NET_PROFIT_MARGIN,
    OPERATING_MARGIN,
    # Balance Sheet — source
    CURRENT_ASSETS,
    CURRENT_LIABILITIES,
    ACCOUNTS_RECEIVABLE,
    ACCOUNTS_PAYABLE,
    INVENTORY,
    CASH_AND_EQUIVALENTS,
    TOTAL_ASSETS,
    TOTAL_LIABILITIES,
    # Balance Sheet — derived
    WORKING_CAPITAL,
    SHAREHOLDERS_EQUITY,
    # Liquidity
    CURRENT_RATIO,
    QUICK_RATIO,
    DSO,
    DPO,
    DIO,
    CASH_CONVERSION_CYCLE,
    # Cash Flow — source
    NON_CASH_CHARGES,
    CHANGE_IN_WORKING_CAPITAL,
    MONTHLY_CASH_OUTFLOWS,
    MONTHLY_CASH_INFLOWS,
    # Cash Flow — derived
    OPERATING_CASH_FLOW,
    FREE_CASH_FLOW,
    BURN_RATE,
    CASH_RUNWAY,
    # Efficiency
    AVERAGE_INVENTORY,
    ASSET_TURNOVER,
    INVENTORY_TURNS,
    # Budgeting
    BUDGET_ATTAINMENT_RATE,
    BUDGET_UTILIZATION_RATE,
    FORECAST_ACCURACY_MAPE,
    # Variance
    VARIANCE_AMOUNT,
    VARIANCE_PCT,
    VOLUME_VARIANCE,
    PRICE_VARIANCE,
    MATERIALITY_SCORE,
    TREND_SCORE,
]


def build_registry() -> FormulaRegistry:
    """Construct and populate the master Formula Registry.

    Registers every formula in dependency order, then freezes the
    registry to prevent further modification.

    Returns:
        A fully populated and frozen ``FormulaRegistry`` instance.
    """
    registry = FormulaRegistry()
    registry.register_many(_ALL_FORMULAS)
    registry.freeze()
    return registry


# Singleton: the authoritative formula registry for the platform.
REGISTRY: FormulaRegistry = build_registry()
