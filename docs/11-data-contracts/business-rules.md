# Business Rule Engine Design

> **Layer:** Governance — validation vs. business rules, registration, evaluation, reporting
> **Audience:** Domain engineers, policy architects, compliance reviewers
> **Status:** Design proposal for Phase 2

## 1. Validation vs. Business Rules

This is the most important distinction in the governance architecture. Confusing validation with business rules leads to brittle, hard-to-audit code.

| Dimension | Validation | Business Rules |
|-----------|-----------|----------------|
| **Definition** | Structural/data integrity checks | Domain-specific policy decisions |
| **Example** | "`amount` must be non-null and >= 0" | "Material variances (>10% and >$50K) require CFO review" |
| **Failure mode** | Rejects the data; pipeline blocks | Routes to human; policy decision logged |
| **Recoverability** | Permanent (data is wrong) | Conditional (data is fine, policy changes) |
| **Who changes** | Engineers (schema evolution) | Domain experts / Compliance (policy updates) |
| **Change frequency** | Low (quarterly) | Medium (monthly) |
| **Test approach** | Unit tests with known input/output | Scenario-based approval tests |
| **Location** | Pandera schemas, Pydantic validators | `finance/rules/` directory |
| **Registry** | `SCHEMA_REGISTRY` in `validation/schemas.py` | `RuleRegistry` (proposed below) |
| **Execution** | Before compute (gate) | During compute (policy engine) |

### 1.1 Clear Boundary Rules

| The check... | Is it validation or a business rule? | Why? |
|-------------|--------------------------------------|------|
| `account_id` is non-null | **Validation** | Structural constraint — no record without an account |
| `budget_amount` >= 0 | **Validation** | Financial model constraint — negative budgets are meaningless |
| `currency` is ISO 4217 | **Validation** | Data format constraint |
| Variance > 10% AND > $50K = material | **Business rule** | Materiality thresholds vary by company, industry, and time |
| CAUSAL assertion needs 2+ evidence sources | **Validation** | Evidence sufficiency — structural requirement for causal claims |
| Revenue variance > 5% must be explained | **Business rule** | Policy choice — some companies require 3%, some 10% |
| `period` in `("2026-Q1", "2026-Q2", ...)` | **Validation** | Fixed set of known periods |
| Action "reduce cost" requires manager approval | **Business rule** | Autonomy policy — varies by action type and impact size |
| Data freshness < 90 days | **Business rule** | Staleness threshold — configurable per data source |
| Same `source_fingerprint` → cache hit | **Validation** | Deterministic computation guarantee |

---

## 2. Rule Engine Architecture

```
Compute Pipeline
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│ Business Rule Engine                                         │
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │ RuleRegistry │  │ RuleContext  │  │ RuleEvaluationReport│ │
│  │ - register() │  │ - period     │  │ - passed_rules[]    │ │
│  │ - evaluate() │  │ - tenant_id  │  │ - failed_rules[]    │ │
│  │ - list()     │  │ - entity     │  │ - not_applicable[]  │ │
│  └──────┬──────┘  └──────┬──────┘  │ - policy_decision    │ │
│         │                │          └──────────────────────┘ │
│         ▼                ▼                                    │
│  ┌───────────────────────────────────────────┐                │
│  │  Rule implementations (one per rule)      │                │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐  │                │
│  │  │Materiality│ │Autonomy  │ │Freshness │  │                │
│  │  │Rule       │ │Rule      │ │Rule      │  │                │
│  │  └──────────┘ └──────────┘ └──────────┘  │                │
│  └───────────────────────────────────────────┘                │
└─────────────────────────────────────────────────────────────┘
     │
     ▼
Policy Decision → (auto_approve | route_for_review | escalate_to_cfo)
```

### 2.1 Rule Definition

