from __future__ import annotations

from typing import Any


def make_state(**overrides: object) -> Any:
    from finance.cognition.state.models import ReasoningState

    defaults: dict[str, object] = dict(query="Analyze")
    defaults.update(overrides)
    return ReasoningState(**defaults)


class TestPlannerNode:
    def test_planner_creates_action_plan(self) -> None:
        from finance.cognition.nodes import PlannerNode

        result = PlannerNode().execute(make_state())
        assert result.success
        assert "action_plan" in result.state_updates
        plan = result.state_updates["action_plan"]
        assert len(plan["actions"]) >= 1

    def test_planner_sets_confidence(self) -> None:
        from finance.cognition.nodes import PlannerNode

        result = PlannerNode().execute(make_state())
        assert result.confidence == 0.5

    def test_planner_returns_message(self) -> None:
        from finance.cognition.nodes import PlannerNode

        result = PlannerNode().execute(make_state())
        assert "action" in result.message.lower()

    def test_planner_parses_query_for_keywords(self) -> None:
        from finance.cognition.nodes import PlannerNode

        state = make_state(query="Analyze revenue variance and KPIs")
        result = PlannerNode().execute(state)
        plan = result.state_updates["action_plan"]
        objectives = [a["objective"] for a in plan["actions"]]
        assert any("variance" in o for o in objectives)
        assert any("kpi" in o or "performance" in o for o in objectives)


class TestRetrieverNode:
    def test_retriever_gathers_context(self) -> None:
        from finance.cognition.nodes import RetrieverNode

        result = RetrieverNode().execute(make_state())
        assert "context" in result.state_updates

    def test_retriever_reports_sources(self) -> None:
        from finance.cognition.nodes import RetrieverNode

        result = RetrieverNode().execute(make_state())
        assert len(result.state_updates["sources"]) >= 1

    def test_retriever_has_confidence(self) -> None:
        from finance.cognition.nodes import RetrieverNode

        result = RetrieverNode().execute(make_state())
        assert result.confidence >= 0.0

    def test_retriever_reports_retrieved_for(self) -> None:
        from finance.cognition.nodes import RetrieverNode
        from finance.cognition.state.action import ActionPlan

        state = make_state()
        state.action_plan = ActionPlan()
        state.action_plan.add(objective="determine_revenue_variance")
        result = RetrieverNode().execute(state)
        assert "retrieved_for" in result.state_updates
        assert "determine_revenue_variance" in result.state_updates["retrieved_for"]

    def test_retriever_with_mock_provider(self) -> None:
        from finance.cognition.nodes.retriever import RetrieverNode
        from finance.integration.mock_provider import MockProvider

        provider = MockProvider(initial_data={"Sheet1!A:Z": [["a", "1"], ["b", "2"]]})
        node = RetrieverNode(spreadsheet_provider=provider)
        state = make_state(context={"spreadsheet_id": "s1", "range": "Sheet1!A:Z"})
        result = node.execute(state)
        assert result.state_updates["raw_data"] == [["a", "1"], ["b", "2"]]
        assert "spreadsheet:s1" in result.state_updates["sources"]

    def test_retriever_with_provider_fallback_on_error(self) -> None:
        from finance.cognition.nodes.retriever import RetrieverNode
        from finance.integration.mock_provider import MockProvider

        provider = MockProvider()
        node = RetrieverNode(spreadsheet_provider=provider)
        result = node.execute(make_state())
        assert "context" in result.state_updates


