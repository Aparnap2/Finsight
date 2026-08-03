# DataOps — Structured Data Layer

> **Layer 2 of the Finance Operations OS.** DataOps owns the ingestion, validation, transformation, and traceability of every structured data point that enters FinSight. It is the foundation beneath MLOps, LLMOps, and AgentOps — if data is wrong, everything above it is wrong.

```
┌──────────────────────────────────────────────┐
│              Finance Operations OS            │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │              AgentOps                  │  │
│  │  Orchestration, evidence, commentary   │  │
│  ├────────────────────────────────────────┤  │
│  │              LLMOps                    │  │
│  │  Prompt management, evaluation         │  │
│  ├────────────────────────────────────────┤  │
│  │              MLOps                     │  │
│  │  Models, embeddings, golden datasets   │  │
│  ├────────────────────────────────────────┤  │
│  │         ⬤  DataOps  ⬤                 │  │
│  │  Pipelines, validation, lineage,       │  │
│  │  schemas, transformations, catalog     │  │
│  ├────────────────────────────────────────┤  │
│  │            DevSecOps                   │  │
│  │  CI/CD, secrets, infra, compliance     │  │
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

## Purpose

DataOps owns every decision about structured financial data from the moment it arrives at the system boundary to the moment it is consumed by deterministic engines and AI agents. It is not a storage layer — it is a **governance and transformation layer** that guarantees:

- **Data enters clean.** Every ingestion path passes through typed validation before any downstream logic touches it.
- **Data stays traceable.** Every assertion that reaches the user carries an unbroken chain of `evidence_ids` back to source records.
- **Schemas are explicit.** Every domain concept (Budget, Actual, Variance, KPI, etc.) is a Pydantic model with `Decimal` monetary fields, not a dictionary or an ORM row.
- **Transformations are deterministic.** Data manipulation uses Polars expressions and DuckDB SQL — no implicit casts, no floating-point arithmetic, no LLM-in-the-loop.

DataOps is the interface between external financial systems and FinSight's internal reasoning machinery.

---

## Key Capabilities

### Data Source Integration

Three provider implementations, all conforming to a single `SpreadsheetProvider` Protocol:

| Provider | File | Purpose |
|----------|------|---------|
| **CSVProvider** | `finance/integration/csv_provider.py` | File-upload ingestion from analyst exports |
| **GoogleSheetsProvider** | `finance/integration/google_sheets_provider.py` | Live Google Sheets pull via API |
| **MockProvider** | `finance/integration/mock_provider.py` | Test doubles and dev-mode data |

Providers are selected by type string through `ProviderFactory` (`finance/integration/factory.py`):

```python
factory = ProviderFactory()
provider = factory.create("csv", path="budget_2026.csv")
data = provider.read_range("default", "A1:Z100")
```

### Schema Registry (Domain Models)

Sixteen Pydantic domain models in `finance/domain/` define every financial entity the platform processes:

```
finance/domain/
├── company.py              # Company entity
├── chart_of_accounts.py    # Account, AccountType, ChartOfAccounts
├── department.py           # Department
├── cost_center.py          # CostCenter
├── budget.py               # Budget, BudgetLine, BudgetVersion
├── actual.py               # Actual, ActualLine
├── variance.py             # Variance, VarianceDirection
├── forecast.py             # Forecast, ForecastLine, ForecastScenario
├── kpi.py                  # KPI, KPIDefinition, KPIValue
├── driver.py               # Driver, DriverTree, DriverType
├── transaction.py          # Transaction
├── evidence.py             # EvidenceItem, EvidenceSource, EvidenceConfidence
├── recommendation.py       # Recommendation, RecommendationStatus, RecommendationType
├── board_report.py         # BoardReport, ReportSection
├── fiscal_calendar.py      # FiscalCalendar, FiscalPeriod, FiscalPeriodType
└── _types.py               # MoneyDecimal type alias
```

Every model uses `Decimal` for monetary fields — `float` is structurally rejected at the Pydantic boundary via the `MoneyDecimal` validator (`finance/domain/_types.py`).

### Data Validation Framework

Three validation layers, each enforcing different constraints:

1. **Field-level validation** — Pydantic model constraints (required fields, types, enum members)
2. **Cross-field domain validation** — `finance/validation/` (calendar consistency, period progression, data quality checks)
3. **Assertion validation** — `shared/utils/validators/` (evidence sufficiency, source diversity, support level downgrade)

### Data Quality Engine

Six deterministic checks in `finance/validation/data_quality.py` against every `ToolResult`:

| Check | Trigger | Severity |
|-------|---------|----------|
| `check_coverage` | `coverage_pct < 50%` | warning |
| `check_freshness` | Data older than 90 days | warning |
| `check_row_count` | Zero rows returned | critical / warning |
| `check_source_diversity` | Single source only | info |
| `check_required_filters` | Missing tenant_id or period filter | critical |
| `check_quality_score` | Overall quality < 50% | warning |

Each check produces a `DataQualityCheck` object; the aggregate is a `DataQualityReport` with an `overall_score` (0.0–1.0) and an active `degraded_modes` list that propagates into `PipelineState`.

### Data Lineage

Every `Assertion` (`shared/models/assertions.py`) carries:

```python
evidence_ids: list[str]       # pointers to EvidenceItem records
```

Every `EvidenceItem` (`finance/domain/evidence.py`) carries:

```python
source_type: EvidenceSource   # kpi | variance | driver | transaction | manual
source_id: str                # identifier of the source object
source_value: MoneyDecimal    # the numerical value
confidence: EvidenceConfidence  # high | medium | low | tentative
```

This creates a closed chain: **Assertion → EvidenceItem → Source Record** — every financial claim in a board report can be traced back to its originating data point.

### Transformation Pipeline

Data flows through a deterministic transformation chain:

```
Source → Provider → ToolResult → Polars transform → DuckDB analytics → Domain model
```

- **Polars** handles row-level transformations (filter, join, aggregate) with lazy evaluation
- **DuckDB** handles analytical queries (window functions, period-over-period calculations)
- Both are zero-copy where possible and enforce strict typing at every stage

---

## Implementation Map

### Data Integration Layer (`finance/integration/`)

| File | Role |
|------|------|
| `protocol.py` | `SpreadsheetProvider` Protocol — duck-typed contract for all providers |
| `csv_provider.py` | CSV file reader implementing the Protocol |
| `google_sheets_provider.py` | Google Sheets API client implementing the Protocol |
| `mock_provider.py` | Deterministic test double for unit tests |
| `factory.py` | `ProviderFactory.create(type, **kwargs)` — string-based provider instantiation |
| `spreadsheet_provider.py` | Convenience re-exports for clean import paths |

### Data Validation Layer (`finance/validation/`)

| File | Role |
|------|------|
| `harness.py` | `ValidationSuite`, `ValidationResult`, `ValidationReport`, `ValidatorAdapter` — composite validation pipeline |
| `data_quality.py` | `DataQualityCheck`, `DataQualityReport`, six check functions, `assess_tool_result()`, `assess_batch()`, `propagate_to_state()` |
| `models.py` | `FiscalPeriod`, `PeriodStatus`, `PeriodType` — period lifecycle models |
| `calendar.py` | `FiscalCalendar` — period generation, navigation, prior-year linking |
| `validator.py` | `PeriodValidator` — overlap detection, gap detection, year validation |
| `progression.py` | `PeriodProgression` — period state advancement, reopening, YTD aggregation |

### Shared Validation Layer (`shared/utils/validators/`)

| File | Role |
|------|------|
| `assertion_validator.py` | `validate_assertion()` — type-specific rules for NUMERIC, COMPARATIVE, CAUSAL, HYPOTHESIS, ACTION assertions; evidence count and source count requirements; `SupportLevel` downgrade logic |
| `claim_validator.py` | Claim-level validation for commentary text |

### Domain Model Layer (`finance/domain/`)

Sixteen Pydantic models, one per file. Each model:
- Uses `MoneyDecimal` (`Decimal` constrained via Pydantic) for all monetary fields
- Has explicit docstrings explaining the business concept
- Uses `StrEnum` for enumerated classifications
- Stores `id` fields that serve as targets for `evidence_ids`

---

## Data Quality Framework

Data quality operates at every boundary where data crosses from one subsystem to another. The framework is designed as a **gate, not a dashboard** — poor quality data blocks pipeline progress rather than merely reporting a metric.

### Boundary 1: Ingestion Boundary

**Where:** `finance/validation/harness.py` — `DataQualityValidator`

**What happens:**

```
Provider.read_range() → raw rows
    ↓