```python
# finance/rules/base.py (proposed)

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar

T = TypeVar("T")  # The type of entity this rule evaluates


class RuleSeverity(str, Enum):
    """How seriously a rule violation is treated."""
    INFO = "info"           # Informational — no action required
    WARNING = "warning"     # Logged, may trigger degraded mode
    ERROR = "error"         # Blocks execution unless overridden
    CRITICAL = "critical"   # Blocks execution, requires human intervention


class RuleOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


@dataclass
class RuleEvaluation:
    """Result of evaluating a single rule against a context."""
    rule_id: str
    rule_name: str
    outcome: RuleOutcome
    severity: RuleSeverity
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    # Optional: which action to take if this rule fails
    suggested_action: str | None = None


class BaseRule(ABC, Generic[T]):
    """Abstract base for all business rules."""

    rule_id: str
    rule_name: str
    description: str
    severity: RuleSeverity = RuleSeverity.ERROR
    # Category for grouping (materiality, autonomy, freshness, ...)
    category: str = "general"

    @abstractmethod
    def evaluate(self, entity: T, context: RuleContext) -> RuleEvaluation:
        """Evaluate this rule against the given entity and context.
        
        Args:
            entity: The domain entity to evaluate (Variance, Budget, etc.)
            context: Pipeline context (period, tenant_id, degraded_modes)
        
        Returns:
            RuleEvaluation with outcome PASS/FAIL/NOT_APPLICABLE.
        """
        ...
```

### 2.2 Rule Context

```python
# finance/rules/context.py (proposed)

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuleContext:
    """Context passed to every rule evaluation.
    
    Carries all information a rule might need about the current
    pipeline execution environment.
    """
    
    # Identity
    tenant_id: str
    period: str
    
    # Pipeline state
    degraded_modes: list[str] = field(default_factory=list)
    data_quality_score: float = 1.0
    
    # Policy overrides (tenant-specific configuration)
    policy_overrides: dict[str, Any] = field(default_factory=dict)
    
    # Entity-specific context (set by the caller)
    entity_type: str = ""
    entity_id: str = ""
    entity_data: dict[str, Any] = field(default_factory=dict)
```

### 2.3 Rule Registry

```python
# finance/rules/registry.py (proposed)

from __future__ import annotations

from typing import Any

from finance.rules.base import BaseRule, RuleEvaluation, RuleOutcome
from finance.rules.context import RuleContext


class RuleRegistry:
    """Central registry of all business rules.
    
    Rules are evaluated in priority order. Early-failing rules
    with ERROR severity can block further evaluation.
    """
    
    _rules: dict[str, BaseRule] = {}
    _priorities: dict[str, int] = {}
    
    @classmethod
    def register(cls, rule: BaseRule, priority: int = 100) -> None:
        """Register a rule.
        
        Args:
            rule: Rule instance.
            priority: Lower number = evaluated first (default 100).
        """
        cls._rules[rule.rule_id] = rule
        cls._priorities[rule.rule_id] = priority
    
    @classmethod
    def evaluate(
        cls,
        entity: Any,
        context: RuleContext,
        category: str | None = None,
    ) -> list[RuleEvaluation]:
        """Evaluate all registered rules against entity, in priority order.
        
        Args:
            entity: The entity to evaluate.
            context: Rule evaluation context.
            category: Optional filter — only evaluate rules in this category.
        
        Returns:
            List of RuleEvaluation results, in priority order.
        """
        results = []
        
        # Sort rules by priority
        sorted_rules = sorted(
            cls._rules.values(),
            key=lambda r: cls._priorities.get(r.rule_id, 100),
        )
        
        for rule in sorted_rules:
            if category and rule.category != category:
                continue
            
            try:
                result = rule.evaluate(entity, context)
            except Exception as exc:
                result = RuleEvaluation(
                    rule_id=rule.rule_id,
                    rule_name=rule.rule_name,
                    outcome=RuleOutcome.FAIL,
                    severity=RuleSeverity.CRITICAL,
                    message=f"Rule evaluation raised exception: {exc}",
                    details={"error": str(exc)},
                )
            
            results.append(result)
            
            # Early exit on blocking failure
            if (result.outcome == RuleOutcome.FAIL 
                and result.severity in (RuleSeverity.ERROR, RuleSeverity.CRITICAL)):
                break
        
        return results
    
    @classmethod
    def list_rules(cls, category: str | None = None) -> list[dict[str, Any]]:
        """List all registered rules, optionally filtered by category."""
        rules = []
        for rule in cls._rules.values():
            if category and rule.category != category:
                continue
            rules.append({
                "rule_id": rule.rule_id,
                "rule_name": rule.rule_name,
                "description": rule.description,
                "severity": rule.severity.value,
                "category": rule.category,
            })
        return rules
```

---

## 3. Rule Catalog

### 3.1 Materiality Rules

