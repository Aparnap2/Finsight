"""Populated Semantic Data Dictionary — 27 tables with full column metadata.

This module instantiates a :class:`DataDictionary` with detailed business
metadata for every column across all ORM tables in the FinSight data model.
Each column includes business name, definition, canonical type, sensitivity
classification, validation rules, and optional glossary linkage.

Usage::

    from business.data_dictionary.registry import DATA_DICTIONARY

    entities_table = DATA_DICTIONARY.get_table("entities")
    actual_amount = DATA_DICTIONARY.get_column("actuals", "amount")
"""

from business.data_dictionary.models import (
    ColumnMetadata,
    DataDictionary,
    TableMetadata,
)

# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------


def _col(
    column_name: str,
    table_name: str,
    business_name: str,
    definition: str,
    canonical_type: str,
    classification: str = "internal",
    sox_relevant: bool = False,
    pii: bool = False,
    source_system: str = "ERP",
    example: str | None = None,
    validation_rules: list[str] | None = None,
    is_nullable: bool = True,
    default_value: str | None = None,
    unit: str | None = None,
    glossary_ref: str | None = None,
) -> ColumnMetadata:
    """Create a ColumnMetadata with positional args for conciseness."""
    return ColumnMetadata(
        column_name=column_name,
        table_name=table_name,
        business_name=business_name,
        definition=definition,
        canonical_type=canonical_type,
        classification=classification,
        sox_relevant=sox_relevant,
        pii=pii,
        source_system=source_system,
        example=example,
        validation_rules=validation_rules or [],
        is_nullable=is_nullable,
        default_value=default_value,
        unit=unit,
        glossary_ref=glossary_ref,
    )


def _table(
    table_name: str,
    business_name: str,
    definition: str,
    columns: list[ColumnMetadata],
    primary_keys: list[str],
    foreign_keys: list[dict[str, str]] | None = None,
    owner: str = "FP&A Team",
    classification: str = "confidential",
) -> TableMetadata:
    """Create a TableMetadata with concise args."""
    return TableMetadata(
        table_name=table_name,
        business_name=business_name,
        definition=definition,
        columns=columns,
        primary_keys=primary_keys,
        foreign_keys=foreign_keys or [],
        owner=owner,
        classification=classification,
    )


# ===================================================================
# 1. entities
# ===================================================================

_ENTITIES = _table(
    table_name="entities",
    business_name="Legal Entities",
    definition=(
        "Legal entities or subsidiaries within the group. Each entity "
        "has its own currency and fiscal calendar."
    ),
    owner="Entity Management",
    classification="internal",
    primary_keys=["id"],
    columns=[
        _col(
            "id", "entities", "Entity Identifier",
            "Unique identifier for the legal entity.",
            "Identifier", source_system="ERP", example="ent_001",
            is_nullable=False,
        ),
        _col(
            "name", "entities", "Entity Name",
            "Legal name of the entity as registered.",
            "String", source_system="ERP", example="FinSight US Corp",
            is_nullable=False,
        ),
        _col(
            "currency", "entities", "Base Currency",
            "ISO 4217 currency code for the entity's functional currency.",
            "CurrencyCode", source_system="ERP", example="USD",
            is_nullable=False, default_value="USD", unit="iso_4217",
        ),
        _col(
            "fiscal_year_start", "entities", "Fiscal Year Start",
            "Month when the entity's fiscal year begins (MM format).",
            "FiscalPeriod", source_system="ERP", example="01",
            is_nullable=False, default_value="01", unit="month",
        ),
    ],
)

# ===================================================================
# 2. gl_accounts
# ===================================================================

_GL_ACCOUNTS = _table(
    table_name="gl_accounts",
    business_name="Chart of Accounts",
    definition=(
        "The chart of accounts listing every general ledger account "
        "across all entities, with account type, department, region, "
        "and product line dimensions."
    ),
    owner="Corporate Accounting",
    classification="internal",
    primary_keys=["id"],
    foreign_keys=[{"entity_id": "entities.id"}],
    columns=[
        _col(
            "id", "gl_accounts", "GL Account Identifier",
            "Unique identifier for the GL account.",
            "Identifier", source_system="ERP", example="acct_001",
            is_nullable=False,
        ),
        _col(
            "entity_id", "gl_accounts", "Entity Identifier",
            "Reference to the legal entity that owns this account.",
            "Identifier", source_system="ERP", example="ent_001",
            is_nullable=False,
        ),
        _col(
            "account_number", "gl_accounts", "Account Number",
            "Account number from the chart of accounts (e.g., 4010).",
            "GLAccountNumber", source_system="ERP", example="4010",
            is_nullable=False, validation_rules=[
                "Must be a valid account number in the chart of accounts",
            ],
        ),
        _col(
            "account_name", "gl_accounts", "Account Name",
            "Human-readable name of the GL account.",
            "String", source_system="ERP", example="Consulting Revenue",
            is_nullable=False,
        ),
        _col(
            "account_type", "gl_accounts", "Account Type",
            "Classification of the account (Revenue, Expense, Asset, Liability, Equity).",
            "String", source_system="ERP", example="Revenue",
            is_nullable=False, validation_rules=[
                "Must be one of: Revenue, Expense, Asset, Liability, Equity",
            ],
        ),
        _col(
            "department", "gl_accounts", "Department",
            "Department associated with this account, if department-specific.",
            "String", source_system="ERP", example="Engineering",
            is_nullable=True,
        ),
        _col(
            "region", "gl_accounts", "Region",
            "Geographic region associated with this account.",
            "String", source_system="ERP", example="North America",
            is_nullable=True,
        ),
        _col(
            "product_line", "gl_accounts", "Product Line",
            "Product or service line associated with this account.",
            "String", source_system="ERP", example="SaaS Platform",
            is_nullable=True,
        ),
    ],
)

# ===================================================================
# 3. trial_balance
# ===================================================================

_TRIAL_BALANCE = _table(
    table_name="trial_balance",
    business_name="Trial Balance",
    definition=(
        "The trial balance for each period, showing debit, credit, and "
        "calculated balance per GL account per entity."
    ),
    owner="Corporate Accounting",
    classification="confidential",
    primary_keys=["id"],
    foreign_keys=[
        {"entity_id": "entities.id"},
        {"account_id": "gl_accounts.id"},
    ],
    columns=[
        _col(
            "id", "trial_balance", "Trial Balance Identifier",
            "Unique identifier for the trial balance record.",
            "Identifier", source_system="ERP", example="tb_001",
            is_nullable=False,
        ),
        _col(
            "entity_id", "trial_balance", "Entity Identifier",
            "Reference to the legal entity.",
            "Identifier", source_system="ERP", example="ent_001",
            is_nullable=False,
        ),
        _col(
            "period", "trial_balance", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="ERP", example="2026-07",
            is_nullable=False, unit="year_month",
        ),
        _col(
            "account_id", "trial_balance", "GL Account Identifier",
            "Reference to the GL account.",
            "Identifier", source_system="ERP", example="acct_001",
            is_nullable=False,
        ),
        _col(
            "debit", "trial_balance", "Debit Amount",
            "Total debit entries for the account in this period.",
            "Money", source_system="ERP", example="150000.00",
            classification="confidential", sox_relevant=True,
            is_nullable=True, default_value="0", unit="entity_currency",
            validation_rules=["Must be >= 0"],
        ),
        _col(
            "credit", "trial_balance", "Credit Amount",
            "Total credit entries for the account in this period.",
            "Money", source_system="ERP", example="75000.00",
            classification="confidential", sox_relevant=True,
            is_nullable=True, default_value="0", unit="entity_currency",
            validation_rules=["Must be >= 0"],
        ),
        _col(
            "balance", "trial_balance", "Net Balance",
            "Calculated balance (debit − credit) for the account.",
            "Money", source_system="ERP (computed)",
            example="75000.00",
            classification="confidential", sox_relevant=True,
            is_nullable=True, unit="entity_currency",
            validation_rules=["balance = debit − credit"],
        ),
    ],
)

# ===================================================================
# 4. budget_lines
# ===================================================================