ToolResult (coverage_pct, row_count, freshness, etc.)
    ↓
DataQualityValidator.validate(tool_result=result)
    ↓
ValidationResult (is_valid, messages, severity)
```

The `DataQualityValidator` runs all six checks from `finance/validation/data_quality.py` and produces a single aggregated `ValidationResult`. If the result fails, the pipeline enters a degraded mode — it does not proceed with low-quality data.

### Boundary 2: Domain Model Boundary

**Where:** Pydantic model constructors across `finance/domain/`

**What happens:**

Every domain model constructor validates:
- **Type correctness** — `amount: MoneyDecimal` rejects `float` and `str`
- **Required fields** — `id`, `company_id`, `fiscal_year` etc.
- **Enum membership** — `BudgetVersion.ORIGINAL | REVISED | ADJUSTED`
- **Optional field consistency** — `None` vs. missing

```python
# finance/domain/_types.py
MoneyDecimal = Decimal  # constrained by Pydantic validator at API boundary
```

### Boundary 3: Calendar Boundary

**Where:** `finance/validation/validator.py` — `PeriodValidator`

**What happens:**

```python
validator = PeriodValidator()
result = validator.validate_period(period, calendar)
# result.is_valid, result.errors, result.overlapping_periods
```

Checks:
- **Overlap detection** — no two periods share date ranges
- **Gap detection** — no unaccounted days between consecutive periods
- **Prior-year linking** — `prior_year_period_id` consistency across fiscal years

### Boundary 4: Assertion Boundary

**Where:** `shared/utils/validators/assertion_validator.py` — `validate_assertion()`

**What happens:**

Each assertion type has distinct validation rules:

| Assertion Type | Minimum Evidence | Minimum Sources | Support Level Ceiling |
|----------------|-----------------|----------------|----------------------|
| `NUMERIC` | 1 | — | VERIFIED |
| `COMPARATIVE` | 2 | — | PROBABLE (if < 3 sources) |
| `CAUSAL` | 2 | 2 | VERIFIED |
| `HYPOTHESIS` | 0 | — | PROBABLE (never VERIFIED) |
| `ACTION` | — | — | VERIFIED (if valid template) |

If validation fails, the support level is downgraded — a claim with insufficient evidence never reaches the user as VERIFIED.

### Boundary 5: Pipeline State Boundary

**Where:** `finance/validation/data_quality.py` — `propagate_to_state()`

**What happens:**

```python
state = propagate_to_state(state, quality_report)
# state["data_quality"] = { overall_score, checks, degraded_modes }
# state["degraded_modes"] = ["low_coverage", "stale_source"]
```

Degraded modes cascade upward into AgentOps — agent orchestration respects degraded modes when deciding whether to proceed, request human review, or halt.

---

## Lineage Model

Lineage in FinSight is not a metadata tag — it is a **structural constraint** enforced by Pydantic types and validated at every stage.

### The Chain

```
Source Record (database row / CSV cell / sheet cell)
    ↓
