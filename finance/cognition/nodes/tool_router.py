from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from finance.cognition.state.models import ReasoningState
from finance.cognition.state.node import NodeResult
from shared.models.assertions import Assertion, AssertionType, SupportLevel

if TYPE_CHECKING:
    from finance.evidence.engine import EvidenceEngine
    from finance.formula_engine.evaluator import FormulaEvaluator
    from finance.validation.harness import ValidationSuite
    from finance.variance_engine.materiality import MaterialityEngine


class ToolRouterNode:
    """Routes state data to real deterministic engines.

    When engines are injected, invokes them with data from the state
    context.  When no engine is available for a given route, that step
    is silently skipped.
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
        assertions: list[Assertion] = []
        state_updates: dict[str, Any] = {}
        messages: list[str] = []
        engine_count = 0

        # ── 1. Materiality Engine ──────────────────────────────────────────
        raw_variances = state.context.get("variances")
        if raw_variances:
            assessments = self._materiality.assess_batch(raw_variances)
            state_updates["materiality_assessments"] = [
                a.model_dump() for a in assessments
            ]
            material_count = sum(1 for a in assessments if a.is_material)
            messages.append(
                f"Assessed {len(assessments)} variances, "
                f"{material_count} material"
            )
            engine_count += 1
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
                    )
                )

        # ── 2. Formula Evaluator ───────────────────────────────────────────
        seed_inputs: dict[str, Decimal] = state.context.get("seed_inputs", {})
        if seed_inputs and self._formula_evaluator is not None:
            ctx = self._formula_evaluator.evaluate(seed_inputs)
            if not ctx.errors:
                kpi_results = {
                    k: float(v)
                    for k, v in ctx.values.items()
                    if k not in seed_inputs
                }
                state_updates["kpi_results"] = kpi_results
                messages.append(
                    f"Evaluated {len(ctx.evaluated)} formulas"
                )
                engine_count += 1
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
                        )
                    )
            else:
                state_updates["formula_errors"] = [str(e) for e in ctx.errors]
                messages.append(
                    f"Formula evaluation errors: {len(ctx.errors)}"
                )

        # ── 3. Evidence Engine ─────────────────────────────────────────────
        account_id = state.context.get("account_id", "")
        period_id = state.context.get("period_id", "")
        if account_id and period_id:
            evidence_items = self._evidence.collect(account_id, period_id)
            state_updates["evidence_items"] = [
                e.model_dump() for e in evidence_items
            ]
            messages.append(
                f"Collected {len(evidence_items)} evidence items"
            )
            engine_count += 1

        # ── 4. Validation Suite ────────────────────────────────────────────
        validation_report = self._validation.run(**state.context)
        state_updates["validation_report"] = validation_report.to_dict()
        if validation_report.total > 0:
            engine_count += 1
        if validation_report.total > 0 and not validation_report.passed:
            messages.append(
                f"Validation: {validation_report.failed_count}/"
                f"{validation_report.total} checks failed"
            )
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
                        )
                    )

        if engine_count == 0:
            return NodeResult(
                node_name="tool_router",
                success=True,
                state_updates={
                    "routed_engines": [],
                    "evidence": [],
                },
                confidence=0.5,
                message="No engines invoked — no data to route",
            )

        avg_confidence = (
            round(
                sum(a.confidence for a in assertions) / len(assertions), 4
            )
            if assertions
            else 0.8
        )

        return NodeResult(
            node_name="tool_router",
            success=True,
            state_updates={
                **state_updates,
                "routed_engines": engine_count,
            },
            new_assertions=assertions,
            confidence=avg_confidence,
            message="; ".join(messages),
        )