_BUDGET_LINES = _table(
    table_name="budget_lines",
    business_name="Budget Lines",
    definition=(
        "Budgeted amounts per entity, period, account, and department. "
        "Represents the approved financial plan."
    ),
    owner="FP&A Team",
    classification="confidential",
    primary_keys=["id"],
    foreign_keys=[
        {"entity_id": "entities.id"},
        {"account_id": "gl_accounts.id"},
    ],
    columns=[
        _col(
            "id", "budget_lines", "Budget Line Identifier",
            "Unique identifier for the budget line.",
            "Identifier", source_system="FP&A tool", example="bl_001",
            is_nullable=False,
        ),
        _col(
            "entity_id", "budget_lines", "Entity Identifier",
            "Reference to the legal entity.",
            "Identifier", source_system="FP&A tool", example="ent_001",
            is_nullable=False,
        ),
        _col(
            "period", "budget_lines", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="FP&A tool", example="2026-07",
            is_nullable=False, unit="year_month",
        ),
        _col(
            "account_id", "budget_lines", "GL Account Identifier",
            "Reference to the GL account being budgeted.",
            "Identifier", source_system="FP&A tool", example="acct_001",
            is_nullable=False,
        ),
        _col(
            "department", "budget_lines", "Department",
            "Department responsible for this budget line.",
            "String", source_system="FP&A tool", example="Engineering",
            is_nullable=True,
        ),
        _col(
            "amount", "budget_lines", "Budget Amount",
            "Approved budget amount for this period-account-department.",
            "Money", source_system="FP&A tool", example="250000.00",
            classification="confidential", sox_relevant=True,
            is_nullable=False, unit="entity_currency",
            validation_rules=[
                "Amount must not be zero for active accounts",
                "Must not exceed entity-level budget cap",
            ],
            glossary_ref="glossary.budgeting.budget",
        ),
        _col(
            "notes", "budget_lines", "Budget Notes",
            "Free-text notes describing assumptions or justifications.",
            "Text", source_system="FP&A tool", example="Based on 15% headcount growth",
            is_nullable=True,
        ),
    ],
)

# ===================================================================
# 5. forecast_lines
# ===================================================================

_FORECAST_LINES = _table(
    table_name="forecast_lines",
    business_name="Forecast Lines",
    definition=(
        "Forecasted amounts per entity, period, account, and department, "
        "with version tracking for multi-scenario planning."
    ),
    owner="FP&A Team",
    classification="confidential",
    primary_keys=["id"],
    foreign_keys=[
        {"entity_id": "entities.id"},
        {"account_id": "gl_accounts.id"},
    ],
    columns=[
        _col(
            "id", "forecast_lines", "Forecast Line Identifier",
            "Unique identifier for the forecast line.",
            "Identifier", source_system="FP&A tool", example="fl_001",
            is_nullable=False,
        ),
        _col(
            "entity_id", "forecast_lines", "Entity Identifier",
            "Reference to the legal entity.",
            "Identifier", source_system="FP&A tool", example="ent_001",
            is_nullable=False,
        ),
        _col(
            "period", "forecast_lines", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="FP&A tool", example="2026-07",
            is_nullable=False, unit="year_month",
        ),
        _col(
            "account_id", "forecast_lines", "GL Account Identifier",
            "Reference to the GL account being forecasted.",
            "Identifier", source_system="FP&A tool", example="acct_001",
            is_nullable=False,
        ),
        _col(
            "department", "forecast_lines", "Department",
            "Department for this forecast line.",
            "String", source_system="FP&A tool", example="Engineering",
            is_nullable=True,
        ),
        _col(
            "amount", "forecast_lines", "Forecast Amount",
            "Forecasted amount for this period-account-department.",
            "Money", source_system="FP&A tool", example="265000.00",
            classification="confidential", sox_relevant=True,
            is_nullable=False, unit="entity_currency",
            validation_rules=["Amount must be a valid projection"],
            glossary_ref="glossary.budgeting.reforecast",
        ),
        _col(
            "version", "forecast_lines", "Forecast Version",
            "Version number for multi-scenario or rolling forecast tracking.",
            "Count", source_system="FP&A tool", example="2",
            is_nullable=True, default_value="1",
            validation_rules=["Must be a positive integer"],
        ),
        _col(
            "created_at", "forecast_lines", "Created At",
            "Timestamp when this forecast line was created.",
            "DateTime", source_system="FP&A tool", example="2026-07-15T10:30:00",
            is_nullable=True,
        ),
    ],
)

# ===================================================================
# 6. actuals
# ===================================================================

_ACTUALS = _table(
    table_name="actuals",
    business_name="Actuals",
    definition=(
        "Recorded actual financial amounts per entity, period, account, "
        "and department. The ground truth for period-end financial results."
    ),
    owner="Corporate Accounting",
    classification="confidential",
    primary_keys=["id"],
    foreign_keys=[
        {"entity_id": "entities.id"},
        {"account_id": "gl_accounts.id"},
    ],
    columns=[
        _col(
            "id", "actuals", "Actual Identifier",
            "Unique identifier for the actual record.",
            "Identifier", source_system="ERP", example="act_001",
            is_nullable=False,
        ),
        _col(
            "entity_id", "actuals", "Entity Identifier",
            "Reference to the legal entity.",
            "Identifier", source_system="ERP", example="ent_001",
            is_nullable=False,
        ),
        _col(
            "period", "actuals", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="ERP", example="2026-07",
            is_nullable=False, unit="year_month",
        ),
        _col(
            "account_id", "actuals", "GL Account Identifier",
            "Reference to the GL account.",
            "Identifier", source_system="ERP", example="acct_001",
            is_nullable=False,
        ),
        _col(
            "department", "actuals", "Department",
            "Department for this actual record.",
            "String", source_system="ERP", example="Engineering",
            is_nullable=True,
        ),
        _col(
            "amount", "actuals", "Actual Amount",
            "Recorded financial value for the period-account combination.",
            "Money", source_system="ERP", example="1250000.00",
            classification="confidential", sox_relevant=True,
            is_nullable=False, unit="entity_currency",
            validation_rules=[
                "Must reconcile with trial balance",
                "Amount must not be null for closed periods",
            ],
            glossary_ref="glossary.revenue.net",
        ),
    ],
)

# ===================================================================
# 7. headcount_data
# ===================================================================

_HEADCOUNT_DATA = _table(
    table_name="headcount_data",
    business_name="Headcount Data",
    definition=(
        "Workforce metrics per entity, period, and department including "
        "headcount, compensation costs, hires, and departures."
    ),
    owner="HR / People Analytics",
    classification="confidential",
    primary_keys=["id"],
    foreign_keys=[{"entity_id": "entities.id"}],
    columns=[
        _col(
            "id", "headcount_data", "Headcount Record Identifier",
            "Unique identifier for the headcount record.",
            "Identifier", source_system="HRIS", example="hc_001",
            is_nullable=False,
        ),
        _col(
            "entity_id", "headcount_data", "Entity Identifier",
            "Reference to the legal entity.",
            "Identifier", source_system="HRIS", example="ent_001",
            is_nullable=False,
        ),
        _col(
            "period", "headcount_data", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="HRIS", example="2026-07",
            is_nullable=False, unit="year_month",
        ),
        _col(
            "department", "headcount_data", "Department",
            "Department for this headcount record.",
            "String", source_system="HRIS", example="Engineering",
            is_nullable=False,
        ),
        _col(
            "headcount", "headcount_data", "Headcount (FTE)",
            "Number of full-time equivalent employees.",
            "Count", source_system="HRIS", example="42",
            classification="confidential", is_nullable=True, default_value="0",
            validation_rules=["Must be >= 0"],
            glossary_ref="glossary.expense.compensation",
        ),
        _col(
            "total_compensation", "headcount_data", "Total Compensation",
            "Total compensation cost including salary, benefits, and equity.",
            "Money", source_system="HRIS", example="8400000.00",
            classification="restricted", sox_relevant=False, pii=True,
            is_nullable=True, default_value="0", unit="entity_currency",
            validation_rules=["Must be >= 0"],
            glossary_ref="glossary.expense.compensation",
        ),
        _col(
            "new_hires", "headcount_data", "New Hires",
            "Number of new employees hired in this period.",
            "Count", source_system="HRIS", example="3",
            is_nullable=True, default_value="0",
            validation_rules=["Must be >= 0"],
        ),
        _col(
            "departures", "headcount_data", "Departures",
            "Number of employees who left the organization in this period.",
            "Count", source_system="HRIS", example="1",
            is_nullable=True, default_value="0",
            validation_rules=["Must be >= 0"],
        ),
    ],
)

# ===================================================================
# 8. vendor_invoices
# ===================================================================

