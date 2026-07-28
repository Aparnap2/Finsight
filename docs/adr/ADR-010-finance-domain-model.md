# ADR-010: Finance Domain Model — Model Financial Concepts, Not Spreadsheets

**Status:** Accepted  
**Date:** 2026-07-28  
**Deciders:** Architecture Team  

---

## Context

Early spreadsheet-based financial tools model their domain after their input format: rows, cells, sheets, workbooks, ranges. This is natural but wrong for a durable financial analysis system. When the domain model reflects the input format, changing the input format breaks the model. When the domain model reflects financial reality, the system survives source changes.

FinSight currently has multiple representations of financial data:

| Location | Model | Problem |
|----------|-------|---------|
| `shared/models/database.py` | SQLAlchemy ORM (15 tables) | Mixed persistence concerns with domain concepts |
| `finance/validation/models.py` | `FiscalPeriod` | Pure domain — good |
| `finance/variance_engine/materiality.py` | `MaterialityRule`, `MaterialityConfig` | Pure domain — good |
| `shared/models/state.py` | `Variance`, `EvidenceItem` | Mixed: state-machine concerns with domain concepts |
| `apps/api/schemas.py` | API response models | Serialisation concerns with domain concepts |

The project lacks a single, authoritative domain model for the core financial concepts that every layer references.

**Critical rule from the user:** Use `finance/domain/` — not `ontology`.

## Decision

Define the authoritative **Finance Domain Model** in `finance/domain/` — a new module that models financial concepts using Domain-Driven Design (DDD) aggregates. This becomes the single source of truth for what a Company, Account, Fiscal Period, and Chart of Accounts mean in the FinSight system.

### Domain Model Location

```
finance/domain/
├── __init__.py
├── company.py          # Company aggregate
├── fiscal_calendar.py  # FiscalCalendar aggregate
├── chart_of_accounts.py # ChartOfAccounts + Account entities
├── period.py           # FiscalPeriod, PeriodStatus value objects
├── account.py          # Account, AccountType, AccountCategory
├── ledger.py           # LedgerEntry, TrialBalance, JournalEntry
├── budget.py           # BudgetLine, BudgetVersion, BudgetScenario
├── variance.py         # Variance, MaterialityThreshold value objects
├── kpi.py              # KpiDefinition, KpiValue value objects
├── scenario.py         # Scenario, ScenarioParameter value objects
└── enums.py            # Shared enums: PeriodType, AccountType, etc.
```

### DDD Aggregates

#### `Company` Aggregate

```python
class Company(BaseModel):
    """Top-level aggregate. Everything belongs to a company."""
    id: str
    name: str
    currency: str = "USD"
    fiscal_calendar: FiscalCalendar
    chart_of_accounts: ChartOfAccounts
    created_at: datetime
    updated_at: datetime
```

#### `FiscalCalendar` Aggregate

```python
class FiscalCalendar(BaseModel):
    """Defines the fiscal year structure for a Company."""
    company_id: str
    fiscal_year_start_month: int  # 1=January, 7=July, etc.
    periods: list[FiscalPeriod]
    current_period_id: str | None = None

    def get_period(self, period_id: str) -> FiscalPeriod: ...
    def get_period_for_date(self, date: date) -> FiscalPeriod: ...
    def get_range(self, start_id: str, end_id: str) -> list[FiscalPeriod]: ...
    def open_periods(self) -> list[FiscalPeriod]: ...
```

#### `ChartOfAccounts` Aggregate

```python
class ChartOfAccounts(BaseModel):
    """The complete account structure for a Company."""
    company_id: str
    accounts: dict[str, Account]  # keyed by account_id
    categories: dict[str, AccountCategory]

    def get_account(self, account_id: str) -> Account: ...
    def get_accounts_by_type(self, account_type: AccountType) -> list[Account]: ...
    def get_accounts_by_category(self, category: str) -> list[Account]: ...
    def get_leaf_accounts(self) -> list[Account]: ...
```

### Value Objects

#### `Account`

```python
class Account(BaseModel):
    """A single account in the chart of accounts."""
    id: str
    account_number: str          # e.g., "4010"
    name: str                    # e.g., "Software Revenue"
    description: str = ""
    account_type: AccountType    # ASSET | LIABILITY | EQUITY | REVENUE | EXPENSE
    category: AccountCategory    # e.g., "Operating Revenue", "COGS", "SG&A"
    sensitivity_tier: SensitivityTier | None = None  # From materiality engine
    is_active: bool = True
    parent_id: str | None = None     # For hierarchical COA
    children_ids: list[str] = []     # Roll-up structure
    metadata: dict[str, Any] = {}    # Extensible
```

#### `FiscalPeriod`

```python
class FiscalPeriod(BaseModel):
    """A specific time period in a fiscal calendar."""
    id: str
    company_id: str
    fiscal_year: int
    fiscal_period_number: int   # 1–12 for monthly, 1–4 for quarterly
    period_type: PeriodType     # MONTHLY | QUARTERLY | YEARLY
    start_date: date
    end_date: date
    status: PeriodStatus        # OPEN | CLOSING | VALIDATING | ANALYZING | REVIEWING | COMPLETED | LOCKED
    prior_period_id: str | None = None
    prior_year_period_id: str | None = None
```

#### `Variance`

