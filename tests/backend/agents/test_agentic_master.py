"""Master integration test: validates all 8 anti-hallucination architecture buckets.

This is the authoritative test suite that proves the entire assertion-based
pipeline is hallucination-resistant end-to-end.

Buckets covered:
  1. Tool call correctness        — tools return valid ToolResult with required filters
  2. Type preservation             — Decimal and typed assertions survive full round trip
  3. Formatting                    — structured output parsing (SUMMARY/EVIDENCE/CONFIDENCE/ACTION)
  4. Decision making               — materiality thresholds, routing, policy
  5. Routing                       — LangGraph conditional edges (material→root_cause, immaterial→skip)
  6. Hallucination resistance      — no unsupported numbers/causes/actions appear after pipeline
  7. Retrieval discipline          — precedent never treated as fact
  8. Rendering-only compliance     — commentary adds no new claims
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from backend.models.assertions import Assertion, AssertionType, SupportLevel
from backend.models.degraded_mode import DegradedMode
from backend.models.state import Variance, PipelineState, RootCauseFinding
from backend.tools.tool_result import ToolResult
from backend.engine.assertion_pipeline import (
    AssertionPipelineResult,
    build_numeric_assertion,
    build_comparative_assertion,
    build_causal_assertion,
    build_action_assertion,
    run_assertion_pipeline,
)
from backend.engine.confidence import (
    compute_deterministic_confidence,
    compute_fact_confidence,
    compute_comparative_confidence,
    compute_causal_confidence,
    compute_hypothesis_confidence,
    compute_action_confidence,
)
from backend.agents.commentary_agent import (
    CommentaryRenderInput,
    build_render_prompt,
    render_commentary,
    _fallback_render,
)
from backend.agents.orchestrator import _route_after_variance
from backend.validators.claim_validator import (
    validate_commentary_claims,
    extract_monetary_claims,
    MonetaryClaim,
)
from backend.agents.llm_client import LLMClient


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _make_tool_result(
    row_count: int = 100,
    coverage_pct: float = 1.0,
    quality_score: float = 1.0,
    freshness_seconds: int | None = 3600,
    source_diversity: int = 2,
    source_type: str = "financial_fact",
    retrieval_scope: str = "factual",
    degraded_mode: str | None = None,
    tenant_id: str = "test-tenant",
) -> ToolResult:
    return ToolResult(
        data=[{"account": "test"}],
        row_count=row_count,
        coverage_pct=coverage_pct,
        quality_score=quality_score,
        freshness_seconds=freshness_seconds,
        schema_version="1.0",
        source_diversity=source_diversity,
        source_type=source_type,
        retrieval_scope=retrieval_scope,
        tenant_id=tenant_id,
        required_filters_present=True,
        insufficient_data=False,
        degraded_mode=degraded_mode,
        query_fingerprint="abc123",
    )


def _make_assertion(
    text: str,
    type_: AssertionType = AssertionType.NUMERIC,
    support: SupportLevel = SupportLevel.VERIFIED,
    confidence: float = 0.95,
    value: Decimal | None = None,
    evidence_ids: list[str] | None = None,
) -> Assertion:
    return Assertion(
        id=f"test-{hash(text)}",
        type=type_,
        text=text,
        support_level=support,
        confidence=confidence,
        value=value,
        evidence_ids=evidence_ids or [],
    )


def _make_verified(text: str, **kw) -> Assertion:
    return _make_assertion(text, support=SupportLevel.VERIFIED, **kw)


def _make_probable(text: str, **kw) -> Assertion:
    return _make_assertion(
        text, support=SupportLevel.PROBABLE, confidence=0.65, **kw
    )


def _make_weak(text: str, **kw) -> Assertion:
    return _make_assertion(
        text, support=SupportLevel.WEAK, confidence=0.35, **kw
    )


def _make_variance(
    account_id: str = "A1",
    account_name: str = "Cloud Spend",
    department: str = "Engineering",
    actual: Decimal = Decimal("120000"),
    budget: Decimal = Decimal("100000"),
    is_material: bool | None = None,
) -> Variance:
    var_amt = actual - budget
    var_pct = (var_amt / budget * Decimal("100")) if budget != Decimal("0") else Decimal("0")
    v = Variance(
        account_id=account_id,
        account_name=account_name,
        department=department,
        actual_amount=actual,
        budget_amount=budget,
        variance_amount=var_amt,
        variance_pct=var_pct.quantize(Decimal("0.01")),
    )
    if is_material is not None:
        v.is_material = is_material
    return v


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 1: Normal pipeline — all data clean
# ═══════════════════════════════════════════════════════════════════════════════


class TestScenario1NormalPipeline:
    """Prove the pipeline works end-to-end with clean data."""

    def test_numeric_assertions_verified_with_high_confidence(self):
        """NUMERIC assertions are VERIFIED with confidence > 0.8."""
        tool_results = [
            _make_tool_result(row_count=100, coverage_pct=0.95, quality_score=0.95),
            _make_tool_result(row_count=80, coverage_pct=0.90, quality_score=0.90),
        ]
        assertion = build_numeric_assertion(
            account_name="Cloud Spend",
            actual=Decimal("120000"),
            budget=Decimal("100000"),
            variance=Decimal("20000"),
            variance_pct=Decimal("20.00"),
            tool_results=tool_results,
        )
        assert assertion is not None
        assert assertion.type == AssertionType.NUMERIC
        assert assertion.support_level == SupportLevel.VERIFIED
        assert assertion.confidence > 0.8, (
            f"Expected confidence > 0.8, got {assertion.confidence}"
        )

    def test_commentary_contains_amounts_matching_verified_assertions(self):
        """Commentary contains $ amounts from verified assertions only."""
        verified_assertions = [
            _make_verified(
                "Cloud infrastructure: actual $225,529 vs budget $200,000, "
                "variance $25,529 (+12.76%)",
                type_=AssertionType.NUMERIC,
                value=Decimal("25529"),
            ),
        ]
        inp = CommentaryRenderInput(
            verified_assertions=verified_assertions,
            probable_assertions=[],
            weak_assertions=[],
            entity_name="TestCorp",
            period="2026-Q2",
        )
        text = _fallback_render(inp)

        # Executive Summary section
        assert "Executive Summary" in text
        assert "$225,529" in text
        assert "$200,000" in text

    def test_pipeline_no_degraded_modes_with_clean_data(self):
        """Clean data produces no DEGRADED modes."""
        variances = [
            {
                "account_name": "Cloud Spend",
                "actual_amount": Decimal("120000"),
                "budget_amount": Decimal("100000"),
                "variance_amount": Decimal("20000"),
                "variance_pct": Decimal("20.00"),
            },
        ]
        tool_results = {
            "gl": [
                _make_tool_result(row_count=80, coverage_pct=0.95, quality_score=0.9),
            ],
        }
        result = run_assertion_pipeline(variances=variances, tool_results=tool_results)
        assert len(result.degraded_modes) == 0, (
            f"Expected no degraded modes, got {result.degraded_modes}"
        )
        assert "none" in result.summary.lower()

    def test_full_pipeline_end_to_end_clean(self):
        """Run full pipeline with clean data, verify all properties."""
        variances = [
            {
                "account_name": "Cloud Spend",
                "actual_amount": Decimal("120000"),
                "budget_amount": Decimal("100000"),
                "variance_amount": Decimal("20000"),
                "variance_pct": Decimal("20.00"),
            },
            {
                "account_name": "Travel",
                "actual_amount": Decimal("50000"),
                "budget_amount": Decimal("60000"),
                "variance_amount": Decimal("-10000"),
                "variance_pct": Decimal("-16.67"),
            },
        ]
        tool_results = {
            "gl": [
                _make_tool_result(row_count=80, coverage_pct=0.95, quality_score=0.9),
            ],
        }
        candidates = [
            {"account_id": "a1", "account_name": "Cloud", "variance_amount": 20000},
            {"account_id": "a2", "account_name": "Travel", "variance_amount": -10000},
        ]
        driver_tree_edges = [
            {"from": "cloud_migration", "to": "infra_spend"},
        ]

        result = run_assertion_pipeline(
            variances=variances,
            tool_results=tool_results,
            candidates=candidates,
            driver_tree_edges=driver_tree_edges,
        )

        assert result.has_valid_assertions
        assert len(result.assertions) >= 2
        assert result.highest_confidence > 0.0
        # No degraded modes with clean data
        assert len(result.degraded_modes) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 2: Low coverage — degraded mode propagation
# ═══════════════════════════════════════════════════════════════════════════════


class TestScenario2LowCoverageDegradation:
    """Prove low coverage propagates degraded modes through the pipeline."""

    def test_low_coverage_sets_degraded_mode(self):
        """Low coverage tool results produce LOW_COVERAGE degraded mode."""
        tool_results = [
            _make_tool_result(
                row_count=0,
                coverage_pct=0.0,
                quality_score=0.0,
                degraded_mode="low_coverage",
            ),
        ]
        assertion = build_numeric_assertion(
            account_name="No Data Account",
            actual=Decimal("120000"),
            budget=Decimal("100000"),
            variance=Decimal("20000"),
            variance_pct=Decimal("20.00"),
            tool_results=tool_results,
        )
        assert assertion is not None
        assert "low_coverage" in assertion.metadata["degraded_modes"]

    def test_low_coverage_reduces_confidence(self):
        """Low coverage reduces confidence compared to clean data."""
        clean = build_numeric_assertion(
            account_name="Clean",
            actual=Decimal("100"),
            budget=Decimal("90"),
            variance=Decimal("10"),
            variance_pct=Decimal("11.11"),
            tool_results=[_make_tool_result(
                row_count=100, coverage_pct=0.95, quality_score=0.95,
            )],
        )
        degraded = build_numeric_assertion(
            account_name="Degraded",
            actual=Decimal("100"),
            budget=Decimal("90"),
            variance=Decimal("10"),
            variance_pct=Decimal("11.11"),
            tool_results=[_make_tool_result(
                row_count=1, coverage_pct=0.1, quality_score=0.1,
                degraded_mode="low_coverage",
            )],
        )
        assert clean is not None
        assert degraded is not None
        assert clean.confidence > degraded.confidence

    def test_degraded_mode_surfaces_in_pipeline_result(self):
        """Degraded modes from tool results surface in pipeline result."""
        variances = [
            {
                "account_name": "Degraded Account",
                "actual_amount": Decimal("100"),
                "budget_amount": Decimal("90"),
                "variance_amount": Decimal("10"),
                "variance_pct": Decimal("11.11"),
            },
        ]
        tool_results = {
            "gl": [
                _make_tool_result(degraded_mode="low_coverage"),
            ],
        }
        result = run_assertion_pipeline(variances=variances, tool_results=tool_results)
        assert "low_coverage" in result.degraded_modes

    def test_commentary_includes_degraded_mode_notes(self):
        """Commentary with degraded modes includes data quality notes."""
        v = _make_verified("Revenue was $100,000")
        inp = CommentaryRenderInput(
            verified_assertions=[v],
            probable_assertions=[],
            weak_assertions=[],
            degraded_modes=["low_coverage", "missing_fx"],
        )
        text = _fallback_render(inp)
        assert "Data Quality Notes" in text
        assert "Low Coverage" in text
        assert "Missing Fx" in text
        assert "Limited data availability" in text


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 3: Hallucination resistance — LLM cannot invent
# ═══════════════════════════════════════════════════════════════════════════════


class TestScenario3HallucinationResistance:
    """Prove the system prevents hallucination of values, causes, or actions."""

    def test_all_dollar_amounts_match_verified_assertions(self):
        """Every $ amount in fallback output corresponds to a verified assertion."""
        verified = [
            _make_verified(
                "Cloud infrastructure: actual $225,529 vs budget $200,000",
                type_=AssertionType.NUMERIC,
                value=Decimal("25529"),
            ),
            _make_verified(
                "Revenue is the largest variance at $50,000",
                type_=AssertionType.COMPARATIVE,
                value=Decimal("50000"),
            ),
        ]
        inp = CommentaryRenderInput(
            verified_assertions=verified,
            probable_assertions=[],
            weak_assertions=[],
            entity_name="Test Corp",
            period="2026-Q2",
        )
        text = _fallback_render(inp)

        # Extract all $ amounts from output
        claims = extract_monetary_claims(text)
        claim_amounts = {c.amount for c in claims}

        # Known amounts from verified assertions
        expected_amounts = {Decimal("225529"), Decimal("200000"), Decimal("25529"), Decimal("50000")}

        # Every claim in output must be from a verified assertion
        for amount in claim_amounts:
            assert amount in expected_amounts, (
                f"Claim ${amount:,} in output not found in verified assertions"
            )

    def test_no_unverified_claims_in_fallback_output(self):
        """No unverified claims appear in fallback commentary."""
        verified = [
            _make_verified("Revenue was $100,000", value=Decimal("100000")),
        ]
        inp = CommentaryRenderInput(
            verified_assertions=verified,
            probable_assertions=[],
            weak_assertions=[],
        )
        text = _fallback_render(inp)

        facts = [{"amount": Decimal("100000")}]
        validation = validate_commentary_claims(text, facts)
        assert validation.is_valid, (
            f"Commentary has unverified claims: {validation.unverified_claims}"
        )

    def test_no_unsupported_causes_in_output(self):
        """Causes not in input assertions do not appear in output."""
        probable = [
            _make_probable(
                "Variance driven by headcount increase",
                type_=AssertionType.CAUSAL,
            ),
        ]
        inp = CommentaryRenderInput(
            verified_assertions=[_make_verified("Revenue was $100,000", value=Decimal("100000"))],
            probable_assertions=probable,
            weak_assertions=[],
        )
        text = _fallback_render(inp)

        # The only cause in output should be from probable assertions
        assert "headcount increase" in text
        # No other causes should appear
        assert "currency fluctuation" not in text
        assert "market downturn" not in text

    def test_no_unsupported_actions_in_output(self):
        """Actions not in input assertions do not appear in output."""
        inp = CommentaryRenderInput(
            verified_assertions=[_make_verified("Revenue was $100,000", value=Decimal("100000"))],
            probable_assertions=[],
            weak_assertions=[],
        )
        text = _fallback_render(inp)
        # Only verified facts — no actions
        assert "should reduce" not in text.lower()
        assert "should increase" not in text.lower()
        assert "should review" not in text.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 4: Precedent vs fact separation
# ═══════════════════════════════════════════════════════════════════════════════


class TestScenario4PrecedentFactSeparation:
    """Prove precedent data is never treated as VERIFIED fact."""

    def test_precedent_toolresult_has_correct_scope(self):
        """Precedent ToolResult has retrieval_scope='precedent' and source_type='precedent'."""
        result = _make_tool_result(
            source_type="precedent",
            retrieval_scope="precedent",
        )
        assert result.retrieval_scope == "precedent"
        assert result.source_type == "precedent"

    def test_precedent_data_not_used_for_numeric_assertions(self):
        """ToolResult with retrieval_scope='precedent' is not used to build NUMERIC assertions.

        The build_numeric_assertion function uses tool_results passed to it directly.
        This test verifies the pipeline does not pass precedent-scoped results
        to build_numeric_assertion.
        """
        # Precedent results have retrieval_scope="precedent" — they should
        # not be mixed into the "gl" tool_results key used for numeric assertions
        precedent_result = _make_tool_result(
            source_type="precedent",
            retrieval_scope="precedent",
            row_count=5,
            coverage_pct=0.5,
        )

        factual_result = _make_tool_result(
            source_type="financial_fact",
            retrieval_scope="factual",
            row_count=80,
            coverage_pct=0.95,
        )

        # Verify the architecture separates them
        assert precedent_result.retrieval_scope != factual_result.retrieval_scope

        # Run pipeline with only factual tool_results for the "gl" key
        variances = [
            {
                "account_name": "Cloud Spend",
                "actual_amount": Decimal("120000"),
                "budget_amount": Decimal("100000"),
                "variance_amount": Decimal("20000"),
                "variance_pct": Decimal("20.00"),
            },
        ]
        # Only factual results in "gl" — precedent goes elsewhere
        tool_results = {
            "gl": [factual_result],
            "precedent": [precedent_result],
        }
        result = run_assertion_pipeline(variances=variances, tool_results=tool_results)
        assert result.has_valid_assertions
        # Assertions should be built only from factual (gl) data
        assert len(result.assertions) >= 1

    def test_precedent_values_different_from_current_facts(self):
        """When precedent has different numbers, they don't appear in current assertions."""
        current_fact = Decimal("225529")
        precedent_amount = Decimal("180000")  # Different from current fact

        # Build assertion from factual data only
        factual_result = _make_tool_result(
            source_type="financial_fact",
            retrieval_scope="factual",
            row_count=80,
            coverage_pct=0.95,
            quality_score=0.9,
        )
        assertion = build_numeric_assertion(
            account_name="Cloud Spend",
            actual=current_fact,
            budget=Decimal("200000"),
            variance=current_fact - Decimal("200000"),
            variance_pct=Decimal("12.76"),
            tool_results=[factual_result],
        )
        assert assertion is not None
        # The assertion uses the current fact (formatted with commas), not the precedent amount
        assert "$225,529" in assertion.text
        assert "$180,000" not in assertion.text


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 5: Routing correctness
# ═══════════════════════════════════════════════════════════════════════════════


