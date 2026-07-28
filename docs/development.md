# Development Guide

This document explains how to extend FinSight with new capabilities. Each section follows a pattern: what you're adding, where it lives, the interface contract, and how to test it.

---

## Table of Contents

- [Adding a New KPI](#adding-a-new-kpi)
- [Adding a New Report](#adding-a-new-report)
- [Adding a New Prompt](#adding-a-new-prompt)
- [Adding a New Validation Rule](#adding-a-new-validation-rule)
- [Adding a New Finance Engine](#adding-a-new-finance-engine)

---

## Adding a New KPI

KPIs are deterministic financial calculations registered in the formula engine.

### Where

```text
finance/formula_engine/formula_registry.py  ← define the Formula object
finance/formula_engine/evaluator.py          ← evaluation context (if needed)
tests/unit/test_finance/test_formula_engine/ ← test your formula
```

### Pattern

```python
# 1. Define the formula function (pure Decimal arithmetic only)
from decimal import Decimal

def _revenue_growth_rate(
    current_revenue: Decimal,
    prior_revenue: Decimal,
) -> Decimal:
    """(Current - Prior) / Prior × 100."""
    if prior_revenue == Decimal("0"):
        return Decimal("0")
    return ((current_revenue - prior_revenue) / prior_revenue) * Decimal("100")


# 2. Create a Formula instance and register it
from finance.formula_engine.formula_registry import Formula, FormulaRegistry

registry = FormulaRegistry()

registry.register(
    Formula(
        name="revenue_growth_rate",
        description="Period-over-period revenue growth rate as a percentage.",
        category="growth",
        inputs=["current_revenue", "prior_revenue"],
        output_name="revenue_growth_rate",
        fn=_revenue_growth_rate,
    )
)

# 3. Evaluate
result = registry.evaluate("revenue_growth_rate", {
    "current_revenue": Decimal("120000"),
    "prior_revenue": Decimal("100000"),
})
# result == Decimal("20.00")
```

### Rules

| Rule | Reason |
|------|--------|
| Every monetary parameter must be `Decimal`, never `float`. | Float rounding corrupts financial calculations. |
| The formula function must be a pure, stateless callable. | Dependencies are resolved by the registry, not by closures. |
| `inputs` must match the callable's keyword arguments exactly. | The registry passes inputs by name. |
| `category` must be one of: `"ratio"`, `"aggregation"`, `"variance"`, `"growth"`, `"margin"`. | Categories enable targeted evaluation and filtering. |

### Testing

```python
# tests/unit/test_finance/test_formula_engine/test_revenue_growth_rate.py
from decimal import Decimal
from finance.formula_engine.formula_registry import FormulaRegistry

class TestRevenueGrowthRate:
    def test_positive_growth(self, registry: FormulaRegistry):
        result = registry.evaluate("revenue_growth_rate", {
            "current_revenue": Decimal("120000"),
            "prior_revenue": Decimal("100000"),
        })
        assert result == Decimal("20.00")

    def test_no_prior_revenue(self, registry: FormulaRegistry):
        result = registry.evaluate("revenue_growth_rate", {
            "current_revenue": Decimal("50000"),
            "prior_revenue": Decimal("0"),
        })
        assert result == Decimal("0")

    def test_declining_revenue(self, registry: FormulaRegistry):
        result = registry.evaluate("revenue_growth_rate", {
            "current_revenue": Decimal("80000"),
            "prior_revenue": Decimal("100000"),
        })
        assert result == Decimal("-20.00")
```

---

## Adding a New Report

Reports combine schemas, context builders, and prompts to produce structured outputs.

### Where

```text
apps/api/schemas.py                           ← report request/response models
finance/reporting/                             ← context builder + prompt
agents/                                        ← agent node (if LLM rendering needed)
tests/unit/test_finance/test_reporting/        ← context builder tests
tests/integration/                             ← end-to-end pipeline tests
```

### Pattern

```text
┌──────────────────┐     ┌───────────────────┐     ┌──────────────────┐
│   ReportSchema   │ ──▶ │  ContextBuilder   │ ──▶ │  PromptTemplate  │
│  (Pydantic I/O)  │     │  (data → context) │     │  (context → LLM) │
└──────────────────┘     └───────────────────┘     └──────────────────┘
                                                           │
                                                           ▼
                                                    ┌──────────────────┐
                                                    │   Validator      │
                                                    │  (LLM output →   │
                                                    │   typed result)  │
                                                    └──────────────────┘
```

#### 1. Define the schema

```python
# apps/api/schemas.py
from pydantic import BaseModel
from decimal import Decimal

class ManagementReportRequest(BaseModel):
    period: str
    tenant_id: str
    sections: list[str]  # e.g. ["executive_summary", "variance_detail"]

class ManagementReportResponse(BaseModel):
    report_id: str
    sections: dict[str, str]  # section_name → rendered markdown
    generated_at: str
```

#### 2. Build the context

```python
# finance/reporting/management_report.py
from decimal import Decimal
from finance.formula_engine.formula_registry import FormulaRegistry

class ManagementReportContext:
    """Collects and structures data needed for the management report prompt."""

    def __init__(self, registry: FormulaRegistry):
        self._registry = registry

    def build(self, period: str, tenant_id: str) -> dict:
        variances = self._fetch_variances(period, tenant_id)
        kpis = self._compute_kpis(variances)
        return {
            "period": period,
            "tenant_id": tenant_id,
            "material_variances": [v for v in variances if v["is_material"]],
            "kpis": kpis,
            "prior_trends": self._fetch_trends(period, tenant_id),
        }
```

#### 3. Create the prompt

```python
# finance/reporting/management_prompt.py
MANAGEMENT_REPORT_PROMPT = """You are a senior FP&A analyst generating a management report.

Period: {period}

## Material Variances
{variance_table}

## Key Metrics
{kpi_table}

## Instructions
1. Write an executive summary covering the top 3 material variances.
2. For each material variance, explain: what changed, by how much, and why.
3. Only use data from the tables above. Do not invent figures.
4. Flag any data quality concerns explicitly.
"""
```

#### 4. Wire the agent node

See the [Adding a New Prompt](#adding-a-new-prompt) section for how to use typed prompts with validation.

### Testing

```python
# tests/unit/test_finance/test_reporting/test_management_report_context.py
class TestManagementReportContext:
    def test_build_returns_expected_keys(self, sample_context):
        result = sample_context.build("2026-Q1", "tenant-abc")
        assert "period" in result
        assert "material_variances" in result
        assert "kpis" in result
```

---

## Adding a New Prompt

Prompts use typed inputs, a render function, and post-generation validation.

### Where

```text
shared/prompts/         ← prompt templates (typed I/O, rendering, validation)
finance/reporting/       ← domain-specific prompts live with their feature
tests/                   ← validation tests
```

### Pattern

```python
# shared/prompts/variance_commentary.py
from pydantic import BaseModel

# ── Typed Input ──────────────────────────────────────────────────────────
class VarianceCommentaryInput(BaseModel):
    account_name: str
    actual_amount: str  # formatted, e.g. "$120,000"
    budget_amount: str
    variance_pct: str
    is_material: bool
    context_notes: list[str] = []

# ── Typed Output (schema for structured generation) ──────────────────────
class VarianceCommentaryOutput(BaseModel):
    explanation: str
    impact: str
    recommended_action: str | None = None

# ── Prompt Template ──────────────────────────────────────────────────────
VARIANCE_COMMENTARY_TEMPLATE = """
Account: {input.account_name}
Actual: {input.actual_amount}
Budget: {input.budget_amount}
Variance: {input.variance_pct}
Material: {input.is_material}
Context: {context}

Write a concise variance explanation. Structure your response as JSON:
{{
  "explanation": "...",
  "impact": "...",
  "recommended_action": "..."
}}
"""

# ── Render ───────────────────────────────────────────────────────────────
def render_variance_commentary(input_data: VarianceCommentaryInput) -> str:
    context = " | ".join(input_data.context_notes) if input_data.context_notes else "None"
    return VARIANCE_COMMENTARY_TEMPLATE.format(
        input=input_data,
        context=context,
    )

# ── Validation ───────────────────────────────────────────────────────────
def validate_variance_commentary(
    raw: str, input_data: VarianceCommentaryInput
) -> VarianceCommentaryOutput | None:
    """Parse and validate the LLM response.
    
    Returns None if validation fails — the caller handles degraded mode.
    """
    import json
    try:
        parsed = json.loads(raw)
        return VarianceCommentaryOutput(**parsed)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
```

### Rules

| Rule | Reason |
|------|--------|
| Every prompt must have typed input and output schemas. | Raw LLM output is not trusted; structured validation gates it. |
| Validation must return `None` on failure, never a partial/invalid result. | Degraded mode handling is explicit. |
| Monetary values in prompts must be formatted strings, never raw `Decimal`. | LLMs handle formatted text better than raw numbers. |

### Testing

```python
# tests/unit/test_shared/test_prompts/test_variance_commentary.py
from decimal import Decimal
from shared.prompts.variance_commentary import (
    VarianceCommentaryInput,
    VarianceCommentaryOutput,
    render_variance_commentary,
    validate_variance_commentary,
)

class TestVarianceCommentary:
    def test_render_includes_all_fields(self):
        inp = VarianceCommentaryInput(
            account_name="Revenue",
            actual_amount="$120,000",
            budget_amount="$100,000",
            variance_pct="+20%",
            is_material=True,
        )
        result = render_variance_commentary(inp)
        assert "Revenue" in result
        assert "$120,000" in result
        assert "+20%" in result

    def test_validate_valid_json(self):
        raw = '{"explanation": "Revenue exceeded budget.", "impact": "Positive", "recommended_action": "Monitor"}'
        inp = VarianceCommentaryInput(
            account_name="Revenue", actual_amount="$120,000",
            budget_amount="$100,000", variance_pct="+20%", is_material=True,
        )
        result = validate_variance_commentary(raw, inp)
        assert isinstance(result, VarianceCommentaryOutput)
        assert result.explanation == "Revenue exceeded budget."

    def test_validate_invalid_json_returns_none(self):
        result = validate_variance_commentary("not json", None)
        assert result is None
```

---

## Adding a New Validation Rule

Validation rules gate data quality and assertion correctness before any LLM call.

### Where

```text
finance/validation/         ← domain-level validation (periods, calendars, data quality)
shared/utils/validators/    ← cross-cutting assertion and claim validation
tests/unit/test_finance/test_validation/
tests/unit/test_shared/test_validators/
```

### Pattern

```python
# finance/validation/cross_period_check.py
from pydantic import BaseModel
from decimal import Decimal
from datetime import date

# ── Rule Input ────────────────────────────────────────────────────────────
class CrossPeriodCheckInput(BaseModel):
    account_id: str
    current_value: Decimal
    prior_value: Decimal
    max_change_pct: Decimal  # e.g. Decimal("50") = 50% max allowed change

# ── Rule Output ───────────────────────────────────────────────────────────
class CrossPeriodCheckResult(BaseModel):
    passed: bool
    account_id: str
    change_pct: Decimal
    message: str

# ── The Rule ──────────────────────────────────────────────────────────────
def check_cross_period_spike(input_data: CrossPeriodCheckInput) -> CrossPeriodCheckResult:
    """Flag accounts where period-over-period change exceeds max_change_pct."""
    if input_data.prior_value == Decimal("0"):
        return CrossPeriodCheckResult(
            passed=True,  # Cannot compute; skip
            account_id=input_data.account_id,
            change_pct=Decimal("0"),
            message="Prior period value is zero; spike check skipped.",
        )

    change_pct = (
        (input_data.current_value - input_data.prior_value)
        / input_data.prior_value
        * Decimal("100")
    )
    passed = abs(change_pct) <= input_data.max_change_pct

    return CrossPeriodCheckResult(
        passed=passed,
        account_id=input_data.account_id,
        change_pct=change_pct,
        message=(
            f"Change of {change_pct:.2f}% "
            f"{'within' if passed else 'exceeds'} "
            f"threshold of {input_data.max_change_pct}%"
        ),
    )
```

### Integration with the Validator Pipeline

Validation rules are composed in the validator that gates pipeline execution:

```python
# finance/validation/validator.py
from finance.validation.cross_period_check import (
    check_cross_period_spike,
    CrossPeriodCheckInput,
    CrossPeriodCheckResult,
)

class PipelineValidator:
    def validate_cross_period(self, variances: list[dict]) -> list[CrossPeriodCheckResult]:
        results = []
        for v in variances:
            result = check_cross_period_spike(CrossPeriodCheckInput(
                account_id=v["account_id"],
                current_value=v["actual_amount"],
                prior_value=v["budget_amount"],
                max_change_pct=Decimal("50"),
            ))
            results.append(result)
        return results
```

### Rules

| Rule | Reason |
|------|--------|
| Every rule must have typed input and output. | Composition and testing depend on clear contracts. |
| Rules must be pure functions (no I/O, no LLM). | Validation must never be the bottleneck. |
| Rules must handle edge cases (zero, None, missing data). | Production data is never clean. |
| A failing rule must never raise — it returns a `passed: False` result. | Validation collects all failures, it does not halt on the first. |

### Testing

```python
# tests/unit/test_finance/test_validation/test_cross_period_check.py
from decimal import Decimal
from finance.validation.cross_period_check import (
    check_cross_period_spike,
    CrossPeriodCheckInput,
)

class TestCrossPeriodSpike:
    def test_normal_change_passes(self):
        result = check_cross_period_spike(CrossPeriodCheckInput(
            account_id="4010",
            current_value=Decimal("110000"),
            prior_value=Decimal("100000"),
            max_change_pct=Decimal("50"),
        ))
        assert result.passed is True

    def test_excessive_change_fails(self):
        result = check_cross_period_spike(CrossPeriodCheckInput(
            account_id="4010",
            current_value=Decimal("200000"),
            prior_value=Decimal("100000"),
            max_change_pct=Decimal("50"),
        ))
        assert result.passed is False

    def test_zero_prior_skips_check(self):
        result = check_cross_period_spike(CrossPeriodCheckInput(
            account_id="4010",
            current_value=Decimal("50000"),
            prior_value=Decimal("0"),
            max_change_pct=Decimal("50"),
        ))
        assert result.passed is True  # skipped gracefully
```

---

## Adding a New Finance Engine

Engines encapsulate deterministic domain logic that operates on financial data.

### Where

```text
finance/<engine_name>/           ← module with __init__.py
  __init__.py
  <engine_name>.py               ← core logic
tests/unit/test_finance/test_<engine_name>/
```

### Pattern

```text
finance/
  scenario_engine/              ← example of a new engine
    __init__.py
    scenario_engine.py           ← core engine class
    models.py                    ← engine-specific data models
    scenario_types.py            ← enums, constants
```

#### 1. Create the module

```python
# finance/scenario_engine/scenario_engine.py
"""Scenario engine — deterministic what-if modelling.

Applies scenario adjustments to base financial data and computes
pro-forma results. No LLM involvement.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

class ScenarioAdjustment(Protocol):
    """A single what-if adjustment. Implementations are pure functions."""
    def apply(self, base_value: Decimal) -> Decimal: ...

@dataclass
class PercentageAdjustment:
    """Adjust a base value by a percentage."""
    label: str
    pct_change: Decimal

    def apply(self, base_value: Decimal) -> Decimal:
        return base_value * (Decimal("1") + self.pct_change / Decimal("100"))

class ScenarioEngine:
    """Orchestrates scenario application across accounts."""

    def run_scenario(
        self,
        base_data: dict[str, Decimal],
        adjustments: dict[str, list[ScenarioAdjustment]],
    ) -> dict[str, Decimal]:
        """Apply scenario adjustments to base data.
        
        Args:
            base_data: account_code → base value
            adjustments: account_code → list of adjustments to apply sequentially
            
        Returns:
            account_code → adjusted value
        """
        result = dict(base_data)
        for account_code, adj_list in adjustments.items():
            if account_code in result:
                for adj in adj_list:
                    result[account_code] = adj.apply(result[account_code])
        return result
```

#### 2. Write the typed interface

The engine must expose a clean public API with typed parameters and return values. Internal details stay private:

```python
# Public API (documented and tested)
__all__ = [
    "ScenarioEngine",
    "ScenarioAdjustment",
    "PercentageAdjustment",
    "AbsoluteAdjustment",  # hypothetical
]
```

#### 3. Write integration tests

```python
# tests/integration/test_scenario_engine.py
from decimal import Decimal
from finance.scenario_engine import ScenarioEngine, PercentageAdjustment

class TestScenarioEngine:
    def test_single_adjustment(self):
        engine = ScenarioEngine()
        base = {"revenue": Decimal("100000")}
        adjustments = {
            "revenue": [PercentageAdjustment("increase 10%", Decimal("10"))],
        }
        result = engine.run_scenario(base, adjustments)
        assert result["revenue"] == Decimal("110000")

    def test_multiple_adjustments_compound(self):
        engine = ScenarioEngine()
        base = {"revenue": Decimal("100000")}
        adjustments = {
            "revenue": [
                PercentageAdjustment("increase 10%", Decimal("10")),
                PercentageAdjustment("decrease 5%", Decimal("-5")),
            ],
        }
        result = engine.run_scenario(base, adjustments)
        # 100000 × 1.10 × 0.95 = 104500
        assert result["revenue"] == Decimal("104500")

    def test_unadjusted_account_passes_through(self):
        engine = ScenarioEngine()
        base = {"revenue": Decimal("100000"), "cogs": Decimal("60000")}
        adjustments = {"revenue": [PercentageAdjustment("up 10%", Decimal("10"))]}
        result = engine.run_scenario(base, adjustments)
        assert result["cogs"] == Decimal("60000")  # unchanged
```

### Rules

| Rule | Reason |
|------|--------|
| Engines must live under `finance/`, not `agents/` or `apps/`. | Finance layer has no dependency on web or AI orchestration. |
| Engines must be pure domain logic — no I/O, no LLM. | Deterministic calculations are the foundation. |
| Engines must accept and return `Decimal` for monetary values. | Float is not allowed anywhere in the financial domain. |
| Engines must raise typed exceptions for error conditions. | Callers need to handle failures predictably. |
| Every engine must have a minimum of one integration test. | Unit tests verify logic; integration tests verify wiring. |

---

## General Guidelines

### Monetary Values

All monetary values use `decimal.Decimal` — never `float`. This is enforced at the API boundary by the `MoneyDecimal` type alias in `apps/api/schemas.py`:

```python
from decimal import Decimal
from typing import Annotated
from pydantic import BeforeValidator

def _reject_float_money(v):
    if isinstance(v, float):
        raise ValueError("Float values are not allowed for monetary fields.")
    return v

MoneyDecimal = Annotated[Decimal, BeforeValidator(_reject_float_money)]
```

### Imports

Follow the layered dependency model:

```python
# Correct
from shared.models.state import PipelineState
from finance.formula_engine import FormulaRegistry
from agents.variance import variance_node

# WRONG — finance must not import apps or agents
from apps.api.schemas import MoneyDecimal  # DO NOT DO THIS
```

### Testing

Every new feature must include tests. See `docs/testing.md` for the full testing strategy.

```bash
# Run all tests
python -m pytest

# Run with coverage
python -m pytest --cov=finance --cov=agents --cov=apps --cov=shared

# Run a specific test class
python -m pytest tests/unit/test_finance/test_formula_engine/test_revenue_growth_rate.py
```

### Documentation

Every new module must have a module-level docstring explaining its purpose. Every public class, function, and method must have a docstring. Complex logic requires inline comments explaining the "why" — not the "what."