```python
class Variance(BaseModel):
    """A computed variance between two values for an Account."""
    account_id: str
    account_name: str
    department: str
    period_id: str
    actual_amount: Decimal
    budget_amount: Decimal
    forecast_amount: Decimal | None = None
    variance_amount: Decimal
    variance_pct: Decimal
    is_material: bool = False
    materiality_rule: MaterialityRule | None = None
```

### What Is Not in the Domain Model

The following concepts are explicitly **excluded** from `finance/domain/`:

```
❌ SpreadsheetRow          — data format, not a domain concept
❌ CellReference           — spreadsheet implementation detail
❌ Workbook                — spreadsheet container
❌ CSVRow                 — data interchange format
❌ DataFrame              — computational structure
❌ Table                  — database implementation
❌ SQLAlchemy Model       — persistence concern
❌ Pydantic FieldValidator — validation concern (belongs at API boundary)
❌ FastAPI Route           — web concern
❌ LangGraph State         — orchestration concern
```

### Relationship to Existing Models

| Existing Location | New Location (finance/domain/) | Relationship |
|------------------|-------------------------------|--------------|
| `shared/models/database.py` (SQLAlchemy) | References domain models as source of truth | Domain models define the schema; SQLAlchemy models implement persistence |
| `finance/validation/models.py` `FiscalPeriod` | `finance/domain/period.py` `FiscalPeriod` | Migration target — domain models replace validation-only models |
| `finance/validation/calendar.py` `FiscalCalendar` | `finance/domain/fiscal_calendar.py` | Migration target |
| `finance/variance_engine/materiality.py` `MaterialityRule` | `finance/domain/variance.py` | Domain model references materiality concepts |
| `shared/models/state.py` `Variance` | `finance/domain/variance.py` | `PipelineState` Variance is the runtime state; domain Variance is the pure value object |
| `apps/api/schemas.py` response models | References domain models (not vice versa) | API schemas serialise domain models |

### Domain Model Principles

1. **Pure Python + Pydantic.** No SQLAlchemy. No FastAPI. No LangGraph. No LLM types. Domain models depend only on `pydantic` and the standard library.
2. **Self-validating.** Domain models validate their own invariants (e.g., `FiscalPeriod.start_date < end_date`, `AccountCategory` is valid).
3. **No behaviour without context.** Domain models have methods that operate on their own state but never call out to external services, databases, or LLMs.
4. **Immutable by convention.** Domain models are frozen (`model_config = {"frozen": True}`) where mutation would cause inconsistency.
5. **Identity equals semantics.** Two `Account` objects with the same `id` are the same account — equality is based on domain identity, not object identity.
6. **Aggregate roots as entry points.** All operations on a `Company` go through the `Company` aggregate root. You don't modify `FiscalPeriod` directly — you go through `Company.fiscal_calendar`.

## Consequences

### Positive

- **One authoritative source of truth.** Every layer references `finance/domain/` for financial concepts. No more duplicated `FiscalPeriod` in `validation/models.py` and `shared/models/state.py`.
- **Spreadsheet independence.** The domain model has zero spreadsheet concepts. If the data source changes (Sheets → CSV → NetSuite API), the domain model doesn't change.
- **Persistence independence.** The SQLAlchemy models in `shared/models/database.py` become implementations of the domain model — not the domain model itself. ORM changes don't cascade to domain logic.
- **Clearer API boundaries.** Response schemas in `apps/api/schemas.py` reference domain types. The API documentation expresses financial concepts, not data structures.
- **DDD aggregates align with bounded contexts.** Each aggregate (`Company`, `FiscalCalendar`, `ChartOfAccounts`) maps to a clear business concept with defined consistency boundaries.
- **Migration path for existing models.** The existing models in `finance/validation/models.py` become implementation details of the domain model — they converge toward the domain model over time.

### Negative

- **Migration effort.** Existing code references `finance/validation/models.py` `FiscalPeriod` and `shared/models/state.py` `Variance`. These must be gradually replaced with references to `finance/domain/`. Until migration is complete, there are two `FiscalPeriod` classes.
- **Boilerplate for simple concepts.** Adding a new domain concept requires: domain model in `finance/domain/`, Pydantic validators, aggregate integration, migration of existing references, updating API schemas.
- **Aggregate boundaries may need adjustment.** The initial aggregate design (`Company` root containing `FiscalCalendar` and `ChartOfAccounts`) might be too coarse for multi-entity organisations. Future decomposition into sub-aggregates may be needed.
- **Learning curve for DDD.** Not all team members are familiar with Domain-Driven Design. The aggregate/entity/value-object distinction takes practice.

## Compliance

1. **`finance/domain/` has zero internal package dependencies.** It imports only `pydantic`, `decimal`, `datetime`, `enum`, and other standard library modules. Verified by checking import statements.
2. **No spreadsheet concepts in `finance/domain/`.** The words "sheet", "row", "cell", "workbook", "csv", "range" do not appear in any `finance/domain/` file.
3. **Domain models are the source of truth for persistence.** The SQLAlchemy models in `shared/models/database.py` are explicitly documented as "implementations of the domain model" — never as the canonical definition.
4. **New financial concepts start in `finance/domain/`.** Any new financial concept (account type, period kind, KPI category) must be defined in `finance/domain/` before it can be used in other layers.
5. **Cross-reference documentation.** The `finance/domain/README.md` (or equivalent module docstring) maps each domain model to its consumers in `finance/`, `agents/`, `shared/`, and `apps/`.