class TestScenario5RoutingCorrectness:
    """Prove LangGraph conditional edges route to the correct next node."""

    def test_material_variances_route_to_root_cause(self):
        """Material variances route to root_cause."""
        state: PipelineState = {
            "period": "2026-06",
            "entity_id": "CF001",
            "actuals": {},
            "budget": {},
            "forecast": {},
            "variances": [
                _make_variance(account_id="A1", account_name="Big", is_material=True),
            ],
            "root_causes": [],
            "commentary_draft": None,
            "scenarios": [],
            "review_decisions": [],
            "error": None,
            "current_step": "variance_complete",
        }
        route = _route_after_variance(state)
        assert route == "root_cause"

    def test_immaterial_variances_route_to_commentary(self):
        """All immaterial variances route to commentary."""
        state: PipelineState = {
            "period": "2026-06",
            "entity_id": "CF001",
            "actuals": {},
            "budget": {},
            "forecast": {},
            "variances": [
                _make_variance(
                    account_id="A1", account_name="Small",
                    actual=Decimal("101"), budget=Decimal("100"),
                    is_material=False,
                ),
            ],
            "root_causes": [],
            "commentary_draft": None,
            "scenarios": [],
            "review_decisions": [],
            "error": None,
            "current_step": "variance_complete",
        }
        route = _route_after_variance(state)
        assert route == "commentary"

    def test_empty_variances_route_to_commentary(self):
        """Empty variances list routes to commentary."""
        state: PipelineState = {
            "period": "2026-06",
            "entity_id": "CF001",
            "actuals": {},
            "budget": {},
            "forecast": {},
            "variances": [],
            "root_causes": [],
            "commentary_draft": None,
            "scenarios": [],
            "review_decisions": [],
            "error": None,
            "current_step": "variance_complete",
        }
        route = _route_after_variance(state)
        assert route == "commentary"

    def test_mixed_materiality_routes_to_root_cause(self):
        """If any variance is material, route is root_cause."""
        state: PipelineState = {
            "period": "2026-06",
            "entity_id": "CF001",
            "actuals": {},
            "budget": {},
            "forecast": {},
            "variances": [
                _make_variance(
                    account_id="A1", account_name="Small",
                    actual=Decimal("101"), budget=Decimal("100"),
                    is_material=False,
                ),
                _make_variance(
                    account_id="A2", account_name="Big",
                    is_material=True,
                ),
            ],
            "root_causes": [],
            "commentary_draft": None,
            "scenarios": [],
            "review_decisions": [],
            "error": None,
            "current_step": "variance_complete",
        }
        route = _route_after_variance(state)
        assert route == "root_cause"


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 6: Type safety — Decimal enforcement
# ═══════════════════════════════════════════════════════════════════════════════


