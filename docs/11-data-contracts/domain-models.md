# Domain Model Architecture — Rich Domain Models for the Finance Operations OS

> **Layer:** Governance & Domain — sits between Data Contracts and the Compute Runtime
> **Audience:** Domain engineers, backend developers, data modelers
> **Status:** Design proposal for Phase 2
> **Existing models audited:** 18 models across `finance/domain/` and `shared/models/`

## 1. Current State Audit

### 1.1 Domain Models in `finance/domain/` (16 Pydantic models)

| # | Model | File | Has Invariants? | Has State Machine? | Has Audit Policy? | Gap |
|---|-------|------|----------------|-------------------|-------------------|-----|
| 1 | `Company` | `company.py` | Partial (fiscal_year_start validation) | No | No | Missing status, onboarding state |
| 2 | `Account` | `chart_of_accounts.py` | No | No | No | Missing active/inactive lifecycle, closure rules |
| 3 | `ChartOfAccounts` | `chart_of_accounts.py` | Partial (version) | No | No | Missing COA lock/unlock, approval state |
| 4 | `BudgetLine` | `budget.py` | No | No | No | Missing period validation, version anchoring |
| 5 | `Budget` | `budget.py` | No | No | No | Missing approval workflow, locked state |
| 6 | `ActualLine` | `actual.py` | No | No | No | Missing source verification, tie-to-GL |
| 7 | `Actual` | `actual.py` | No | No | No | Missing posting state, reconciliation status |
| 8 | `Variance` | `variance.py` | Partial (direction, materiality) | No | No | Missing analysis state, review status |
| 9 | `ForecastLine` | `forecast.py` | No | No | No | Missing scenario cross-reference |
| 10 | `Forecast` | `forecast.py` | No | No | No | Missing approval, version comparison |
| 11 | `KPI` / `KPIValue` | `kpi.py` | No | No | No | Missing calculation status, data freshness |
| 12 | `Driver` / `DriverTree` | `driver.py` | Partial (weight sum) | No | No | Missing driver confidence, validation state |
| 13 | `Transaction` | `transaction.py` | No | No | No | Missing posting state, audit reference |
| 14 | `EvidenceItem` | `evidence.py` | No | No | No | Missing verification state, chain validation |
| 15 | `Recommendation` | `recommendation.py` | No | Yes (`PROPOSED→REVIEWED→APPROVED→IMPLEMENTED/REJECTED`) | No | State machine exists partially; missing rejected-from-any-state |
| 16 | `BoardReport` | `board_report.py` | No | No | No | Missing publishing state, approval workflow |
| 17 | `FiscalPeriod` / `FiscalCalendar` | `fiscal_calendar.py` | Partial (closed) | Partial (is_closed flag) | No | Missing period progression state machine |
| 18 | `EvidenceItem` (duplicate ref) | `evidence.py` | — | — | — | See #14 |

### 1.2 ORM Models in `shared/models/database.py` (18 SQLAlchemy models)

These are the persistence layer. The domain model audit above identifies which concepts need enrichment at the Pydantic level. ORM models are NOT being redesigned — only the domain Pydantic models that sit between connectors and the runtime.

---

## 2. Domain Aggregate Architecture

Six aggregates group related models under a single consistency boundary. Each aggregate defines:
- **Root entity** — the entry point for all operations
- **Invariants** — conditions that must always hold true
- **State machine** — legal state transitions
- **Audit policy** — what events must be recorded

```
┌─────────────────────────────────────────────────────────────────┐
│                   FINANCE OPERATIONS OS                          │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ Identity │  │ Finance  │  │  Risk    │  │ Workflow │        │
│  │ Aggregate│  │Aggregate │  │Aggregate │  │Aggregate │        │
│  ├──────────┤  ├──────────┤  ├──────────┤  ├──────────┤        │
│  │ Company  │  │ Account  │  │ Variance │  │ Pipeline │        │
│  │ COA      │  │BudgetLine│  │Evidence  │  │ AgentRun │        │
│  │ Fiscal   │  │ActualLine│  │Driver    │  │ Review   │        │
│  │ Calendar │  │Forecast  │  │RootCause │  │ Action   │        │
│  │          │  │ KPI      │  │          │  │          │        │
│  │          │  │Transaction│  │          │  │          │        │
│  ├──────────┤  ├──────────┤  ├──────────┤  ├──────────┤        │
│  │  Audit   │  │ Compute  │  │          │  │          │        │
│  │Aggregate │  │Aggregate │  │          │  │          │        │
│  ├──────────┤  ├──────────┤  │          │  │          │        │
│  │AuditLog  │  │ Job      │  │          │  │          │        │
│  │Assertion │  │ Dataset  │  │          │  │          │        │
│  │Policy    │  │ Cache    │  │          │  │          │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

### 2.1 Identity Aggregate

**Root:** `Company`

**Models:** `Company`, `ChartOfAccounts`, `Account`, `FiscalCalendar`, `FiscalPeriod`

**Invariants:**
1. A `Company` MUST have exactly one active `FiscalCalendar` at all times.
2. Every `FiscalPeriod` in a calendar MUST have a unique combination of `fiscal_year` + `period_number` + `period_type`.
3. Consecutive `FiscalPeriod`s MUST NOT overlap and MUST NOT have gaps.
4. An `Account.code` MUST be unique within a `ChartOfAccounts`.
5. A `ChartOfAccounts` version is incremented on every structural change (add, remove, reclassify account).

**Enriched Pydantic model for Company:**

```python
class CompanyStatus(str, Enum):
    ACTIVE = "active"
    ONBOARDING = "onboarding"      # Initial setup, chart not loaded
    SUSPENDED = "suspended"        # Temporarily inactive
    ARCHIVED = "archived"          # No longer active, data retained