ToolResult (query_fingerprint, tenant_id, row_count, quality metadata)
    ↓
EvidenceItem (id, source_type, source_id, source_value, confidence)
    ↓
Assertion (evidence_ids=[...], support_level)
    ↓
Commentary / Board Report (rendered narrative with cited evidence)
```

### How evidence_ids Work

Every `Assertion` has an `evidence_ids: list[str]` field. Each string in that list must match the `id` field of an `EvidenceItem`. The evidence item in turn stores:

```python
class EvidenceItem(BaseModel):
    id: str                          # "evt_2026_001"
    claim: str                       # "Revenue grew 12% YoY"
    source_type: EvidenceSource      # EvidenceSource.VARIANCE
    source_id: str                   # "var_revenue_2026_q1"
    source_value: MoneyDecimal | None
    supporting_metrics: list[str]    # ["kpi_revenue_growth"]
    confidence: EvidenceConfidence   # EvidenceConfidence.HIGH
    assumptions: list[str]
    limitations: list[str]
    created_at: datetime
```

### Auditing a Claim End-to-End

To verify a statement in a board report:

```
Board report: "Revenue grew 12% year-over-year, driven by a 15% increase
              in average deal size."

    ↓  Find the Assertion that rendered this sentence

Assertion(id="as_017", type="CAUSAL", evidence_ids=["evt_012", "evt_013"])

    ↓  Resolve evidence_ids

