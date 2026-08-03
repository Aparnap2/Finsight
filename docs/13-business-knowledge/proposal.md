# Business Knowledge Layer — Phase 3 Proposal

> **Layer:** Proposed Layer 0 — Business Knowledge  
> **Audience:** Staff engineers, platform architects, domain engineers, product managers, data stewards  
> **Status:** Design proposal — pending review  
> **Reviewer:** Staff Engineer (unreviewed draft)

---

## Executive Summary

The Business Knowledge Layer (BKL) is a proposed Phase 3 addition to FinSight's architecture that sits **below the existing 12 validation layers** as a semantic foundation. Its purpose is to encode financial domain knowledge — terms, measures, formulas, relationships, classifications, and business rules — as first-class, machine-readable metadata rather than tribal knowledge scattered across code, configuration, and team members' heads.

Today, every engineered system in FinSight has been built with sound architectural rigor: the data contract layers, state machines, business rules, database constraints, and audit trails enforce structural integrity. But **structural integrity is not semantic integrity**. The platform knows that a `Variance.amount` is a `Decimal` — it does not know that "Revenue Variance" is a metric that depends on `Actual.Revenue` minus `Budget.Revenue`, computed monthly, owned by the FP&A team, and subject to SOX review if it exceeds 5%.

The Business Knowledge Layer fills this gap. It is not a new validation layer — it is a **knowledge substrate** that every other layer references. When complete, FinSight will no longer have a single `Decimal` field whose business meaning can only be inferred from context. Every data point, every formula, every classification will carry an explicit, versioned, auditable business definition.

**"Pause database work. Spend next iteration on domain semantics, not infrastructure."**

---

## Motivation

### Problem 1: Prompt Drift

Today, LLM prompts for commentary and analysis embed implicit financial knowledge. When an FP&A analyst asks "why is revenue down?" the system constructs a context pack with variance data. The LLM interprets that data through its training — not through FinSight's explicit domain model. As prompts evolve, the implicit knowledge drifts. A prompt that correctly identifies material revenue variances in March may miss them in April if the underlying metric definition changed.

**Without BKL:** Financial knowledge is embedded in prompt templates, agent code, and engineer intuition. Changes require prompt rewrites and manual testing.

**With BKL:** The Formula Registry provides a canonical `RevenueVariance` definition. Context builders fetch the definition dynamically. Prompts reference `revenue_variance.formula` — never hardcode it.

### Problem 2: Ad-Hoc Recomputation

Every agent and engine currently implements its own financial logic — sometimes duplicating the same formula across four places:

- `finance/variance_engine/` computes variance amounts
- `finance/formula_engine/formula_registry.py` registers KPI formulas
- `agents/commentary/` formats variance explanations
- `apps/api/` exposes variance endpoints

When a formula changes (e.g., materiality threshold moves from 10% to 8%), all four locations must be updated in sync. In practice, they drift.

**Without BKL:** Four implementations of the same business rule. No single source of truth.

**With BKL:** The Formula Registry is the single source of truth. All engines and agents read from it.

### Problem 3: No Semantic Registry

FinSight has 16 Pydantic domain models and 18 ORM models. There is no registry that answers:

- "Which metrics depend on headcount data?"
- "What is the canonical definition of Gross Margin?"
- "Which fields are PII? Which are SOX-relevant?"
- "What is the data classification for vendor bank accounts?"
- "Which business capabilities does the `invoice_import` event support?"

Without answers to these questions, the platform cannot reason about its own data. The DataOps layer validates structure — the BKL validates meaning.

### Problem 4: New Engineer Onboarding

A new engineer joining the team spends weeks learning that "Period 7" means July, that `is_material = true` means a variance exceeds both $50K and 10%, and that `Account Type 4010` is consulting revenue. This knowledge lives in Slack threads, PR comments, and README files.

**Without BKL:** Six-week ramp-up before an engineer can safely touch financial logic.

**With BKL:** The glossary, semantic dictionary, and formula registry provide self-service onboarding. Engineers search "revenue definition" and find the canonical answer.

---

## Architecture

### Layer Positioning

The Business Knowledge Layer sits at Layer 0 — below the existing 12 validation layers. It is not a pipeline stage (it does not validate runtime data) but a **reference substrate** that all other layers depend on.