| Rule ID | Name | Severity | Description |
|---------|------|----------|-------------|
| `mat-001` | `AbsoluteThreshold` | WARNING | Variance exceeds absolute threshold (default: $50K) |
| `mat-002` | `PercentageThreshold` | WARNING | Variance exceeds percentage threshold (default: 10%) |
| `mat-003` | `CombinedThreshold` | ERROR | Variance exceeds BOTH absolute AND percentage (material) |
| `mat-004` | `AccountTypeOverride` | WARNING | Revenue variances have lower materiality threshold (5%) |
| `mat-005` | `TrendMateriality` | INFO | Small variance that has been trending for 3+ consecutive periods |

```python
# finance/rules/materiality.py (proposed)

from decimal import Decimal

from finance.rules.base import BaseRule, RuleEvaluation, RuleOutcome, RuleSeverity
from finance.rules.context import RuleContext


class AbsoluteThresholdRule(BaseRule):
    """A variance exceeding the absolute threshold is flagged."""
    
    rule_id = "mat-001"
    rule_name = "Absolute Threshold"
    description = "Variance exceeds absolute dollar threshold"
    severity = RuleSeverity.WARNING
    category = "materiality"
    
    def __init__(self, threshold: Decimal = Decimal("50000")):
        self._threshold = threshold
    
    def evaluate(self, entity: dict, context: RuleContext) -> RuleEvaluation:
        variance_amount = abs(entity.get("variance_amount", 0))
        is_material = variance_amount > self._threshold
        
        # Allow tenant-specific overrides
        threshold = context.policy_overrides.get(
            "materiality_absolute_threshold", self._threshold
        )
        
        if variance_amount > threshold:
            return RuleEvaluation(
                rule_id=self.rule_id,
                rule_name=self.rule_name,
                outcome=RuleOutcome.FAIL,
                severity=self.severity,
                message=f"Variance ${variance_amount:,.2f} exceeds "
                        f"absolute threshold ${threshold:,.2f}",
                details={
                    "variance_amount": str(variance_amount),
                    "threshold": str(threshold),
                    "exceeds_by": str(variance_amount - threshold),
                },
            )
        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            outcome=RuleOutcome.PASS,
            severity=self.severity,
            message="Within absolute threshold",
        )
```

### 3.2 Autonomy Rules

| Rule ID | Name | Severity | Description |
|---------|------|----------|-------------|
| `aut-001` | `DegradedModeGate` | CRITICAL | Pipeline with critical degraded modes must route to human |
| `aut-002` | `ActionImpactReview` | ERROR | Action with impact > $100K requires manager approval |
| `aut-003` | `FirstTimeAction` | WARNING | First action of a type by a tenant requires human review |
| `aut-004` | `CrossEntityAction` | WARNING | Action affecting multiple entities requires consolidation review |
| `aut-005` | `CommentaryAssertionMatch` | ERROR | Commentary assertion must be cited in evidence; mismatch = review |

```python
# finance/rules/autonomy.py (proposed)

CRITICAL_DEGRADED_MODES = {"low_coverage", "stale_source", "missing_fx"}


class DegradedModeGateRule(BaseRule):
    """Pipeline with degraded modes must route to human review."""
    
    rule_id = "aut-001"
    rule_name = "Degraded Mode Gate"
    description = "Critical degraded modes force human review"
    severity = RuleSeverity.CRITICAL
    category = "autonomy"
    
    def evaluate(self, entity: None, context: RuleContext) -> RuleEvaluation:
        active_modes = set(context.degraded_modes)
        critical = active_modes & CRITICAL_DEGRADED_MODES
        
        if critical:
            return RuleEvaluation(
                rule_id=self.rule_id,
                rule_name=self.rule_name,
                outcome=RuleOutcome.FAIL,
                severity=self.severity,
                message=f"Critical degraded modes active: {', '.join(critical)}",
                details={"active_modes": list(critical)},
                suggested_action="route_for_review",
            )
        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.rule_name,
            outcome=RuleOutcome.PASS,
            severity=self.severity,
            message="No critical degraded modes",
        )
```

### 3.3 Freshness Rules

| Rule ID | Name | Severity | Description |
|---------|------|----------|-------------|
| `frs-001` | `DataFreshness` | WARNING | Data older than 90 days is flagged as stale |
| `frs-002` | `SourceLag` | ERROR | Source has not updated in > 30 days |
| `frs-003` | `PeriodCutoff` | ERROR | Data for a closed period must not be from after period end |
| `frs-004` | `ForecastHorizon` | WARNING | Forecast extends beyond 12-month horizon |