_VENDOR_INVOICES = _table(
    table_name="vendor_invoices",
    business_name="Vendor Invoices",
    definition=(
        "Accounts payable invoices from vendors, tracking amounts due, "
        "categories, payment status, and linked GL accounts."
    ),
    owner="Accounts Payable",
    classification="confidential",
    primary_keys=["id"],
    foreign_keys=[
        {"entity_id": "entities.id"},
        {"account_id": "gl_accounts.id"},
    ],
    columns=[
        _col(
            "id", "vendor_invoices", "Invoice Identifier",
            "Unique identifier for the vendor invoice.",
            "Identifier", source_system="AP system", example="inv_001",
            is_nullable=False,
        ),
        _col(
            "entity_id", "vendor_invoices", "Entity Identifier",
            "Reference to the legal entity receiving the invoice.",
            "Identifier", source_system="AP system", example="ent_001",
            is_nullable=False,
        ),
        _col(
            "period", "vendor_invoices", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="AP system", example="2026-07",
            is_nullable=False, unit="year_month",
        ),
        _col(
            "vendor_name", "vendor_invoices", "Vendor Name",
            "Legal name of the vendor or supplier.",
            "String", source_system="AP system", example="Acme Corp",
            is_nullable=False,
        ),
        _col(
            "account_id", "vendor_invoices", "GL Account Identifier",
            "Reference to the GL account for expense coding.",
            "Identifier", source_system="AP system", example="acct_001",
            is_nullable=False,
        ),
        _col(
            "amount", "vendor_invoices", "Invoice Amount",
            "Total invoice amount in entity currency.",
            "Money", source_system="AP system", example="15000.00",
            classification="confidential", sox_relevant=True,
            is_nullable=False, unit="entity_currency",
            validation_rules=["Must match vendor statement"],
            glossary_ref="glossary.balance_sheet.ap",
        ),
        _col(
            "category", "vendor_invoices", "Expense Category",
            "Classification of the expense (e.g., Software, Travel, Consulting).",
            "String", source_system="AP system", example="Software",
            is_nullable=True,
        ),
        _col(
            "invoice_date", "vendor_invoices", "Invoice Date",
            "Date the invoice was issued by the vendor.",
            "DateTime", source_system="AP system", example="2026-07-01",
            is_nullable=False,
        ),
        _col(
            "status", "vendor_invoices", "Invoice Status",
            "Current processing status (draft, approved, paid, disputed).",
            "String", source_system="AP system", example="approved",
            is_nullable=False, default_value="draft",
            validation_rules=[
                "Must be one of: draft, approved, paid, disputed, cancelled",
            ],
        ),
    ],
)

# ===================================================================
# 9. sales_pipeline
# ===================================================================

_SALES_PIPELINE = _table(
    table_name="sales_pipeline",
    business_name="Sales Pipeline",
    definition=(
        "Deal-level sales pipeline data tracking opportunities through "
        "the sales funnel with stage, expected close date, amount, "
        "region, and product information."
    ),
    owner="Sales Operations",
    classification="confidential",
    primary_keys=["id"],
    foreign_keys=[{"entity_id": "entities.id"}],
    columns=[
        _col(
            "id", "sales_pipeline", "Pipeline Identifier",
            "Unique identifier for the sales pipeline deal.",
            "Identifier", source_system="CRM", example="deal_001",
            is_nullable=False,
        ),
        _col(
            "entity_id", "sales_pipeline", "Entity Identifier",
            "Reference to the legal entity.",
            "Identifier", source_system="CRM", example="ent_001",
            is_nullable=False,
        ),
        _col(
            "period", "sales_pipeline", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="CRM", example="2026-07",
            is_nullable=False, unit="year_month",
        ),
        _col(
            "deal_name", "sales_pipeline", "Deal Name",
            "Descriptive name of the sales opportunity.",
            "String", source_system="CRM", example="Acme Corp - Enterprise License",
            is_nullable=False,
        ),
        _col(
            "stage", "sales_pipeline", "Deal Stage",
            "Current stage in the sales process (e.g., prospecting, negotiation, closed-won).",
            "String", source_system="CRM", example="negotiation",
            is_nullable=False,
        ),
        _col(
            "expected_close_date", "sales_pipeline", "Expected Close Date",
            "Expected date when the deal will close.",
            "DateTime", source_system="CRM", example="2026-08-15",
            is_nullable=False, validation_rules=["Must be in the future"],
        ),
        _col(
            "amount", "sales_pipeline", "Deal Amount",
            "Expected revenue from the deal.",
            "Money", source_system="CRM", example="120000.00",
            classification="confidential", sox_relevant=False,
            is_nullable=False, unit="entity_currency",
            validation_rules=["Must be > 0"],
            glossary_ref="glossary.revenue.average_deal_size",
        ),
        _col(
            "region", "sales_pipeline", "Region",
            "Geographic region of the deal.",
            "String", source_system="CRM", example="North America",
            is_nullable=True,
        ),
        _col(
            "product", "sales_pipeline", "Product",
            "Product or service line associated with the deal.",
            "String", source_system="CRM", example="Enterprise SaaS",
            is_nullable=True,
        ),
    ],
)

# ===================================================================
# 10. agent_runs
# ===================================================================

_AGENT_RUNS = _table(
    table_name="agent_runs",
    business_name="Agent Runs",
    definition=(
        "Tracks each execution of an AI agent pipeline, including status, "
        "timing, and linkage to the originating pipeline request."
    ),
    owner="ML Platform",
    classification="internal",
    primary_keys=["id"],
    foreign_keys=[{"entity_id": "entities.id"}],
    columns=[
        _col(
            "id", "agent_runs", "Agent Run Identifier",
            "Unique identifier for the agent run.",
            "Identifier", source_system="Agent engine", example="run_001",
            is_nullable=False,
        ),
        _col(
            "pipeline_id", "agent_runs", "Pipeline Identifier",
            "Reference to the pipeline that triggered this run.",
            "Identifier", source_system="Agent engine", example="pl_001",
            is_nullable=True,
        ),
        _col(
            "entity_id", "agent_runs", "Entity Identifier",
            "Reference to the legal entity being analyzed.",
            "Identifier", source_system="Agent engine", example="ent_001",
            is_nullable=False,
        ),
        _col(
            "period", "agent_runs", "Fiscal Period",
            "The fiscal period being analyzed in YYYY-MM format.",
            "FiscalPeriod", source_system="Agent engine", example="2026-07",
            is_nullable=False, unit="year_month",
        ),
        _col(
            "status", "agent_runs", "Run Status",
            "Current status (pending, running, completed, failed).",
            "String", source_system="Agent engine", example="completed",
            is_nullable=False, default_value="pending",
        ),
        _col(
            "started_at", "agent_runs", "Started At",
            "Timestamp when the agent run was initiated.",
            "DateTime", source_system="Agent engine", example="2026-07-30T08:00:00",
            is_nullable=False,
        ),
        _col(
            "completed_at", "agent_runs", "Completed At",
            "Timestamp when the agent run completed.",
            "DateTime", source_system="Agent engine", example="2026-07-30T08:05:30",
            is_nullable=True,
        ),
    ],
)

# ===================================================================
# 11. variances
# ===================================================================

