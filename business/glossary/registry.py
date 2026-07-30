"""Populated Business Glossary registry — 75+ financial terms.

This module instantiates a :class:`GlossaryRegistry` with the full set of
canonical FP&A terms. The registry is built from the source glossary in
``docs/13-business-knowledge/glossary.md`` and extended with additional
revenue, expense, balance-sheet, cash-flow, and SaaS-metric terms.

Usage::

    from business.glossary.registry import GLOSSARY

    entry = GLOSSARY.lookup("glossary.revenue.net")
    assert entry is not None
"""

from datetime import date

from business.glossary.models import (
    DataClassification,
    GlossaryCategory,
    GlossaryEntry,
    GlossaryRegistry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TODAY = date(2026, 7, 30)


def _entry(
    term_id: str,
    term: str,
    definition: str,
    category: GlossaryCategory,
    data_type: str,
    source_system: str,
    classification: DataClassification,
    aliases: list[str] | None = None,
    formula: str | None = None,
    sox_relevant: bool = False,
    pii: bool = False,
    owner: str = "FP&A Team",
    steward: str = "Data Governance",
    tags: list[str] | None = None,
    version: str = "1.0.0",
    url: str | None = None,
) -> GlossaryEntry:
    """Create a GlossaryEntry with sensible defaults."""
    return GlossaryEntry(
        term_id=term_id,
        term=term,
        aliases=aliases or [],
        definition=definition,
        category=category,
        formula=formula,
        data_type=data_type,
        source_system=source_system,
        classification=classification,
        sox_relevant=sox_relevant,
        pii=pii,
        owner=owner,
        steward=steward,
        tags=tags or [],
        version=version,
        valid_from=_TODAY,
        url=url,
    )


# ===================================================================
# REVENUE CONCEPTS  (7 original + 3 additional = 10)
# ===================================================================

_REVENUE: list[GlossaryEntry] = [
    _entry(
        term_id="glossary.revenue.net",
        term="Net Revenue",
        definition=(
            "Total revenue from operations after deducting returns, "
            "allowances, and discounts."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Money",
        source_system="ERP (NetSuite, SAP, Oracle)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Revenue", "Sales", "Top Line", "Net Sales"],
        formula="Gross Revenue − Returns − Allowances − Discounts",
        tags=["gaap", "p&l", "kpi"],
    ),
    _entry(
        term_id="glossary.revenue.gross",
        term="Gross Revenue",
        definition="Total invoiced revenue before any deductions.",
        category=GlossaryCategory.REVENUE,
        data_type="Money",
        source_system="Billing system, ERP",
        classification="confidential",
        sox_relevant=True,
        aliases=["Billings", "Gross Sales"],
        formula="Sum of all invoices before adjustments",
        tags=["gaap", "p&l"],
    ),
    _entry(
        term_id="glossary.revenue.recurring",
        term="Recurring Revenue (ARR / MRR)",
        definition=(
            "Annualized or monthly value of subscription revenue from customers. "
            "ARR is the annualized run-rate; MRR is the monthly recurring value."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Money",
        source_system="Subscription management (Stripe, Zuora)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Annual Recurring Revenue", "Monthly Recurring Revenue", "ARR", "MRR"],
        formula="ARR = MRR × 12; MRR = Sum of monthly subscription fees",
        tags=["saas", "kpi", "subscription"],
    ),
    _entry(
        term_id="glossary.revenue.growth_rate",
        term="Revenue Growth Rate",
        definition=(
            "Period-over-period percentage change in net revenue, measuring "
            "the company's top-line expansion rate."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Percentage",
        source_system="Computed (formula engine)",
        classification="internal",
        sox_relevant=True,
        aliases=["Revenue Growth %", "YoY Growth"],
        formula="((Current Period Revenue − Prior Period Revenue) / Prior Period Revenue) × 100",
        tags=["kpi", "growth", "board_report"],
    ),
    _entry(
        term_id="glossary.revenue.average_deal_size",
        term="Average Deal Size",
        definition=(
            "Average revenue per closed deal or customer contract, "
            "commonly measured as Annual Contract Value (ACV)."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Money",
        source_system="CRM (Salesforce, HubSpot)",
        classification="confidential",
        aliases=["ACV", "Annual Contract Value", "Deal Size"],
        formula="Total New Bookings / Number of Deals Closed",
        tags=["saas", "sales", "kpi"],
    ),
    _entry(
        term_id="glossary.revenue.per_fte",
        term="Revenue per FTE",
        definition=(
            "Net revenue divided by total headcount, measuring workforce "
            "productivity in generating revenue."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Money",
        source_system="Computed (cross-system)",
        classification="internal",
        aliases=["Revenue per Employee"],
        formula="Net Revenue / Total Headcount (FTE)",
        tags=["kpi", "efficiency", "productivity"],
    ),
    _entry(
        term_id="glossary.revenue.deferred",
        term="Deferred Revenue",
        definition=(
            "Cash received for services not yet delivered or earned. "
            "Recorded as a liability on the balance sheet until the "
            "revenue recognition criteria are met."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Money",
        source_system="ERP, billing system",
        classification="confidential",
        sox_relevant=True,
        aliases=["Unearned Revenue", "Deferred Income"],
        formula="Sum of unearned revenue balances",
        tags=["gaap", "balance_sheet", "revenue_recognition"],
    ),
    _entry(
        term_id="glossary.revenue.unbilled_ar",
        term="Unbilled Accounts Receivable",
        definition=(
            "Revenue that has been recognized but not yet invoiced to the "
            "customer. Arises when performance obligations are satisfied "
            "before billing occurs."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Money",
        source_system="ERP, billing system",
        classification="confidential",
        sox_relevant=True,
        aliases=["Unbilled AR", "Unbilled Receivables", "Accrued Revenue"],
        formula="Sum of recognized revenue not yet invoiced",
        tags=["gaap", "revenue_recognition", "balance_sheet"],
    ),
    _entry(
        term_id="glossary.revenue.contract_asset",
        term="Contract Asset",
        definition=(
            "Right to consideration from a customer for goods or services "
            "transferred but not yet invoiced, conditional on something "
            "other than the passage of time."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Money",
        source_system="ERP (ASC 606 / IFRS 15 module)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Unbilled Revenue (ASC 606)"],
        tags=["gaap", "ifrs", "revenue_recognition", "asc_606"],
        url="https://www.fasb.org/asc/606",
    ),
    _entry(
        term_id="glossary.revenue.contract_liability",
        term="Contract Liability",
        definition=(
            "Obligation to transfer goods or services to a customer for "
            "which the entity has received consideration. Includes deferred "
            "revenue under ASC 606 terminology."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Money",
        source_system="ERP (ASC 606 / IFRS 15 module)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Deferred Revenue (ASC 606)", "Customer Deposit"],
        tags=["gaap", "ifrs", "revenue_recognition", "asc_606"],
    ),
]


# ===================================================================
# EXPENSE CONCEPTS  (7 original + 4 additional = 11)
# ===================================================================

_EXPENSE: list[GlossaryEntry] = [
    _entry(
        term_id="glossary.expense.cogs",
        term="Cost of Goods Sold (COGS)",
        definition=(
            "Direct costs attributable to producing goods or services sold, "
            "including materials, labor, and manufacturing overhead."
        ),
        category=GlossaryCategory.EXPENSE,
        data_type="Money",
        source_system="ERP, inventory management",
        classification="confidential",
        sox_relevant=True,
        aliases=["Cost of Sales"],
        formula="Direct Materials + Direct Labor + Manufacturing Overhead",
        tags=["gaap", "p&l"],
    ),
    _entry(
        term_id="glossary.expense.opex",
        term="Operating Expenses (OPEX)",
        definition=(
            "Expenses incurred through normal business operations excluding "
            "COGS. Includes SG&A, R&D, and depreciation."
        ),
        category=GlossaryCategory.EXPENSE,
        data_type="Money",
        source_system="ERP",
        classification="confidential",
        sox_relevant=True,
        aliases=["OpEx", "Operating Costs"],
        formula="SG&A + R&D + Depreciation + Amortization",
        tags=["gaap", "p&l"],
    ),
    _entry(
        term_id="glossary.expense.sga",
        term="Selling, General & Administrative (SG&A)",
        definition=(
            "Operating expenses related to sales, marketing, and management "
            "functions, excluding R&D and COGS."
        ),
        category=GlossaryCategory.EXPENSE,
        data_type="Money",
        source_system="ERP",
        classification="confidential",
        sox_relevant=True,
        aliases=["SG&A", "Sales & Marketing"],
        formula="Sales Expenses + Marketing + Administrative + Rent + Utilities",
        tags=["gaap", "p&l"],
    ),
    _entry(
        term_id="glossary.expense.rd",
        term="Research & Development (R&D)",
        definition=(
            "Expenses related to product development, innovation, and "
            "engineering, including salaries and prototyping costs."
        ),
        category=GlossaryCategory.EXPENSE,
        data_type="Money",
        source_system="ERP, HR system",
        classification="confidential",
        sox_relevant=True,
        aliases=["Product Development", "R&D"],
        formula="Engineering salaries + Prototyping + Lab expenses + Software tools",
        tags=["gaap", "p&l"],
    ),
    _entry(
        term_id="glossary.expense.capex",
        term="Capital Expenditure (CAPEX)",
        definition=(
            "Funds used by a company to acquire, upgrade, or maintain "
            "long-term physical assets such as property, equipment, or technology."
        ),
        category=GlossaryCategory.EXPENSE,
        data_type="Money",
        source_system="ERP, fixed asset module",
        classification="confidential",
        sox_relevant=True,
        aliases=["CapEx", "Fixed Asset Investment"],
        formula="Purchase price of asset + Installation + Transportation",
        tags=["gaap", "cash_flow", "investing"],
    ),
    _entry(
        term_id="glossary.expense.compensation",
        term="Employee Compensation",
        definition=(
            "Total cost of employing staff, including base salary, benefits, "
            "payroll taxes, bonuses, and equity compensation."
        ),
        category=GlossaryCategory.EXPENSE,
        data_type="Money",
        source_system="HRIS / Payroll (Workday, ADP)",
        classification="restricted",
        sox_relevant=False,
        pii=True,
        aliases=["Total Rewards", "Total Compensation", "Payroll Cost"],
        formula="Base Salary + Benefits + Payroll Taxes + Bonuses + Equity",
        tags=["pii", "hr", "payroll"],
    ),
    _entry(
        term_id="glossary.expense.da",
        term="Depreciation & Amortization (D&A)",
        definition=(
            "Non-cash expense that allocates the cost of tangible and "
            "intangible assets over their useful lives."
        ),
        category=GlossaryCategory.EXPENSE,
        data_type="Money",
        source_system="Fixed asset ledger",
        classification="confidential",
        sox_relevant=True,
        aliases=["D&A", "Depreciation", "Amortization"],
        formula="(Asset Cost − Salvage Value) / Useful Life",
        tags=["gaap", "p&l", "non_cash"],
    ),
    _entry(
        term_id="glossary.expense.direct_labor",
        term="Direct Labor",
        definition=(
            "Wages and payroll costs for employees directly involved in "
            "producing goods or delivering services. A component of COGS."
        ),
        category=GlossaryCategory.EXPENSE,
        data_type="Money",
        source_system="ERP, payroll system",
        classification="confidential",
        sox_relevant=True,
        aliases=["Production Labor", "Touch Labor"],
        formula="Sum of production employee wages + payroll taxes + benefits",
        tags=["gaap", "cogs", "manufacturing"],
    ),
    _entry(
        term_id="glossary.expense.direct_materials",
        term="Direct Materials",
        definition=(
            "Raw materials and components that become part of the finished "
            "product and can be directly traced to production output."
        ),
        category=GlossaryCategory.EXPENSE,
        data_type="Money",
        source_system="Inventory management, ERP",
        classification="confidential",
        sox_relevant=True,
        aliases=["Raw Materials", "Production Materials"],
        formula="Sum of material costs directly allocated to production",
        tags=["gaap", "cogs", "manufacturing", "inventory"],
    ),
    _entry(
        term_id="glossary.expense.manufacturing_overhead",
        term="Manufacturing Overhead",
        definition=(
            "Indirect production costs not directly traceable to specific "
            "units, including factory rent, utilities, indirect labor, and "
            "maintenance."
        ),
        category=GlossaryCategory.EXPENSE,
        data_type="Money",
        source_system="ERP, cost accounting",
        classification="confidential",
        sox_relevant=True,
        aliases=["Factory Overhead", "Production Overhead"],
        formula=(
            "Indirect labor + Factory rent + Utilities + Maintenance + "
            "Quality control costs"
        ),
        tags=["gaap", "cogs", "manufacturing", "cost_accounting"],
    ),
    _entry(
        term_id="glossary.expense.sales_commission",
        term="Sales Commission",
        definition=(
            "Variable compensation paid to sales personnel based on revenue "
            "generated or deals closed."
        ),
        category=GlossaryCategory.EXPENSE,
        data_type="Money",
        source_system="CRM, commission management system",
        classification="confidential",
        sox_relevant=True,
        aliases=["Commission", "Sales Compensation", "Commission Expense"],
        formula="Sum of deal-level commission payouts",
        tags=["sales", "variable_comp", "cogs_saas"],
    ),
]


# ===================================================================
# PROFITABILITY METRICS  (7 original + 3 additional = 10)
# ===================================================================

_PROFITABILITY: list[GlossaryEntry] = [
    _entry(
        term_id="glossary.profitability.gross_profit",
        term="Gross Profit",
        definition="Revenue remaining after deducting the cost of goods sold.",
        category=GlossaryCategory.PROFITABILITY,
        data_type="Money",
        source_system="Computed (formula engine)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Gross Income"],
        formula="Net Revenue − COGS",
        tags=["gaap", "p&l", "kpi"],
    ),
    _entry(
        term_id="glossary.profitability.gross_margin",
        term="Gross Margin",
        definition=(
            "Gross profit expressed as a percentage of revenue, indicating "
            "how efficiently a company produces its goods or services."
        ),
        category=GlossaryCategory.PROFITABILITY,
        data_type="Percentage",
        source_system="Computed (formula engine)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Gross Margin %"],
        formula="(Net Revenue − COGS) / Net Revenue × 100",
        tags=["gaap", "p&l", "kpi", "board_report"],
    ),
    _entry(
        term_id="glossary.profitability.ebitda",
        term="EBITDA",
        definition=(
            "Earnings Before Interest, Taxes, Depreciation, and Amortization. "
            "A proxy for operating cash flow that isolates profitability "
            "from capital structure and non-cash charges."
        ),
        category=GlossaryCategory.PROFITABILITY,
        data_type="Money",
        source_system="Computed (formula engine)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Operating Cash Flow Proxy", "Adjusted EBITDA"],
        formula="Net Income + Interest + Taxes + D&A",
        tags=["gaap", "p&l", "kpi", "board_report", "valuation"],
    ),
    _entry(
        term_id="glossary.profitability.ebit",
        term="EBIT",
        definition=(
            "Earnings Before Interest and Taxes. Represents operating "
            "profit — the company's core business earnings."
        ),
        category=GlossaryCategory.PROFITABILITY,
        data_type="Money",
        source_system="Computed (formula engine)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Operating Income", "Operating Profit"],
        formula="Revenue − COGS − OPEX",
        tags=["gaap", "p&l", "kpi"],
    ),
    _entry(
        term_id="glossary.profitability.net_income",
        term="Net Income",
        definition=(
            "The bottom line: total revenue minus all expenses, taxes, "
            "and interest. Represents the company's total earnings."
        ),
        category=GlossaryCategory.PROFITABILITY,
        data_type="Money",
        source_system="Computed (formula engine)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Net Profit", "Net Earnings", "The Bottom Line"],
        formula="EBIT − Interest − Taxes",
        tags=["gaap", "p&l", "kpi", "board_report"],
    ),
    _entry(
        term_id="glossary.profitability.net_margin",
        term="Net Profit Margin",
        definition=(
            "Net income as a percentage of revenue, measuring overall "
            "profitability after all expenses."
        ),
        category=GlossaryCategory.PROFITABILITY,
        data_type="Percentage",
        source_system="Computed (formula engine)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Net Margin", "Return on Sales"],
        formula="Net Income / Net Revenue × 100",
        tags=["gaap", "p&l", "kpi"],
    ),
    _entry(
        term_id="glossary.profitability.operating_margin",
        term="Operating Margin",
        definition=(
            "Operating income (EBIT) as a percentage of revenue, measuring "
            "operational efficiency before financing and tax effects."
        ),
        category=GlossaryCategory.PROFITABILITY,
        data_type="Percentage",
        source_system="Computed (formula engine)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Operating Profit Margin"],
        formula="EBIT / Net Revenue × 100",
        tags=["gaap", "p&l", "kpi"],
    ),
    _entry(
        term_id="glossary.profitability.contribution_margin",
        term="Contribution Margin",
        definition=(
            "Revenue minus variable costs, showing how much each unit "
            "sold contributes to fixed costs and profit."
        ),
        category=GlossaryCategory.PROFITABILITY,
        data_type="Percentage",
        source_system="Computed (cost accounting)",
        classification="confidential",
        sox_relevant=False,
        aliases=["Contribution Margin %", "Unit Contribution"],
        formula="(Revenue − Variable Costs) / Revenue × 100",
        tags=["cost_accounting", "p&l", "kpi"],
    ),
    _entry(
        term_id="glossary.profitability.operating_leverage",
        term="Operating Leverage",
        definition=(
            "The degree to which a company's cost structure includes fixed "
            "costs vs. variable costs. Higher leverage means profits grow "
            "faster with revenue increases."
        ),
        category=GlossaryCategory.PROFITABILITY,
        data_type="Ratio",
        source_system="Computed (formula engine)",
        classification="confidential",
        aliases=["DOL", "Degree of Operating Leverage"],
        formula="Contribution Margin / Operating Income",
        tags=["kpi", "efficiency", "cost_structure"],
    ),
    _entry(
        term_id="glossary.profitability.ebitda_margin",
        term="EBITDA Margin",
        definition=(
            "EBITDA as a percentage of revenue, measuring operating "
            "profitability before capital structure effects."
        ),
        category=GlossaryCategory.PROFITABILITY,
        data_type="Percentage",
        source_system="Computed (formula engine)",
        classification="confidential",
        sox_relevant=True,
        aliases=["EBITDA %"],
        formula="EBITDA / Net Revenue × 100",
        tags=["gaap", "kpi", "board_report", "valuation"],
    ),
]