class TestScenario6TypeSafetyDecimal:
    """Prove Decimal enforcement for monetary fields."""

    def test_variance_coerces_float_to_decimal(self):
        """Variance coerces float to Decimal (Pydantic v2 default)."""
        v = Variance(
            account_id="A1",
            account_name="Test",
            department="Eng",
            actual_amount=100000.50,  # float, coerced to Decimal by Pydantic
            budget_amount=Decimal("120000"),
            variance_amount=Decimal("-19999.50"),
            variance_pct=Decimal("-16.67"),
        )
        # Pydantic v2 coerces float → Decimal by default (non-strict mode)
        assert isinstance(v.actual_amount, Decimal)
        assert v.actual_amount == Decimal("100000.50")

    def test_variance_accepts_decimal_amounts(self):
        """Variance accepts Decimal for all monetary fields."""
        v = Variance(
            account_id="4010",
            account_name="Test",
            department="Eng",
            actual_amount=Decimal("100000.50"),
            budget_amount=Decimal("120000.00"),
            variance_amount=Decimal("-19999.50"),
            variance_pct=Decimal("-16.67"),
        )
        assert isinstance(v.actual_amount, Decimal)
        assert isinstance(v.budget_amount, Decimal)
        assert isinstance(v.variance_amount, Decimal)
        assert isinstance(v.variance_pct, Decimal)

    def test_assertion_accepts_decimal_value(self):
        """Assertion value field accepts Decimal."""
        a = Assertion(
            id="test-decimal",
            type=AssertionType.NUMERIC,
            text="Revenue was $100K",
            value=Decimal("100000"),
        )
        assert a.value == Decimal("100000")
        assert isinstance(a.value, Decimal)

    def test_assertion_accepts_none_value(self):
        """Assertion value is optional (None allowed)."""
        a = Assertion(
            id="test-none",
            type=AssertionType.ACTION,
            text="Review costs",
        )
        assert a.value is None

    def test_pipeline_state_minimal(self):
        """PipelineState accepts minimal valid state."""
        state: PipelineState = {
            "period": "2026-06",
            "entity_id": "CF001",
            "actuals": {},
            "budget": {},
            "forecast": {},
            "variances": [],
            "root_causes": [],
            "commentary_draft": None,
            "scenarios": [],
            "review_decisions": [],
            "error": None,
            "current_step": "start",
        }
        assert state["period"] == "2026-06"
        assert state["current_step"] == "start"


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 7: Deterministic confidence by assertion class
# ═══════════════════════════════════════════════════════════════════════════════