```
┌──────────────────────────────────────────────────────────────────┐
│                     AGENT / API LAYER                            │
│  (orchestration, commentary, board reports, API endpoints)       │
├──────────────────────────────────────────────────────────────────┤
│                     COMPUTE RUNTIME                              │
│  (formula engine, variance engine, scenario engine, forecast)    │
├──────────────────────────────────────────────────────────────────┤
│                     DOMAIN LAYER                                 │
│  (Pydantic models, state machines, business rules)               │
├──────────────────────────────────────────────────────────────────┤
│                     DATA LAYER                                   │
│  (data contracts, database constraints, audit, RLS)              │
├──────────────────────────────────────────────────────────────────┤
│  ⬤  BUSINESS KNOWLEDGE LAYER  ⬤  ← YOU ARE HERE                 │
│  (glossary, formula registry, canonical objects, capability map, │
│   semantic dictionary, domain events, reference data,            │
│   data classification)                                           │
└──────────────────────────────────────────────────────────────────┘
```

### Dependency Flow

```
Business Knowledge Layer (Layer 0) — zero internal dependencies
    ↑
    │  referenced by
    │
Domain Layer — reads canonical objects, glossary, formula registry
Data Layer — reads semantic dictionary, data classification
Compute Runtime — reads formula registry for evaluation
Agent/API Layer — reads glossary for prompt construction, reads capability map for routing
```

The BKL is a **read-mostly** layer. It is populated during onboarding and updated through a formal change management process (Business Knowledge Change Request). It is consumed by every layer above it but depends on nothing.

### Relationship to Existing Layers

| Existing Layer | What It Validates | What BKL Provides |
|----------------|-------------------|-------------------|
| Connector Validation | File format, column presence | Expected column semantics, source system metadata |
| API Contract | Request structure | Business meaning of each field |
| Dataset Schema | DataFrame types | Expected business domain for each column |
| Domain Models | Pydantic invariants | Canonical value objects, state definitions |
| Database Constraints | SQL constraints | Business rationale for each constraint |
| State Machines | Transition legality | Business context for each state |
| Business Rules | Policy decisions | Business rule metadata (owner, justification) |
| Security | Tenant isolation | Data classification for each field |
| Audit Trail | Immutability | Audit significance of each event |
| Versioned Models | Schema evolution | Business impact of schema changes |
| Compute Validation | Results structure | Expected result semantics |
| Agent Validation | Evidence sufficiency | Evidence significance |

---

## Components

### A. Business Glossary (150+ Finance Concepts)

A central registry of every financial term the platform understands. Each entry includes:

| Field | Description | Example |
|-------|-------------|---------|
| `term_id` | Stable identifier | `glossary.revenue.net` |
| `term` | Canonical name | "Net Revenue" |
| `aliases` | Alternative names | `["Revenue", "Sales", "Top Line", "Income"]` |
| `definition` | 1-2 sentence business definition | "Total revenue from operations after deducting returns, allowances, and discounts." |
| `category` | High-level grouping | `revenue` |
| `formula` | Canonical formula (if derived) | `GrossRevenue - Returns - Allowances - Discounts` |
| `data_type` | Canonical value type | `Money` |
| `source_system` | Typical source | `ERP (NetSuite, SAP)` |
| `classification` | Data sensitivity | `confidential` |
| `sox_relevant` | SOX compliance flag | `true` |
| `owner` | Business owner | `FP&A Team` |
| `steward` | Data steward | `Data Governance` |
| `tags` | Arbitrary tags | `["gaap", "p&l"]` |

### B. Canonical Value Objects

First-class Python types for every financial primitive. These are not models — they are **value objects** with type safety, validation, and formatting built in.

Detailed in [`canonical-objects.md`](./canonical-objects.md). Summary:

| Object | Description | Key Invariant |
|--------|-------------|---------------|
| `Money` | `(amount: Decimal, currency: CurrencyCode)` | `Decimal` only, no `float`; currency-aware arithmetic |
| `Percentage` | `(value: Decimal)` with mode flag | Bounded `[0, 1]` or `[0, 100]` depending on mode |
| `CurrencyCode` | ISO 4217 string | Upper-case, 3-letter, validated against ISO set |
| `FiscalPeriod` | `(year, period, type)` | YYYY-MM format; ordering; period arithmetic |
| `ExchangeRate` | `(from, to, rate, date)` | Inverse auto-computed; dated lookup |
| `GLAccountNumber` | Typed string | Format-validated per entity |
| `CostCenter` / `Department` | Typed strings | Exists-in-registry validation |
| `LedgerAccount` | Typed string with type | Debit/credit normal balance association |

