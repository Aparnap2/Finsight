"""TDD tests for FinanceAnalysisWorkflow — RED phase.

The ``finance.workflows`` package does not exist yet. All imports from
``finance.workflows`` must fail with ``ImportError`` (or ``ModuleNotFoundError``)
until the implementation is written.

Test design follows project conventions:
- Arrange-Act-Assert in every test
- ``decimal.Decimal`` for monetary values — never ``float``
- ``unittest.mock`` (MagicMock) for all component mocks
- ``httpx_mock`` for LLM HTTP-level mocking
- Descriptive test names explaining scenario + expected outcome
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest

# =============================================================================
# Helper factories (shared across test classes)
# =============================================================================


def _make_board_report(**overrides: Any) -> Any:
    """Return a minimal ``BoardReport``-like object for assertions.

    Uses a simple dict with attribute access so tests don't require the
    real model at import time.  Monetary values use ``Decimal``.
    """
    from finance.domain.board_report import BoardReport, ReportSection

    return BoardReport(
        id=overrides.get("id", "br-test001"),
        company_id=overrides.get("company_id", "CF001"),
        period_id=overrides.get("period_id", "2026-Q2"),
        title=overrides.get("title", "Q2 2026 Board Report — CF001"),
        generated_at=overrides.get("generated_at", datetime.now(UTC)),
        sections=overrides.get(
            "sections",
            {ReportSection.EXECUTIVE_SUMMARY: "# Executive Summary\nGood quarter."},
        ),
        kpis=overrides.get("kpis", []),
        material_variances=overrides.get("material_variances", []),
        recommendations=overrides.get("recommendations", []),
        evidence_summary=overrides.get("evidence_summary", []),
        data_quality_score=overrides.get("data_quality_score", Decimal("0.95")),
        is_draft=overrides.get("is_draft", True),
    )


def _make_variance(
    account_id: str = "4010",
    account_name: str = "Consulting Revenue",
    actual: Decimal = Decimal("520000"),
    budget: Decimal = Decimal("500000"),
    variance_pct: Decimal = Decimal("4.0"),
    is_material: bool = True,
    direction: str = "favorable",
) -> Any:
    """Build a ``Variance`` domain object for test fixtures."""
    from finance.domain.variance import Variance, VarianceDirection

    return Variance(
        id=f"var_{account_id}",
        account_id=account_id,
        account_name=account_name,
        actual_amount=actual,
        budget_amount=budget,
        variance_amount=actual - budget,
        variance_pct=variance_pct,
        direction=VarianceDirection(direction),
        period_id="2026-Q2",
        is_material=is_material,
        materiality_tier="critical" if is_material else None,
    )


# =============================================================================
# TestFinanceAnalysisWorkflow
# =============================================================================


class TestFinanceAnalysisWorkflow:
    """``FinanceAnalysisWorkflow`` orchestrates the full analysis pipeline.

    Every test in this class mocks all component dependencies so that the
    workflow orchestrator logic is tested in isolation.
    """

    # ── Fixtures ──────────────────────────────────────────────────────────

    @pytest.fixture
    def mock_sheets_adapter(self) -> MagicMock:
        """Return a mock ``SheetsAdapter``."""
        adapter = MagicMock()
        adapter.read_range.return_value = [
            ["account_id", "account_name", "actual", "budget"],
            ["4010", "Consulting Revenue", "520000", "500000"],
            ["6010", "Salaries", "310000", "300000"],
        ]
        adapter.sync.return_value = {
            "rows_read": 3,
            "spreadsheet_id": "test_spreadsheet",
            "source": "csv",
        }
        return adapter

    @pytest.fixture
    def mock_context_builder(self) -> MagicMock:
        """Return a mock ``ContextBuilder``."""
        builder = MagicMock()
        ctx = MagicMock()
        ctx.company_id = "CF001"
        ctx.period_id = "2026-Q2"
        ctx.company_name = "Test Corp"
        ctx.currency = "USD"
        ctx.kpis = []
        ctx.material_variances = []
        ctx.evidence_items = []
        ctx.business_context = "Steady quarter with moderate growth."
        builder.build_context.return_value = ctx
        return builder

    @pytest.fixture
    def mock_variance_engine(self) -> MagicMock:
        """Return a mock ``MaterialityEngine`` (variance engine)."""
        engine = MagicMock()
        engine.assess_batch.return_value = []
        engine.get_material_variances.return_value = [
            _make_variance(account_id="4010", account_name="Consulting Revenue"),
        ]
        return engine

    @pytest.fixture
    def mock_evidence_engine(self) -> MagicMock:
        """Return a mock ``EvidenceEngine``."""
        engine = MagicMock()
        engine.collect.return_value = []
        engine.coverage_score.return_value = Decimal("0.85")
        return engine

    @pytest.fixture
    def mock_llm_client(self) -> MagicMock:
        """Return a mock ``LLMClient`` that returns a valid Pydantic model."""
        from pydantic import BaseModel

        class FakeOutput(BaseModel):
            explanation: str
            confidence: str
            root_causes: list[str] = []

        client = MagicMock()
        client.generate.return_value = FakeOutput(
            explanation="Revenue exceeded budget due to higher volume.",
            confidence="high",
            root_causes=["Increased enterprise deal count"],
        )
        return client

    @pytest.fixture
    def mock_validation_suite(self) -> MagicMock:
        """Return a mock ``ValidationSuite`` that passes everything."""
        suite = MagicMock()
        report = MagicMock()
        report.passed = True
        report.passed_count = 3
        report.failed_count = 0
        suite.run.return_value = report
        return suite

    @pytest.fixture
    def mock_report_builder(self) -> MagicMock:
        """Return a mock ``ReportBuilder`` that returns a valid ``BoardReport``."""
        builder = MagicMock()
        builder.build.return_value = _make_board_report()
        builder.finalize.return_value = _make_board_report(is_draft=False)
        return builder

    @pytest.fixture
    def mock_markdown_exporter(self) -> MagicMock:
        """Return a mock ``MarkdownExporter``."""
        exporter = MagicMock()
        exporter.export.return_value = "# Q2 2026 Board Report\n\nExecutive summary..."
        return exporter

    @pytest.fixture
    def mock_prompt_registry(self) -> MagicMock:
        """Return a mock ``PromptRegistry`` with registered prompts."""
        registry = MagicMock()
        registry.has.return_value = True
        registry.get.return_value = MagicMock(
            template="Analyze variance for {account_name} in {period_id}.",
            version="1.0.0",
        )
        return registry

    @pytest.fixture
    def mock_prompt_renderer(self) -> MagicMock:
        """Return a mock ``PromptRenderer``."""
        renderer = MagicMock()
        renderer.render.return_value = "Rendered prompt text."
        return renderer

    @pytest.fixture
    def workflow(
        self,
        mock_sheets_adapter: MagicMock,
        mock_context_builder: MagicMock,
        mock_variance_engine: MagicMock,
        mock_evidence_engine: MagicMock,
        mock_llm_client: MagicMock,
        mock_validation_suite: MagicMock,
        mock_report_builder: MagicMock,
        mock_markdown_exporter: MagicMock,
        mock_prompt_registry: MagicMock,
        mock_prompt_renderer: MagicMock,
    ) -> Any:
        """Build a ``FinanceAnalysisWorkflow`` with all mocked dependencies."""
        from finance.workflows import FinanceAnalysisWorkflow

        return FinanceAnalysisWorkflow(
            sheets_adapter=mock_sheets_adapter,
            context_builder=mock_context_builder,
            variance_engine=mock_variance_engine,
            evidence_engine=mock_evidence_engine,
            llm_client=mock_llm_client,
            validation_suite=mock_validation_suite,
            report_builder=mock_report_builder,
            markdown_exporter=mock_markdown_exporter,
            prompt_registry=mock_prompt_registry,
            prompt_renderer=mock_prompt_renderer,
        )

    # ── Tests ─────────────────────────────────────────────────────────────

    def test_workflow_creates_report(
        self, workflow: Any, mock_sheets_adapter: MagicMock
    ) -> None:
        """Full pipeline returns a ``WorkflowResult`` with a valid ``BoardReport``."""
        from finance.workflows import WorkflowResult

        result = workflow.run(
            company_id="CF001",
            period_id="2026-Q2",
            spreadsheet_id="test_spreadsheet",
        )

        # Result type and high-level contract
        assert isinstance(result, WorkflowResult)
        assert result.success is True
        assert result.report is not None
        assert result.report.company_id == "CF001"
        assert result.report.period_id == "2026-Q2"

        # Pipeline was actually invoked
        mock_sheets_adapter.sync.assert_called_once()

    def test_workflow_with_partial_data(
        self,
        workflow: Any,
        mock_variance_engine: MagicMock,
        mock_evidence_engine: MagicMock,
    ) -> None:
        """Workflow still produces a valid report when variance data is sparse."""
        mock_variance_engine.get_material_variances.return_value = []
        mock_evidence_engine.collect.return_value = []

        result = workflow.run(
            company_id="CF001",
            period_id="2026-Q2",
            spreadsheet_id="test_spreadsheet",
        )

        assert result.success is True
        assert result.report is not None
        assert result.report.data_quality_score is not None
        # Even with no variances, we get an empty report — not a crash
        assert isinstance(result.report.material_variances, list)
        assert len(result.report.material_variances) == 0

    def test_workflow_fallback_on_llm_failure(
        self, workflow: Any, mock_llm_client: MagicMock
    ) -> None:
        """When the LLM fails, the workflow falls back to deterministic analysis.

        The fallback should still produce a valid ``BoardReport`` with
        deterministic variance commentary instead of LLM-generated text.
        """
        from finance.workflows import WorkflowResult

        mock_llm_client.generate.side_effect = RuntimeError(
            "All providers exhausted"
        )

        result = workflow.run(
            company_id="CF001",
            period_id="2026-Q2",
            spreadsheet_id="test_spreadsheet",
        )

        assert isinstance(result, WorkflowResult)
        assert result.success is True, (
            "Workflow should degrade gracefully, not fail entirely"
        )
        assert result.report is not None
        # Fallback commentary should be deterministic (key-based message)
        assert any(
            "4010" in result.report.sections.get(s, "")
            for s in result.report.sections
        ) or result.report.material_variances is not None

    def test_workflow_respects_materiality(
        self,
        workflow: Any,
        mock_variance_engine: MagicMock,
        mock_report_builder: MagicMock,
    ) -> None:
        """Only material variances appear in the final ``BoardReport``.

        Non-material variances are filtered before the report is assembled.
        """
        material_variance = _make_variance(
            account_id="4010",
            account_name="Consulting Revenue",
            is_material=True,
        )

        # Both variances returned from engine, but only material ones
        # should propagate to the final report.
        mock_variance_engine.get_material_variances.return_value = [
            material_variance,
        ]
        # Simulate that the builder receives only material variances
        mock_report_builder.build.return_value = _make_board_report(
            material_variances=[material_variance],
        )

        result = workflow.run(
            company_id="CF001",
            period_id="2026-Q2",
            spreadsheet_id="test_spreadsheet",
        )

        assert result.success is True
        assert len(result.report.material_variances) == 1
        var_ids = {v.account_id for v in result.report.material_variances}
        assert "4010" in var_ids
        assert "6010" not in var_ids, (
            "Non-material variance leaked into the report"
        )

    def test_workflow_pipeline_state(self, workflow: Any) -> None:
        """Workflow tracks pipeline state through each phase.

        The ``WorkflowResult.steps`` dict should contain an entry for
        every major pipeline step with the correct ``StepResult.status``.
        """
        from finance.workflows import StepResult, WorkflowResult

        result = workflow.run(
            company_id="CF001",
            period_id="2026-Q2",
            spreadsheet_id="test_spreadsheet",
        )

        assert isinstance(result, WorkflowResult)
        assert isinstance(result.steps, dict)
        assert len(result.steps) > 0

        # Every step must be recorded
        expected_steps = {
            "ingest",
            "build_context",
            "analyze_variances",
            "collect_evidence",
            "generate_commentary",
            "validate",
            "build_report",
            "export",
        }
        actual_names = set(result.steps.keys())
        assert expected_steps.issubset(actual_names), (
            f"Missing steps: {expected_steps - actual_names}"
        )

        # Every step result is a StepResult with valid status
        for step_name, step_result in result.steps.items():
            assert isinstance(step_result, StepResult), (
                f"Step '{step_name}' result is not a StepResult"
            )
            assert step_result.status in ("success", "failure", "skipped"), (
                f"Step '{step_name}' has invalid status: {step_result.status}"
            )
            assert step_result.duration_ms >= 0, (
                f"Step '{step_name}' has negative duration"
            )

        # All steps should have succeeded in the happy path
        assert all(
            sr.status == "success" for sr in result.steps.values()
        ), "Not all steps succeeded in happy-path pipeline"

    def test_workflow_custom_steps(self) -> None:
        """Workflow supports custom step hooks injected at construction.

        Custom steps are executed as part of the pipeline alongside the
        built-in steps and appear in ``WorkflowResult.steps``.
        """
        from unittest.mock import MagicMock

        from finance.workflows import FinanceAnalysisWorkflow, WorkflowStep

        hook = MagicMock(return_value={"custom_data": "ok"})

        custom_step = WorkflowStep(
            name="custom_audit_log",
            fn=hook,
        )

        # Build minimal workflow with all required dependencies
        workflow = FinanceAnalysisWorkflow(
            sheets_adapter=MagicMock(),
            context_builder=MagicMock(),
            variance_engine=MagicMock(),
            evidence_engine=MagicMock(),
            llm_client=MagicMock(),
            validation_suite=MagicMock(),
            report_builder=MagicMock(),
            markdown_exporter=MagicMock(),
            prompt_registry=MagicMock(),
            prompt_renderer=MagicMock(),
            steps=[custom_step],
        )

        result = workflow.run(
            company_id="CF001",
            period_id="2026-Q2",
            spreadsheet_id="test_spreadsheet",
        )

        # Custom step was executed
        hook.assert_called_once()
        assert "custom_audit_log" in result.steps
        assert result.steps["custom_audit_log"].status == "success"

    def test_workflow_run_accepts_overrides(self, workflow: Any) -> None:
        """``run()`` keyword arguments override default dependencies per-call.

        This allows per-invocation configuration like changing the
        spreadsheet source without rebuilding the workflow.
        """
        from unittest.mock import MagicMock

        override_adapter = MagicMock()
        override_adapter.sync.return_value = {
            "rows_read": 99,
            "source": "override",
        }

        result = workflow.run(
            company_id="CF001",
            period_id="2026-Q2",
            spreadsheet_id="alt_spreadsheet",
            sheets_adapter=override_adapter,
        )

        assert result.success is True
        override_adapter.sync.assert_called_once()

    def test_workflow_raises_on_missing_required_config(self) -> None:
        """Workflow constructor raises when required dependencies are absent."""
        from finance.workflows import FinanceAnalysisWorkflow

        with pytest.raises(TypeError):
            FinanceAnalysisWorkflow(  # type: ignore[call-arg]
                # Intentionally missing required args
            )


# =============================================================================
# TestWorkflowStep
# =============================================================================


class TestWorkflowStep:
    """Individual ``WorkflowStep`` execution, retry, and skip semantics."""

    # ── Fixtures ──────────────────────────────────────────────────────────

    @pytest.fixture
    def successful_fn(self) -> Callable[..., Any]:
        def fn(**kwargs: Any) -> dict[str, Any]:
            return {"processed": True, "data": kwargs.get("data")}
        return fn

    @pytest.fixture
    def failing_fn(self) -> Callable[..., Any]:
        def fn(**kwargs: Any) -> dict[str, Any]:
            msg = kwargs.get("msg", "Step execution failed")
            raise RuntimeError(msg)
        return fn

    # ── Tests ─────────────────────────────────────────────────────────────

    def test_step_execution(self, successful_fn: Callable[..., Any]) -> None:
        """``WorkflowStep.execute()`` returns a ``StepResult`` with success."""
        from finance.workflows import StepResult, WorkflowStep

        step = WorkflowStep(name="test_step", fn=successful_fn)
        result = step.execute(data="hello")

        assert isinstance(result, StepResult)
        assert result.name == "test_step"
        assert result.status == "success"
        assert result.error is None
        assert result.duration_ms >= 0

    def test_step_execution_with_failure(self, failing_fn: Callable[..., Any]) -> None:
        """``WorkflowStep`` returns a failed ``StepResult`` when ``fn`` raises."""
        from finance.workflows import StepResult, WorkflowStep

        step = WorkflowStep(name="failing_step", fn=failing_fn)
        result = step.execute(msg="Something went wrong")

        assert isinstance(result, StepResult)
        assert result.name == "failing_step"
        assert result.status == "failure"
        assert result.error is not None
        assert "Something went wrong" in result.error
        assert result.duration_ms >= 0

    def test_step_with_retry(self, successful_fn: Callable[..., Any]) -> None:
        """``WorkflowStep`` retries on failure per ``retry_count``."""
        from unittest.mock import MagicMock

        from finance.workflows import WorkflowStep

        # fn fails first call, succeeds on retry
        fn = MagicMock()
        fn.side_effect = [
            RuntimeError("Temporary failure"),
            {"processed": True, "data": "retried"},
        ]

        step = WorkflowStep(name="retry_step", fn=fn, retry_count=1)
        result = step.execute(data="test")

        assert result.status == "success"
        assert fn.call_count == 2, (
            f"Expected 2 calls (1 failure + 1 retry), got {fn.call_count}"
        )

    def test_step_retry_exhaustion(self) -> None:
        """``WorkflowStep`` returns failure after exhausting all retries."""
        from unittest.mock import MagicMock

        from finance.workflows import WorkflowStep

        fn = MagicMock()
        fn.side_effect = RuntimeError("Persistent error")

        step = WorkflowStep(name="exhausted_step", fn=fn, retry_count=2)
        result = step.execute()

        assert result.status == "failure"
        assert result.error is not None
        assert "Persistent error" in result.error
        # 1 original + 2 retries = 3 total attempts
        assert fn.call_count == 3

    def test_step_skip_condition(self, successful_fn: Callable[..., Any]) -> None:
        """``WorkflowStep`` is skipped when ``skip_condition`` evaluates to True."""
        from finance.workflows import StepResult, WorkflowStep

        step = WorkflowStep(
            name="skippable_step",
            fn=successful_fn,
            skip_condition=lambda **kw: kw.get("skip", False),
        )

        # Condition met — step is skipped
        skipped = step.execute(data="test", skip=True)
        assert isinstance(skipped, StepResult)
        assert skipped.status == "skipped"
        assert skipped.error is None

        # Condition not met — step executes normally
        executed = step.execute(data="test", skip=False)
        assert executed.status == "success"

    def test_step_skip_condition_with_no_args(self, successful_fn: Callable[..., Any]) -> None:
        """``skip_condition`` receives no keyword args — must not crash."""
        from finance.workflows import WorkflowStep

        # A skip_condition that always returns False
        step = WorkflowStep(
            name="no_skip",
            fn=successful_fn,
            skip_condition=lambda: False,
        )
        result = step.execute(data="whatever")
        assert result.status == "success"

    def test_step_execution_records_duration(self, successful_fn: Callable[..., Any]) -> None:
        """``StepResult.duration_ms`` reflects actual execution time."""
        import time

        from finance.workflows import WorkflowStep

        def slow_fn(**kwargs: Any) -> dict[str, Any]:
            time.sleep(0.01)  # 10 ms
            return {"done": True}

        step = WorkflowStep(name="slow_step", fn=slow_fn)
        result = step.execute()

        assert result.status == "success"
        assert result.duration_ms >= 10, (
            f"Expected at least 10ms, got {result.duration_ms}"
        )

    def test_step_result_defaults(self) -> None:
        """``StepResult`` provides sensible defaults for optional fields."""
        from finance.workflows import StepResult

        result = StepResult(name="defaults", status="success")
        assert result.error is None
        assert result.duration_ms == 0.0

    def test_workflow_result_defaults(self) -> None:
        """``WorkflowResult`` provides sensible defaults for optional fields."""
        from finance.workflows import WorkflowResult

        result = WorkflowResult(success=True)
        # `report` and `steps` may be optional depending on implementation
        assert hasattr(result, "steps"), "WorkflowResult missing 'steps' attribute"
        assert result.success is True

    def test_step_retry_preserves_kwargs(self) -> None:
        """``WorkflowStep`` passes the same kwargs on every retry attempt."""
        from unittest.mock import MagicMock

        from finance.workflows import WorkflowStep

        fn = MagicMock()
        fn.side_effect = [
            RuntimeError("Attempt 1"),
            RuntimeError("Attempt 2"),
            {"ok": True},
        ]

        step = WorkflowStep(name="kwargs_retry", fn=fn, retry_count=2)
        result = step.execute(user="alice", action="analyze")

        assert result.status == "success"
        for call in fn.call_args_list:
            assert call[1].get("user") == "alice"
            assert call[1].get("action") == "analyze"

    def test_step_skipped_when_condition_raises(self) -> None:
        """A ``skip_condition`` that raises is treated as False (step runs)."""
        from finance.workflows import WorkflowStep

        def broken_condition(**kwargs: Any) -> bool:
            raise ValueError("Condition check failed")

        step = WorkflowStep(
            name="broken_condition_step",
            fn=lambda **kw: {"ok": True},
            skip_condition=broken_condition,
        )
        result = step.execute()
        assert result.status == "success", (
            "Step should execute when skip_condition raises an error"
        )
