"""TDD tests for Phase 5 — Prompt Harness.

Written before implementation. Must fail first.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

# ── Prompt Schemas ───────────────────────────────────────────────────────────


class TestPromptSchemas:
    """Prompt I/O schemas define typed contracts for every prompt type."""

    def test_variance_input_schema(self) -> None:
        """VarianceAnalysisInput requires account_id, period, variance_pct."""
        from finance.prompts.schemas import VarianceAnalysisInput
        inp = VarianceAnalysisInput(
            account_id="4010",
            account_name="Consulting Revenue",
            period_id="2026-07",
            actual_amount=Decimal("520000"),
            budget_amount=Decimal("500000"),
            variance_amount=Decimal("20000"),
            variance_pct=Decimal("4.0"),
            direction="favorable",
            is_material=True,
            materiality_tier="critical",
        )
        assert inp.account_id == "4010"
        assert inp.variance_pct == Decimal("4.0")

    def test_variance_output_schema(self) -> None:
        """VarianceAnalysisOutput has explanation, drivers, confidence."""
        from finance.prompts.schemas import VarianceAnalysisOutput
        out = VarianceAnalysisOutput(
            explanation="Revenue exceeded budget due to higher deal volume.",
            root_causes=["Increased enterprise deal count"],
            impact="+4% revenue vs budget",
            confidence="high",
            evidence_ids=["kpi_revenue_growth", "var_4010"],
        )
        assert out.confidence == "high"
        assert len(out.evidence_ids) == 2

    def test_executive_summary_input_schema(self) -> None:
        """ExecutiveSummaryInput takes aggregated KPIs and variances."""
        from finance.prompts.schemas import ExecutiveSummaryInput
        inp = ExecutiveSummaryInput(
            company_name="Test Corp",
            period_id="2026-07",
            total_revenue=Decimal("1000000"),
            total_expenses=Decimal("850000"),
            net_income=Decimal("150000"),
            kpi_count=5,
            material_variance_count=3,
        )
        assert inp.net_income == Decimal("150000")

    def test_executive_summary_output_schema(self) -> None:
        """ExecutiveSummaryOutput has narrative sections."""
        from finance.prompts.schemas import ExecutiveSummaryOutput
        out = ExecutiveSummaryOutput(
            executive_summary="Strong quarter with 15% net income margin.",
            financial_highlights="Revenue up 8% YoY, expenses controlled.",
            key_risks="Rising COGS may impact Q3 margins.",
            outlook="On track to meet annual targets.",
        )
        assert "Strong quarter" in out.executive_summary

    def test_board_report_input_schema(self) -> None:
        """BoardReportInput takes full context pack data."""
        from finance.prompts.schemas import BoardReportInput
        inp = BoardReportInput(
            company_name="Test Corp",
            period_id="2026-Q2",
            executive_summary="Good quarter.",
            variance_highlights=[],
            kpi_summary={},
            recommendations=[],
            risk_assessment=[],
        )
        assert inp.company_name == "Test Corp"

    def test_schema_rejects_float_for_amounts(self) -> None:
        """Prompt input schemas reject float for monetary fields."""
        from finance.prompts.schemas import VarianceAnalysisInput
        with pytest.raises(ValidationError):
            VarianceAnalysisInput(
                account_id="4010",
                account_name="Revenue",
                period_id="2026-07",
                actual_amount=520000.0,  # float — should be rejected
                budget_amount=500000.0,
                variance_amount=20000.0,
                variance_pct=4.0,
                direction="favorable",
                is_material=True,
            )


# ── Prompt Registry ──────────────────────────────────────────────────────────


class TestPromptRegistry:
    """PromptRegistry manages all prompt templates by name and version."""

    def test_register_prompt(self) -> None:
        """Register a prompt template by name."""
        from finance.prompts.registry import PromptRegistry
        registry = PromptRegistry()
        registry.register(
            name="variance_analysis",
            version="1.0.0",
            template="Analyze variance for {account_name}.",
        )
        assert registry.has("variance_analysis")

    def test_register_duplicate_name_raises(self) -> None:
        """Registering same name twice raises ValueError."""
        from finance.prompts.registry import PromptRegistry
        registry = PromptRegistry()
        registry.register("test", "1.0.0", "template {x}")
        with pytest.raises(ValueError, match="already registered"):
            registry.register("test", "1.0.0", "duplicate")

    def test_get_prompt(self) -> None:
        """Get a registered prompt template by name."""
        from finance.prompts.registry import PromptRegistry
        registry = PromptRegistry()
        registry.register("variance", "1.0.0", "Explain variance for {account}.")
        tmpl = registry.get("variance")
        assert tmpl.template == "Explain variance for {account}."

    def test_get_missing_prompt_raises(self) -> None:
        """Getting unregistered prompt raises KeyError."""
        from finance.prompts.registry import PromptRegistry
        registry = PromptRegistry()
        with pytest.raises(KeyError, match="nonexistent"):
            registry.get("nonexistent")

    def test_list_prompts(self) -> None:
        """List all registered prompt names."""
        from finance.prompts.registry import PromptRegistry
        registry = PromptRegistry()
        registry.register("a", "1.0.0", "a")
        registry.register("b", "1.0.0", "b")
        names = registry.list_names()
        assert "a" in names
        assert "b" in names

    def test_prompt_version_tracking(self) -> None:
        """Prompt metadata includes version, created_at, description."""
        from finance.prompts.registry import PromptRegistry
        registry = PromptRegistry()
        registry.register(
            name="variance",
            version="2.1.0",
            template="Analyze variance for {account} in {period}.",
            description="Variance analysis prompt v2",
        )
        tmpl = registry.get("variance")
        assert tmpl.version == "2.1.0"
        assert tmpl.description == "Variance analysis prompt v2"
        assert tmpl.created_at is not None


# ── Prompt Renderer ──────────────────────────────────────────────────────────


class TestPromptRenderer:
    """PromptRenderer injects variables into templates."""

    def test_render_simple_template(self) -> None:
        """Render replaces {variables} with provided values."""
        from finance.prompts.renderer import PromptRenderer
        renderer = PromptRenderer()
        result = renderer.render(
            template="Analyze variance for {account} in {period}.",
            variables={"account": "4010", "period": "2026-07"},
        )
        assert result == "Analyze variance for 4010 in 2026-07."

    def test_render_missing_variable_raises(self) -> None:
        """Render raises on missing template variable."""
        from finance.prompts.renderer import PromptRenderer
        renderer = PromptRenderer()
        with pytest.raises(ValueError, match="Missing"):
            renderer.render(
                template="Variance for {account} in {period}.",
                variables={"account": "4010"},  # missing 'period'
            )

    def test_render_with_context_injection(self) -> None:
        """Render injects context pack data as template variables."""
        from finance.prompts.renderer import PromptRenderer
        renderer = PromptRenderer()
        result = renderer.render(
            template="Company: {company_name}, Period: {period_id}, KPIs: {kpi_count}",
            variables={
                "company_name": "Test Corp",
                "period_id": "2026-07",
                "kpi_count": "5",
            },
        )
        assert "Test Corp" in result
        assert "2026-07" in result
        assert "5" in result


# ── Execution Context ────────────────────────────────────────────────────────


class TestExecutionContext:
    """ExecutionContext captures metadata about a prompt execution."""

    def test_execution_context_creation(self) -> None:
        """ExecutionContext stores prompt metadata."""
        from finance.prompts.execution_context import ExecutionContext
        ctx = ExecutionContext(
            prompt_name="variance_analysis",
            prompt_version="1.0.0",
            model="llama-3.3-70b",
            provider="groq",
            variables={"account_id": "4010"},
            started_at=datetime.now(),
        )
        assert ctx.prompt_name == "variance_analysis"
        assert ctx.provider == "groq"

    def test_execution_context_completion(self) -> None:
        """ExecutionContext records completion time and token usage."""
        from finance.prompts.execution_context import ExecutionContext
        ctx = ExecutionContext(
            prompt_name="test",
            prompt_version="1.0.0",
            model="test",
            provider="test",
            variables={},
            started_at=datetime.now(),
        )
        ctx.completed_at = datetime.now()
        ctx.token_count = 150
        ctx.latency_ms = 1200
        ctx.success = True
        assert ctx.success is True
        assert ctx.token_count == 150
        assert ctx.latency_ms == 1200


# ── Template Files ───────────────────────────────────────────────────────────


class TestPromptTemplates:
    """Pre-registered prompt templates load correctly."""

    def test_variance_template_exists(self) -> None:
        """variance.py template is registered."""
        import finance.prompts.templates
        from finance.prompts.registry import PromptRegistry
        registry = PromptRegistry()
        finance.prompts.templates.register_all(registry)
        assert registry.has("variance_analysis")

    def test_executive_summary_template_exists(self) -> None:
        """executive_summary.py template is registered."""
        import finance.prompts.templates
        from finance.prompts.registry import PromptRegistry
        registry = PromptRegistry()
        finance.prompts.templates.register_all(registry)
        assert registry.has("executive_summary")

    def test_driver_template_exists(self) -> None:
        """driver.py template is registered."""
        import finance.prompts.templates
        from finance.prompts.registry import PromptRegistry
        registry = PromptRegistry()
        finance.prompts.templates.register_all(registry)
        assert registry.has("driver_investigation")

    def test_recommendation_template_exists(self) -> None:
        """recommendation.py template is registered."""
        import finance.prompts.templates
        from finance.prompts.registry import PromptRegistry
        registry = PromptRegistry()
        finance.prompts.templates.register_all(registry)
        assert registry.has("recommendation")

    def test_board_report_template_exists(self) -> None:
        """board_report.py template is registered."""
        import finance.prompts.templates
        from finance.prompts.registry import PromptRegistry
        registry = PromptRegistry()
        finance.prompts.templates.register_all(registry)
        assert registry.has("board_report")

    def test_risk_template_exists(self) -> None:
        """risk.py template is registered."""
        import finance.prompts.templates
        from finance.prompts.registry import PromptRegistry
        registry = PromptRegistry()
        finance.prompts.templates.register_all(registry)
        assert registry.has("risk_assessment")


# ── Integrated Prompt Execution ──────────────────────────────────────────────


class TestPromptExecution:
    """End-to-end: schema → template → render → output."""

    def test_variance_prompt_full_cycle(self) -> None:
        """Full prompt execution pipeline: input → render → output schema."""
        import finance.prompts.templates
        from finance.prompts.registry import PromptRegistry
        from finance.prompts.renderer import PromptRenderer
        from finance.prompts.schemas import VarianceAnalysisInput, VarianceAnalysisOutput

        registry = PromptRegistry()
        finance.prompts.templates.register_all(registry)
        renderer = PromptRenderer()

        inp = VarianceAnalysisInput(
            account_id="4010",
            account_name="Consulting Revenue",
            period_id="2026-07",
            actual_amount=Decimal("520000"),
            budget_amount=Decimal("500000"),
            variance_amount=Decimal("20000"),
            variance_pct=Decimal("4.0"),
            direction="favorable",
            is_material=True,
            materiality_tier="critical",
        )

        template = registry.get("variance_analysis")
        rendered = renderer.render(template.template, vars(inp))

        assert "Consulting Revenue" in rendered
        assert "4.0%" in rendered or "4.0" in rendered
        assert "favorable" in rendered

        # Output would come from LLM — verify schema at least
        out = VarianceAnalysisOutput(
            explanation="Revenue exceeded budget due to volume.",
            root_causes=["Volume increase"],
            impact="+4%",
            confidence="high",
            evidence_ids=["var_4010"],
        )
        assert isinstance(out, VarianceAnalysisOutput)