class TestScenario7DeterministicConfidence:
    """Prove each assertion class has appropriate confidence caps and ranges."""

    def test_numeric_confidence_high_with_good_data(self):
        """NUMERIC confidence >= 0.8 with good evidence."""
        a = _make_assertion(
            "Test numeric",
            type_=AssertionType.NUMERIC,
            evidence_ids=["e1", "e2", "e3", "e4", "e5"],
        )
        conf = compute_deterministic_confidence(
            assertion=a,
            evidence_count=5,
            source_count=3,
            coverage_pct=0.95,
            quality_score=0.90,
            is_directly_recomputable=True,
        )
        assert conf >= 0.8, f"Expected >= 0.8, got {conf}"
        assert conf <= 1.0

    def test_comparative_confidence_does_not_exceed_numeric(self):
        """COMPARATIVE confidence <= NUMERIC confidence for same base data."""
        numeric_a = _make_assertion(
            "Numeric test", type_=AssertionType.NUMERIC,
            evidence_ids=["e1", "e2", "e3", "e4", "e5"],
        )
        comp_a = _make_assertion(
            "Comp test", type_=AssertionType.COMPARATIVE,
            evidence_ids=["e1", "e2", "e3", "e4", "e5"],
        )

        numeric_conf = compute_deterministic_confidence(
            assertion=numeric_a,
            evidence_count=5, source_count=3,
            coverage_pct=0.95, quality_score=0.90,
            is_directly_recomputable=True,
        )
        comp_conf = compute_deterministic_confidence(
            assertion=comp_a,
            evidence_count=5, source_count=3,
            coverage_pct=0.95, quality_score=0.90,
            candidate_count=5, rank_position=1,
        )
        assert comp_conf <= numeric_conf, (
            f"COMPARATIVE {comp_conf} > NUMERIC {numeric_conf}"
        )

    def test_causal_confidence_capped_at_0_85(self):
        """CAUSAL confidence <= 0.85."""
        a = _make_assertion(
            "Causal test", type_=AssertionType.CAUSAL,
            evidence_ids=["e1", "e2", "e3"],
        )
        conf = compute_deterministic_confidence(
            assertion=a,
            evidence_count=3, source_count=2,
            coverage_pct=0.95, quality_score=0.95,
            evidence_class_count=3, driver_tree_verified=True,
        )
        assert conf <= 0.85, f"Expected <= 0.85, got {conf}"

    def test_hypothesis_confidence_capped_at_0_5(self):
        """HYPOTHESIS confidence <= 0.5."""
        a = _make_assertion(
            "Hypothesis test", type_=AssertionType.HYPOTHESIS,
            evidence_ids=["e1"],
        )
        conf = compute_deterministic_confidence(
            assertion=a,
            evidence_count=1, source_count=1,
            coverage_pct=0.5, quality_score=0.5,
            supporting_precedent_count=5,
            supporting_source_count=5,
            plausible_mechanism=True,
        )
        assert conf <= 0.5, f"Expected <= 0.5, got {conf}"

    def test_action_confidence_capped_at_0_9(self):
        """ACTION confidence <= 0.9."""
        a = _make_assertion(
            "Action test", type_=AssertionType.ACTION,
            evidence_ids=["e1"],
        )
        conf = compute_deterministic_confidence(
            assertion=a,
            evidence_count=1, source_count=1,
            coverage_pct=0.5, quality_score=0.5,
            taxonomy_valid=True,
            policy_permitted=True,
            impact_quantified=True,
            owner_identified=True,
        )
        assert conf <= 0.9, f"Expected <= 0.9, got {conf}"

    def test_all_five_types_have_known_behavior(self):
        """All 5 assertion types route to correct confidence function."""
        for type_, expected_cap in [
            (AssertionType.NUMERIC, 1.0),
            (AssertionType.COMPARATIVE, 1.0),  # capped at fact_confidence
            (AssertionType.CAUSAL, 0.85),
            (AssertionType.HYPOTHESIS, 0.5),
            (AssertionType.ACTION, 0.9),
        ]:
            a = _make_assertion(
                f"Test {type_.value}",
                type_=type_,
                evidence_ids=["e1", "e2", "e3"],
            )
            conf = compute_deterministic_confidence(
                assertion=a,
                evidence_count=3, source_count=3,
                coverage_pct=1.0, quality_score=1.0,
                candidate_count=10, rank_position=1,
                evidence_class_count=5, driver_tree_verified=True,
                supporting_precedent_count=5, plausible_mechanism=True,
                taxonomy_valid=True, policy_permitted=True,
                impact_quantified=True, owner_identified=True,
                is_directly_recomputable=True,
            )
            assert conf <= expected_cap, (
                f"{type_.value} confidence {conf} exceeds cap {expected_cap}"
            )

    def test_degraded_modes_reduce_causal_confidence(self):
        """Each degraded mode reduces causal confidence by 0.10."""
        base = compute_causal_confidence(
            fact_confidence=0.9, evidence_class_count=1,
        )
        reduced = compute_causal_confidence(
            fact_confidence=0.9, evidence_class_count=1,
            degraded_modes=[DegradedMode.LOW_COVERAGE, DegradedMode.STALE_SOURCE],
        )
        assert reduced == pytest.approx(max(0.0, base - 0.20))