class Company(BaseModel):
    id: str
    name: str
    currency: str = "USD"
    fiscal_year_start: str = "01-01"
    status: CompanyStatus = CompanyStatus.ONBOARDING
    onboarding_completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    # Invariant: fiscal_year_start must be MM-DD
    @field_validator("fiscal_year_start")
    @classmethod
    def validate_fiscal_year_start(cls, v: str) -> str:
        ...  # existing validation logic

    # State transitions
    def complete_onboarding(self) -> None:
        assert self.status == CompanyStatus.ONBOARDING
        self.status = CompanyStatus.ACTIVE
        self.onboarding_completed_at = datetime.utcnow()

    def suspend(self) -> None:
        assert self.status in (CompanyStatus.ACTIVE, CompanyStatus.ONBOARDING)
        self.status = CompanyStatus.SUSPENDED

    def archive(self) -> None:
        assert self.status == CompanyStatus.SUSPENDED
        self.status = CompanyStatus.ARCHIVED
```

**Enriched Account:**

```python
class AccountStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"      # Existing, not used in new budgets
    CLOSED = "closed"          # No longer valid for any posting

class Account(BaseModel):
    id: str
    code: str
    name: str
    type: AccountType
    parent_code: str | None = None
    status: AccountStatus = AccountStatus.ACTIVE
    currency: str | None = None
    closed_at: datetime | None = None

    def deactivate(self) -> None:
        assert self.status == AccountStatus.ACTIVE
        self.status = AccountStatus.INACTIVE

    def close(self) -> None:
        assert self.status == AccountStatus.INACTIVE
        self.status = AccountStatus.CLOSED
        self.closed_at = datetime.utcnow()

    def can_post_transaction(self) -> bool:
        return self.status == AccountStatus.ACTIVE
```

### 2.2 Finance Aggregate

**Root:** `Budget`

**Models:** `Budget`, `BudgetLine`, `Actual`, `ActualLine`, `Variance`, `Forecast`, `ForecastLine`, `KPI`, `KPIValue`, `Transaction`

**Invariants:**
1. Every `BudgetLine.period_id` MUST reference a `FiscalPeriod` that is NOT closed.
2. Every `BudgetLine.amount` MUST be >= 0 for cost accounts. Revenue accounts may be negative in rare cases (returns).
3. `Variance.variance_amount` MUST equal `Variance.actual_amount - Variance.budget_amount` exactly.
4. `Variance.variance_pct` MUST be `(variance_amount / |budget_amount|) * 100` — guaranteed by constructor.
5. A `BudgetLine` version must match its parent `Budget.version`.
6. `ForecastLine.scenario` MUST be one of the scenarios defined in the parent `Forecast`.

**Enriched BudgetLine with invariants enforced at construction:**

```python
class BudgetLine(BaseModel):
    id: str
    account_id: str
    department_id: str | None = None
    cost_center_id: str | None = None
    amount: MoneyDecimal
    period_id: str
    version: BudgetVersion = BudgetVersion.ORIGINAL

    @model_validator(mode="after")
    def validate_amount_sign(self) -> "BudgetLine":
        """Cost accounts must have non-negative budget amounts."""
        # Cross-reference with account type requires context — enforced
        # at the Budget aggregate level, not here.
        if self.amount < 0:
            raise ValueError("BudgetLine amount must be non-negative")
        return self