class TestExecutorNode:
    def test_executor_empty_plan(self) -> None:
        from finance.cognition.nodes import ExecutorNode
        from finance.cognition.state.action import ActionPlan

        state = make_state()
        state.action_plan = ActionPlan()
        result = ExecutorNode().execute(state)
        assert result.success
        assert result.state_updates.get("plan_status") == "no_actions"

    def test_executor_routes_variances(self) -> None:
        from decimal import Decimal

        from finance.cognition.nodes import ExecutorNode
        from finance.cognition.state.action import ActionPlan
        from shared.models.state import Variance

        state = make_state(context={"variances": [
            Variance(
                account_id="4000", account_name="Revenue", department="Sales",
                actual_amount=Decimal("110000"), budget_amount=Decimal("100000"),
                variance_amount=Decimal("10000"), variance_pct=Decimal("10.0"),
            ),
        ]})
        state.action_plan = ActionPlan()
        state.action_plan.add(objective="determine_revenue_variance")
        result = ExecutorNode().execute(state)
        assert "action_traces" in result.state_updates
        assert result.state_updates["plan_status"] in ("all_succeeded", "some_failed")
        # Should have produced assertions
        if result.new_assertions:
            assert any(a.id.startswith("mat_") for a in result.new_assertions)

    def test_executor_routes_kpis(self) -> None:
        from decimal import Decimal

        from finance.cognition.nodes import ExecutorNode
        from finance.cognition.state.action import ActionPlan
        from finance.formula_engine.evaluator import FormulaEvaluator
        from finance.formula_engine.formula_registry import Formula, FormulaRegistry
        from finance.formula_engine.dependency_resolver import DependencyResolver

        registry = FormulaRegistry()
        registry.register(Formula(
            name="gross_margin", description="GM", category="margin",
            inputs=["revenue", "cogs"], output_name="gross_margin",
            fn=lambda revenue, cogs: revenue - cogs,
        ))
        resolver = DependencyResolver()
        evaluator = FormulaEvaluator(registry=registry, resolver=resolver)
        plan = ActionPlan()
        plan.add(objective="compute_key_performance_indicators",
                 inputs={"seed_inputs": {"revenue": Decimal("1000"), "cogs": Decimal("600")}})
        state = make_state()
        state.action_plan = plan
        result = ExecutorNode(formula_evaluator=evaluator).execute(state)
        assert "action_traces" in result.state_updates
        # KPI assertions
        kpi_assertions = [a for a in result.new_assertions if a.id.startswith("kpi_")]
        assert len(kpi_assertions) >= 1

    def test_executor_records_action_trace(self) -> None:
        from decimal import Decimal

        from finance.cognition.nodes import ExecutorNode
        from finance.cognition.state.action import ActionPlan
        from shared.models.state import Variance

        state = make_state(context={"variances": [
            Variance(
                account_id="4000", account_name="Revenue", department="Sales",
                actual_amount=Decimal("110000"), budget_amount=Decimal("100000"),
                variance_amount=Decimal("10000"), variance_pct=Decimal("10.0"),
            ),
        ]})
        state.action_plan = ActionPlan()
        state.action_plan.add(objective="determine_revenue_variance")
        result = ExecutorNode().execute(state)
        traces = result.state_updates["action_traces"]
        assert len(traces) >= 1
        trace = traces[0]
        assert "action_id" in trace
        assert "objective" in trace
        assert "tool" in trace
        assert "status" in trace
        assert "latency_ms" in trace
        assert "retries" in trace

    def test_executor_with_injected_engines(self) -> None:
        from finance.cognition.nodes import ExecutorNode
        from finance.evidence.engine import EvidenceEngine
        from finance.validation.harness import ValidationSuite
        from finance.cognition.state.action import ActionPlan

        node = ExecutorNode(
            evidence_engine=EvidenceEngine(),
            validation_suite=ValidationSuite(),
        )
        state = make_state()
        state.action_plan = ActionPlan()
        result = node.execute(state)
        assert result.success