_VARIANCES = _table(
    table_name="variances",
    business_name="Variances",
    definition=(
        "Computed variances between actual and budget amounts per account "
        "and department, with materiality flags and classification."
    ),
    owner="FP&A Team",
    classification="confidential",
    primary_keys=["id"],
    foreign_keys=[
        {"agent_run_id": "agent_runs.id"},
        {"account_id": "gl_accounts.id"},
    ],
    columns=[
        _col(
            "id", "variances", "Variance Identifier",
            "Unique identifier for the variance record.",
            "Identifier", source_system="Variance engine", example="var_001",
            is_nullable=False,
        ),
        _col(
            "agent_run_id", "variances", "Agent Run Identifier",
            "Reference to the agent run that computed this variance.",
            "Identifier", source_system="Variance engine", example="run_001",
            is_nullable=False,
        ),
        _col(
            "account_id", "variances", "GL Account Identifier",
            "Reference to the GL account being analyzed.",
            "Identifier", source_system="Variance engine", example="acct_001",
            is_nullable=False,
        ),
        _col(
            "department", "variances", "Department",
            "Department for this variance, if department-level analysis.",
            "String", source_system="Variance engine", example="Engineering",
            is_nullable=True,
        ),
        _col(
            "actual_amount", "variances", "Actual Amount",
            "The actual recorded amount for the period.",
            "Money", source_system="ERP", example="1250000.00",
            classification="confidential", sox_relevant=True,
            is_nullable=False, unit="entity_currency",
            glossary_ref="glossary.revenue.net",
        ),
        _col(
            "budget_amount", "variances", "Budget Amount",
            "The budgeted amount for the period.",
            "Money", source_system="FP&A tool", example="1100000.00",
            classification="confidential", sox_relevant=True,
            is_nullable=False, unit="entity_currency",
            glossary_ref="glossary.budgeting.budget",
        ),
        _col(
            "variance_amount", "variances", "Variance Amount",
            "Computed difference (actual − budget).",
            "Money", source_system="Variance engine (computed)",
            example="150000.00",
            classification="confidential", sox_relevant=True,
            is_nullable=True, unit="entity_currency",
            validation_rules=["variance_amount = actual_amount − budget_amount"],
            glossary_ref="glossary.variance.variance",
        ),
        _col(
            "variance_pct", "variances", "Variance Percentage",
            "Variance expressed as a percentage of budget.",
            "Percentage", source_system="Variance engine (computed)",
            example="13.6400",
            classification="confidential", sox_relevant=True,
            is_nullable=True, unit="percentage",
            validation_rules=[
                "variance_pct = (actual − budget) / ABS(budget) * 100",
            ],
            glossary_ref="glossary.variance.percentage",
        ),
        _col(
            "is_material", "variances", "Is Material",
            "Whether this variance exceeds materiality thresholds.",
            "Boolean", source_system="Materiality engine", example="true",
            classification="confidential", sox_relevant=True,
            is_nullable=False, default_value="false",
            validation_rules=[
                "Material if variance > $50K AND > 10%",
            ],
            glossary_ref="glossary.variance.material",
        ),
        _col(
            "classification", "variances", "Variance Classification",
            "Root cause classification (favorable, unfavorable).",
            "String", source_system="Variance engine", example="favorable",
            is_nullable=False,
            validation_rules=["Must be favorable or unfavorable"],
            glossary_ref="glossary.variance.favorable",
        ),
        _col(
            "confidence_score", "variances", "Confidence Score",
            "Confidence level in the variance computation (0-1).",
            "Percentage", source_system="Variance engine", example="0.9500",
            is_nullable=True, unit="decimal",
            validation_rules=["Must be between 0 and 1"],
        ),
    ],
)

# ===================================================================
# 12. root_causes
# ===================================================================

_ROOT_CAUSES = _table(
    table_name="root_causes",
    business_name="Root Causes",
    definition=(
        "Root cause analysis findings for identified variances, "
        "including evidence, confidence scores, and recommended actions."
    ),
    owner="FP&A Team",
    classification="confidential",
    primary_keys=["id"],
    foreign_keys=[{"variance_id": "variances.id"}],
    columns=[
        _col(
            "id", "root_causes", "Root Cause Identifier",
            "Unique identifier for the root cause record.",
            "Identifier", source_system="Root cause agent",
            example="rc_001", is_nullable=False,
        ),
        _col(
            "variance_id", "root_causes", "Variance Identifier",
            "Reference to the variance being analyzed.",
            "Identifier", source_system="Root cause agent",
            example="var_001", is_nullable=False,
        ),
        _col(
            "summary", "root_causes", "Root Cause Summary",
            "Natural language summary of the root cause finding.",
            "Text", source_system="Root cause agent",
            example="Revenue shortfall driven by 15% deal slip in Enterprise segment",
            is_nullable=False,
        ),
        _col(
            "evidence_json", "root_causes", "Evidence (JSON)",
            "Structured evidence supporting the root cause finding.",
            "JSON", source_system="Root cause agent",
            example='{"segments": [{"name": "Enterprise", "impact": -30000}]}',
            is_nullable=True,
        ),
        _col(
            "confidence_score", "root_causes", "Confidence Score",
            "Confidence in the root cause determination (0-1).",
            "Percentage", source_system="Root cause agent", example="0.8700",
            is_nullable=True, unit="decimal",
            validation_rules=["Must be between 0 and 1"],
        ),
        _col(
            "recommended_action", "root_causes", "Recommended Action",
            "Suggested action to address the root cause.",
            "Text", source_system="Root cause agent",
            example="Increase engagement with Enterprise segment through targeted campaigns",
            is_nullable=True,
        ),
        _col(
            "similar_case_ref", "root_causes", "Similar Case Reference",
            "Reference to a similar historical root cause finding.",
            "String", source_system="Root cause agent", example="rc_045",
            is_nullable=True,
        ),
    ],
)

# ===================================================================
# 13. commentary_drafts
# ===================================================================

_COMMENTARY_DRAFTS = _table(
    table_name="commentary_drafts",
    business_name="Commentary Drafts",
    definition=(
        "Versioned drafts of narrative commentary generated by AI agents, "
        "tracking review status and reviewer assignments."
    ),
    owner="FP&A Team",
    classification="confidential",
    primary_keys=["id"],
    foreign_keys=[{"agent_run_id": "agent_runs.id"}],
    columns=[
        _col(
            "id", "commentary_drafts", "Commentary Draft Identifier",
            "Unique identifier for the commentary draft.",
            "Identifier", source_system="Commentary agent", example="cd_001",
            is_nullable=False,
        ),
        _col(
            "agent_run_id", "commentary_drafts", "Agent Run Identifier",
            "Reference to the agent run that generated this draft.",
            "Identifier", source_system="Commentary agent", example="run_001",
            is_nullable=False,
        ),
        _col(
            "version", "commentary_drafts", "Draft Version",
            "Version number for tracking draft iterations.",
            "Count", source_system="Commentary agent", example="1",
            is_nullable=False, default_value="1",
        ),
        _col(
            "content_json", "commentary_drafts", "Content (JSON)",
            "Structured commentary content as JSON.",
            "JSON", source_system="Commentary agent",
            classification="confidential",
            example='{"headline": "Revenue up 15% vs budget"}',
            is_nullable=True,
        ),
        _col(
            "status", "commentary_drafts", "Draft Status",
            "Review status (draft, under_review, approved, rejected).",
            "String", source_system="Commentary agent", example="under_review",
            is_nullable=False, default_value="draft",
        ),
        _col(
            "reviewed_by", "commentary_drafts", "Reviewed By",
            "User identifier of the reviewer.",
            "String", source_system="Commentary agent",
            example="jane.doe@finsight.com",
            is_nullable=True,
        ),
        _col(
            "reviewed_at", "commentary_drafts", "Reviewed At",
            "Timestamp when the draft was reviewed.",
            "DateTime", source_system="Commentary agent",
            example="2026-07-30T14:00:00",
            is_nullable=True,
        ),
    ],
)

# ===================================================================
# 14. scenarios
# ===================================================================

_SCENARIOS = _table(
    table_name="scenarios",
    business_name="Scenarios",
    definition=(
        "Financial scenario definitions capturing assumptions and projected "
        "impacts on revenue, EBITDA, and cash flow."
    ),
    owner="FP&A Team",
    classification="confidential",
    primary_keys=["id"],
    foreign_keys=[{"agent_run_id": "agent_runs.id"}],
    columns=[
        _col(
            "id", "scenarios", "Scenario Identifier",
            "Unique identifier for the scenario.",
            "Identifier", source_system="Scenario engine", example="sc_001",
            is_nullable=False,
        ),
        _col(
            "agent_run_id", "scenarios", "Agent Run Identifier",
            "Reference to the agent run that created this scenario.",
            "Identifier", source_system="Scenario engine", example="run_001",
            is_nullable=False,
        ),
        _col(
            "name", "scenarios", "Scenario Name",
            "Human-readable name for the scenario (e.g., Base Case, Upside).",
            "String", source_system="Scenario engine", example="Upside Case",
            is_nullable=False,
        ),
        _col(
            "description", "scenarios", "Scenario Description",
            "Detailed description of the scenario assumptions.",
            "Text", source_system="Scenario engine",
            example="Assumes 20% headcount growth and 15% revenue uplift",
            is_nullable=True,
        ),
        _col(
            "assumptions_json", "scenarios", "Assumptions (JSON)",
            "Structured assumption parameters used in the scenario.",
            "JSON", source_system="Scenario engine",
            example='{"revenue_growth": 0.15, "headcount_growth": 0.20}',
            is_nullable=True,
            glossary_ref="glossary.forecasting.scenario",
        ),
        _col(
            "revenue_impact", "scenarios", "Revenue Impact",
            "Projected revenue impact of this scenario.",
            "Money", source_system="Scenario engine", example="2500000.00",
            classification="confidential", sox_relevant=False,
            is_nullable=True, unit="entity_currency",
        ),
        _col(
            "ebitda_impact", "scenarios", "EBITDA Impact",
            "Projected EBITDA impact of this scenario.",
            "Money", source_system="Scenario engine", example="850000.00",
            classification="confidential", sox_relevant=False,
            is_nullable=True, unit="entity_currency",
            glossary_ref="glossary.profitability.ebitda",
        ),
        _col(
            "cash_impact", "scenarios", "Cash Impact",
            "Projected cash flow impact of this scenario.",
            "Money", source_system="Scenario engine", example="500000.00",
            classification="confidential", sox_relevant=False,
            is_nullable=True, unit="entity_currency",
            glossary_ref="glossary.cash_flow.free",
        ),
        _col(
            "probability", "scenarios", "Probability",
            "Estimated probability of this scenario occurring.",
            "String", source_system="Scenario engine", example="medium",
            is_nullable=True,
            validation_rules=["Must be one of: low, medium, high"],
        ),
    ],
)