# ===================================================================
# BALANCE SHEET ITEMS  (6 original + 5 additional = 11)
# ===================================================================

_BALANCE_SHEET: list[GlossaryEntry] = [
    _entry(
        term_id="glossary.balance_sheet.cash",
        term="Cash & Cash Equivalents",
        definition=(
            "Liquid assets including physical cash, bank deposits, and "
            "short-term investments with original maturities under 90 days."
        ),
        category=GlossaryCategory.BALANCE_SHEET,
        data_type="Money",
        source_system="Treasury system, ERP",
        classification="confidential",
        sox_relevant=True,
        aliases=["Cash", "Liquid Assets"],
        formula="Cash + Bank Balances + Marketable Securities (< 90 days)",
        tags=["gaap", "balance_sheet", "liquidity"],
    ),
    _entry(
        term_id="glossary.balance_sheet.ar",
        term="Accounts Receivable (AR)",
        definition=(
            "Money owed to the company by customers for delivered goods "
            "or services that have been invoiced but not yet paid."
        ),
        category=GlossaryCategory.BALANCE_SHEET,
        data_type="Money",
        source_system="ERP, AR sub-ledger",
        classification="confidential",
        sox_relevant=True,
        aliases=["Receivables", "Trade Debtors", "AR"],
        formula="Sum of unpaid customer invoices",
        tags=["gaap", "balance_sheet", "working_capital"],
    ),
    _entry(
        term_id="glossary.balance_sheet.ap",
        term="Accounts Payable (AP)",
        definition=(
            "Money owed by the company to vendors and suppliers for "
            "received goods or services that have been invoiced."
        ),
        category=GlossaryCategory.BALANCE_SHEET,
        data_type="Money",
        source_system="ERP, AP sub-ledger",
        classification="confidential",
        sox_relevant=True,
        aliases=["Payables", "Trade Creditors", "AP"],
        formula="Sum of unpaid vendor invoices",
        tags=["gaap", "balance_sheet", "working_capital"],
    ),
    _entry(
        term_id="glossary.balance_sheet.inventory",
        term="Inventory",
        definition=(
            "Value of raw materials, work-in-progress, and finished goods "
            "held for production or sale."
        ),
        category=GlossaryCategory.BALANCE_SHEET,
        data_type="Money",
        source_system="Inventory management, ERP",
        classification="confidential",
        sox_relevant=True,
        aliases=["Stock", "Merchandise Inventory"],
        formula="Raw Materials + WIP + Finished Goods (at cost)",
        tags=["gaap", "balance_sheet", "working_capital", "cogs"],
    ),
    _entry(
        term_id="glossary.balance_sheet.equity",
        term="Shareholders' Equity",
        definition=(
            "Residual interest in the company's assets after deducting "
            "all liabilities. Represents the owners' stake in the business."
        ),
        category=GlossaryCategory.BALANCE_SHEET,
        data_type="Money",
        source_system="ERP, equity management",
        classification="confidential",
        sox_relevant=True,
        aliases=["Equity", "Net Worth", "Stockholders' Equity"],
        formula="Total Assets − Total Liabilities",
        tags=["gaap", "balance_sheet", "valuation"],
    ),
    _entry(
        term_id="glossary.balance_sheet.working_capital",
        term="Working Capital",
        definition=(
            "Measure of short-term liquidity and operational efficiency, "
            "calculated as current assets minus current liabilities."
        ),
        category=GlossaryCategory.BALANCE_SHEET,
        data_type="Money",
        source_system="Computed (balance sheet)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Net Working Capital"],
        formula="Current Assets − Current Liabilities",
        tags=["gaap", "balance_sheet", "liquidity", "kpi"],
    ),
    _entry(
        term_id="glossary.balance_sheet.goodwill",
        term="Goodwill",
        definition=(
            "Intangible asset arising from business acquisitions, representing "
            "the excess of purchase price over the fair value of identifiable "
            "net assets acquired."
        ),
        category=GlossaryCategory.BALANCE_SHEET,
        data_type="Money",
        source_system="ERP, consolidation module",
        classification="confidential",
        sox_relevant=True,
        aliases=["Acquisition Premium"],
        formula="Purchase Price − Fair Value of Net Assets Acquired",
        tags=["gaap", "balance_sheet", "intangible", "acquisition"],
    ),
    _entry(
        term_id="glossary.balance_sheet.intangible_assets",
        term="Intangible Assets",
        definition=(
            "Non-physical long-term assets including patents, trademarks, "
            "copyrights, software, and customer relationships."
        ),
        category=GlossaryCategory.BALANCE_SHEET,
        data_type="Money",
        source_system="ERP, fixed asset ledger",
        classification="confidential",
        sox_relevant=True,
        aliases=["Intangibles", "Intellectual Property"],
        formula="Sum of identifiable non-monetary assets without physical substance",
        tags=["gaap", "balance_sheet", "intangible", "valuation"],
    ),
    _entry(
        term_id="glossary.balance_sheet.accrued_liabilities",
        term="Accrued Liabilities",
        definition=(
            "Expenses that have been incurred but not yet invoiced or paid, "
            "such as accrued wages, taxes, and interest payable."
        ),
        category=GlossaryCategory.BALANCE_SHEET,
        data_type="Money",
        source_system="ERP, accrual module",
        classification="confidential",
        sox_relevant=True,
        aliases=["Accruals", "Accrued Expenses", "Accrued Payables"],
        formula="Sum of incurred but unpaid expenses",
        tags=["gaap", "balance_sheet", "accrual"],
    ),
    _entry(
        term_id="glossary.balance_sheet.short_term_debt",
        term="Short-term Debt",
        definition=(
            "Borrowings and debt obligations that are due within one year, "
            "including bank overdrafts, commercial paper, and current "
            "portions of long-term debt."
        ),
        category=GlossaryCategory.BALANCE_SHEET,
        data_type="Money",
        source_system="ERP, treasury management",
        classification="confidential",
        sox_relevant=True,
        aliases=["Current Debt", "Short-term Borrowings"],
        formula="Current portion of long-term debt + Short-term notes payable",
        tags=["gaap", "balance_sheet", "debt", "liquidity"],
    ),
    _entry(
        term_id="glossary.balance_sheet.long_term_debt",
        term="Long-term Debt",
        definition=(
            "Borrowings and debt obligations due beyond one year, including "
            "bank loans, bonds payable, and lease obligations."
        ),
        category=GlossaryCategory.BALANCE_SHEET,
        data_type="Money",
        source_system="ERP, treasury management",
        classification="confidential",
        sox_relevant=True,
        aliases=["Non-current Debt", "Notes Payable", "Bonds Payable"],
        formula="Total debt obligations with maturity > 12 months",
        tags=["gaap", "balance_sheet", "debt", "capital_structure"],
    ),
]