EvidenceItem(id="evt_012", source_type="VARIANCE",
             source_id="var_rev_2026_q1", source_value=Decimal("0.12"))
EvidenceItem(id="evt_013", source_type="KPI",
             source_id="kpi_avg_deal_size", source_value=Decimal("0.15"))

    ↓  Resolve source_ids to ToolResult data

ToolResult(query_fingerprint="a1b2c3...", source_type="financial_fact",
           row_count=48, coverage_pct=0.94, ...)
```

This chain is machine-verifiable: every `evidence_id` can be resolved, every `source_id` can be dereferenced, and every value in the chain can be checked for consistency.

### What Breaks Lineage

- **Orphaned evidence** — an `evidence_id` that points to a non-existent `EvidenceItem` (validated by `assertion_validator.py`)
- **Unsupported causal claims** — CAUSAL assertions with fewer than 2 distinct sources (downgraded to PROBABLE or INSUFFICIENT)
- **Circular references** — evidence items that reference each other's assertions (prevented by strict directionality: EvidenceItem → source, never assertion → evidence → assertion)

---

## Interfaces

DataOps provides typed interfaces to the layers above it (MLOps, LLMOps, AgentOps) and consumes data from external systems below it.

### Upward Interfaces (what DataOps provides)

| Interface | Type | Provider | Consumer |
|-----------|------|----------|----------|
| Domain models | Pydantic `BaseModel` | `finance.domain.*` | All engines, agents, API |
| `ValidationResult` | Pydantic `BaseModel` | `finance.validation.harness` | Agent orchestration |
| `DataQualityReport` | Typed class with `.passed` | `finance.validation.data_quality` | Pipeline orchestration |
| `EvidenceItem` | Pydantic `BaseModel` | `finance.domain.evidence` | Commentary engine, assertion pipeline |
| `AssertionValidationResult` | Pydantic `BaseModel` | `shared.utils.validators.assertion_validator` | Agent nodes |
| `ToolResult` | Pydantic `BaseModel` (frozen) | `shared.utils.tools.tool_result` | All tools, data quality engine |
| `FiscalCalendar` | Class with typed methods | `finance.validation.calendar` | Variance engine, scenario engine |
| `SpreadsheetProvider` | Protocol | `finance.integration.protocol` | Ingestion API endpoints |

### Downward Interfaces (what DataOps consumes)

| Interface | Provider | Notes |
|-----------|----------|-------|
| CSV files | End-user upload | Via `CSVProvider.read_range()` |
| Google Sheets API | External HTTP | Via `GoogleSheetsProvider` with OAuth2 |
| PostgreSQL | Database | Via SQLAlchemy async sessions in tool layer |
| Mock data | Test fixtures | Via `MockProvider` for dev/test environments |

### Design Contract

All upward interfaces share four properties:

1. **Typed** — No dictionaries cross the boundary. Every return value is a Pydantic model or a typed class with documented fields.
2. **Validated at construction** — Invalid data cannot be represented. Pydantic raises on construction, not on access.
3. **Self-documenting** — Every field has a docstring explaining its business meaning, not its data type.
4. **Immutable where possible** — `ToolResult` is frozen; `EvidenceItem` fields are set-once. Mutability is a design smell in data pipelines.

---

## Operational Metrics

### Validation Pass Rate

```
metric: dataops.validation.pass_rate
definition: percentage of ValidationResults with is_valid=True
target: > 95%
measurement: ValidationReport.passed_count / ValidationReport.total
source: finance.validation.harness.ValidationReport
```

Track by validation stage (ingestion, calendar, assertion) to identify where quality breaks.

### Schema Compliance

```
metric: dataops.schema.compliance_rate
definition: percentage of ingested records that construct valid domain models
target: > 99%
measurement: (total records — Pydantic validation errors) / total records
source: finance.domain.* model constructors
```

A sudden drop in schema compliance often signals upstream schema drift (new column, renamed field, changed data type) in a connected spreadsheet or API.

### Lineage Completeness

```
metric: dataops.lineage.completeness
definition: percentage of evidence_ids that resolve to existing EvidenceItem records
target: 100%
measurement: count of orphaned evidence_ids / total evidence_ids
source: shared.utils.validators.assertion_validator (evidence_count parameter)
```

Orphaned evidence IDs indicate a broken pipeline stage — data was transformed but lineage metadata was not carried forward.

### Data Quality Score Distribution

```
metric: dataops.quality.score_distribution
definition: distribution of DataQualityReport.overall_score values
target: median > 0.85, p10 > 0.5
measurement: histogram across all pipeline runs
source: finance.validation.data_quality.DataQualityReport
```

Track by source type to identify chronically low-quality integrations.

### Ingestion Freshness

```
metric: dataops.ingestion.freshness_p99
definition: 99th percentile of ToolResult.freshness_seconds across all sources
target: < 7 days (604,800 seconds)
measurement: percentile aggregation of freshness_seconds
source: shared.utils.tools.tool_result.ToolResult
```

Stale data triggers the `FRESHNESS_CHECK` degraded mode. A rising p99 indicates a connector or provider that is falling behind.

### Degraded Mode Frequency

```
metric: dataops.degraded.frequency
definition: count of pipeline runs entering each degraded mode type
target: low_coverage < 5%, stale_source < 2%
measurement: histogram of DegradedMode values in PipelineState
source: finance.validation.data_quality.propagate_to_state()
```

High degraded mode frequency warrants investigation of the affected data source or ingestion path.

---

## Failure Modes

### F-1: Schema Drift

**What happens:** The upstream data source changes a column name, adds a required field, or changes a data type (string → numeric, date format change). Pydantic model construction fails.

**Detection:** `Schema compliance rate` drops. Pydantic `ValidationError` surfaces in ingestion logs.

**Response:**
1. Identify the changed field from the `ValidationError` message — Pydantic errors are self-describing
2. Update the affected domain model in `finance/domain/` and add a migration test
3. Backfill historical data if the new field is required
4. Add a schema version check to the `SpreadsheetProvider` Protocol if the drift is recurring

**Prevention:**
- Pin a schema version string in each provider's `validate()` method
- Use `ProviderFactory` to register a new provider version when upstream changes are non-backward-compatible

### F-2: Missing Data

**What happens:** A connector returns zero rows, or a required data source is unavailable. `ToolResult.row_count` is 0 and `insufficient_data` is `True`.

**Detection:** `ROW_COUNT_CHECK` fires at `critical` severity. `DataQualityReport.overall_score` drops to 0.0. Pipeline enters `LOW_COVERAGE` degraded mode.

**Response:**
1. Distinguish between "source is down" (transient) and "source has no data for this period" (informational)
2. For transient failures: retry with exponential backoff (connector-level)
3. For informational empty results: proceed with explicit caveat in the commentary
4. If data is expected but missing: escalate to human review via policy routing

**Prevention:**
- Configure expected row count ranges per source in the ingestion configuration
- Use `check_required_filters` to ensure empty results aren't caused by missing filter parameters

### F-3: Connector Failure

**What happens:** The Google Sheets API returns a 403, the CSV file is malformed, or the network is unreachable. The provider raises an exception rather than returning data.

**Detection:** Provider method raises. `ValidatorAdapter.validate()` catches the exception and returns a non-valid `ValidationResult` with the exception message.

**Response:**
1. Identify the connector type from the provider registry (`ProviderFactory._PROVIDERS`)
2. Check the exception type — authentication failures (OAuth expiry), rate limits (429), or availability (503) each have distinct remediation
3. Route to human ops team for credential refresh or API quota increase

**Prevention:**
- Implement provider-level health checks via the `validate(spreadsheet_id)` method on the `SpreadsheetProvider` Protocol
- Monitor credential expiry and rotate before they expire
- Implement circuit-breaker pattern for external API connectors

### F-4: Data Alignment Failure

**What happens:** Calendar periods from upstream do not match FinSight's fiscal calendar. Period IDs conflict, date ranges overlap, or gaps exist between consecutive periods.

**Detection:** `PeriodValidator.validate_year()` returns errors with `overlapping_periods` or `missing_periods` populated.

**Response:**
1. Compare the upstream fiscal year start month against `FiscalCalendar.fiscal_year_start_month`
2. Regenerate periods with the correct start month using `FiscalCalendar.generate_periods(year)`
3. Re-run the period validation before proceeding to variance analysis

**Prevention:**
- Configure `FiscalCalendar` with the tenant's fiscal year start month at onboarding
- Validate all incoming period references against the calendar before ingestion
- Use `PeriodProgression.advance()` to enforce sequential period lifecycle

### F-5: Lineage Breakage

**What happens:** A transformation step discards or modifies `evidence_ids` without updating the chain. An assertion references an `evidence_id` that no longer exists.

**Detection:** `assertion_validator.py` computes `evidence_count < 2` for COMPARATIVE or CAUSAL assertions, triggering a support level downgrade. In severe cases, `evidence_ids` are empty and the assertion is classified `INSUFFICIENT`.

**Response:**
1. Trace the affected assertion's `source` field ("deterministic" vs. "llm_analysis" vs. "human") to identify which pipeline stage broke the chain
2. Audit the transformation logic for missing evidence propagation
3. Add an integration test that verifies evidence chain integrity through the full pipeline

**Prevention:**
- Treat `evidence_ids` as immutable through transformation — always append, never replace
- Add a pre-commit hook that rejects code where evidence metadata is constructed without a source reference
- Run lineage completeness checks as part of CI

### F-6: Silent Quality Degradation

**What happens:** Data quality metrics drift downward gradually — coverage drops from 95% to 80% to 60% over weeks. No single check fails, but the aggregate `overall_score` trends below threshold.

**Detection:** `data_quality.score_distribution` shows a monotonic downward trend. The median drops below 0.85.

**Response:**
1. Analyze per-check trend: is one check (e.g., `freshness`) driving the decline, or is it broad?
2. If freshness: investigate source update frequency
3. If coverage: investigate whether expected data volume has grown without corresponding connector scaling
4. If quality_score: investigate data completeness at the source

**Prevention:**
- Set trend alerts on `overall_score` — alert if 7-day rolling average drops by more than 10%
- Run data quality trend reports weekly as part of DataOps operational review

---

## Dependency Map

```
External Systems
    │
    ▼