# ===================================================================
# 15. review_logs
# ===================================================================

_REVIEW_LOGS = _table(
    table_name="review_logs",
    business_name="Review Logs",
    definition=(
        "Audit trail of human review checkpoints for agent-generated "
        "content, tracking reviewer decisions and notes."
    ),
    owner="FP&A Team",
    classification="internal",
    primary_keys=["id"],
    foreign_keys=[{"agent_run_id": "agent_runs.id"}],
    columns=[
        _col(
            "id", "review_logs", "Review Log Identifier",
            "Unique identifier for the review log entry.",
            "Identifier", source_system="Review system", example="rl_001",
            is_nullable=False,
        ),
        _col(
            "agent_run_id", "review_logs", "Agent Run Identifier",
            "Reference to the agent run under review.",
            "Identifier", source_system="Review system", example="run_001",
            is_nullable=True,
        ),
        _col(
            "checkpoint", "review_logs", "Checkpoint",
            "Name of the review checkpoint (e.g., variance_review, commentary_review).",
            "String", source_system="Review system",
            example="variance_review",
            is_nullable=True,
        ),
        _col(
            "reviewer", "review_logs", "Reviewer",
            "User identifier of the reviewer.",
            "String", source_system="Review system",
            example="jane.doe@finsight.com",
            is_nullable=True,
        ),
        _col(
            "decision", "review_logs", "Decision",
            "Review decision (approved, rejected, needs_revision).",
            "String", source_system="Review system", example="approved",
            is_nullable=True,
        ),
        _col(
            "notes", "review_logs", "Review Notes",
            "Free-text notes from the reviewer.",
            "Text", source_system="Review system",
            example="Variance explanations look accurate. Approved.",
            is_nullable=True,
        ),
        _col(
            "timestamp", "review_logs", "Timestamp",
            "Timestamp when the review was logged.",
            "DateTime", source_system="Review system",
            example="2026-07-30T14:30:00",
            is_nullable=True,
        ),
    ],
)

# ===================================================================
# 16. review_decisions
# ===================================================================

_REVIEW_DECISIONS = _table(
    table_name="review_decisions",
    business_name="Review Decisions",
    definition=(
        "Human or automated review decisions on assertions, tracking "
        "approvals, rejections, and escalations."
    ),
    owner="Data Governance",
    classification="internal",
    primary_keys=["id"],
    columns=[
        _col(
            "id", "review_decisions", "Review Decision Identifier",
            "Unique identifier for the review decision.",
            "Identifier", source_system="Assertion pipeline",
            example="rd_001", is_nullable=False,
        ),
        _col(
            "tenant_id", "review_decisions", "Tenant Identifier",
            "Multi-tenant identifier for data isolation.",
            "Identifier", source_system="Platform", example="tenant_acme",
            is_nullable=False,
        ),
        _col(
            "period", "review_decisions", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="Assertion pipeline",
            example="2026-07", is_nullable=False, unit="year_month",
        ),
        _col(
            "assertion_id", "review_decisions", "Assertion Identifier",
            "Reference to the assertion being reviewed.",
            "Identifier", source_system="Assertion pipeline",
            example="assert_001", is_nullable=False,
        ),
        _col(
            "decision", "review_decisions", "Decision",
            "Review outcome (approved, rejected, escalated).",
            "String", source_system="Review system", example="approved",
            is_nullable=False,
            validation_rules=[
                "Must be one of: approved, rejected, escalated",
            ],
        ),
        _col(
            "reviewer", "review_decisions", "Reviewer",
            "User or system that made the review decision.",
            "String", source_system="Review system",
            example="auto_policy_engine", is_nullable=False,
        ),
        _col(
            "confidence", "review_decisions", "Confidence Score",
            "Confidence in the review decision (0-1).",
            "Percentage", source_system="Review system", example="0.9500",
            is_nullable=True, unit="decimal",
            validation_rules=["Must be between 0 and 1"],
        ),
        _col(
            "notes", "review_decisions", "Notes",
            "Free-text notes explaining the decision rationale.",
            "Text", source_system="Review system", example="Auto-approved per policy P-042",
            is_nullable=True,
        ),
        _col(
            "created_at", "review_decisions", "Created At",
            "Timestamp when the review decision was recorded.",
            "DateTime", source_system="Review system",
            example="2026-07-30T14:00:00", is_nullable=True,
        ),
    ],
)

# ===================================================================
# 17. action_items
# ===================================================================

_ACTION_ITEMS = _table(
    table_name="action_items",
    business_name="Action Items",
    definition=(
        "Proposed and tracked action items with full gate-enforcement "
        "metadata including domain, target, status, and linked assertions."
    ),
    owner="FP&A Team",
    classification="confidential",
    primary_keys=["id"],
    columns=[
        _col(
            "id", "action_items", "Action Item Identifier",
            "Unique identifier for the action item.",
            "Identifier", source_system="Recommendation engine",
            example="ai_001", is_nullable=False,
        ),
        _col(
            "tenant_id", "action_items", "Tenant Identifier",
            "Multi-tenant identifier for data isolation.",
            "Identifier", source_system="Platform", example="tenant_acme",
            is_nullable=False,
        ),
        _col(
            "period", "action_items", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="Recommendation engine",
            example="2026-07", is_nullable=False, unit="year_month",
        ),
        _col(
            "action", "action_items", "Action Verb",
            "Proposed action verb (reduce, increase, reallocate, etc.).",
            "String", source_system="Recommendation engine",
            example="reduce", is_nullable=False,
        ),
        _col(
            "domain", "action_items", "Domain",
            "Business domain of the action (cost, revenue, headcount).",
            "String", source_system="Recommendation engine",
            example="cost", is_nullable=False,
        ),
        _col(
            "target", "action_items", "Target",
            "Specific target of the action (account, department, process).",
            "String", source_system="Recommendation engine",
            example="Travel Expenses - Marketing", is_nullable=False,
        ),
        _col(
            "description", "action_items", "Description",
            "Detailed description of the proposed action.",
            "Text", source_system="Recommendation engine",
            example="Reduce travel budget by 15% for Q3 based on low utilization",
            is_nullable=True,
        ),
        _col(
            "status", "action_items", "Status",
            "Lifecycle status (proposed, approved, in_progress, completed, cancelled).",
            "String", source_system="Recommendation engine",
            example="proposed", is_nullable=True, default_value="proposed",
        ),
        _col(
            "owner", "action_items", "Owner",
            "User or team responsible for executing this action.",
            "String", source_system="Recommendation engine",
            example="marketing_team", is_nullable=True,
        ),
        _col(
            "impact_json", "action_items", "Financial Impact (JSON)",
            "Estimated financial impact of executing the action.",
            "JSON", source_system="Recommendation engine",
            classification="confidential",
            example='{"savings": 50000, "confidence": 0.8}',
            is_nullable=True,
        ),
        _col(
            "cited_assertion_ids", "action_items", "Cited Assertion IDs",
            "List of assertion IDs that support this recommendation.",
            "JSON", source_system="Recommendation engine",
            example='["assert_001", "assert_002"]',
            is_nullable=True,
        ),
        _col(
            "blocked_reason", "action_items", "Blocked Reason",
            "Explanation of why the action is blocked, if applicable.",
            "Text", source_system="Policy engine",
            example="Requires VP approval for amounts over $25K",
            is_nullable=True,
        ),
        _col(
            "created_at", "action_items", "Created At",
            "Timestamp when the action item was created.",
            "DateTime", source_system="Recommendation engine",
            example="2026-07-30T14:00:00", is_nullable=True,
        ),
        _col(
            "updated_at", "action_items", "Updated At",
            "Timestamp of the last update to this action item.",
            "DateTime", source_system="Recommendation engine",
            example="2026-07-30T15:00:00", is_nullable=True,
        ),
    ],
)