# ===================================================================
# CASH FLOW CONCEPTS  (5 original + 4 additional = 9)
# ===================================================================

_CASH_FLOW: list[GlossaryEntry] = [
    _entry(
        term_id="glossary.cash_flow.operating",
        term="Operating Cash Flow (OCF)",
        definition=(
            "Cash generated from core business operations, excluding "
            "capital expenditures and financing activities."
        ),
        category=GlossaryCategory.CASH_FLOW,
        data_type="Money",
        source_system="Cash flow statement, ERP",
        classification="confidential",
        sox_relevant=True,
        aliases=["Cash from Operations", "CFO"],
        formula="Net Income + Non-Cash Charges − Change in Working Capital",
        tags=["gaap", "cash_flow", "kpi", "board_report"],
    ),
    _entry(
        term_id="glossary.cash_flow.free",
        term="Free Cash Flow (FCF)",
        definition=(
            "Cash available to the company after accounting for capital "
            "expenditures, representing the cash that can be used for "
            "dividends, debt repayment, or reinvestment."
        ),
        category=GlossaryCategory.CASH_FLOW,
        data_type="Money",
        source_system="Computed (cash flow)",
        classification="confidential",
        sox_relevant=True,
        aliases=["FCF", "Free Cash"],
        formula="Operating Cash Flow − CAPEX",
        tags=["gaap", "cash_flow", "kpi", "board_report", "valuation"],
    ),
    _entry(
        term_id="glossary.cash_flow.burn_rate",
        term="Burn Rate",
        definition=(
            "Rate at which a company consumes cash, typically measured "
            "monthly. Net burn considers both inflows and outflows."
        ),
        category=GlossaryCategory.CASH_FLOW,
        data_type="Money",
        source_system="Computed (cash flow)",
        classification="confidential",
        aliases=["Cash Burn", "Net Burn"],
        formula="Monthly Operating Cash Outflows − Monthly Operating Cash Inflows",
        tags=["saas", "cash_flow", "startup", "kpi"],
    ),
    _entry(
        term_id="glossary.cash_flow.runway",
        term="Cash Runway",
        definition=(
            "Number of months the company can continue operating before "
            "exhausting its cash balance at the current burn rate."
        ),
        category=GlossaryCategory.CASH_FLOW,
        data_type="Ratio",
        source_system="Computed (cash flow)",
        classification="confidential",
        aliases=["Runway", "Cash Runway (Months)"],
        formula="Current Cash Balance / Monthly Burn Rate",
        tags=["saas", "cash_flow", "startup", "kpi"],
    ),
    _entry(
        term_id="glossary.cash_flow.dso",
        term="Days Sales Outstanding (DSO)",
        definition=(
            "Average number of days the company takes to collect payment "
            "after a sale. Lower DSO indicates more efficient collections."
        ),
        category=GlossaryCategory.CASH_FLOW,
        data_type="Ratio",
        source_system="Computed (AR analysis)",
        classification="internal",
        sox_relevant=True,
        aliases=["DSO", "Collection Period"],
        formula="(Accounts Receivable / Net Revenue) × Number of Days",
        tags=["gaap", "working_capital", "kpi", "efficiency"],
    ),
    _entry(
        term_id="glossary.cash_flow.financing",
        term="Financing Cash Flow",
        definition=(
            "Cash flows from transactions with the company's owners and "
            "creditors, including debt issuance, equity financing, "
            "dividends, and share buybacks."
        ),
        category=GlossaryCategory.CASH_FLOW,
        data_type="Money",
        source_system="Cash flow statement, treasury",
        classification="confidential",
        sox_relevant=True,
        aliases=["Cash from Financing", "CFF"],
        formula="Debt proceeds − Debt repayments + Equity proceeds − Dividends − Buybacks",
        tags=["gaap", "cash_flow", "capital_structure"],
    ),
    _entry(
        term_id="glossary.cash_flow.investing",
        term="Investing Cash Flow",
        definition=(
            "Cash flows from the purchase and sale of long-term assets "
            "and investments, including property, equipment, and securities."
        ),
        category=GlossaryCategory.CASH_FLOW,
        data_type="Money",
        source_system="Cash flow statement, ERP",
        classification="confidential",
        sox_relevant=True,
        aliases=["Cash from Investing", "CFI"],
        formula="CAPEX payments − Asset sale proceeds + Investment purchases − Sales",
        tags=["gaap", "cash_flow"],
    ),
    _entry(
        term_id="glossary.cash_flow.unlevered_fcf",
        term="Unlevered Free Cash Flow",
        definition=(
            "Free cash flow available to all capital providers (both debt "
            "and equity), before interest payments. Used for DCF valuation."
        ),
        category=GlossaryCategory.CASH_FLOW,
        data_type="Money",
        source_system="Computed (valuation)",
        classification="confidential",
        aliases=["UFCF", "Free Cash Flow to Firm", "FCFF"],
        formula="EBIT × (1 − Tax Rate) + D&A − CAPEX − Change in Working Capital",
        tags=["valuation", "dcf", "kpi", "board_report"],
    ),
    _entry(
        term_id="glossary.cash_flow.levered_fcf",
        term="Levered Free Cash Flow",
        definition=(
            "Free cash flow available to equity holders after interest "
            "and debt payments. Represents cash that can be distributed "
            "as dividends or reinvested."
        ),
        category=GlossaryCategory.CASH_FLOW,
        data_type="Money",
        source_system="Computed (valuation)",
        classification="confidential",
        aliases=["LFCF", "Free Cash Flow to Equity", "FCFE"],
        formula="Unlevered FCF − Interest × (1 − Tax Rate) − Net Debt Repayments",
        tags=["valuation", "dcf", "equity"],
    ),
]