### C. Formula Registry (Every Derived Metric as Metadata)

A declarative registry of every formula the platform computes, distinct from the runtime `formula_registry.py` that evaluates them.

```python
@dataclass
class FormulaDefinition:
    """Metadata for a derived metric."""
    formula_id: str                        # e.g., "gross_margin"
    name: str                              # "Gross Margin"
    description: str                       # "Gross profit as a percentage of revenue"
    expression: str                        # "(Revenue - COGS) / Revenue * 100"
    depends_on: list[str]                  # ["net_revenue", "cogs"]
    data_type: Literal["Money", "Percentage", "Ratio", "Count"]
    category: str                          # "profitability"
    owner: str                             # "FP&A Team"
    version: str                           # "1.0.0"
    valid_from: date                       # When this formula version became active
    valid_until: date | None               # When superseded (None = current)
    tags: list[str]                        # ["gaap", "ifrs", "board_report"]
    source: Literal["formula_engine", "kpi_engine", "manual"]
```

Initial scope: ~40 formulae covering:

| Category | Formulae |
|----------|----------|
| Revenue | Net Revenue, Revenue Growth %, ARR, MRR, Avg Deal Size, Revenue per FTE |
| Expense | Total OPEX, COGS, SG&A, R&D as % of Revenue, Cost per Hire |
| Profitability | Gross Margin, EBITDA, EBIT, Net Margin, Operating Margin |
| Liquidity | Current Ratio, Quick Ratio, DSO, DPO, Cash Conversion Cycle |
| Efficiency | Revenue per Employee, Asset Turnover, Inventory Turns |
| Budgeting | Budget Attainment %, Budget Utilization Rate, Forecast Accuracy |
| Variance | Variance Amount, Variance %, Materiality Score, Trend Score |

### D. Business Capability Map

A structured map of the FP&A domain showing which business capabilities FinSight supports and how they relate.

```
FP&A Domain
├── Planning & Budgeting
│   ├── Budget Creation
│   ├── Budget Revision
│   ├── Rolling Forecast
│   └── Scenario Planning
├── Financial Close
│   ├── Period Close
│   ├── Account Reconciliation
│   ├── Journal Entry Review
│   └── Intercompany Reconciliation
├── Accounts Payable
│   ├── Invoice Processing
│   ├── Payment Execution
│   ├── Vendor Management
│   └── Expense Reporting
├── Accounts Receivable
│   ├── Billing & Invoicing
│   ├── Collections
│   ├── Credit Management
│   └── Cash Application
├── Variance Analysis
│   ├── Revenue Variance
│   ├── Expense Variance
│   ├── Headcount Variance
│   └── FX Variance
├── Forecasting
│   ├── Revenue Forecasting
│   ├── Expense Forecasting
│   ├── Cash Flow Forecasting
│   └── Driver-Based Forecasting
└── Reporting
    ├── Board Reporting
    ├── Management Reporting
    ├── Regulatory Reporting
    └── Ad-Hoc Analysis
```

Each capability entry includes:

| Field | Description |
|-------|-------------|
| `capability_id` | Stable identifier `cap.budgeting.create` |
| `name` | Human-readable name |
| `description` | Business description |
| `parent_id` | Parent capability (for hierarchy) |
| `supported_by` | Which FinSight engines support this |
| `events` | Domain events this capability produces/consumes |
| `maturity` | `planned | partial | full` |

### E. Semantic Data Dictionary

Field-level business metadata for every column in the FinSight data model. This is the bridge between database schemas and business meaning.

```yaml
tables:
  actuals:
    columns:
      amount:
        business_name: "Actual Amount"
        definition: "Recorded financial value for the period-account combination"
        canonical_type: "Money"
        unit: "entity_currency"
        classification: "confidential"
        sox_relevant: true
        pii: false
        source_system: "ERP"
        example: "1250000.00"
        validation_rules:
          - "amount != 0"
          - "amount is consistent with trial balance"
      period:
        business_name: "Fiscal Period"
        definition: "The fiscal period this actual belongs to"
        canonical_type: "FiscalPeriod"
        format: "YYYY-MM"
        classification: "internal"
        example: "2026-07"
      account_id:
        business_name: "GL Account Identifier"
        definition: "Reference to the chart of accounts entry"
        canonical_type: "GLAccountNumber"
        classification: "internal"
```