# ===================================================================
# 18. commentary_versions
# ===================================================================

_COMMENTARY_VERSIONS = _table(
    table_name="commentary_versions",
    business_name="Commentary Versions",
    definition=(
        "Versioned commentary narratives for each period, supporting "
        "iteration tracking with status and author metadata."
    ),
    owner="FP&A Team",
    classification="confidential",
    primary_keys=["id"],
    columns=[
        _col(
            "id", "commentary_versions", "Commentary Version Identifier",
            "Unique identifier for the commentary version.",
            "Identifier", source_system="Commentary engine",
            example="cv_001", is_nullable=False,
        ),
        _col(
            "tenant_id", "commentary_versions", "Tenant Identifier",
            "Multi-tenant identifier for data isolation.",
            "Identifier", source_system="Platform", example="tenant_acme",
            is_nullable=False,
        ),
        _col(
            "period", "commentary_versions", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="Commentary engine",
            example="2026-07", is_nullable=False, unit="year_month",
        ),
        _col(
            "version", "commentary_versions", "Version Number",
            "Version number for the commentary.",
            "Count", source_system="Commentary engine", example="1",
            is_nullable=True, default_value="1",
        ),
        _col(
            "content", "commentary_versions", "Commentary Content",
            "Full text of the commentary narrative.",
            "Text", source_system="Commentary engine",
            classification="confidential",
            example="Revenue performance was strong in Q2...",
            is_nullable=True,
        ),
        _col(
            "status", "commentary_versions", "Status",
            "Status (draft, under_review, published, archived).",
            "String", source_system="Commentary engine",
            example="draft", is_nullable=True, default_value="draft",
        ),
        _col(
            "author", "commentary_versions", "Author",
            "User identifier of the author or generating agent.",
            "String", source_system="Commentary engine",
            example="commentary_agent_v2", is_nullable=True,
        ),
        _col(
            "created_at", "commentary_versions", "Created At",
            "Timestamp when this version was created.",
            "DateTime", source_system="Commentary engine",
            example="2026-07-30T14:00:00", is_nullable=True,
        ),
    ],
)

# ===================================================================
# 19. audit_logs
# ===================================================================

_AUDIT_LOGS = _table(
    table_name="audit_logs",
    business_name="Audit Logs",
    definition=(
        "Append-only audit trail for all pipeline and user events, "
        "providing an immutable record for compliance and debugging."
    ),
    owner="Data Governance",
    classification="internal",
    primary_keys=["id"],
    columns=[
        _col(
            "id", "audit_logs", "Audit Log Identifier",
            "Unique identifier for the audit log entry.",
            "Identifier", source_system="Platform", example="al_001",
            is_nullable=False,
        ),
        _col(
            "tenant_id", "audit_logs", "Tenant Identifier",
            "Multi-tenant identifier for data isolation.",
            "Identifier", source_system="Platform", example="tenant_acme",
            is_nullable=False,
        ),
        _col(
            "period", "audit_logs", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="Platform",
            example="2026-07", is_nullable=False, unit="year_month",
        ),
        _col(
            "event_type", "audit_logs", "Event Type",
            "Type of event being logged (e.g., variance_computed, commentary_reviewed).",
            "String", source_system="Platform",
            example="variance_computed",
            is_nullable=False,
        ),
        _col(
            "event_data", "audit_logs", "Event Data (JSON)",
            "Structured event payload with relevant context.",
            "JSON", source_system="Platform",
            example='{"variance_id": "var_001", "is_material": true}',
            is_nullable=True,
        ),
        _col(
            "user_id", "audit_logs", "User Identifier",
            "User who triggered the event, if applicable.",
            "String", source_system="Platform",
            example="jane.doe@finsight.com",
            is_nullable=True,
        ),
        _col(
            "created_at", "audit_logs", "Created At",
            "Timestamp when the audit entry was created.",
            "DateTime", source_system="Platform",
            example="2026-07-30T14:30:00", is_nullable=True,
        ),
    ],
)

# ===================================================================
# 20. pipeline_runs
# ===================================================================

_PIPELINE_RUNS = _table(
    table_name="pipeline_runs",
    business_name="Pipeline Runs",
    definition=(
        "Tracks each end-to-end pipeline execution with timing, "
        "status, result data, and error capture."
    ),
    owner="ML Platform",
    classification="internal",
    primary_keys=["id"],
    columns=[
        _col(
            "id", "pipeline_runs", "Pipeline Run Identifier",
            "Unique identifier for the pipeline run.",
            "Identifier", source_system="Pipeline engine", example="pr_001",
            is_nullable=False,
        ),
        _col(
            "tenant_id", "pipeline_runs", "Tenant Identifier",
            "Multi-tenant identifier for data isolation.",
            "Identifier", source_system="Platform", example="tenant_acme",
            is_nullable=False,
        ),
        _col(
            "period", "pipeline_runs", "Fiscal Period",
            "The fiscal period being processed in YYYY-MM format.",
            "FiscalPeriod", source_system="Pipeline engine",
            example="2026-07", is_nullable=False, unit="year_month",
        ),
        _col(
            "status", "pipeline_runs", "Run Status",
            "Pipeline execution status (pending, running, completed, failed).",
            "String", source_system="Pipeline engine", example="completed",
            is_nullable=True, default_value="pending",
        ),
        _col(
            "started_at", "pipeline_runs", "Started At",
            "Timestamp when the pipeline started execution.",
            "DateTime", source_system="Pipeline engine",
            example="2026-07-30T08:00:00", is_nullable=True,
        ),
        _col(
            "completed_at", "pipeline_runs", "Completed At",
            "Timestamp when the pipeline completed.",
            "DateTime", source_system="Pipeline engine",
            example="2026-07-30T08:05:30", is_nullable=True,
        ),
        _col(
            "result_json", "pipeline_runs", "Result (JSON)",
            "Structured pipeline output result.",
            "JSON", source_system="Pipeline engine",
            classification="confidential",
            example='{"variances_found": 12, "material_count": 3}',
            is_nullable=True,
        ),
        _col(
            "error", "pipeline_runs", "Error Message",
            "Error message if the pipeline failed.",
            "Text", source_system="Pipeline engine",
            example="Connection timeout connecting to ERP datasource",
            is_nullable=True,
        ),
    ],
)

# ===================================================================
# 21. assertions_db
# ===================================================================