# ===================================================================
# BUDGETING CONCEPTS  (7 original = 7)
# ===================================================================

_BUDGETING: list[GlossaryEntry] = [
    _entry(
        term_id="glossary.budgeting.budget",
        term="Budget",
        definition=(
            "A financial plan approved by management that allocates resources "
            "and sets performance targets for a defined period."
        ),
        category=GlossaryCategory.BUDGETING,
        data_type="Money",
        source_system="FP&A tool, spreadsheet, ERP budgeting module",
        classification="confidential",
        aliases=["Operating Budget", "Financial Plan"],
        tags=["budgeting", "planning"],
    ),
    _entry(
        term_id="glossary.budgeting.original",
        term="Original Budget",
        definition=(
            "The initial budget approved at the start of the fiscal year. "
            "Serves as the baseline against which actuals are compared."
        ),
        category=GlossaryCategory.BUDGETING,
        data_type="Money",
        source_system="FP&A tool",
        classification="confidential",
        sox_relevant=True,
        aliases=["Baseline Budget", "Approved Budget", "Static Budget"],
        tags=["budgeting", "planning", "sox"],
    ),
    _entry(
        term_id="glossary.budgeting.revised",
        term="Revised Budget",
        definition=(
            "An updated budget reflecting approved changes, reforecasts, "
            "and reallocations during the fiscal year."
        ),
        category=GlossaryCategory.BUDGETING,
        data_type="Money",
        source_system="FP&A tool",
        classification="confidential",
        sox_relevant=True,
        aliases=["Current Budget", "Reforecast"],
        tags=["budgeting", "planning", "sox"],
    ),
    _entry(
        term_id="glossary.budgeting.zbb",
        term="Zero-Based Budgeting (ZBB)",
        definition=(
            "A budgeting methodology where all expenses must be justified "
            "from a zero base each period, rather than incrementing from "
            "prior-period levels."
        ),
        category=GlossaryCategory.BUDGETING,
        data_type="String",
        source_system="FP&A tool",
        classification="internal",
        aliases=["ZBB", "Zero-Base Budgeting"],
        tags=["budgeting", "methodology"],
    ),
    _entry(
        term_id="glossary.budgeting.attainment_rate",
        term="Budget Attainment Rate",
        definition=(
            "The percentage of the budgeted amount that was actually "
            "achieved in a given period."
        ),
        category=GlossaryCategory.BUDGETING,
        data_type="Percentage",
        source_system="Computed (variance analysis)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Budget Utilization", "Budget Achievement"],
        formula="(Actual Amount / Budget Amount) × 100",
        tags=["budgeting", "kpi", "variance"],
    ),
    _entry(
        term_id="glossary.budgeting.cycle",
        term="Budget Cycle",
        definition=(
            "The annual end-to-end process of creating, reviewing, approving, "
            "and monitoring the budget, from preparation through periodic review."
        ),
        category=GlossaryCategory.BUDGETING,
        data_type="String",
        source_system="Process / calendar",
        classification="internal",
        aliases=["Planning Cycle", "Budget Season"],
        tags=["budgeting", "process", "governance"],
    ),
    _entry(
        term_id="glossary.budgeting.reforecast",
        term="Reforecast",
        definition=(
            "A mid-cycle update to financial projections that replaces the "
            "budget for remaining periods, typically more frequent than the "
            "annual budget cycle."
        ),
        category=GlossaryCategory.BUDGETING,
        data_type="Money",
        source_system="FP&A tool",
        classification="confidential",
        aliases=["Rolling Forecast", "Updated Forecast"],
        tags=["budgeting", "forecasting", "planning"],
    ),
]