### F. Domain Event Catalog

A catalog of every business event the platform produces or consumes. Events are the glue between capabilities and data flows.

| Event | Producer | Consumer | Description |
|-------|----------|----------|-------------|
| `InvoiceImported` | CSV/API Connector | AP Engine, Data Quality | A vendor invoice was successfully ingested |
| `InvoiceRejected` | CSV/API Connector | AP Engine, Audit | An invoice failed validation and was rejected |
| `BudgetApproved` | Budget Workflow | Variance Engine, Scenario Engine | A budget version was approved for a period |
| `BudgetRevised` | Budget Workflow | Variance Engine | A budget revision was created |
| `PeriodClosed` | Close Engine | Variance Engine, Forecast Engine | A fiscal period was closed for postings |
| `PeriodReopened` | Close Engine | Audit, Variance Engine | A period was exceptionally reopened |
| `VarianceDetected` | Variance Engine | Commentary Engine, Policy Engine | A material variance was identified |
| `RootCauseIdentified` | Root Cause Agent | Recommendation Engine | A root cause was found for a variance |
| `ForecastPublished` | Forecast Engine | Board Report, Variance Engine | A new forecast version was published |
| `AssertionGenerated` | Assertion Pipeline | Commentary Engine, Policy Engine | A new set of assertions was created |
| `ActionProposed` | Recommendation Engine | Workflow Engine | An action item was proposed for approval |
| `BoardReportGenerated` | Commentary Engine | Reporting, Export | A board report was compiled and rendered |

Each event entry includes:

| Field | Description |
|-------|-------------|
| `event_id` | Stable identifier |
| `name` | Human-readable name |
| `description` | Business description |
| `schema` | Expected payload fields |
| `producer` | System component that emits this |
| `consumers` | System components that react to this |
| `category` | `financial | operational | governance` |
| `sensitivity` | `public | internal | confidential | restricted` |

### G. Reference Data Lifecycle

Template for managing reference data sets that change slowly but must be versioned.

| Reference Set | Update Frequency | Source of Truth | Validation |
|--------------|-----------------|-----------------|------------|
| Currencies (ISO 4217) | Yearly | ISO standard | 3-letter code, uppercase |
| Countries (ISO 3166) | Yearly | ISO standard | 2-letter code, uppercase |
| Tax Codes | Quarterly | Tax authority | Format per jurisdiction |
| GL Account Types | Rarely | Accounting standards | Enum of known types |
| Cost Centers | Monthly | HR/ERP system | HR system is authoritative |
| Departments | Monthly | HR/ERP system | Active flag required |
| Period Statuses | Per close | Fiscal calendar | State machine enforced |
| Entity List | Onboarding | CRM/Onboarding | Unique per deployment |

Each reference data set has a defined:
- **Authoritative source** — where updates originate
- **Refresh cadence** — how often it changes
- **Validation rules** — what makes a valid entry
- **Propagation method** — how updates reach downstream systems
- **Rollback plan** — how to revert a bad update

### H. Data Classification Matrix

A cross-reference of every field in the platform against its data classification. This matrix drives data masking, access control, and compliance reporting.

| Classification | Definition | Examples | Access Restrictions |
|---------------|------------|----------|-------------------|
| **Public** | No harm if disclosed | Product names, public financial reports (10-K) | None |
| **Internal** | Harmless but not public | Department names, fiscal calendars | Authenticated users only |
| **Confidential** | Harm if disclosed broadly | Actual amounts, budget details, headcount data | Role-based access |
| **Restricted** | Significant harm if disclosed | PII (employee names, compensation), bank account numbers, vendor payment details | Need-to-know only, encrypted at rest |
| **SOX-Relevant** | Subject to Sarbanes-Oxley controls | Any field used in financial reporting | Audit trail required, sign-off needed |

---

## Integration

### Connection to Existing Agents

```
Agents
  │
  ├── Commentary Agent ─────────► Glossary — reads term definitions for context
  │                              Formula Registry — reads formula for explanations
  │
  ├── Root Cause Agent ─────────► Capability Map — which capability had the variance
  │                              Domain Event Catalog — which events preceded the variance
  │
  ├── Scenario Agent ───────────► Formula Registry — knows which KPIs to project
  │                              Reference Data — reads exchange rates for scenarios
  │
  └── Recommendation Agent ─────► Capability Map — suggests improvements to capabilities
                                 Data Classification — respects sensitivity of fields
```