class TestVerifierNode:
    def test_verifier_accepts_empty_assertions(self) -> None:
        from finance.cognition.nodes import VerifierNode

        result = VerifierNode().execute(make_state())
        assert result.success

    def test_verifier_detects_low_confidence(self) -> None:
        from finance.cognition.nodes import VerifierNode
        from shared.models.assertions import Assertion, AssertionType

        state = make_state()
        state.assertions = [
            Assertion(id="a1", type=AssertionType.NUMERIC, text="Low", confidence=0.3),
        ]
        result = VerifierNode().execute(state)
        assert result.state_updates.get("needs_revision") is True

    def test_verifier_passes_high_confidence(self) -> None:
        from finance.cognition.nodes import VerifierNode
        from shared.models.assertions import Assertion, AssertionType, SupportLevel

        state = make_state()
        state.assertions = [
            Assertion(
                id="a1",
                type=AssertionType.NUMERIC,
                text="High",
                confidence=0.95,
                support_level=SupportLevel.VERIFIED,
            ),
        ]
        result = VerifierNode().execute(state)
        assert result.state_updates.get("needs_revision") is False

    def test_verifier_computes_average_confidence(self) -> None:
        from finance.cognition.nodes import VerifierNode
        from shared.models.assertions import Assertion, AssertionType

        state = make_state()
        state.assertions = [
            Assertion(id="a1", type=AssertionType.NUMERIC, text="V1", confidence=0.9),
            Assertion(id="a2", type=AssertionType.NUMERIC, text="V2", confidence=0.7),
        ]
        result = VerifierNode().execute(state)
        assert result.state_updates["overall_confidence"] == 0.8

    def test_verifier_detects_unsupported(self) -> None:
        from finance.cognition.nodes import VerifierNode
        from shared.models.assertions import Assertion, AssertionType, SupportLevel

        state = make_state()
        state.assertions = [
            Assertion(
                id="a1", type=AssertionType.NUMERIC, text="Weak",
                confidence=0.6, support_level=SupportLevel.WEAK,
            ),
        ]
        result = VerifierNode().execute(state)
        assert result.state_updates["unsupported_count"] >= 1
        assert result.state_updates["needs_revision"] is True

    def test_verifier_detects_missing_evidence(self) -> None:
        from finance.cognition.nodes import VerifierNode
        from shared.models.assertions import Assertion, AssertionType

        state = make_state()
        state.assertions = [
            Assertion(
                id="a1", type=AssertionType.NUMERIC, text="No evidence",
                confidence=0.6, missing_evidence=["gl_accounts"],
            ),
        ]
        result = VerifierNode().execute(state)
        assert result.state_updates["missing_evidence_count"] == 1

    def test_verifier_detects_contradictions(self) -> None:
        from finance.cognition.nodes import VerifierNode
        from shared.models.assertions import Assertion, AssertionType

        state = make_state()
        state.assertions = [
            Assertion(
                id="a1", type=AssertionType.NUMERIC, text="Contradicted",
                confidence=0.6, contradictions=["a2 says opposite"],
            ),
        ]
        result = VerifierNode().execute(state)
        assert result.state_updates["contradicted_count"] == 1

    def test_verifier_checks_action_results(self) -> None:
        from finance.cognition.nodes import VerifierNode
        from finance.cognition.state.action import ActionPlan, ActionStatus

        plan = ActionPlan()
        a = plan.add(objective="determine_revenue_variance")
        a.status = ActionStatus.SUCCESS
        a.outputs = {"assessments": [{"test": True}]}
        a.evidence_ids = ["e1"]
        state = make_state(context={"action_verifications": []})
        state.action_plan = plan
        result = VerifierNode().execute(state)
        assert "action_verifications" in result.state_updates

    def test_verifier_detects_failed_actions(self) -> None:
        from finance.cognition.nodes import VerifierNode
        from finance.cognition.state.action import ActionPlan, ActionStatus

        plan = ActionPlan()
        a = plan.add(objective="determine_revenue_variance")
        a.status = ActionStatus.FAILED
        a.outputs = {}
        state = make_state(context={"action_verifications": []})
        state.action_plan = plan
        result = VerifierNode().execute(state)
        assert result.state_updates["actions_passed"] == 0
        assert result.state_updates["actions_total"] == 1