# ===================================================================
# VARIANCE ANALYSIS  (7 original + 1 additional = 8)
# ===================================================================

_VARIANCE: list[GlossaryEntry] = [
    _entry(
        term_id="glossary.variance.variance",
        term="Variance",
        definition=(
            "The difference between actual results and the budget or forecast. "
            "The fundamental unit of analysis for FP&A."
        ),
        category=GlossaryCategory.VARIANCE,
        data_type="Money",
        source_system="Computed (variance engine)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Budget Variance", "Actual vs. Budget"],
        formula="Actual Amount − Budget Amount",
        tags=["variance", "kpi", "analysis"],
    ),
    _entry(
        term_id="glossary.variance.favorable",
        term="Favorable Variance",
        definition=(
            "A variance that benefits the organization: revenue higher than "
            "budget or costs lower than budget."
        ),
        category=GlossaryCategory.VARIANCE,
        data_type="String",
        source_system="Computed (variance engine)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Favourable Variance", "Positive Variance"],
        tags=["variance", "analysis"],
    ),
    _entry(
        term_id="glossary.variance.unfavorable",
        term="Unfavorable Variance",
        definition=(
            "A variance that harms the organization: revenue lower than "
            "budget or costs higher than budget."
        ),
        category=GlossaryCategory.VARIANCE,
        data_type="String",
        source_system="Computed (variance engine)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Adverse Variance", "Negative Variance"],
        tags=["variance", "analysis"],
    ),
    _entry(
        term_id="glossary.variance.material",
        term="Material Variance",
        definition=(
            "A variance exceeding defined significance thresholds "
            "(e.g., $50K absolute and 10% relative). Material variances "
            "trigger review and commentary requirements."
        ),
        category=GlossaryCategory.VARIANCE,
        data_type="String",
        source_system="Computed (materiality engine)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Significant Variance", "Exception"],
        tags=["variance", "materiality", "sox", "governance"],
    ),
    _entry(
        term_id="glossary.variance.percentage",
        term="Variance Percentage",
        definition=(
            "The variance expressed as a percentage of the budget/plan, "
            "providing a normalized view of deviation magnitude."
        ),
        category=GlossaryCategory.VARIANCE,
        data_type="Percentage",
        source_system="Computed (variance engine)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Variance %", "Percent Variance"],
        formula="(Actual − Budget) / ABS(Budget) × 100",
        tags=["variance", "kpi"],
    ),
    _entry(
        term_id="glossary.variance.volume",
        term="Volume Variance",
        definition=(
            "The portion of total variance attributable to changes in "
            "quantity or volume of goods sold, holding price constant."
        ),
        category=GlossaryCategory.VARIANCE,
        data_type="Money",
        source_system="Computed (driver analysis)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Quantity Variance"],
        formula="(Actual Volume − Budget Volume) × Budget Price",
        tags=["variance", "driver_analysis", "kpi"],
    ),
    _entry(
        term_id="glossary.variance.price",
        term="Price Variance",
        definition=(
            "The portion of total variance attributable to changes in "
            "price or rate, holding volume constant."
        ),
        category=GlossaryCategory.VARIANCE,
        data_type="Money",
        source_system="Computed (driver analysis)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Rate Variance", "Spending Variance"],
        formula="(Actual Price − Budget Price) × Actual Volume",
        tags=["variance", "driver_analysis", "kpi"],
    ),
    _entry(
        term_id="glossary.variance.mix",
        term="Mix Variance",
        definition=(
            "The portion of variance attributable to changes in the mix "
            "of products or services sold, when different items have "
            "different margins."
        ),
        category=GlossaryCategory.VARIANCE,
        data_type="Money",
        source_system="Computed (driver analysis)",
        classification="confidential",
        sox_relevant=True,
        aliases=["Product Mix Variance", "Sales Mix Variance"],
        formula=(
            "Sum over products of (Actual Mix % − Budget Mix %) × "
            "Budget Margin per unit × Actual Total Volume"
        ),
        tags=["variance", "driver_analysis", "kpi"],
    ),
]


