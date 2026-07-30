"""Financial Knowledge Graph Registry.

Populates a directed graph of **26 financial entities** and
**39 relationships** representing the core financial data
lineage from transactions through statements.

The canonical flow:

    Vendor → Invoice → JournalEntry → GeneralLedger → TrialBalance
        → IncomeStatement → BalanceSheet → CashFlowStatement
"""

from business.knowledge_graph.models import GraphEdge, GraphNode, KnowledgeGraph

# ── Node Definitions (26 nodes) ──────────────────────────────────

NODES: list[GraphNode] = [
    # ── Transactional Entities ──
    GraphNode(
        node_id="entity",
        label="Entity",
        node_type="legal_entity",
        properties={
            "description": "A legal entity or business unit",
            "examples": "FinSight Inc., FinSight Europe GmbH",
        },
    ),
    GraphNode(
        node_id="vendor",
        label="Vendor",
        node_type="counterparty",
        properties={
            "description": "External supplier or service provider",
            "category": "accounts_payable",
        },
    ),
    GraphNode(
        node_id="customer",
        label="Customer",
        node_type="counterparty",
        properties={
            "description": "External buyer of goods or services",
            "category": "accounts_receivable",
        },
    ),
    GraphNode(
        node_id="cost_center",
        label="Cost Center",
        node_type="organizational_unit",
        properties={
            "description": "Department or unit for cost tracking",
            "examples": "Engineering, Sales, Marketing, G&A",
        },
    ),
    GraphNode(
        node_id="department",
        label="Department",
        node_type="organizational_unit",
        properties={
            "description": "Functional department within an entity",
            "examples": "Engineering, Sales, Marketing, Finance",
        },
    ),
    # ── Source Documents ──
    GraphNode(
        node_id="invoice",
        label="Invoice",
        node_type="source_document",
        properties={
            "description": "Vendor invoice for goods or services received",
            "domain": "accounts_payable",
        },
    ),
    GraphNode(
        node_id="sales_pipeline",
        label="Sales Pipeline",
        node_type="source_document",
        properties={
            "description": "Opportunity and deal tracking for revenue forecasting",
            "domain": "revenue",
        },
    ),
    GraphNode(
        node_id="contract",
        label="Contract",
        node_type="source_document",
        properties={
            "description": "Customer or vendor agreement with terms",
            "domain": "legal",
        },
    ),
    # ── Accounting Records ──
    GraphNode(
        node_id="journal_entry",
        label="Journal Entry",
        node_type="accounting_record",
        properties={
            "description": "Debit/credit entry posted to the general ledger",
            "types": "accrual, adjustment, reclassification, intercompany",
        },
    ),
    GraphNode(
        node_id="gl_account",
        label="GL Account",
        node_type="account",
        properties={
            "description": "Chart of accounts entry with normal balance",
            "types": "asset, liability, equity, revenue, expense",
        },
    ),
    GraphNode(
        node_id="general_ledger",
        label="General Ledger",
        node_type="accounting_record",
        properties={
            "description": "Complete record of all financial transactions",
            "source": "journal_entries",
        },
    ),
    GraphNode(
        node_id="sub_ledger_ap",
        label="AP Sub-Ledger",
        node_type="accounting_record",
        properties={
            "description": "Detailed vendor invoice and payment records",
            "domain": "accounts_payable",
        },
    ),
    GraphNode(
        node_id="sub_ledger_ar",
        label="AR Sub-Ledger",
        node_type="accounting_record",
        properties={
            "description": "Detailed customer invoice and receipt records",
            "domain": "accounts_receivable",
        },
    ),
    # ── Financial Statements ──
    GraphNode(
        node_id="trial_balance",
        label="Trial Balance",
        node_type="financial_statement",
        properties={
            "description": "List of all GL account balances at period end",
            "purpose": "Verify debits = credits before statement preparation",
        },
    ),
    GraphNode(
        node_id="income_statement",
        label="Income Statement",
        node_type="financial_statement",
        properties={
            "description": "Revenue, expenses, and profit/loss over a period",
            "also_known_as": "P&L, Profit and Loss Statement",
        },
    ),
    GraphNode(
        node_id="balance_sheet",
        label="Balance Sheet",
        node_type="financial_statement",
        properties={
            "description": "Assets, liabilities, and equity at a point in time",
            "equation": "Assets = Liabilities + Equity",
        },
    ),
    GraphNode(
        node_id="cash_flow",
        label="Cash Flow Statement",
        node_type="financial_statement",
        properties={
            "description": "Cash inflows and outflows from operations, investing, and financing",
            "method": "indirect (reconciliation from net income)",
        },
    ),
    # ── Planning & Analysis ──
    GraphNode(
        node_id="budget",
        label="Budget",
        node_type="planning_document",
        properties={
            "description": "Annual financial plan with revenue targets and expense limits",
            "version": "FY 2026 Approved Budget",
        },
    ),
    GraphNode(
        node_id="forecast",
        label="Forecast",
        node_type="planning_document",
        properties={
            "description": "Updated forward-looking financial projection",
            "types": "rolling, driver-based, scenario",
        },
    ),
    GraphNode(
        node_id="variance",
        label="Variance",
        node_type="analysis",
        properties={
            "description": "Difference between actual and planned financial outcomes",
            "dimensions": "amount, percentage, materiality",
        },
    ),
    GraphNode(
        node_id="scenario",
        label="Scenario",
        node_type="planning_document",
        properties={
            "description": "Alternative business scenario with adjusted assumptions",
            "types": "base, upside, downside, stress",
        },
    ),
    # ── Regulatory & Audit ──
    GraphNode(
        node_id="audit_trail",
        label="Audit Trail",
        node_type="governance",
        properties={
            "description": "Immutable log of all financial transactions and changes",
            "retention": "7 years minimum",
        },
    ),
    GraphNode(
        node_id="regulatory_filing",
        label="Regulatory Filing",
        node_type="governance",
        properties={
            "description": "Submitted regulatory reports (SEC, tax authorities)",
            "types": "10-K, 10-Q, tax return, statistical report",
        },
    ),
    GraphNode(
        node_id="assertion",
        label="Assertion",
        node_type="governance",
        properties={
            "description": "Validated claim about financial data integrity",
            "types": "numeric, comparative, causal, hypothesis",
        },
    ),
    # ── Reporting ──
    GraphNode(
        node_id="board_report",
        label="Board Report",
        node_type="report",
        properties={
            "description": "Executive reporting package for board of directors",
            "audience": "Board, CEO, CFO",
        },
    ),
    GraphNode(
        node_id="kpi",
        label="KPI",
        node_type="metric",
        properties={
            "description": "Key performance indicator derived from financial data",
            "examples": "Gross Margin, EBITDA, Revenue Growth, DSO",
        },
    ),
]