_ASSERTIONS_DB = _table(
    table_name="assertions_db",
    business_name="Assertions Database",
    definition=(
        "Persistent store of assertions generated by the assertion "
        "pipeline, with type classification, confidence, and evidence links."
    ),
    owner="Data Governance",
    classification="confidential",
    primary_keys=["id"],
    columns=[
        _col(
            "id", "assertions_db", "Assertion DB Identifier",
            "Unique row identifier for the assertion record.",
            "Identifier", source_system="Assertion pipeline",
            example="asrt_001", is_nullable=False,
        ),
        _col(
            "tenant_id", "assertions_db", "Tenant Identifier",
            "Multi-tenant identifier for data isolation.",
            "Identifier", source_system="Platform", example="tenant_acme",
            is_nullable=False,
        ),
        _col(
            "period", "assertions_db", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="Assertion pipeline",
            example="2026-07", is_nullable=False, unit="year_month",
        ),
        _col(
            "assertion_id", "assertions_db", "Assertion Identifier",
            "Logical identifier for the assertion, unique per tenant.",
            "Identifier", source_system="Assertion pipeline",
            example="assert_001", is_nullable=False,
        ),
        _col(
            "type", "assertions_db", "Assertion Type",
            "Type of assertion (numeric, comparative, causal, forecast).",
            "String", source_system="Assertion pipeline",
            example="comparative", is_nullable=False,
            validation_rules=[
                "Must be one of: numeric, comparative, causal, forecast, trend",
            ],
        ),
        _col(
            "text", "assertions_db", "Assertion Text",
            "Natural language text of the assertion.",
            "Text", source_system="Assertion pipeline",
            classification="confidential",
            example="Revenue increased by 15% compared to budget",
            is_nullable=False,
        ),
        _col(
            "value", "assertions_db", "Assertion Value",
            "Numeric value associated with the assertion, if applicable.",
            "Money", source_system="Assertion pipeline", example="150000.00",
            classification="confidential", sox_relevant=True,
            is_nullable=True, unit="entity_currency",
        ),
        _col(
            "support_level", "assertions_db", "Support Level",
            "Evidence support level (verified, probable, weak, unsupported).",
            "String", source_system="Assertion pipeline", example="verified",
            is_nullable=True,
            validation_rules=[
                "Must be one of: verified, probable, weak, unsupported",
            ],
        ),
        _col(
            "confidence", "assertions_db", "Confidence Score",
            "Confidence in the assertion (0-1).",
            "Percentage", source_system="Assertion pipeline", example="0.9500",
            is_nullable=True, unit="decimal",
            validation_rules=["Must be between 0 and 1"],
        ),
        _col(
            "evidence_ids_json", "assertions_db", "Evidence IDs (JSON)",
            "List of evidence identifiers supporting this assertion.",
            "JSON", source_system="Assertion pipeline",
            example='["var_001", "tb_045"]', is_nullable=True,
        ),
        _col(
            "metadata_json", "assertions_db", "Metadata (JSON)",
            "Additional structured metadata about the assertion.",
            "JSON", source_system="Assertion pipeline",
            example='{"source": "variance_engine", "version": "2.1"}',
            is_nullable=True,
        ),
        _col(
            "created_at", "assertions_db", "Created At",
            "Timestamp when the assertion was created.",
            "DateTime", source_system="Assertion pipeline",
            example="2026-07-30T14:00:00", is_nullable=True,
        ),
    ],
)

# ===================================================================
# 22. tool_result_cache
# ===================================================================

_TOOL_RESULT_CACHE = _table(
    table_name="tool_result_cache",
    business_name="Tool Result Cache",
    definition=(
        "Cache for external tool and API call results, keyed by "
        "tool name and query fingerprint with TTL management."
    ),
    owner="ML Platform",
    classification="internal",
    primary_keys=["id"],
    columns=[
        _col(
            "id", "tool_result_cache", "Cache Entry Identifier",
            "Unique identifier for the cache entry.",
            "Identifier", source_system="Platform", example="cache_001",
            is_nullable=False,
        ),
        _col(
            "tenant_id", "tool_result_cache", "Tenant Identifier",
            "Multi-tenant identifier for data isolation.",
            "Identifier", source_system="Platform", example="tenant_acme",
            is_nullable=False,
        ),
        _col(
            "period", "tool_result_cache", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="Platform",
            example="2026-07", is_nullable=False, unit="year_month",
        ),
        _col(
            "tool_name", "tool_result_cache", "Tool Name",
            "Name of the tool or external API that produced the result.",
            "String", source_system="Platform", example="erp_connector",
            is_nullable=False,
        ),
        _col(
            "query_fingerprint", "tool_result_cache", "Query Fingerprint",
            "Hash or unique string identifying the query parameters.",
            "String", source_system="Platform",
            example="a1b2c3d4e5f6",
            is_nullable=False,
        ),
        _col(
            "result_json", "tool_result_cache", "Result (JSON)",
            "Cached result payload.",
            "JSON", source_system="Platform",
            example='{"status": "ok", "rows": 150}',
            is_nullable=True,
        ),
        _col(
            "created_at", "tool_result_cache", "Created At",
            "Timestamp when the cache entry was created.",
            "DateTime", source_system="Platform",
            example="2026-07-30T08:00:00", is_nullable=True,
        ),
        _col(
            "expires_at", "tool_result_cache", "Expires At",
            "Timestamp when the cache entry expires and should be refreshed.",
            "DateTime", source_system="Platform",
            example="2026-07-30T09:00:00", is_nullable=True,
        ),
    ],
)

# ===================================================================
# 23. data_quality_snapshots
# ===================================================================

_DATA_QUALITY_SNAPSHOTS = _table(
    table_name="data_quality_snapshots",
    business_name="Data Quality Snapshots",
    definition=(
        "Point-in-time snapshots of data quality metrics, including "
        "overall quality score and detailed per-dimension reports."
    ),
    owner="Data Governance",
    classification="internal",
    primary_keys=["id"],
    columns=[
        _col(
            "id", "data_quality_snapshots", "Snapshot Identifier",
            "Unique identifier for the data quality snapshot.",
            "Identifier", source_system="Data quality pipeline",
            example="dq_001", is_nullable=False,
        ),
        _col(
            "tenant_id", "data_quality_snapshots", "Tenant Identifier",
            "Multi-tenant identifier for data isolation.",
            "Identifier", source_system="Platform", example="tenant_acme",
            is_nullable=False,
        ),
        _col(
            "period", "data_quality_snapshots", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="Data quality pipeline",
            example="2026-07", is_nullable=False, unit="year_month",
        ),
        _col(
            "report_json", "data_quality_snapshots", "Quality Report (JSON)",
            "Detailed data quality metrics per dimension.",
            "JSON", source_system="Data quality pipeline",
            classification="internal",
            example='{"completeness": 0.98, "accuracy": 0.95}',
            is_nullable=True,
        ),
        _col(
            "overall_score", "data_quality_snapshots", "Overall Quality Score",
            "Aggregate data quality score (0-1).",
            "Percentage", source_system="Data quality pipeline",
            example="0.9600",
            is_nullable=True, unit="decimal",
            validation_rules=["Must be between 0 and 1"],
        ),
        _col(
            "created_at", "data_quality_snapshots", "Created At",
            "Timestamp when the snapshot was taken.",
            "DateTime", source_system="Data quality pipeline",
            example="2026-07-30T08:00:00", is_nullable=True,
        ),
    ],
)

# ===================================================================
# 24. policy_decision_logs
# ===================================================================

_POLICY_DECISION_LOGS = _table(
    table_name="policy_decision_logs",
    business_name="Policy Decision Logs",
    definition=(
        "Audit log of policy-driven decisions about autonomy level "
        "and routing targets for agent actions."
    ),
    owner="Data Governance",
    classification="internal",
    primary_keys=["id"],
    columns=[
        _col(
            "id", "policy_decision_logs", "Policy Decision Identifier",
            "Unique identifier for the policy decision log entry.",
            "Identifier", source_system="Policy engine", example="pd_001",
            is_nullable=False,
        ),
        _col(
            "tenant_id", "policy_decision_logs", "Tenant Identifier",
            "Multi-tenant identifier for data isolation.",
            "Identifier", source_system="Platform", example="tenant_acme",
            is_nullable=False,
        ),
        _col(
            "period", "policy_decision_logs", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="Policy engine",
            example="2026-07", is_nullable=False, unit="year_month",
        ),
        _col(
            "autonomy_level", "policy_decision_logs", "Autonomy Level",
            "Determined autonomy level (autonomous, semi_autonomous, manual).",
            "String", source_system="Policy engine", example="semi_autonomous",
            is_nullable=True,
        ),
        _col(
            "routing_target", "policy_decision_logs", "Routing Target",
            "Where the action was routed (auto_approve, human_review, escalated).",
            "String", source_system="Policy engine", example="human_review",
            is_nullable=True,
        ),
        _col(
            "reasons_json", "policy_decision_logs", "Reasons (JSON)",
            "Structured list of reasons for the policy decision.",
            "JSON", source_system="Policy engine",
            example='["Exceeds materiality threshold", "SOX-relevant field"]',
            is_nullable=True,
        ),
        _col(
            "confidence", "policy_decision_logs", "Confidence Score",
            "Confidence in the policy decision (0-1).",
            "Percentage", source_system="Policy engine", example="0.9200",
            is_nullable=True, unit="decimal",
            validation_rules=["Must be between 0 and 1"],
        ),
        _col(
            "created_at", "policy_decision_logs", "Created At",
            "Timestamp when the policy decision was logged.",
            "DateTime", source_system="Policy engine",
            example="2026-07-30T14:00:00", is_nullable=True,
        ),
    ],
)

# ===================================================================
# 25. bridge_analysis_results
# ===================================================================