# ===================================================================
# FORECASTING CONCEPTS  (4 original + 4 additional = 8)
# ===================================================================

_FORECASTING: list[GlossaryEntry] = [
    _entry(
        term_id="glossary.forecasting.rolling",
        term="Rolling Forecast",
        definition=(
            "A continuously updated forecast where each month/quarter a new "
            "period is added and the oldest is dropped, maintaining a "
            "constant forward-looking horizon."
        ),
        category=GlossaryCategory.FORECASTING,
        data_type="String",
        source_system="FP&A tool",
        classification="confidential",
        aliases=["Continuous Forecast", "Rolling Projection"],
        tags=["forecasting", "methodology"],
    ),
    _entry(
        term_id="glossary.forecasting.driver_based",
        term="Driver-Based Forecasting",
        definition=(
            "A methodology using operational drivers (headcount, units sold) "
            "to project financial outcomes, modeling relationships between "
            "operational metrics and financial results."
        ),
        category=GlossaryCategory.FORECASTING,
        data_type="String",
        source_system="FP&A tool, driver models",
        classification="confidential",
        aliases=["Driver Model", "Driver Tree"],
        tags=["forecasting", "methodology", "drivers"],
    ),
    _entry(
        term_id="glossary.forecasting.accuracy",
        term="Forecast Accuracy",
        definition=(
            "Measure of how closely the forecast matched actual results, "
            "commonly calculated using Mean Absolute Percentage Error (MAPE)."
        ),
        category=GlossaryCategory.FORECASTING,
        data_type="Percentage",
        source_system="Computed (forecast engine)",
        classification="internal",
        sox_relevant=True,
        aliases=["Forecast Error", "MAPE", "Mean Absolute Percentage Error"],
        formula="Mean(|Actual − Forecast| / |Actual|) × 100",
        tags=["forecasting", "kpi", "quality"],
    ),
    _entry(
        term_id="glossary.forecasting.scenario",
        term="Scenario Analysis",
        definition=(
            "A modelling technique that evaluates financial performance "
            "under multiple sets of assumptions (base case, upside, downside) "
            "to understand the range of possible outcomes."
        ),
        category=GlossaryCategory.FORECASTING,
        data_type="String",
        source_system="FP&A tool, scenario engine",
        classification="confidential",
        aliases=["What-If Analysis", "Sensitivity Analysis"],
        tags=["forecasting", "scenario", "planning"],
    ),
    _entry(
        term_id="glossary.forecasting.bottom_up",
        term="Bottom-Up Forecasting",
        definition=(
            "A forecasting approach built from granular operational details "
            "(individual deals, hires, line items) aggregated upward to "
            "total financial projections."
        ),
        category=GlossaryCategory.FORECASTING,
        data_type="String",
        source_system="FP&A tool, CRM, HRIS",
        classification="confidential",
        aliases=["Build-Up Forecast", "Operational Forecast"],
        tags=["forecasting", "methodology"],
    ),
    _entry(
        term_id="glossary.forecasting.top_down",
        term="Top-Down Forecasting",
        definition=(
            "A forecasting approach that starts with macro-level targets "
            "(market size, growth rate) and allocates down to operational units."
        ),
        category=GlossaryCategory.FORECASTING,
        data_type="String",
        source_system="FP&A tool, strategic planning",
        classification="confidential",
        aliases=["Macro Forecast", "Target-Down Forecast"],
        tags=["forecasting", "methodology", "planning"],
    ),
    _entry(
        term_id="glossary.forecasting.predictive",
        term="Predictive Forecasting (ML)",
        definition=(
            "Forecasting using statistical and machine learning models to "
            "identify patterns and predict future financial outcomes based "
            "on historical data and external signals."
        ),
        category=GlossaryCategory.FORECASTING,
        data_type="String",
        source_system="ML forecast engine, Python runtime",
        classification="confidential",
        aliases=["ML Forecast", "Statistical Forecast"],
        tags=["forecasting", "ml", "advanced_analytics"],
    ),
    _entry(
        term_id="glossary.forecasting.wave",
        term="Forecast Wave Planning",
        definition=(
            "A structured approach to updating forecasts in phased waves "
            "(e.g., revenue first, then expenses, then cash flow) to manage "
            "dependencies and assumptions systematically."
        ),
        category=GlossaryCategory.FORECASTING,
        data_type="String",
        source_system="FP&A tool",
        classification="internal",
        aliases=["Wave Planning", "Phased Forecast"],
        tags=["forecasting", "methodology", "process"],
    ),
]