# ── Edge Definitions (39 edges) ─────────────────────────────────

EDGES: list[GraphEdge] = [
    # ═══════════════════════════════════════════════════════════════
    # Transaction Processing Flow
    # ═══════════════════════════════════════════════════════════════
    # Vendor → Invoice
    GraphEdge(
        source_id="vendor",
        target_id="invoice",
        relationship="sends",
        properties={"description": "Vendor sends invoice for goods/services"},
    ),
    # Invoice → AP Sub-Ledger
    GraphEdge(
        source_id="invoice",
        target_id="sub_ledger_ap",
        relationship="recorded_in",
        properties={"description": "Invoice is recorded in AP sub-ledger"},
    ),
    # AP Sub-Ledger → Journal Entry
    GraphEdge(
        source_id="sub_ledger_ap",
        target_id="journal_entry",
        relationship="produces",
        properties={"description": "AP sub-ledger produces journal entry batch"},
    ),
    # AR Sub-Ledger → Journal Entry
    GraphEdge(
        source_id="sub_ledger_ar",
        target_id="journal_entry",
        relationship="produces",
        properties={"description": "AR sub-ledger produces journal entry batch"},
    ),
    # Journal Entry → General Ledger
    GraphEdge(
        source_id="journal_entry",
        target_id="general_ledger",
        relationship="posted_to",
        properties={"description": "Journal entry is posted to the general ledger"},
    ),
    # GL Account → General Ledger
    GraphEdge(
        source_id="gl_account",
        target_id="general_ledger",
        relationship="classified_in",
        properties={"description": "GL account is part of the chart of accounts"},
    ),
    # General Ledger → Trial Balance
    GraphEdge(
        source_id="general_ledger",
        target_id="trial_balance",
        relationship="feeds_into",
        properties={
            "description": "GL balances are aggregated into trial balance",
            "frequency": "monthly",
        },
    ),
    # Trial Balance → Income Statement
    GraphEdge(
        source_id="trial_balance",
        target_id="income_statement",
        relationship="feeds_into",
        properties={
            "description": "Revenue and expense accounts flow to P&L",
            "accounts": "4000-8000 range",
        },
    ),
    # Trial Balance → Balance Sheet
    GraphEdge(
        source_id="trial_balance",
        target_id="balance_sheet",
        relationship="feeds_into",
        properties={
            "description": "Asset, liability, and equity accounts flow to balance sheet",
            "accounts": "1000-3000 range",
        },
    ),
    # Income Statement → Balance Sheet
    GraphEdge(
        source_id="income_statement",
        target_id="balance_sheet",
        relationship="feeds_into",
        properties={
            "description": "Net income flows to retained earnings",
            "relationship": "via closing entries",
        },
    ),
    # Balance Sheet → Cash Flow Statement
    GraphEdge(
        source_id="balance_sheet",
        target_id="cash_flow",
        relationship="feeds_into",
        properties={
            "description": "Balance sheet changes drive cash flow statement",
            "method": "indirect method reconciliation",
        },
    ),
    # Income Statement → Cash Flow Statement
    GraphEdge(
        source_id="income_statement",
        target_id="cash_flow",
        relationship="feeds_into",
        properties={
            "description": "Net income is starting point for operating cash flow",
            "adjustments": "add back non-cash items",
        },
    ),
    # ═══════════════════════════════════════════════════════════════
    # Contracting & Sales
    # ═══════════════════════════════════════════════════════════════
    # Customer → Contract
    GraphEdge(
        source_id="customer",
        target_id="contract",
        relationship="signs",
        properties={"description": "Customer signs a contract"},
    ),
    # Contract → Sales Pipeline
    GraphEdge(
        source_id="contract",
        target_id="sales_pipeline",
        relationship="feeds_into",
        properties={"description": "Deal stages tracked in pipeline"},
    ),
    # Contract → AR Sub-Ledger
    GraphEdge(
        source_id="contract",
        target_id="sub_ledger_ar",
        relationship="drives",
        properties={"description": "Contract terms drive billing schedule"},
    ),
    # Customer → Invoice
    GraphEdge(
        source_id="customer",
        target_id="invoice",
        relationship="receives",
        properties={"description": "Customer receives invoice"},
    ),
    # ═══════════════════════════════════════════════════════════════
    # Budget & Forecast Integration
    # ═══════════════════════════════════════════════════════════════
    # Budget → General Ledger
    GraphEdge(
        source_id="budget",
        target_id="general_ledger",
        relationship="compared_against",
        properties={
            "description": "Budget serves as benchmark for actuals",
            "comparison": "variance analysis",
        },
    ),
    # Forecast → General Ledger
    GraphEdge(
        source_id="forecast",
        target_id="general_ledger",
        relationship="compared_against",
        properties={
            "description": "Forecast projected vs actual comparison",
            "purpose": "track forecasting accuracy",
        },
    ),
    # Variance → Income Statement
    GraphEdge(
        source_id="variance",
        target_id="income_statement",
        relationship="explains",
        properties={
            "description": "Variance analysis explains P&L deviations",
        },
    ),
    # Budget → Forecast
    GraphEdge(
        source_id="budget",
        target_id="forecast",
        relationship="baseline_for",
        properties={
            "description": "Budget is the starting baseline for forecasts",
        },
    ),
    # Forecast → Scenario
    GraphEdge(
        source_id="forecast",
        target_id="scenario",
        relationship="variation_of",
        properties={
            "description": "Scenarios are alternative forecast paths",
        },
    ),
    # ═══════════════════════════════════════════════════════════════
    # Entity & Organizational
    # ═══════════════════════════════════════════════════════════════
    # Entity → General Ledger
    GraphEdge(
        source_id="entity",
        target_id="general_ledger",
        relationship="owns",
        properties={
            "description": "Entity owns its general ledger data",
        },
    ),
    # Entity → Trial Balance
    GraphEdge(
        source_id="entity",
        target_id="trial_balance",
        relationship="prepares",
        properties={
            "description": "Entity prepares its own trial balance",
        },
    ),
    # Department → Cost Center
    GraphEdge(
        source_id="department",
        target_id="cost_center",
        relationship="contains",
        properties={
            "description": "Departments contain one or more cost centers",
        },
    ),
    # Cost Center → Budget
    GraphEdge(
        source_id="cost_center",
        target_id="budget",
        relationship="budgeted_by",
        properties={
            "description": "Cost center has an allocated budget",
        },
    ),
    # ═══════════════════════════════════════════════════════════════
    # Governance & Control
    # ═══════════════════════════════════════════════════════════════
    # Audit Trail → General Ledger
    GraphEdge(
        source_id="audit_trail",
        target_id="general_ledger",
        relationship="tracks",
        properties={
            "description": "Audit trail records all GL changes",
        },
    ),
    # Audit Trail → Journal Entry
    GraphEdge(
        source_id="audit_trail",
        target_id="journal_entry",
        relationship="tracks",
        properties={
            "description": "Audit trail records all journal entries",
        },
    ),
    # Assertion → Variance
    GraphEdge(
        source_id="assertion",
        target_id="variance",
        relationship="supports",
        properties={
            "description": "Assertions provide evidence for variance explanations",
        },
    ),
    # Assertion → Audit Trail
    GraphEdge(
        source_id="assertion",
        target_id="audit_trail",
        relationship="recorded_in",
        properties={
            "description": "Assertions are recorded in the audit trail",
        },
    ),
    # ═══════════════════════════════════════════════════════════════
    # Reporting
    # ═══════════════════════════════════════════════════════════════
    # Income Statement → Board Report
    GraphEdge(
        source_id="income_statement",
        target_id="board_report",
        relationship="feeds_into",
        properties={
            "description": "P&L is core component of board reporting",
        },
    ),
    # Balance Sheet → Board Report
    GraphEdge(
        source_id="balance_sheet",
        target_id="board_report",
        relationship="feeds_into",
        properties={
            "description": "Balance sheet is core component of board reporting",
        },
    ),
    # Cash Flow → Board Report
    GraphEdge(
        source_id="cash_flow",
        target_id="board_report",
        relationship="feeds_into",
        properties={
            "description": "Cash flow statement is core component of board reporting",
        },
    ),
    # KPI → Board Report
    GraphEdge(
        source_id="kpi",
        target_id="board_report",
        relationship="feeds_into",
        properties={
            "description": "KPIs are presented in board reports",
        },
    ),
    # Income Statement → Regulatory Filing
    GraphEdge(
        source_id="income_statement",
        target_id="regulatory_filing",
        relationship="feeds_into",
        properties={
            "description": "P&L is submitted in regulatory filings",
        },
    ),
    # Balance Sheet → Regulatory Filing
    GraphEdge(
        source_id="balance_sheet",
        target_id="regulatory_filing",
        relationship="feeds_into",
        properties={
            "description": "Balance sheet is submitted in regulatory filings",
        },
    ),
    # ═══════════════════════════════════════════════════════════════
    # Cross-Statement Dependencies
    # ═══════════════════════════════════════════════════════════════
    # KPI → Income Statement
    GraphEdge(
        source_id="kpi",
        target_id="income_statement",
        relationship="derived_from",
        properties={
            "description": "KPIs are derived from P&L line items",
        },
    ),
    # Variance → KPI
    GraphEdge(
        source_id="variance",
        target_id="kpi",
        relationship="impacts",
        properties={
            "description": "Variances impact KPI calculations",
        },
    ),
    # Entity → Regulatory Filing
    GraphEdge(
        source_id="entity",
        target_id="regulatory_filing",
        relationship="submits",
        properties={
            "description": "Legal entity submits regulatory filings",
        },
    ),
]

# ── Graph Instance ───────────────────────────────────────────────

FINANCIAL_GRAPH: KnowledgeGraph = KnowledgeGraph(
    nodes={node.node_id: node for node in NODES},
    edges=EDGES,
)