```

**Enriched Variance with guaranteed mathematical invariants:**

```python
class Variance(BaseModel):
    id: str
    account_id: str
    account_name: str
    department_id: str | None = None
    actual_amount: MoneyDecimal
    budget_amount: MoneyDecimal
    variance_amount: MoneyDecimal
    variance_pct: MoneyDecimal
    direction: VarianceDirection
    period_id: str
    is_material: bool = False
    materiality_tier: str | None = None
    drivers: list[str] = []
    analysis_status: VarianceAnalysisStatus = VarianceAnalysisStatus.UNANALYZED

    @model_validator(mode="after")
    def validate_variance_math(self) -> "Variance":
        """Guarantee variance_amount and variance_pct are correct."""
        expected_variance = self.actual_amount - self.budget_amount
        if self.variance_amount != expected_variance:
            raise ValueError(
                f"variance_amount ({self.variance_amount}) != "
                f"actual - budget ({expected_variance})"
            )
        if self.budget_amount != 0:
            expected_pct = (
                self.variance_amount
                / abs(self.budget_amount)
                * Decimal("100")
            )
            # Allow for rounding differences at 4 decimal places
            if abs(self.variance_pct - expected_pct) > Decimal("0.0001"):
                raise ValueError(
                    f"variance_pct ({self.variance_pct}) != "
                    f"calculated ({expected_pct})"
                )
        return self

    @model_validator(mode="after")
    def validate_direction(self) -> "Variance":
        """Direction must be consistent with the sign of variance_amount."""
        if self.variance_amount > 0 and self.direction == VarianceDirection.ADVERSE:
            raise ValueError("Positive variance must be FAVORABLE")
        if self.variance_amount < 0 and self.direction == VarianceDirection.FAVORABLE:
            raise ValueError("Negative variance must be ADVERSE")
        return self
```

### 2.3 Risk Aggregate

**Root:** `Variance` (in risk context)

**Models:** `Variance` (analysis extension), `EvidenceItem`, `RootCauseFinding`, `Driver`, `DriverTree`

**Invariants:**
1. Every `RootCauseFinding` MUST cite at least one `Assertion` (via `evidence_ids`).
2. Every `CAUSAL` assertion MUST have at least 2 distinct evidence sources.
3. `DriverTree` child weights MUST sum to <= 1.0 (they represent decomposition; may not cover all causes).
4. A `RootCauseFinding` CANNOT have `confidence > 0.5` if any cited evidence has `confidence = "tentative"`.

**Enriched RootCauseFinding:**

```python
class RootCauseFinding(BaseModel):
    variance_id: str
    summary: str
    assertions: list[Assertion] = []
    evidence: list[EvidenceItem] = []
    confidence_score: float
    recommended_action: str | None = None
    similar_historical_case: str | None = None
    alternative_hypotheses: list[Assertion] = []
    data_gaps: list[str] = []
    status: RootCauseStatus = RootCauseStatus.DRAFT

    @model_validator(mode="after")
    def validate_evidence_sufficiency(self) -> "RootCauseFinding":
        """At least one assertion with evidence is required."""
        if not self.assertions:
            raise ValueError("RootCauseFinding must have at least one assertion")
        total_evidence = sum(len(a.evidence_ids) for a in self.assertions)
        if total_evidence == 0:
            raise ValueError("RootCauseFinding must cite at least one evidence item")
        return self

    @model_validator(mode="after")
    def validate_confidence_bounds(self) -> "RootCauseFinding":
        """Confidence cannot exceed evidence ceiling."""
        has_tentative = any(
            e.confidence == EvidenceConfidence.TENTATIVE
            for e in self.evidence
        )
        if has_tentative and self.confidence_score > 0.5:
            raise ValueError(
                "Confidence cannot exceed 0.5 when any evidence is tentative"
            )
        return self
```

### 2.4 Workflow Aggregate

**Root:** `PipelineRun`

**Models:** `PipelineRun`, `AgentRun`, `ReviewDecision`, `ActionItemDB`, `CommentaryVersion`, `Scenario`

**Invariants:**
1. A `ReviewDecision` can only be created for an existing `AgentRun`.
2. `ActionItemDB.status` transitions are governed by the action state machine.
3. `CommentaryVersion.version` MUST be strictly increasing (no gaps, no duplicates).
4. A `Scenario` cannot be marked as `approved` unless all required analyses are complete.

### 2.5 Audit Aggregate

**Root:** `AuditLog`

**Models:** `AuditLog`, `AssertionDB`, `PolicyDecisionLog`, `ReviewLog`

**Invariants:**
1. `AuditLog` is append-only — no UPDATE, no DELETE.
2. Every `AssertionDB` MUST have a complete `evidence_ids_json` chain.
3. `PolicyDecisionLog.autonomy_level` MUST be consistent with `degraded_modes` active at time of decision.

### 2.6 Compute Aggregate

**Root:** `Job`

**Models:** `Job`, `JobTelemetry`, `Dataset`, `ComputeError`, `ToolResultCache`, `DataQualitySnapshot`

**Invariants:**
1. Every `Job` MUST have a valid `JobStatus` transition (state machine enforced).
2. `Job.result_ref` is `None` unless `status == SUCCESS`.
3. `Job.error` is `None` unless `status in (FAILED, CANCELLED)`.
4. `DataQualitySnapshot.overall_score` MUST be in range [0.0, 1.0].

---

## 3. Making Invalid States Unrepresentable

### 3.1 Type-Level Guarantees

| Invalid State | Prevention Technique |
|--------------|---------------------|
| Float monetary value | `MoneyDecimal` with `BeforeValidator` — structurally rejected |
| Negative budget amount | `@model_validator` enforces `amount >= 0` |
| Variance math inconsistency | `@model_validator` recomputes and compares |
| Missing evidence chain | `evidence_ids: list[str]` with min length enforcement |
| Closed period posting | `FiscalPeriod.can_post()` check in aggregate service |
| Duplicate period in calendar | `unique_together` constraint at ORM level |
| Orphaned foreign key | ORM `ForeignKey` + `nullable=False` |
| Future-dated transaction in closed period | Temporal invariant at service layer |

### 3.2 Algebraic Type Design

Use Python's type system to encode states:

```python
# Instead of: status: str = "pending"  (any string is valid)