### 3.4 Compliance Rules

| Rule ID | Name | Severity | Description |
|---------|------|----------|-------------|
| `cmp-001` | `TaxAccountPosting` | CRITICAL | Tax accounts require auditor review for all postings |
| `cmp-002` | `PeriodCutoffDiscipline` | CRITICAL | Postings to closed periods are prohibited |
| `cmp-003` | `CurrencyConsistency` | ERROR | Cross-currency comparisons must use consistent fx rates |
| `cmp-004` | `MaterialityOverrideAudit` | INFO | Manual override of materiality classification must be logged |

### 3.5 Data Quality Rules

| Rule ID | Name | Severity | Description |
|---------|------|----------|-------------|
| `dqa-001` | `CoverageThreshold` | WARNING | Data coverage below 50% triggers degraded mode |
| `dqa-002` | `RowCountMinimum` | ERROR | Expected row count range check |
| `dqa-003` | `SourceDiversity` | INFO | Single source may miss cross-validation |
| `dqa-004` | `QualityScoreGate` | ERROR | Overall quality score < 0.5 blocks pipeline |

---

## 4. Rule Registration

Rules are registered at application startup:

```python
# finance/rules/__init__.py (proposed)

from finance.rules.registry import RuleRegistry
from finance.rules.materiality import (
    AbsoluteThresholdRule,
    PercentageThresholdRule,
    CombinedThresholdRule,
    AccountTypeOverrideRule,
    TrendMaterialityRule,
)
from finance.rules.autonomy import (
    DegradedModeGateRule,
    ActionImpactReviewRule,
    FirstTimeActionRule,
    CommentaryAssertionMatchRule,
)
from finance.rules.freshness import (
    DataFreshnessRule,
    SourceLagRule,
    PeriodCutoffRule,
)
from finance.rules.compliance import (
    TaxAccountPostingRule,
    PeriodCutoffDisciplineRule,
    CurrencyConsistencyRule,
)
from finance.rules.data_quality import (
    CoverageThresholdRule,
    RowCountMinimumRule,
    SourceDiversityRule,
)


def register_all_rules() -> None:
    """Register every business rule in the engine.
    
    Called once at application startup.
    """
    # Materiality Rules (priority 10-50 — evaluated early)
    RuleRegistry.register(AbsoluteThresholdRule(), priority=10)
    RuleRegistry.register(PercentageThresholdRule(), priority=20)
    RuleRegistry.register(CombinedThresholdRule(), priority=30)
    RuleRegistry.register(AccountTypeOverrideRule(), priority=40)
    RuleRegistry.register(TrendMaterialityRule(), priority=50)
    
    # Autonomy Rules (priority 60-100)
    RuleRegistry.register(DegradedModeGateRule(), priority=60)
    RuleRegistry.register(ActionImpactReviewRule(), priority=70)
    RuleRegistry.register(FirstTimeActionRule(), priority=80)
    RuleRegistry.register(CommentaryAssertionMatchRule(), priority=90)
    
    # Freshness Rules (priority 110-140)
    RuleRegistry.register(DataFreshnessRule(), priority=110)
    RuleRegistry.register(SourceLagRule(), priority=120)
    RuleRegistry.register(PeriodCutoffRule(), priority=130)
    
    # Compliance Rules (priority 200+ — evaluated last)
    RuleRegistry.register(TaxAccountPostingRule(), priority=200)
    RuleRegistry.register(PeriodCutoffDisciplineRule(), priority=210)
    RuleRegistry.register(CurrencyConsistencyRule(), priority=220)
    
    # Data Quality Rules
    RuleRegistry.register(CoverageThresholdRule(), priority=300)
    RuleRegistry.register(RowCountMinimumRule(), priority=310)
    RuleRegistry.register(SourceDiversityRule(), priority=320)
```

---

## 5. Integration with Assertion Pipeline

The business rule engine integrates with the assertion pipeline at two points:

### 5.1 During Assertion Construction