### Connection to Formula Engine

The existing `finance/formula_engine/formula_registry.py` is a **runtime evaluator**. The BKL Formula Registry is a **metadata catalog**. The relationship:

```
BKL Formula Registry (metadata)     Runtime Formula Registry (evaluation)
───────────────────────────────     ───────────────────────────────────
FormulaDefinition.formula_id  ──→   registered as evaluate_formula()
FormulaDefinition.expression   ──→   used to build the computation DAG
FormulaDefinition.depends_on  ──→   determines evaluation order
FormulaDefinition.version      ──→   selects which version to evaluate
```

The runtime registry imports metadata from the BKL registry at startup. When a formula changes, the BKL registry is updated first, then the runtime registry reloads.

### Connection to Assertion Pipeline

The assertion pipeline (`agents/assertion_pipeline.py`) generates claims about financial data. The BKL provides:

- **Semantic types** — an assertion about "Revenue" knows it references the `net_revenue` glossary term
- **Classification awareness** — assertions about RESTRICTED data are escalated
- **Formula derivation** — an assertion about Gross Margin can link back to its component formulae

### Connection to the Business Rules Engine

The business rules in `finance/rules/` (Phase 2, Layer 7) evaluate policy decisions. The BKL provides:

- **Materiality thresholds per metric** — read from formula definitions, not hardcoded
- **Classification gates** — RESTRICTED data always routes to human review
- **Capability-aware routing** — which review queue to route to based on affected capability

---

## Phased Rollout

### Phase 3a: Foundation (Weeks 1-2)

**Theme:** Establish the core data structures and populate the glossary.

| Task | Deliverable | Effort |
|------|-------------|--------|
| 3a.1 | Define `BusinessGlossary` model, `FormulaDefinition`, `CanonicalValueObject` base classes | 2d |
| 3a.2 | Implement `Money`, `CurrencyCode`, `Percentage`, `FiscalPeriod` value objects | 2d |
| 3a.3 | Populate initial 50-term glossary (revenue + expense categories) | 2d |
| 3a.4 | Populate Formula Registry with 15 core KPI formulas | 2d |
| 3a.5 | Write unit tests for all value objects | 1d |
| 3a.6 | Document glossary and formula definitions | 1d |
| **Total** | | **10d** |

### Phase 3b: Semantic Layer (Weeks 3-4)

**Theme:** Build the semantic data dictionary and domain event catalog.

| Task | Deliverable | Effort |
|------|-------------|--------|
| 3b.1 | Implement `SemanticDataDictionary` model | 2d |
| 3b.2 | Map all 30+ columns across `actuals`, `budget_lines`, `trial_balance` | 3d |
| 3b.3 | Implement `DomainEventCatalog` model | 1d |
| 3b.4 | Define 15 domain events with schemas | 2d |
| 3b.5 | Implement `DataClassificationMatrix` model | 1d |
| 3b.6 | Classify all mapped columns | 1d |
| **Total** | | **10d** |

### Phase 3c: Capability & Integration (Weeks 5-6)

**Theme:** Build the capability map and integrate BKL with existing layers.

| Task | Deliverable | Effort |
|------|-------------|--------|
| 3c.1 | Implement `BusinessCapabilityMap` model | 2d |
| 3c.2 | Define FP&A capability hierarchy (30+ capabilities) | 2d |
| 3c.3 | Integrate BKL glossary with commentary agent context builder | 2d |
| 3c.4 | Integrate BKL Formula Registry with runtime formula engine | 2d |
| 3c.5 | Integrate BKL classification with RLS and audit policies | 1d |
| 3c.6 | Integration tests for BKL → all downstream consumers | 1d |
| **Total** | | **10d** |

### Phase 3d: Reference Data & Governance (Weeks 7-8)

**Theme:** Reference data lifecycle, data stewardship tooling, and governance.

| Task | Deliverable | Effort |
|------|-------------|--------|
| 3d.1 | Implement Reference Data Lifecycle framework | 2d |
| 3d.2 | Populate initial reference data (currencies, countries, tax codes) | 1d |
| 3d.3 | Build Business Knowledge Change Request workflow | 2d |
| 3d.4 | Build BKL health dashboard (coverage, staleness, owner gaps) | 2d |
| 3d.5 | Documentation and team training | 1d |
| **Total** | | **8d** |