class TestReflectionNode:
    def test_reflection_decides_finalize_on_high_confidence(self) -> None:
        from finance.cognition.nodes import ReflectionNode
        from finance.cognition.state.action import ActionPlan

        plan = ActionPlan()
        plan.add(objective="determine_revenue_variance")
        plan.add(objective="compute_key_performance_indicators")
        plan.add(objective="collect_supporting_evidence")
        state = make_state(
            context={
                "overall_confidence": 0.85,
                "evidence_items": [{"claim": "test"}],
            },
        )
        state.action_plan = plan
        result = ReflectionNode().execute(state)
        assert result.state_updates["loop_decision"] == "finalize"

    def test_reflection_decides_revise_on_low_confidence(self) -> None:
        from finance.cognition.nodes import ReflectionNode

        state = make_state(context={"overall_confidence": 0.3, "needs_revision": True})
        result = ReflectionNode().execute(state)
        assert result.state_updates["loop_decision"] == "revise"

    def test_reflection_identifies_missing_evidence(self) -> None:
        from finance.cognition.nodes import ReflectionNode

        state = make_state(context={"evidence": []})
        result = ReflectionNode().execute(state)
        gaps = result.state_updates.get("gaps", [])
        assert len(gaps) > 0

    def test_reflection_continue_no_gaps_medium_confidence(self) -> None:
        from finance.cognition.nodes import ReflectionNode
        from finance.cognition.state.action import ActionPlan

        plan = ActionPlan()
        plan.add(objective="determine_revenue_variance")
        plan.add(objective="compute_key_performance_indicators")
        plan.add(objective="collect_supporting_evidence")
        state = make_state(context={
            "overall_confidence": 0.5,
            "evidence": ["e1"],
            "evidence_items": [{"claim": "test"}],
        })
        state.action_plan = plan
        result = ReflectionNode().execute(state)
        assert result.state_updates["loop_decision"] in ("continue", "finalize")

    def test_reflection_inspects_validation_failures(self) -> None:
        from finance.cognition.nodes import ReflectionNode
        from finance.cognition.state.action import ActionPlan

        plan = ActionPlan()
        plan.add(objective="determine_revenue_variance")
        plan.add(objective="compute_key_performance_indicators")
        plan.add(objective="collect_supporting_evidence")
        state = make_state(context={
            "overall_confidence": 0.5,
            "validation_report": {"failed_count": 2, "passed": False},
            "evidence_items": [{"claim": "test"}],
        })
        state.action_plan = plan
        result = ReflectionNode().execute(state)
        gaps = result.state_updates.get("gaps", [])
        assert any("validation" in g.lower() for g in gaps)
        assert result.state_updates["loop_decision"] == "revise"

    def test_reflection_inspects_missing_kpi(self) -> None:
        from finance.cognition.nodes import ReflectionNode
        from finance.cognition.state.action import ActionPlan

        plan = ActionPlan()
        plan.add(objective="determine_revenue_variance")
        state = make_state(context={"overall_confidence": 0.5, "evidence_items": [{"claim": "test"}]})
        state.action_plan = plan
        result = ReflectionNode().execute(state)
        gaps = result.state_updates.get("gaps", [])
        assert any("kpi" in g.lower() for g in gaps)

    def test_reflection_detects_failed_action_verifications(self) -> None:
        from finance.cognition.nodes import ReflectionNode
        from finance.cognition.state.action import ActionPlan

        plan = ActionPlan()
        plan.add(objective="determine_revenue_variance")
        plan.add(objective="compute_key_performance_indicators")
        plan.add(objective="collect_supporting_evidence")
        state = make_state(context={
            "overall_confidence": 0.5,
            "evidence_items": [{"claim": "test"}],
            "action_verifications": [
                {"objective": "determine_revenue_variance", "passed": False, "status": "failed"},
            ],
        })
        state.action_plan = plan
        result = ReflectionNode().execute(state)
        gaps = result.state_updates.get("gaps", [])
        assert any("failed" in g.lower() for g in gaps)