_BRIDGE_ANALYSIS_RESULTS = _table(
    table_name="bridge_analysis_results",
    business_name="Bridge Analysis Results",
    definition=(
        "Period-to-period bridge analysis results for GL accounts, "
        "breaking down the change between periods into drivers."
    ),
    owner="FP&A Team",
    classification="confidential",
    primary_keys=["id"],
    columns=[
        _col(
            "id", "bridge_analysis_results", "Bridge Analysis Identifier",
            "Unique identifier for the bridge analysis result.",
            "Identifier", source_system="Bridge engine", example="br_001",
            is_nullable=False,
        ),
        _col(
            "tenant_id", "bridge_analysis_results", "Tenant Identifier",
            "Multi-tenant identifier for data isolation.",
            "Identifier", source_system="Platform", example="tenant_acme",
            is_nullable=False,
        ),
        _col(
            "period", "bridge_analysis_results", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="Bridge engine",
            example="2026-07", is_nullable=False, unit="year_month",
        ),
        _col(
            "account_id", "bridge_analysis_results", "GL Account Identifier",
            "Reference to the GL account being analyzed.",
            "Identifier", source_system="Bridge engine", example="acct_001",
            is_nullable=False,
        ),
        _col(
            "bridge_json", "bridge_analysis_results", "Bridge Detail (JSON)",
            "Structured bridge analysis showing period-over-period drivers.",
            "JSON", source_system="Bridge engine",
            classification="confidential",
            example='{"volume_impact": 50000, "price_impact": -10000}',
            is_nullable=True,
        ),
        _col(
            "reconciles", "bridge_analysis_results", "Reconciles",
            "Whether the bridge analysis reconciles to the total change.",
            "Boolean", source_system="Bridge engine", example="true",
            is_nullable=True, default_value="false",
        ),
        _col(
            "confidence", "bridge_analysis_results", "Confidence Score",
            "Confidence in the bridge analysis (0-1).",
            "Percentage", source_system="Bridge engine", example="0.8800",
            is_nullable=True, unit="decimal",
            validation_rules=["Must be between 0 and 1"],
        ),
        _col(
            "created_at", "bridge_analysis_results", "Created At",
            "Timestamp when the analysis was created.",
            "DateTime", source_system="Bridge engine",
            example="2026-07-30T14:00:00", is_nullable=True,
        ),
    ],
)

# ===================================================================
# 26. variance_snapshots
# ===================================================================

_VARIANCE_SNAPSHOTS = _table(
    table_name="variance_snapshots",
    business_name="Variance Snapshots",
    definition=(
        "Point-in-time snapshots of variance data for audit and "
        "period-over-period comparison."
    ),
    owner="FP&A Team",
    classification="confidential",
    primary_keys=["id"],
    columns=[
        _col(
            "id", "variance_snapshots", "Variance Snapshot Identifier",
            "Unique identifier for the variance snapshot.",
            "Identifier", source_system="Variance engine",
            example="vs_001", is_nullable=False,
        ),
        _col(
            "tenant_id", "variance_snapshots", "Tenant Identifier",
            "Multi-tenant identifier for data isolation.",
            "Identifier", source_system="Platform", example="tenant_acme",
            is_nullable=False,
        ),
        _col(
            "period", "variance_snapshots", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="Variance engine",
            example="2026-07", is_nullable=False, unit="year_month",
        ),
        _col(
            "account_id", "variance_snapshots", "GL Account Identifier",
            "Reference to the GL account being snapshotted.",
            "Identifier", source_system="Variance engine", example="acct_001",
            is_nullable=False,
        ),
        _col(
            "variance_json", "variance_snapshots", "Variance Data (JSON)",
            "Full variance data captured at the snapshot time.",
            "JSON", source_system="Variance engine",
            classification="confidential",
            example='{"actual": 1250000, "budget": 1100000, "variance": 150000}',
            is_nullable=True,
            glossary_ref="glossary.variance.variance",
        ),
        _col(
            "is_material", "variance_snapshots", "Is Material",
            "Whether the variance was flagged as material at snapshot time.",
            "Boolean", source_system="Variance engine", example="true",
            classification="confidential", sox_relevant=True,
            is_nullable=True, default_value="false",
            glossary_ref="glossary.variance.material",
        ),
        _col(
            "created_at", "variance_snapshots", "Created At",
            "Timestamp when the snapshot was taken.",
            "DateTime", source_system="Variance engine",
            example="2026-07-30T14:00:00", is_nullable=True,
        ),
    ],
)

# ===================================================================
# 27. root_cause_findings_db
# ===================================================================

_ROOT_CAUSE_FINDINGS_DB = _table(
    table_name="root_cause_findings_db",
    business_name="Root Cause Findings (DB)",
    definition=(
        "Persistent store of root cause findings with structured "
        "evidence and confidence scoring."
    ),
    owner="FP&A Team",
    classification="confidential",
    primary_keys=["id"],
    columns=[
        _col(
            "id", "root_cause_findings_db", "Root Cause Finding Identifier",
            "Unique identifier for the root cause finding.",
            "Identifier", source_system="Root cause agent",
            example="rcf_001", is_nullable=False,
        ),
        _col(
            "tenant_id", "root_cause_findings_db", "Tenant Identifier",
            "Multi-tenant identifier for data isolation.",
            "Identifier", source_system="Platform", example="tenant_acme",
            is_nullable=False,
        ),
        _col(
            "period", "root_cause_findings_db", "Fiscal Period",
            "The fiscal period in YYYY-MM format.",
            "FiscalPeriod", source_system="Root cause agent",
            example="2026-07", is_nullable=False, unit="year_month",
        ),
        _col(
            "account_id", "root_cause_findings_db", "GL Account Identifier",
            "Reference to the GL account.",
            "Identifier", source_system="Root cause agent",
            example="acct_001", is_nullable=False,
        ),
        _col(
            "finding_json", "root_cause_findings_db", "Finding Detail (JSON)",
            "Structured root cause finding with evidence and attribution.",
            "JSON", source_system="Root cause agent",
            classification="confidential",
            example='{"driver": "volume", "impact": -30000, "confidence": 0.85}',
            is_nullable=True,
        ),
        _col(
            "confidence", "root_cause_findings_db", "Confidence Score",
            "Confidence in the root cause finding (0-1).",
            "Percentage", source_system="Root cause agent", example="0.8500",
            is_nullable=True, unit="decimal",
            validation_rules=["Must be between 0 and 1"],
        ),
        _col(
            "created_at", "root_cause_findings_db", "Created At",
            "Timestamp when the finding was created.",
            "DateTime", source_system="Root cause agent",
            example="2026-07-30T14:00:00", is_nullable=True,
        ),
    ],
)

# ===================================================================
# ASSEMBLED DATA DICTIONARY
# ===================================================================

DATA_DICTIONARY = DataDictionary()
"""The canonical Semantic Data Dictionary, populated with metadata for
all 27 database tables.

Usage::

    from business.data_dictionary.registry import DATA_DICTIONARY

    table = DATA_DICTIONARY.get_table("actuals")
    col = DATA_DICTIONARY.get_column("actuals", "amount")
    sox_fields = DATA_DICTIONARY.sox_relevant_fields()
    pii_fields = DATA_DICTIONARY.pii_fields()
"""


def _build_dictionary() -> None:
    """Register all table metadata into the global DATA_DICTIONARY instance."""
    all_tables: list[TableMetadata] = [
        _ENTITIES,
        _GL_ACCOUNTS,
        _TRIAL_BALANCE,
        _BUDGET_LINES,
        _FORECAST_LINES,
        _ACTUALS,
        _HEADCOUNT_DATA,
        _VENDOR_INVOICES,
        _SALES_PIPELINE,
        _AGENT_RUNS,
        _VARIANCES,
        _ROOT_CAUSES,
        _COMMENTARY_DRAFTS,
        _SCENARIOS,
        _REVIEW_LOGS,
        _REVIEW_DECISIONS,
        _ACTION_ITEMS,
        _COMMENTARY_VERSIONS,
        _AUDIT_LOGS,
        _PIPELINE_RUNS,
        _ASSERTIONS_DB,
        _TOOL_RESULT_CACHE,
        _DATA_QUALITY_SNAPSHOTS,
        _POLICY_DECISION_LOGS,
        _BRIDGE_ANALYSIS_RESULTS,
        _VARIANCE_SNAPSHOTS,
        _ROOT_CAUSE_FINDINGS_DB,
    ]
    DATA_DICTIONARY.register_many(all_tables)


_build_dictionary()