### Rollout Summary

| Phase | Focus | Weeks | New Files | Tests |
|-------|-------|-------|-----------|-------|
| 3a | Foundation | 1-2 | ~10 | ~30 |
| 3b | Semantic Layer | 3-4 | ~8 | ~20 |
| 3c | Capability & Integration | 5-6 | ~6 | ~15 |
| 3d | Governance | 7-8 | ~6 | ~10 |
| **Total** | | **8 weeks** | **~30** | **~75** |

---

## Success Criteria

### Must-Have (Ship Gate)

- [ ] **Glossary coverage**: 150+ financial terms defined with formula, source, classification
- [ ] **Formula Registry**: 40+ formula definitions with `depends_on`, `version`, `owner`
- [ ] **Canonical value objects**: `Money`, `Percentage`, `CurrencyCode`, `FiscalPeriod`, `ExchangeRate` implemented with full validation
- [ ] **Semantic dictionary**: Every column in `actuals`, `budget_lines`, `forecast_lines`, `trial_balance` has a business definition
- [ ] **Data classification**: Every field classified (PII, SOX, Confidential, Internal, Public)
- [ ] **Glossary consumed by commentary agent**: Commentary agent context builder reads glossary term definitions
- [ ] **Formula registry consumed by formula engine**: Runtime formula engine registers formulae from BKL metadata
- [ ] **Test suite**: Passes `ruff check .`, `mypy .`, `python -m pytest` in CI

### Should-Have (Target)

- [ ] **Capability map**: 30+ capabilities in hierarchical structure
- [ ] **Domain event catalog**: 15+ events with payload schemas
- [ ] **Reference data lifecycle**: Currencies, countries, tax codes managed through BKL
- [ ] **Business Knowledge Change Request workflow**: Formal process for glossary/registry updates
- [ ] **BKL health dashboard**: Coverage percentage, stale entries, owner gaps

### Nice-to-Have (Stretch)

- [ ] **Auto-classification**: ML-assisted suggestion of data classification based on field name and glossary lookup
- [ ] **Impact analysis**: "If I change this formula, which reports break?" computed from `depends_on` graph
- [ ] **Lineage integration**: BKL term IDs appear in assertion evidence chain

### Regression Gates

- [ ] All existing 83+ tests pass unchanged (Phase 1-2 regression)
- [ ] Existing agent pipelines produce identical output with BKL enabled vs. disabled (for non-BKL-aware paths)
- [ ] RLS and audit policies unchanged for fields whose classification hasn't changed
- [ ] Formula engine produces identical results with metadata-driven vs. hardcoded registrations

---

## Risk & Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Glossary becomes stale within 2 months | Medium | High | Governance process with scheduled reviews; auto-detect orphaned entries |
| Engineers bypass BKL and hardcode knowledge | Medium | Medium | Code review gates enforce BKL consumption for new features |
| Phase 3 slips into Phase 4 scope creep | High | Medium | Define strict ship gate (Must-Have); defer stretch goals |
| BKL adds latency to hot paths | Low | High | BKL is reference data — cache aggressively; no runtime queries to BKL layer |
| Business stakeholders disagree on definitions | Medium | Medium | Every glossary term has an explicit `owner`; disagreements escalate to that owner |
| Little adoption — nobody reads the glossary | High | Low | Integrate glossary into IDE (auto-complete term IDs); make BKL required by the pipeline |

---

## Appendix: Comparison with Existing Approaches

| Aspect | Traditional Data Dictionary | FinSight Phase 1-2 | FinSight Phase 3 (BKL) |
|--------|---------------------------|---------------------|-----------------------|
| Scope | Database columns only | Pydantic model fields | Business terms + formulae + capabilities + events + classifications |
| Audience | Technical | Technical | Technical + Business |
| Freshness | Static document | Code-driven (schema changes) | Governance-driven (change requests) |
| Consumed by | Humans | Type checkers + validators | Runtime engines + agents + governance |
| Versioning | None | Git history | Formal version + valid_from/valid_until |
| Change process | Edit document | Code review | Business Knowledge Change Request (with business sign-off) |
| Coverage | Sporadic | 100% of models | 100% of terms + 100% of columns + 100% of formulae |
