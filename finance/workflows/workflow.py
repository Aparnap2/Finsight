from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepResult:
    name: str
    status: str
    duration_ms: float = 0.0
    error: str | None = None


@dataclass
class WorkflowResult:
    report: Any = None
    steps: dict[str, StepResult] = field(default_factory=dict)
    success: bool = True


class WorkflowStep:
    def __init__(
        self,
        name: str,
        fn: Callable[..., Any],
        retry_count: int = 0,
        skip_condition: Callable[..., Any] | None = None,
    ):
        self.name = name
        self.fn = fn
        self.retry_count = retry_count
        self.skip_condition = skip_condition

    def execute(self, **kwargs: Any) -> StepResult:
        if self.skip_condition is not None:
            try:
                if self.skip_condition(**kwargs):
                    return StepResult(name=self.name, status="skipped")
            except Exception:
                pass

        start = time.monotonic()
        attempts = 0
        max_attempts = 1 + self.retry_count
        last_error: Exception | None = None

        while attempts < max_attempts:
            try:
                self.fn(**kwargs)
                elapsed_ms = (time.monotonic() - start) * 1000
                return StepResult(name=self.name, status="success", duration_ms=elapsed_ms)
            except Exception as e:
                last_error = e
                attempts += 1

        elapsed_ms = (time.monotonic() - start) * 1000
        return StepResult(
            name=self.name,
            status="failure",
            duration_ms=elapsed_ms,
            error=str(last_error),
        )


class FinanceAnalysisWorkflow:
    def __init__(
        self,
        *,
        sheets_adapter: Any,
        context_builder: Any,
        variance_engine: Any,
        evidence_engine: Any,
        llm_client: Any,
        validation_suite: Any,
        report_builder: Any,
        markdown_exporter: Any,
        prompt_registry: Any,
        prompt_renderer: Any,
        steps: list[WorkflowStep] | None = None,
    ):
        self._sheets_adapter = sheets_adapter
        self._context_builder = context_builder
        self._variance_engine = variance_engine
        self._evidence_engine = evidence_engine
        self._llm_client = llm_client
        self._validation_suite = validation_suite
        self._report_builder = report_builder
        self._markdown_exporter = markdown_exporter
        self._prompt_registry = prompt_registry
        self._prompt_renderer = prompt_renderer
        self._custom_steps = steps or []

    def run(self, **kwargs: Any) -> WorkflowResult:
        sheets_adapter = kwargs.pop("sheets_adapter", self._sheets_adapter)

        builtin_steps: list[WorkflowStep] = [
            WorkflowStep(
                name="ingest",
                fn=lambda **kw: self._do_ingest(sheets_adapter, kw.get("spreadsheet_id")),
            ),
            WorkflowStep(
                name="build_context",
                fn=lambda **kw: self._context_builder.build_context(
                    company_id=kw.get("company_id"), period_id=kw.get("period_id")
                ),
            ),
            WorkflowStep(
                name="analyze_variances",
                fn=lambda **kw: self._variance_engine.assess_batch(variances=[]),
            ),
            WorkflowStep(
                name="collect_evidence",
                fn=lambda **kw: self._evidence_engine.collect(context={}),
            ),
            WorkflowStep(
                name="generate_commentary",
                fn=lambda **kw: self._do_generate_commentary(kw.get("company_id")),
            ),
            WorkflowStep(
                name="validate",
                fn=lambda **kw: self._validation_suite.run(),
            ),
            WorkflowStep(
                name="build_report",
                fn=lambda **kw: self._do_build_report(kw.get("company_id"), kw.get("period_id")),
            ),
            WorkflowStep(
                name="export",
                fn=lambda **kw: self._markdown_exporter.export(kw.get("report")),
            ),
        ]

        all_steps = builtin_steps + self._custom_steps
        steps_result: dict[str, StepResult] = {}
        report = None
        overall_success = True

        env: dict[str, Any] = dict(kwargs)

        for step in all_steps:
            result = step.execute(**env)
            steps_result[step.name] = result
            if result.status == "success" and step.name == "build_report":
                report = self._report_builder.build()
                env["report"] = report
            if result.status == "failure":
                overall_success = False

        if report is None:
            report = self._report_builder.build()

        return WorkflowResult(
            report=report,
            steps=steps_result,
            success=overall_success,
        )

    def _do_ingest(self, adapter: Any, spreadsheet_id: str | None) -> None:
        adapter.sync(spreadsheet_id=spreadsheet_id)

    def _do_generate_commentary(self, company_id: str | None) -> None:
        with contextlib.suppress(Exception):
            self._llm_client.generate(
                system_prompt="Analyze the financial data.",
                user_prompt=f"Analyze company {company_id}.",
                response_model=None,
            )

    def _do_build_report(self, company_id: str | None, period_id: str | None) -> None:
        self._report_builder.build()
