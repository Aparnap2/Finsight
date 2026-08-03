"""FP&A Capability Registry — the canonical capability hierarchy.

Populates the full FP&A domain capability map with **35+ capabilities**
across 7 top-level domains plus cross-cutting governance capabilities.

Every capability links to the engines, agents, and domain events that
support it, along with a maturity rating that reflects the current
implementation state.
"""

from business.capabilities.models import Capability, CapabilityTree

# ── Capability Definitions ───────────────────────────────────────

CAPABILITIES: list[Capability] = [
    # ═══════════════════════════════════════════════════════════════
    # Planning & Budgeting
    # ═══════════════════════════════════════════════════════════════
    Capability(
        capability_id="cap.planning",
        name="Planning & Budgeting",
        description=(
            "Strategic and operational planning including annual budgeting, "
            "rolling forecasts, and multi-scenario analysis."
        ),
        parent_id=None,
        supported_by=["Budget Engine", "Scenario Engine", "Forecast Engine"],
        events=["BudgetPeriodOpened", "BudgetApproved", "BudgetRevised"],
        maturity="production",
        owner="FP&A Team",
        tags=["core", "planning"],
    ),
    Capability(
        capability_id="cap.planning.budget.create",
        name="Budget Creation",
        description=(
            "Author and submit annual operating budgets including "
            "revenue targets, expense limits, and headcount plans."
        ),
        parent_id="cap.planning",
        supported_by=["Budget Engine", "Formula Engine"],
        events=["BudgetLineCreated", "BudgetSubmitted", "BudgetApproved"],
        maturity="production",
        owner="FP&A Team",
        tags=["core", "planning", "budgeting"],
    ),
    Capability(
        capability_id="cap.planning.budget.revise",
        name="Budget Revision",
        description=(
            "Create and approve budget revision requests with "
            "justification tracking and impact analysis."
        ),
        parent_id="cap.planning",
        supported_by=["Budget Engine"],
        events=["BudgetRevisionCreated", "BudgetRevisionApproved"],
        maturity="partial",
        owner="FP&A Team",
        tags=["core", "planning", "budgeting"],
    ),
    Capability(
        capability_id="cap.planning.forecast.rolling",
        name="Rolling Forecast",
        description=(
            "Maintain a continuously updated forecast that extends "
            "forward 12-18 months, refreshed monthly or quarterly."
        ),
        parent_id="cap.planning",
        supported_by=["Forecast Engine", "Driver Engine"],
        events=["ForecastPublished", "ForecastUpdated"],
        maturity="partial",
        owner="FP&A Team",
        tags=["core", "planning", "forecasting"],
    ),
    Capability(
        capability_id="cap.planning.scenario",
        name="Scenario Planning",
        description=(
            "Model multiple business scenarios (best case, base case, "
            "worst case) with driver-based assumptions and sensitivity analysis."
        ),
        parent_id="cap.planning",
        supported_by=["Scenario Engine", "Driver Engine"],
        events=["ScenarioCreated", "ScenarioCompared"],
        maturity="partial",
        owner="FP&A Team",
        tags=["core", "planning", "scenario"],
    ),
    # ═══════════════════════════════════════════════════════════════
    # Financial Close
    # ═══════════════════════════════════════════════════════════════
    Capability(
        capability_id="cap.close",
        name="Financial Close",
        description=(
            "Period-end close processes including account reconciliation, "
            "journal entry review, and intercompany matching."
        ),
        parent_id=None,
        supported_by=["Close Engine", "Reconciliation Engine"],
        events=["PeriodClosed", "PeriodReopened", "CloseChecklistComplete"],
        maturity="partial",
        owner="Controller Team",
        tags=["core", "close"],
    ),
    Capability(
        capability_id="cap.close.period",
        name="Period Close",
        description=(
            "Manage the month-end / quarter-end close calendar with "
            "task checklists, sign-offs, and status tracking."
        ),
        parent_id="cap.close",
        supported_by=["Close Engine"],
        events=["PeriodClosed", "PeriodReopened"],
        maturity="partial",
        owner="Controller Team",
        tags=["core", "close"],
    ),
    Capability(
        capability_id="cap.close.reconciliation",
        name="Account Reconciliation",
        description=(
            "Automate balance sheet account reconciliations with "
            "matching rules, variance flags, and approval workflows."
        ),
        parent_id="cap.close",
        supported_by=["Reconciliation Engine"],
        events=["ReconciliationComplete", "ReconciliationException"],
        maturity="partial",
        owner="Controller Team",
        tags=["core", "close"],
    ),
    Capability(
        capability_id="cap.close.journal",
        name="Journal Entry Review",
        description=(
            "Review, approve, and post journal entries with audit "
            "trail and segregation-of-duties enforcement."
        ),
        parent_id="cap.close",
        supported_by=["Journal Engine"],
        events=["JournalEntrySubmitted", "JournalEntryApproved", "JournalEntryPosted"],
        maturity="partial",
        owner="Controller Team",
        tags=["core", "close"],
    ),
    Capability(
        capability_id="cap.close.intercompany",
        name="Intercompany Reconciliation",
        description=(
            "Match and reconcile intercompany accounts across "
            "entities with automated elimination entries."
        ),
        parent_id="cap.close",
        supported_by=["Reconciliation Engine"],
        events=["IntercompanyMatched", "IntercompanyException"],
        maturity="planned",
        owner="Controller Team",
        tags=["core", "close"],
    ),
    # ═══════════════════════════════════════════════════════════════
    # Accounts Payable
    # ═══════════════════════════════════════════════════════════════
    Capability(
        capability_id="cap.ap",
        name="Accounts Payable",
        description=(
            "End-to-end vendor invoice processing, payment execution, and expense management."
        ),
        parent_id=None,
        supported_by=["AP Engine", "Payment Engine"],
        events=["InvoiceImported", "InvoiceRejected", "PaymentExecuted"],
        maturity="partial",
        owner="AP Team",
        tags=["core", "ap"],
    ),
    Capability(
        capability_id="cap.ap.invoice",
        name="Invoice Processing",
        description=(
            "Ingest, validate, and route vendor invoices through "
            "approval workflows with GL coding and matching."
        ),
        parent_id="cap.ap",
        supported_by=["AP Engine", "Data Quality Pipeline"],
        events=["InvoiceImported", "InvoiceApproved", "InvoiceRejected"],
        maturity="production",
        owner="AP Team",
        tags=["core", "ap"],
    ),
    Capability(
        capability_id="cap.ap.payment",
        name="Payment Execution",
        description=(
            "Schedule and execute vendor payments across multiple "
            "channels (ACH, wire, check) with cash forecasting."
        ),
        parent_id="cap.ap",
        supported_by=["Payment Engine"],
        events=["PaymentScheduled", "PaymentExecuted", "PaymentFailed"],
        maturity="planned",
        owner="Treasury Team",
        tags=["core", "ap"],
    ),
    Capability(
        capability_id="cap.ap.vendor",
        name="Vendor Management",
        description=(
            "Maintain vendor master data, payment terms, 1099 "
            "compliance status, and performance metrics."
        ),
        parent_id="cap.ap",
        supported_by=["AP Engine"],
        events=["VendorOnboarded", "VendorUpdated"],
        maturity="partial",
        owner="AP Team",
        tags=["core", "ap"],
    ),
    Capability(
        capability_id="cap.ap.expense",
        name="Expense Reporting",
        description=(
            "Employee expense report submission, policy validation, "
            "approval routing, and reimbursement processing."
        ),
        parent_id="cap.ap",
        supported_by=["Expense Engine"],
        events=["ExpenseReportSubmitted", "ExpenseReportApproved"],
        maturity="planned",
        owner="AP Team",
        tags=["core", "ap"],
    ),
    # ═══════════════════════════════════════════════════════════════
    # Accounts Receivable
    # ═══════════════════════════════════════════════════════════════
    Capability(
        capability_id="cap.ar",
        name="Accounts Receivable",
        description=(
            "Customer billing, collections, credit management, and cash application processes."
        ),
        parent_id=None,
        supported_by=["AR Engine", "Collections Engine"],
        events=["InvoiceGenerated", "PaymentReceived", "CreditLimitUpdated"],
        maturity="planned",
        owner="AR Team",
        tags=["core", "ar"],
    ),
    Capability(
        capability_id="cap.ar.billing",
        name="Billing & Invoicing",
        description=(
            "Generate customer invoices from contracts, usage data, "
            "or recurring schedules with accurate revenue recognition."
        ),
        parent_id="cap.ar",
        supported_by=["AR Engine", "Revenue Engine"],
        events=["InvoiceGenerated", "InvoiceSent"],
        maturity="planned",
        owner="AR Team",
        tags=["core", "ar"],
    ),
    Capability(
        capability_id="cap.ar.collections",
        name="Collections",
        description=(
            "Manage aging receivables, automated dunning, collection "
            "worklists, and dispute resolution."
        ),
        parent_id="cap.ar",
        supported_by=["Collections Engine"],
        events=["DunningSent", "PaymentPromiseReceived"],
        maturity="planned",
        owner="AR Team",
        tags=["core", "ar"],
    ),
    Capability(
        capability_id="cap.ar.credit",
        name="Credit Management",
        description=(
            "Evaluate customer creditworthiness, set credit limits, "
            "and monitor credit exposure in real time."
        ),
        parent_id="cap.ar",
        supported_by=["Credit Engine"],
        events=["CreditLimitUpdated", "CreditHoldPlaced"],
        maturity="planned",
        owner="Credit Team",
        tags=["core", "ar"],
    ),
    Capability(
        capability_id="cap.ar.cashapp",
        name="Cash Application",
        description=(
            "Automatically match inbound payments to open invoices "
            "using remittance data and ML-based prediction."
        ),
        parent_id="cap.ar",
        supported_by=["Cash Application Engine"],
        events=["PaymentReceived", "PaymentMatched", "UnmatchedPayment"],
        maturity="planned",
        owner="AR Team",
        tags=["core", "ar"],
    ),
    # ═══════════════════════════════════════════════════════════════
    # Variance Analysis
    # ═══════════════════════════════════════════════════════════════
    Capability(
        capability_id="cap.variance",
        name="Variance Analysis",
        description=(
            "Detect, quantify, and explain variances between actuals, "
            "budgets, forecasts, and prior periods."
        ),
        parent_id=None,
        supported_by=[
            "Variance Engine",
            "Root Cause Agent",
            "Commentary Agent",
        ],
        events=[
            "VarianceDetected",
            "RootCauseIdentified",
            "CommentaryGenerated",
        ],
        maturity="production",
        owner="FP&A Team",
        tags=["core", "analysis"],
    ),
    Capability(
        capability_id="cap.variance.revenue",
        name="Revenue Variance",
        description=(
            "Analyze revenue variances by product, region, channel, "
            "and customer segment with price/volume/mix decomposition."
        ),
        parent_id="cap.variance",
        supported_by=["Variance Engine", "Formula Engine"],
        events=["VarianceDetected", "VarianceExplained"],
        maturity="production",
        owner="FP&A Team",
        tags=["core", "analysis", "revenue"],
    ),
    Capability(
        capability_id="cap.variance.expense",
        name="Expense Variance",
        description=(
            "Analyze expense variances by department, cost center, "
            "and account with driver attribution."
        ),
        parent_id="cap.variance",
        supported_by=["Variance Engine", "Formula Engine"],
        events=["VarianceDetected", "VarianceExplained"],
        maturity="production",
        owner="FP&A Team",
        tags=["core", "analysis", "expense"],
    ),
    Capability(
        capability_id="cap.variance.headcount",
        name="Headcount Variance",
        description=(
            "Compare actual headcount and compensation to budget with "
            "hiring lag, attrition, and compensation mix analysis."
        ),
        parent_id="cap.variance",
        supported_by=["Variance Engine", "HR Analytics Engine"],
        events=["HeadcountVarianceDetected"],
        maturity="partial",
        owner="HR Team",
        tags=["core", "analysis", "headcount"],
    ),
    Capability(
        capability_id="cap.variance.fx",
        name="FX Variance",
        description=(
            "Isolate and report foreign exchange impacts on "
            "cross-currency revenues, expenses, and balance sheet items."
        ),
        parent_id="cap.variance",
        supported_by=["Variance Engine", "FX Engine"],
        events=["FXVarianceDetected"],
        maturity="partial",
        owner="Treasury Team",
        tags=["core", "analysis", "fx"],
    ),
    # ═══════════════════════════════════════════════════════════════
    # Forecasting
    # ═══════════════════════════════════════════════════════════════
    Capability(
        capability_id="cap.forecast",
        name="Forecasting",
        description=(
            "Predictive modeling across revenue, expenses, cash flow, "
            "and driver-based operational metrics."
        ),
        parent_id=None,
        supported_by=["Forecast Engine", "Driver Engine", "ML Engine"],
        events=["ForecastPublished", "ForecastUpdated"],
        maturity="partial",
        owner="FP&A Team",
        tags=["core", "forecasting"],
    ),
    Capability(
        capability_id="cap.forecast.revenue",
        name="Revenue Forecasting",
        description=(
            "Predict future revenue using pipeline analysis, "
            "historical trends, seasonality, and leading indicators."
        ),
        parent_id="cap.forecast",
        supported_by=["Forecast Engine", "ML Engine"],
        events=["RevenueForecastPublished"],
        maturity="partial",
        owner="FP&A Team",
        tags=["core", "forecasting", "revenue"],
    ),
    Capability(
        capability_id="cap.forecast.expense",
        name="Expense Forecasting",
        description=(
            "Project operating expenses based on headcount plans, "
            "contractual commitments, and activity drivers."
        ),
        parent_id="cap.forecast",
        supported_by=["Forecast Engine"],
        events=["ExpenseForecastPublished"],
        maturity="partial",
        owner="FP&A Team",
        tags=["core", "forecasting", "expense"],
    ),
    Capability(
        capability_id="cap.forecast.cashflow",
        name="Cash Flow Forecasting",
        description=(
            "Model cash inflows and outflows including collections, "
            "payables, debt service, and capital expenditures."
        ),
        parent_id="cap.forecast",
        supported_by=["Forecast Engine", "Treasury Engine"],
        events=["CashFlowForecastPublished"],
        maturity="planned",
        owner="Treasury Team",
        tags=["core", "forecasting", "cashflow"],
    ),
    Capability(
        capability_id="cap.forecast.driver",
        name="Driver-Based Forecasting",
        description=(
            "Build forecast models driven by operational and market "
            "drivers (headcount, square footage, CPI, exchange rates)."
        ),
        parent_id="cap.forecast",
        supported_by=["Driver Engine", "Scenario Engine"],
        events=["DriverModelUpdated", "DriverForecastPublished"],
        maturity="planned",
        owner="FP&A Team",
        tags=["core", "forecasting", "drivers"],
    ),
    # ═══════════════════════════════════════════════════════════════
    # Reporting
    # ═══════════════════════════════════════════════════════════════
    Capability(
        capability_id="cap.reporting",
        name="Reporting",
        description=(
            "Author, distribute, and archive financial reports for "
            "boards, management, regulators, and ad-hoc analysis."
        ),
        parent_id=None,
        supported_by=["Commentary Agent", "Report Engine", "Export Engine"],
        events=["BoardReportGenerated", "ManagementReportGenerated"],
        maturity="production",
        owner="FP&A Team",
        tags=["core", "reporting"],
    ),
    Capability(
        capability_id="cap.reporting.board",
        name="Board Reporting",
        description=(
            "Compile board packages with executive summaries, KPI "
            "dashboards, variance commentary, and strategic analysis."
        ),
        parent_id="cap.reporting",
        supported_by=["Commentary Agent", "Report Engine"],
        events=["BoardReportGenerated", "BoardReportApproved"],
        maturity="production",
        owner="FP&A Team",
        tags=["core", "reporting", "board"],
    ),
    Capability(
        capability_id="cap.reporting.management",
        name="Management Reporting",
        description=(
            "Produce monthly and quarterly management reports with "
            "P&L, balance sheet, cash flow, and operational metrics."
        ),
        parent_id="cap.reporting",
        supported_by=["Report Engine"],
        events=["ManagementReportGenerated"],
        maturity="partial",
        owner="FP&A Team",
        tags=["core", "reporting", "management"],
    ),
    Capability(
        capability_id="cap.reporting.regulatory",
        name="Regulatory Reporting",
        description=(
            "Generate regulatory filings (SEC, tax, statistical) with "
            "XBRL tagging, validation rules, and audit trails."
        ),
        parent_id="cap.reporting",
        supported_by=["Report Engine", "Compliance Engine"],
        events=["RegulatoryFilingGenerated", "RegulatoryFilingSubmitted"],
        maturity="planned",
        owner="Compliance Team",
        tags=["core", "reporting", "regulatory"],
    ),
    Capability(
        capability_id="cap.reporting.adhoc",
        name="Ad-Hoc Analysis",
        description=(
            "Support interactive drill-down, free-form queries, and "
            "custom report creation for FP&A analysts."
        ),
        parent_id="cap.reporting",
        supported_by=["Ad-Hoc Query Engine", "OLAP Engine"],
        events=["AdHocReportCreated", "AdHocReportExported"],
        maturity="partial",
        owner="FP&A Team",
        tags=["core", "reporting", "adhoc"],
    ),
    # ═══════════════════════════════════════════════════════════════
    # Governance & Compliance (cross-cutting)
    # ═══════════════════════════════════════════════════════════════
    Capability(
        capability_id="cap.governance",
        name="Governance & Compliance",
        description=(
            "Cross-cutting data governance, SOX compliance, policy "
            "enforcement, and audit readiness."
        ),
        parent_id=None,
        supported_by=["Policy Engine", "Audit Engine"],
        events=["PolicyEvaluated", "ComplianceCheckComplete"],
        maturity="partial",
        owner="Compliance Team",
        tags=["cross-cutting", "governance"],
    ),
    Capability(
        capability_id="cap.governance.dataquality",
        name="Data Quality",
        description=(
            "Monitor, measure, and remediate data quality issues "
            "across all financial data sources and pipelines."
        ),
        parent_id="cap.governance",
        supported_by=["Data Quality Pipeline", "Assertion Pipeline"],
        events=["DataQualityIssueDetected", "DataQualitySnapshotCreated"],
        maturity="partial",
        owner="Data Governance Team",
        tags=["cross-cutting", "governance", "quality"],
    ),
    Capability(
        capability_id="cap.governance.audit",
        name="Audit Trail",
        description=(
            "Maintain immutable records of all financial transactions "
            "and user actions for internal and external audit."
        ),
        parent_id="cap.governance",
        supported_by=["Audit Engine"],
        events=["AuditEventLogged", "AuditTrailExported"],
        maturity="partial",
        owner="Compliance Team",
        tags=["cross-cutting", "governance", "audit"],
    ),
]

# ── Registry Exports ─────────────────────────────────────────────

CAPABILITIES_BY_ID: dict[str, Capability] = {cap.capability_id: cap for cap in CAPABILITIES}

CAPABILITY_TREE: CapabilityTree = CapabilityTree(capabilities=CAPABILITIES)