```python
# In assertion_pipeline.py — after initial assertion generation

from finance.rules.registry import RuleRegistry
from finance.rules.context import RuleContext

def enrich_assertions_with_rules(
    assertions: list[Assertion],
    context: RuleContext,
) -> list[Assertion]:
    """Evaluate business rules and attach policy decisions to assertions."""
    
    for assertion in assertions:
        # Evaluate relevant rules
        results = RuleRegistry.evaluate(assertion, context)
        
        # Check if any CRITICAL rule failed
        failures = [r for r in results if r.outcome == "fail"]
        critical_failures = [r for r in failures 
                             if r.severity in ("error", "critical")]
        
        if critical_failures:
            assertion.max_allowed_action = "route_for_review"
        
        # Record rule evaluations in assertion metadata
        assertion.metadata["rule_evaluations"] = [
            {
                "rule_id": r.rule_id,
                "outcome": r.outcome.value,
                "message": r.message,
            }
            for r in results
        ]
    
    return assertions
```

### 5.2 During Policy Evaluation

```python
# In policy_evaluation.py

def evaluate_from_pipeline_result(
    result: PipelineResult,
    context: RuleContext,
) -> PolicyDecision:
    """Evaluate all business rules and determine routing policy."""
    
    # Evaluate autonomy rules
    autonomy_results = RuleRegistry.evaluate(
        entity=None,
        context=context,
        category="autonomy",
    )
    
    # Determine autonomy level from results
    has_critical = any(
        r.outcome == "fail" and r.severity in ("error", "critical")
        for r in autonomy_results
    )
    
    if has_critical:
        return PolicyDecision(
            autonomy_level="manager_approval",
            routing_target="manager_review",
            reasons=[r.message for r in autonomy_results if r.outcome == "fail"],
        )
    
    return PolicyDecision(
        autonomy_level="auto_approve",
        routing_target="auto_publish",
        reasons=[],
    )
```

---

## 6. Rule Evaluation Report

Every rule evaluation produces a structured report that is persisted in `PolicyDecisionLog`:

```python
# finance/rules/report.py (proposed)

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RuleEvaluationReport:
    """Complete report of a rule evaluation session.
    
    Persisted to PolicyDecisionLog for audit.
    """
    
    # Evaluation metadata
    evaluated_at: datetime
    entity_type: str
    entity_id: str
    tenant_id: str
    period: str
    
    # Results
    total_rules: int
    passed: int
    failed: int
    not_applicable: int
    
    # Blocking failure info
    has_blocking_failure: bool
    blocking_rule_id: str | None = None
    blocking_message: str | None = None
    
    # All evaluations
    evaluations: list[dict[str, Any]] = field(default_factory=list)
    
    # Computed policy
    suggested_autonomy_level: str = "auto_approve"
    suggested_routing: str = "auto_publish"
```

---

## 7. Directory Structure

```
finance/rules/
├── __init__.py              # register_all_rules()
├── base.py                  # BaseRule, RuleEvaluation, RuleOutcome, RuleSeverity
├── registry.py              # RuleRegistry
├── context.py               # RuleContext
├── report.py                # RuleEvaluationReport
├── materiality.py           # AbsoluteThresholdRule, PercentageThresholdRule, etc.
├── autonomy.py              # DegradedModeGateRule, ActionImpactReviewRule, etc.
├── freshness.py             # DataFreshnessRule, SourceLagRule, etc.
├── compliance.py            # TaxAccountPostingRule, PeriodCutoffDisciplineRule, etc.
├── data_quality.py          # CoverageThresholdRule, RowCountMinimumRule, etc.
└── tests/
    ├── test_materiality_rules.py
    ├── test_autonomy_rules.py
    ├── test_freshness_rules.py
    └── test_compliance_rules.py
```

---

## 8. Key Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Rule definition | Abstract base class, not protocol | All rules share common metadata; ABC enforces `evaluate()` signature |
| Registry pattern | Central singleton, not dependency injection | Rules are application-wide; no per-test rule swapping needed |
| Priority ordering | Integer, lower = first | Simple, explicit, easy to debug |
| Early exit | On ERROR/CRITICAL failure | Prevents cascading failures; most important rules run first |
| Error handling | Caught per-rule, never crashes engine | One misbehaving rule does not break all rules |
| Context object | Dataclass, expanded by caller | Single source of truth for evaluation environment |
| Audit trail | Full report persisted to DB | Every rule decision is traceable; supports compliance review |
| Tenant overrides | `context.policy_overrides` dict | No rule subclassing needed for tenant-specific thresholds |