class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    PAID = "paid"
    CANCELLED = "cancelled"

class Invoice(BaseModel):
    status: InvoiceStatus  # Only legal values
```

For mutually exclusive fields:

```python
# Instead of: error: str | None; result: dict | None; both could be set

from typing import Union

class JobOutcome(BaseModel):
    """Discriminated union — exactly one variant is populated."""
    result: HandlerResult | None = None
    error: RuntimeErrorInfo | None = None

    @model_validator(mode="after")
    def mutually_exclusive(self) -> "JobOutcome":
        if self.result is not None and self.error is not None:
            raise ValueError("JobOutcome cannot have both result and error")
        if self.result is None and self.error is None:
            raise ValueError("JobOutcome must have either result or error")
        return self
```

### 3.3 Enriched Model Patterns

Every enriched model follows this structure:

```python
class EnrichedModel(BaseModel):
    # 1. Identity and references
    id: str
    tenant_id: str

    # 2. Domain data (typed, validated)
    ...

    # 3. Status (enum, not string)
    status: SomeStatusEnum

    # 4. Metadata
    created_at: datetime
    updated_at: datetime
    created_by: str | None = None

    # 5. Version (for optimistic concurrency)
    version: int = 1

    # 6. Invariants (model validators)
    @model_validator(mode="after")
    def invariant_name(self) -> "EnrichedModel":
        ...
        return self

    # 7. State transitions (methods, not direct field mutation)
    def transition_to_next_state(self) -> None:
        """Use state machine defined in state-machines.md."""
        ...
```

---

## 4. Audit Policy by Aggregate

| Aggregate | Events to Audit | Retention | Immutable? |
|-----------|----------------|-----------|------------|
| **Identity** | Company created/suspended/archived, COA version change, account closed | 7 years | Yes |
| **Finance** | Budget approved, actuals loaded, variance materiality override | 7 years | Yes |
| **Risk** | Root cause identified, evidence chain modified | 7 years | Yes |
| **Workflow** | Pipeline run, review decision, action state change | 2 years | Yes |
| **Audit** | Policy override, configuration change | 7 years | Yes |
| **Compute** | Job lifecycle, cache clear, export | 90 days | Yes |

---

## 5. Migration Path

### Phase 1 — Add model validators (no structural changes)
Add `@model_validator` methods to existing `Variance`, `BudgetLine`, `RootCauseFinding`, and `Company` models. These are backward-compatible — they reject already-invalid data on construction.

### Phase 2 — Add status enums
Replace `str` status fields with `StrEnum` subclasses. Add state transition methods. Add `company_status` migration to ORM.

### Phase 3 — Add audit metadata
Add `created_at`, `updated_at`, `version`, `created_by` fields to domain models that lack them. Update constructors across the codebase.

### Phase 4 — Add aggregate services
Create aggregate boundary services (`IdentityService`, `FinanceService`, `RiskService`, `WorkflowService`) that enforce cross-model invariants.

---

## 6. Key Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Invariant enforcement | Pydantic `@model_validator` (mode="after") | Catches violations at construction time; no separate validate() call needed |
| State transitions | Methods on the model (not a separate state machine class) | Keeps model self-contained; state machines for complex workflows in `state-machines.md` |
| Status fields | `StrEnum` not plain `str` | Make illegal states unrepresentable; IDE autocompletion |
| Audit policy | Separate policy per aggregate | Different retention and sensitivity requirements per domain |
| Version field | `int` on every model | Enables optimistic concurrency; matches `CommentaryVersion.version` pattern |
| Tenant isolation | `tenant_id: str` on all root entities | Consistent with existing ORM pattern; row-level security |
| Aggregate services | Stateless service classes | Avoid ORM coupling in domain models; services orchestrate persistence |