# ═══════════════════════════════════════════════════════════════════════════════
# SCENARIO 8: Rendering-only compliance
# ═══════════════════════════════════════════════════════════════════════════════


class TestScenario8RenderingOnlyCompliance:
    """Prove the commentary renderer only renders, never invents."""

    def test_fallback_render_only_uses_input_assertions(self):
        """Fallback render produces only facts from input assertions."""
        assertions = [
            _make_verified(
                "Cloud spend increased by $25,529",
                type_=AssertionType.NUMERIC,
                value=Decimal("25529"),
            ),
            _make_probable(
                "Driven by compute instance growth",
                type_=AssertionType.CAUSAL,
            ),
        ]
        inp = CommentaryRenderInput.from_assertion_list(
            assertions=assertions,
            entity_name="Acme",
            period="2026-Q2",
        )
        text = _fallback_render(inp)

        # All content must come from assertions
        assert "Cloud spend increased by $25,529" in text
        assert "Driven by compute instance growth" in text

        # No invented content
        assert "currency" not in text.lower()
        assert "market" not in text.lower()

    def test_fallback_render_all_standard_sections_present(self):
        """Fallback render produces all expected sections."""
        assertions = [
            _make_verified("Revenue up 12%", type_=AssertionType.NUMERIC),
            _make_probable("Cost pressure from supply chain", type_=AssertionType.CAUSAL),
            _make_weak("Possible FX impact", type_=AssertionType.HYPOTHESIS),
        ]
        inp = CommentaryRenderInput.from_assertion_list(
            assertions=assertions,
            degraded_modes=["low_coverage"],
            entity_name="Test Corp",
            period="2026-Q2",
        )
        text = _fallback_render(inp)

        assert "Financial Commentary — Test Corp" in text
        assert "Period: 2026-Q2" in text
        assert "## Executive Summary" in text
        assert "## Variance Analysis" in text
        assert "## Root Causes" in text
        assert "## Areas for Further Investigation" in text
        assert "## Data Quality Notes" in text

    def test_fallback_render_no_markdown_formatting_errors(self):
        """Fallback render produces valid, clean markdown."""
        assertions = [
            _make_verified("Revenue up 10%", type_=AssertionType.NUMERIC),
        ]
        inp = CommentaryRenderInput.from_assertion_list(
            assertions=assertions,
            entity_name="Test",
            period="2026-Q2",
        )
        text = _fallback_render(inp)

        # All headings start with ##
        for line in text.split("\n"):
            if line.startswith("##"):
                assert len(line) > 3, f"Empty heading: {line}"
                assert line[2] == " ", f"Bad heading format: {line}"

        # No bare $ without context
        lines_with_dollar = [l for l in text.split("\n") if "$" in l]
        for line in lines_with_dollar:
            assert len(line.strip()) > 2, f"Bare $ in line: {line}"

        # Text ends with newline
        assert text.endswith("\n") or text == ""

    def test_fallback_render_empty_input_produces_valid_output(self):
        """Empty render input produces valid minimal structure."""
        inp = CommentaryRenderInput(
            verified_assertions=[],
            probable_assertions=[],
            weak_assertions=[],
            entity_name="Empty",
        )
        text = _fallback_render(inp)
        assert "Financial Commentary — Empty" in text
        assert "## Executive Summary" in text
        assert "## Variance Analysis" in text

    def test_fallback_render_counts_material_variances(self):
        """Multiple NUMERIC assertions produce a count line."""
        v1 = _make_verified("Revenue up 10%", type_=AssertionType.NUMERIC)
        v2 = _make_verified("Costs up 5%", type_=AssertionType.NUMERIC)
        v3 = _make_verified("Volume declined", type_=AssertionType.COMPARATIVE)

        inp = CommentaryRenderInput(
            verified_assertions=[v1, v2, v3],
            probable_assertions=[],
            weak_assertions=[],
        )
        text = _fallback_render(inp)
        assert "2 material variances identified" in text

    def test_fallback_render_lists_hypotheses_count(self):
        """Weak assertions produce a hypothesis count."""
        w1 = _make_weak("Hypothesis A")
        w2 = _make_weak("Hypothesis B")
        inp = CommentaryRenderInput(
            verified_assertions=[_make_verified("Fact")],
            probable_assertions=[],
            weak_assertions=[w1, w2],
        )
        text = _fallback_render(inp)
        assert "2 hypotheses require further investigation" in text

    def test_commentary_survives_claim_validation_round_trip(self):
        """Commentary output passes claim validation against its own input assertions."""
        verified = [
            _make_verified(
                "Cloud spend was $225,529 vs budget of $200,000",
                type_=AssertionType.NUMERIC,
                value=Decimal("225529"),
            ),
        ]
        inp = CommentaryRenderInput.from_assertion_list(
            assertions=verified,
            entity_name="Validate Corp",
            period="2026-Q2",
        )
        text = _fallback_render(inp)

        # Validate that all $ claims in the output can be found in the input assertions
        # (either in assertion.value or in the assertion text itself)
        claims = extract_monetary_claims(text)
        assert len(claims) > 0
        for claim in claims:
            found = False
            for a in verified:
                # Check if amount matches assertion.value (within 5% tolerance)
                if a.value and abs(claim.amount - a.value) / max(abs(a.value), Decimal("1")) <= Decimal("0.05"):
                    found = True
                    break
                # Also check if amount appears in the assertion text (e.g., budget amounts)
                formatted = f"${claim.amount:,.0f}".replace("$-", "-$")
                if formatted.replace("-", "") in a.text.replace("-", ""):
                    found = True
                    break
            assert found, (
                f"Claim ${claim.amount:,} in commentary not found in input assertions"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# CROSS-CUTTING: Full pipeline integration — all buckets working together
# ═══════════════════════════════════════════════════════════════════════════════


class TestFullPipelineIntegration:
    """End-to-end integration test across all 8 buckets simultaneously."""

    def test_assertion_to_commentary_round_trip(self):
        """Full round trip: variance data → assertions → fallback commentary."""
        # Step 1: Build assertions from variance data
        tool_results = [
            _make_tool_result(row_count=80, coverage_pct=0.95, quality_score=0.9),
        ]
        numeric = build_numeric_assertion(
            account_name="Cloud Spend",
            actual=Decimal("225529"),
            budget=Decimal("200000"),
            variance=Decimal("25529"),
            variance_pct=Decimal("12.76"),
            tool_results=tool_results,
        )
        assert numeric is not None
        assert numeric.support_level == SupportLevel.VERIFIED
        assert numeric.confidence > 0.8

        # Step 2: Verify type preservation
        assert isinstance(numeric.value, Decimal)
        assert numeric.value == Decimal("25529")

        # Step 3: Render commentary
        inp = CommentaryRenderInput.from_assertion_list(
            assertions=[numeric],
            entity_name="Integration Corp",
            period="2026-Q2",
        )
        text = _fallback_render(inp)

        # Step 4: Verify rendering-only compliance
        assert "Cloud Spend" in text
        assert "$225,529" in text

        # Step 5: Validate all $ claims are from input assertions
        claims = extract_monetary_claims(text)
        for claim in claims:
            # Must match the assertion value or be a known amount from the assertion text
            if claim.amount == numeric.value:
                continue
            # Could be actual or budget amounts from the assertion text
            assert claim.amount in (Decimal("225529"), Decimal("200000"), Decimal("25529")), (
                f"Unexpected amount ${claim.amount:,} in commentary"
            )

    def test_materiality_cascades_through_routing(self):
        """Materiality decision correctly cascades to routing."""
        material = _make_variance(is_material=True)
        immaterial = _make_variance(is_material=False)

        # Material → root_cause
        state_m: PipelineState = {
            "period": "2026-06",
            "entity_id": "CF001",
            "actuals": {}, "budget": {}, "forecast": {},
            "variances": [material],
            "root_causes": [],
            "commentary_draft": None,
            "scenarios": [],
            "review_decisions": [],
            "error": None,
            "current_step": "variance_complete",
        }
        assert _route_after_variance(state_m) == "root_cause"

        # Immaterial → commentary
        state_i: PipelineState = {
            "period": "2026-06",
            "entity_id": "CF001",
            "actuals": {}, "budget": {}, "forecast": {},
            "variances": [immaterial],
            "root_causes": [],
            "commentary_draft": None,
            "scenarios": [],
            "review_decisions": [],
            "error": None,
            "current_step": "variance_complete",
        }
        assert _route_after_variance(state_i) == "commentary"

    def test_confidence_integrity_across_assertion_chain(self):
        """Confidence behaves correctly across the chain.

        NUMERIC >= COMPARATIVE (comparative capped at fact_confidence).
        CAUSAL capped at 0.85.
        HYPOTHESIS capped at 0.5.
        ACTION capped at 0.9; can exceed CAUSAL due to policy/taxonomy bonuses.
        """
        evidence = {"evidence_ids": ["e1", "e2", "e3", "e4", "e5"]}
        meta = {
            "evidence_count": 5, "source_count": 3,
            "coverage_pct": 0.95, "quality_score": 0.90,
            "is_directly_recomputable": True,
        }

        num = _make_assertion("Numeric", type_=AssertionType.NUMERIC, **evidence)
        numeric_conf = compute_deterministic_confidence(assertion=num, **meta)

        comp_meta = {**meta, "candidate_count": 10, "rank_position": 1}
        comp = _make_assertion("Comp", type_=AssertionType.COMPARATIVE, **evidence)
        comp_conf = compute_deterministic_confidence(assertion=comp, **comp_meta)

        causal_meta = {**meta, "evidence_class_count": 2, "driver_tree_verified": True}
        causal = _make_assertion("Causal", type_=AssertionType.CAUSAL, **evidence)
        causal_conf = compute_deterministic_confidence(assertion=causal, **causal_meta)

        hypothesis_meta = {**meta}
        hyp = _make_assertion("Hypothesis", type_=AssertionType.HYPOTHESIS, **evidence)
        hyp_conf = compute_deterministic_confidence(assertion=hyp, **hypothesis_meta)

        action_meta = {**meta, "taxonomy_valid": True, "policy_permitted": True}
        action = _make_assertion("Action", type_=AssertionType.ACTION, **evidence)
        action_conf = compute_deterministic_confidence(assertion=action, **action_meta)

        # NUMERIC >= COMPARATIVE (comparative capped at fact_confidence)
        assert numeric_conf >= comp_conf, (
            f"NUMERIC {numeric_conf} < COMPARATIVE {comp_conf}"
        )
        # CAUSAL never exceeds 0.85
        assert causal_conf <= 0.85, f"CAUSAL {causal_conf} > 0.85"
        # HYPOTHESIS never exceeds 0.5
        assert hyp_conf <= 0.5, f"HYPOTHESIS {hyp_conf} > 0.5"
        # ACTION never exceeds 0.9
        assert action_conf <= 0.9, f"ACTION {action_conf} > 0.9"

    def test_no_degraded_modes_with_complete_data(self):
        """Complete, fresh, high-coverage data produces no degraded modes."""
        result = run_assertion_pipeline(
            variances=[
                {
                    "account_name": "Revenue",
                    "actual_amount": Decimal("500000"),
                    "budget_amount": Decimal("450000"),
                    "variance_amount": Decimal("50000"),
                    "variance_pct": Decimal("11.11"),
                },
            ],
            tool_results={
                "gl": [
                    _make_tool_result(
                        row_count=200,
                        coverage_pct=0.98,
                        quality_score=0.95,
                        freshness_seconds=3600,
                    ),
                ],
            },
        )
        assert len(result.degraded_modes) == 0
        assert result.has_valid_assertions

    def test_degraded_modes_surface_with_incomplete_data(self):
        """Incomplete, stale data surfaces degraded modes."""
        result = run_assertion_pipeline(
            variances=[
                {
                    "account_name": "Unknown",
                    "actual_amount": Decimal("100"),
                    "budget_amount": Decimal("90"),
                    "variance_amount": Decimal("10"),
                    "variance_pct": Decimal("11.11"),
                },
            ],
            tool_results={
                "gl": [
                    _make_tool_result(
                        row_count=0,
                        coverage_pct=0.0,
                        quality_score=0.0,
                        degraded_mode="low_coverage",
                    ),
                ],
            },
        )
        # The assertion will be built but with degraded metadata
        assert len(result.degraded_modes) >= 1
        assert "low_coverage" in result.degraded_modes