finance/integration/     ← SpreadsheetProvider Protocol
    │                        │ CSVProvider, GoogleSheetsProvider, MockProvider
    │                        │ ProviderFactory
    ▼
ToolResult                ← shared/utils/tools/tool_result.py
    │                        (frozen, quality metadata, query fingerprint)
    ▼
finance/validation/       ← DataQualityValidator, ValidationSuite
    │                        DataQualityReport, FiscalCalendar, PeriodValidator
    ▼
finance/domain/           ← 16 Pydantic models (Budget, Actual, Variance, ...)
    │                        EvidenceItem with source_id chain
    ▼
shared/utils/validators/  ← assertion_validator.py, claim_validator.py
    │                        (evidence count rules, support level downgrade)
    ▼
Agents / Engines / API    ← typed consumption of validated, traceable data
```

---

## Relationship to Other Platform Layers

| Layer | DataOps Provides | DataOps Requires |
|-------|-----------------|-----------------|
| **MLOps** | Domain models as training targets, lineage for feature provenance | Embeddings for schema matching, anomaly detection thresholds |
| **LLMOps** | Validated context packs, structured evidence for prompts | Prompt schemas that preserve `evidence_ids` through generation |
| **AgentOps** | `DataQualityReport` for degraded mode decisions, `ValidationResult` for gate logic | Pipeline state that carries quality metadata forward |
| **DevSecOps** | Provider credentials, configuration-as-code | Secure secret storage for API keys, CI/CD for schema migrations |