# ===================================================================
# SAAS & OPERATIONAL METRICS  (7 additional)
# ===================================================================

_SAAS_METRICS: list[GlossaryEntry] = [
    _entry(
        term_id="glossary.saas.cac",
        term="Customer Acquisition Cost (CAC)",
        definition=(
            "Total cost of acquiring a new customer, including sales and "
            "marketing expenses divided by the number of new customers added."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Money",
        source_system="Computed (CRM, ERP)",
        classification="confidential",
        aliases=["CAC", "Customer Acquisition Cost"],
        formula="Total Sales & Marketing Cost / Number of New Customers",
        tags=["saas", "kpi", "efficiency", "sales"],
    ),
    _entry(
        term_id="glossary.saas.ltv",
        term="Customer Lifetime Value (LTV)",
        definition=(
            "The predicted net profit attributable to the entire future "
            "relationship with a customer."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Money",
        source_system="Computed (subscription analytics)",
        classification="confidential",
        aliases=["LTV", "CLV", "Customer Lifetime Value"],
        formula="Average Revenue per Account × Gross Margin × Average Customer Lifespan",
        tags=["saas", "kpi", "valuation", "subscription"],
    ),
    _entry(
        term_id="glossary.saas.ltv_cac_ratio",
        term="LTV:CAC Ratio",
        definition=(
            "The ratio of customer lifetime value to acquisition cost, "
            "measuring the efficiency of customer acquisition investments. "
            "A ratio above 3:1 is generally considered healthy."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Ratio",
        source_system="Computed (subscription analytics)",
        classification="confidential",
        aliases=["LTV/CAC", "LTV to CAC", "CAC Payback"],
        formula="Customer LTV / Customer Acquisition Cost",
        tags=["saas", "kpi", "efficiency", "board_report"],
    ),
    _entry(
        term_id="glossary.saas.nrr",
        term="Net Revenue Retention (NRR)",
        definition=(
            "The percentage of recurring revenue retained from existing "
            "customers over a period, including expansions, contractions, "
            "and churn. Above 100% indicates net growth from existing base."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Percentage",
        source_system="Computed (subscription analytics)",
        classification="confidential",
        aliases=["NRR", "Net Dollar Retention", "NDR"],
        formula=(
            "(Starting MRR + Expansion − Contraction − Churn) / Starting MRR × 100"
        ),
        tags=["saas", "kpi", "board_report", "subscription"],
    ),
    _entry(
        term_id="glossary.saas.grr",
        term="Gross Revenue Retention (GRR)",
        definition=(
            "The percentage of recurring revenue retained from existing "
            "customers excluding expansions. Always ≤ 100% and measures "
            "only base retention."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Percentage",
        source_system="Computed (subscription analytics)",
        classification="confidential",
        aliases=["GRR", "Gross Dollar Retention", "Logo Retention"],
        formula=(
            "(Starting MRR − Contraction − Churn) / Starting MRR × 100"
        ),
        tags=["saas", "kpi", "board_report", "subscription"],
    ),
    _entry(
        term_id="glossary.saas.churn_rate",
        term="Churn Rate",
        definition=(
            "The percentage of customers who stop using a product or "
            "service over a given period. Can be measured by customer "
            "count (logo churn) or revenue value (revenue churn)."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Percentage",
        source_system="Computed (subscription analytics)",
        classification="confidential",
        aliases=["Customer Churn", "Logo Churn", "Revenue Churn"],
        formula="(Customers Lost in Period / Starting Customers) × 100",
        tags=["saas", "kpi", "subscription"],
    ),
    _entry(
        term_id="glossary.saas.magic_number",
        term="Magic Number (Sales Efficiency)",
        definition=(
            "A SaaS efficiency metric measuring incremental revenue "
            "generated per dollar of sales and marketing investment."
        ),
        category=GlossaryCategory.REVENUE,
        data_type="Ratio",
        source_system="Computed (CRM, ERP)",
        classification="confidential",
        aliases=["Sales Efficiency", "Magic Number"],
        formula=(
            "(Current Quarter Net New ARR − Prior Quarter Net New ARR) "
            "/ Prior Quarter S&M Spend"
        ),
        tags=["saas", "kpi", "efficiency", "sales"],
    ),
]


# ===================================================================
# ADDITIONAL OPERATIONAL METRICS  (2 additional)
# ===================================================================

_OPERATIONAL: list[GlossaryEntry] = [
    _entry(
        term_id="glossary.operational.book_value",
        term="Book Value",
        definition=(
            "The net value of a company's assets as recorded on the "
            "balance sheet, calculated as total assets minus intangible "
            "assets and liabilities."
        ),
        category=GlossaryCategory.BALANCE_SHEET,
        data_type="Money",
        source_system="ERP, balance sheet",
        classification="confidential",
        sox_relevant=True,
        aliases=["Net Book Value", "Carrying Value"],
        formula="Total Assets − Intangible Assets − Total Liabilities",
        tags=["gaap", "balance_sheet", "valuation"],
    ),
    _entry(
        term_id="glossary.operational.dpo",
        term="Days Payable Outstanding (DPO)",
        definition=(
            "Average number of days the company takes to pay its suppliers "
            "and vendors. Higher DPO can improve working capital."
        ),
        category=GlossaryCategory.CASH_FLOW,
        data_type="Ratio",
        source_system="Computed (AP analysis)",
        classification="internal",
        sox_relevant=True,
        aliases=["DPO", "Average Payment Period"],
        formula="(Accounts Payable / COGS) × Number of Days",
        tags=["gaap", "working_capital", "kpi", "efficiency"],
    ),
]

# ===================================================================
# ASSEMBLED REGISTRY
# ===================================================================

GLOSSARY = GlossaryRegistry()
"""The canonical Business Glossary registry, populated with all terms.

Usage::

    from business.glossary.registry import GLOSSARY

    revenue_entry = GLOSSARY.lookup("glossary.revenue.net")
    matching = GLOSSARY.search("deferred revenue")
    expenses = GLOSSARY.list_by_category("expense")
"""


def _build_registry() -> None:
    """Register all glossary terms into the global GLOSSARY instance."""
    all_terms: list[GlossaryEntry] = []
    all_terms.extend(_REVENUE)
    all_terms.extend(_EXPENSE)
    all_terms.extend(_PROFITABILITY)
    all_terms.extend(_BALANCE_SHEET)
    all_terms.extend(_CASH_FLOW)
    all_terms.extend(_BUDGETING)
    all_terms.extend(_VARIANCE)
    all_terms.extend(_FORECASTING)
    all_terms.extend(_SAAS_METRICS)
    all_terms.extend(_OPERATIONAL)

    GLOSSARY.register_many(all_terms)


_build_registry()
