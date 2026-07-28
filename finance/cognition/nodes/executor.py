"""Executor cognitive node.

Replaces the old ToolRouterNode.  Reads the ActionPlan from state and
routes each action to the appropriate deterministic engine (materiality,
formula evaluation, evidence collection, validation).  Records action
traces with timing and status for downstream verification and telemetry.
"""

from __future__ import annotations

from decimal import Decimal
from time import perf_counter
from typing import TYPE_CHECKING, Any

from finance.cognition.state.action import ActionStatus
from finance.cognition.state.models import ReasoningState
from finance.cognition.state.node import NodeResult
from shared.models.assertions import Assertion, AssertionType, SupportLevel

if TYPE_CHECKING:
    from finance.evidence.engine import EvidenceEngine
    from finance.formula_engine.evaluator import FormulaEvaluator
    from finance.validation.harness import ValidationSuite
    from finance.variance_engine.materiality import MaterialityEngine


class ExecutorNode:
    """Execute actions in the ActionPlan by routing them to deterministic engines.

    Each action is dispatched based on keywords in its ``objective``:

    * ``variance`` → MaterialityEngine
    * ``kpi`` or ``performance`` → FormulaEvaluator
    * ``evidence`` or ``supporting`` → EvidenceEngine
    * Any action → ValidationSuite

    When an engine is not injected its route is silently skipped.
    """

    def __init__(
        self,
        materiality_engine: MaterialityEngine | None = None,
        formula_evaluator: FormulaEvaluator | None = None,
        evidence_engine: EvidenceEngine | None = None,
        validation_suite: ValidationSuite | None = None,
    ) -> None:
        from finance.evidence.engine import EvidenceEngine
        from finance.validation.harness import ValidationSuite
        from finance.variance_engine.materiality import MaterialityEngine

        self._materiality = materiality_engine or MaterialityEngine()
        self._formula_evaluator = formula_evaluator
        self._evidence = evidence_engine or EvidenceEngine()
        self._validation = validation_suite or ValidationSuite()

    def execute(self, state: ReasoningState) -> NodeResult:
        plan = state.action_plan

        # ── Empty plan ────────────────────────────────────────────────────
        if plan is None or not plan.actions:
            return NodeResult(
                node_name="executor",
                success=True,
                state_updates={"plan_status": "no_actions"},
            )

        assertions: list[Assertion] = []
        action_traces: list[dict[str, Any]] = []
        messages: list[str] = []

        for action in plan.actions:
            started_at = perf_counter()

            action_trace: dict[str, Any] = {
                "action_id": action.id,
                "objective": action.objective,
                "tool": "",
                "status": "pending",
                "latency_ms": 0.0,
                "retries": action.retry_count,
                "assertion_count": 0,
                "evidence_count": 0,
                "validation_status": "unchecked",
                "error": "",
            }

            try:
                obj = action.objective.lower()

                # ── Variance route ────────────────────────────────────
                if "variance" in obj:
                    action_trace["tool"] = "variance_engine"
                    raw_variances = state.context.get("variances", [])
                    if raw_variances:
                        assessments = self._materiality.assess_batch(raw_variances)
                        action.outputs["assessments"] = [
                            a.model_dump() for a in assessments
                        ]
                        action_trace["assertion_count"] = len(assessments)
                        for a in assessments:
                            pct = abs(a.variance_pct)
                            assertions.append(
                                Assertion(
                                    id=f"mat_{a.variance_id}",
                                    type=AssertionType.NUMERIC,
                                    text=(
                                        f"Variance {a.variance_id} is "
                                        f"{'material' if a.is_material else 'not material'} "
                                        f"({pct:.2f}%)"
                                    ),
                                    value=a.variance_abs,
                                    confidence=0.9,
                                    support_level=(
                                        SupportLevel.VERIFIED
                                        if a.is_material
                                        else SupportLevel.PROBABLE
                                    ),
                                ),
                            )
                        messages.append(
                            f"Assessed {len(assessments)} variances for '{obj}'"
                        )
                    action.status = ActionStatus.SUCCESS
                    action_trace["status"] = "success"

                # ── KPI route ─────────────────────────────────────────
                elif "kpi" in obj or "performance" in obj:
                    action_trace["tool"] = "kpi_engine"
                    seed_inputs = action.inputs.get("seed_inputs", {})
                    if seed_inputs and self._formula_evaluator is not None:
                        ctx = self._formula_evaluator.evaluate(seed_inputs)
                        if not ctx.errors:
                            kpi_results = {
                                k: float(v)
                                for k, v in ctx.values.items()
                                if k not in seed_inputs
                            }
                            action.outputs["kpi_results"] = kpi_results
                            action_trace["assertion_count"] = len(kpi_results)
                            for name, value in kpi_results.items():
                                assertions.append(
                                    Assertion(
                                        id=f"kpi_{name}",
                                        type=AssertionType.NUMERIC,
                                        text=f"KPI {name} = {value}",
                                        value=Decimal(str(value)),
                                        confidence=0.95,
                                        support_level=SupportLevel.VERIFIED,
                                        source="deterministic",
                                    ),
                                )
                            messages.append(
                                f"Evaluated {len(kpi_results)} KPIs for '{obj}'"
                            )
                        else:
                            action.outputs["errors"] = [str(e) for e in ctx.errors]
                            action_trace["error"] = "; ".join(
                                str(e) for e in ctx.errors
                            )
                    action.status = ActionStatus.SUCCESS
                    action_trace["status"] = "success"

                # ── Evidence route ─────────────────────────────────────
                elif "evidence" in obj or "supporting" in obj:
                    action_trace["tool"] = "evidence_engine"
                    account_id = state.context.get("account_id", "")
                    period_id = state.context.get("period_id", "")
                    if account_id and period_id:
                        items = self._evidence.collect(account_id, period_id)
                        action.outputs["evidence_items"] = [
                            e.model_dump() for e in items
                        ]
                        action_trace["evidence_count"] = len(items)
                        messages.append(
                            f"Collected {len(items)} evidence items for '{obj}'"
                        )
                    action.status = ActionStatus.SUCCESS
                    action_trace["status"] = "success"

                # ── Fallback: run validation at least ──────────────────
                else:
                    action_trace["tool"] = "validation_suite"
                    action.status = ActionStatus.SUCCESS
                    action_trace["status"] = "success"

            except Exception as exc:
                action.status = ActionStatus.FAILED
                action_trace["status"] = "failed"
                action_trace["error"] = str(exc)

            # ── Always run validation suite ────────────────────────────
            validation_report = self._validation.run(**state.context)
            action.outputs["validation"] = validation_report.to_dict()
            action_trace["validation_status"] = (
                "passed" if validation_report.passed else "failed"
            )
            if validation_report.total > 0 and not validation_report.passed:
                for r in validation_report.results:
                    if not r.is_valid:
                        assertions.append(
                            Assertion(
                                id=f"val_{r.validator_name}",
                                type=AssertionType.NUMERIC,
                                text=(
                                    f"Validation '{r.validator_name}' "
                                    f"failed: {'; '.join(r.messages)}"
                                ),
                                confidence=0.3,
                                support_level=SupportLevel.INSUFFICIENT,
                                source="deterministic",
                            ),
                        )

            elapsed = perf_counter() - started_at
            action.latency_ms = elapsed * 1000
            action_trace["latency_ms"] = action.latency_ms
            action_trace["retries"] = action.retry_count
            action_trace["assertion_count"] = len(
                [a for a in assertions if a.id.startswith(("mat_", "kpi_", "val_"))]
            )
            action_traces.append(action_trace)

        all_succeeded = all(t["status"] == "success" for t in action_traces)
        some_failed = any(t["status"] == "failed" for t in action_traces)

        if all_succeeded:
            plan_status = "all_succeeded"
        elif some_failed:
            plan_status = "some_failed"
        else:
            plan_status = "completed"

        avg_confidence = (
            round(
                sum(a.confidence for a in assertions) / len(assertions), 4
            )
            if assertions
            else 0.8
        )

        return NodeResult(
            node_name="executor",
            success=True,
            state_updates={
                "action_traces": action_traces,
                "plan_status": plan_status,
            },
            new_assertions=assertions,
            confidence=avg_confidence,
            message="; ".join(messages) if messages else "No actions to execute",
        )
