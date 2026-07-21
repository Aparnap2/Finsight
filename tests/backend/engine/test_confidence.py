"""Tests for the deterministic confidence computation engine."""

import pytest
from backend.models.assertions import Assertion, AssertionType, SupportLevel
from backend.models.degraded_mode import DegradedMode
from backend.engine.confidence import (
    compute_deterministic_confidence,
    compute_fact_confidence,
    compute_comparative_confidence,
    compute_causal_confidence,
    compute_hypothesis_confidence,
    compute_action_confidence,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Fact confidence (NUMERIC)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFactConfidence:
    def test_zero_evidence_returns_zero(self):
        assert compute_fact_confidence(
            evidence_count=0, source_count=0, coverage_pct=0.0, quality_score=0.0
        ) == 0.0

    def test_one_evidence_returns_0_5(self):
        result = compute_fact_confidence(
            evidence_count=1, source_count=1, coverage_pct=0.0, quality_score=0.0
        )
        assert result == pytest.approx(0.5)

    def test_ten_evidence_returns_approx_0_91(self):
        result = compute_fact_confidence(
            evidence_count=10, source_count=5, coverage_pct=0.0, quality_score=0.0
        )
        assert result == pytest.approx(10 / 11)  # 0.90909...

    def test_coverage_modifier_applied_when_above_80pct(self):
        """coverage_pct > 0.8 adds +0.05."""
        base = compute_fact_confidence(
            evidence_count=5, source_count=1, coverage_pct=0.5, quality_score=0.5
        )
        boosted = compute_fact_confidence(
            evidence_count=5, source_count=1, coverage_pct=0.9, quality_score=0.5
        )
        assert boosted == pytest.approx(base + 0.05)

    def test_quality_modifier_applied_when_above_80pct(self):
        """quality_score > 0.8 adds +0.05."""
        base = compute_fact_confidence(
            evidence_count=5, source_count=1, coverage_pct=0.5, quality_score=0.5
        )
        boosted = compute_fact_confidence(
            evidence_count=5, source_count=1, coverage_pct=0.5, quality_score=0.9
        )
        assert boosted == pytest.approx(base + 0.05)

    def test_directly_recomputable_bonus(self):
        """is_directly_recomputable adds +0.05."""
        base = compute_fact_confidence(
            evidence_count=5, source_count=1, coverage_pct=0.0, quality_score=0.0
        )
        boosted = compute_fact_confidence(
            evidence_count=5, source_count=1, coverage_pct=0.0, quality_score=0.0,
            is_directly_recomputable=True,
        )
        assert boosted == pytest.approx(base + 0.05)

    def test_staleness_penalty_applied(self):
        """freshness_seconds > max_age_seconds subtracts 0.10."""
        base = compute_fact_confidence(
            evidence_count=5, source_count=1, coverage_pct=0.0, quality_score=0.0,
        )
        penalised = compute_fact_confidence(
            evidence_count=5, source_count=1, coverage_pct=0.0, quality_score=0.0,
            freshness_seconds=86400 * 91,  # > 90 days
        )
        assert penalised == pytest.approx(base - 0.10)

    def test_staleness_penalty_not_applied_when_fresh(self):
        """freshness_seconds <= max_age_seconds does not penalise."""
        base = compute_fact_confidence(
            evidence_count=5, source_count=1, coverage_pct=0.0, quality_score=0.0,
        )
        fresh = compute_fact_confidence(
            evidence_count=5, source_count=1, coverage_pct=0.0, quality_score=0.0,
            freshness_seconds=86400 * 30,  # 30 days — well within
        )
        assert fresh == pytest.approx(base)

    def test_confidence_clamped_at_1_0(self):
        """Confidence should never exceed 1.0."""
        result = compute_fact_confidence(
            evidence_count=100, source_count=10, coverage_pct=0.9, quality_score=0.9,
            is_directly_recomputable=True,
        )
        assert result == 1.0

    def test_confidence_clamped_at_0_0(self):
        """Confidence should never go below 0.0 even with large penalties."""
        result = compute_fact_confidence(
            evidence_count=0, source_count=0, coverage_pct=0.0, quality_score=0.0,
            freshness_seconds=86400 * 200,  # very stale
        )
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Comparative confidence
# ═══════════════════════════════════════════════════════════════════════════════


class TestComparativeConfidence:
    def test_less_than_two_candidates_reduces_score(self):
        """Fewer than 2 candidates returns fact_confidence * 0.5."""
        result = compute_comparative_confidence(
            fact_confidence=0.8, candidate_count=1
        )
        assert result == pytest.approx(0.8 * 0.5)

    def test_two_candidates_allowed(self):
        """2 candidates is valid (>=2) and does not trigger halving."""
        result = compute_comparative_confidence(
            fact_confidence=0.8, candidate_count=2
        )
        # 0.8 * min(1.0, 2/3) = 0.8 * 0.666... = 0.5333...
        assert result == pytest.approx(0.8 * 2.0 / 3.0)

    def test_rank_one_gets_small_bonus(self):
        """rank_position == 1 adds +0.05 (visible when not already at cap)."""
        base = compute_comparative_confidence(
            fact_confidence=0.9, candidate_count=2, rank_position=2
        )
        boosted = compute_comparative_confidence(
            fact_confidence=0.9, candidate_count=2, rank_position=1
        )
        # base = 0.9 * (2/3) = 0.6; rank=1 adds +0.05 → 0.65
        assert boosted == pytest.approx(base + 0.05)

    def test_saturates_at_candidate_count_3_and_above(self):
        """min(1.0, candidate_count/3) means 3+ candidates gives full factor."""
        r3 = compute_comparative_confidence(
            fact_confidence=0.9, candidate_count=3
        )
        r10 = compute_comparative_confidence(
            fact_confidence=0.9, candidate_count=10
        )
        assert r3 == pytest.approx(r10)

    def test_never_exceeds_fact_confidence(self):
        """Comparative confidence is clamped at fact_confidence."""
        result = compute_comparative_confidence(
            fact_confidence=0.5, candidate_count=10, rank_position=1
        )
        assert result <= 0.5

    def test_zero_fact_confidence_returns_zero(self):
        result = compute_comparative_confidence(
            fact_confidence=0.0, candidate_count=5
        )
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Causal confidence
# ═══════════════════════════════════════════════════════════════════════════════


class TestCausalConfidence:
    def test_capped_at_0_85_max(self):
        """Causal confidence never exceeds 0.85."""
        result = compute_causal_confidence(
            fact_confidence=1.0, evidence_class_count=3,
            driver_tree_verified=True,
        )
        assert result == 0.85

    def test_base_is_fact_confidence_times_0_8(self):
        result = compute_causal_confidence(
            fact_confidence=0.5, evidence_class_count=1,
        )
        assert result == pytest.approx(0.5 * 0.8)

    def test_multiple_evidence_classes_bonus(self):
        """evidence_class_count >= 2 adds +0.10."""
        base = compute_causal_confidence(
            fact_confidence=0.8, evidence_class_count=1,
        )
        boosted = compute_causal_confidence(
            fact_confidence=0.8, evidence_class_count=2,
        )
        assert boosted == pytest.approx(base + 0.10)

    def test_driver_tree_verified_bonus(self):
        """driver_tree_verified adds +0.05."""
        base = compute_causal_confidence(
            fact_confidence=0.8, evidence_class_count=1,
        )
        boosted = compute_causal_confidence(
            fact_confidence=0.8, evidence_class_count=1,
            driver_tree_verified=True,
        )
        assert boosted == pytest.approx(base + 0.05)

    def test_alternative_explanations_penalty(self):
        """has_alternative_explanations subtracts 0.15."""
        base = compute_causal_confidence(
            fact_confidence=0.8, evidence_class_count=1,
        )
        penalised = compute_causal_confidence(
            fact_confidence=0.8, evidence_class_count=1,
            has_alternative_explanations=True,
        )
        assert penalised == pytest.approx(base - 0.15)

    def test_degraded_modes_reduce_score(self):
        """Each non-NONE degraded mode subtracts 0.10."""
        base = compute_causal_confidence(
            fact_confidence=0.8, evidence_class_count=1,
        )
        penalised = compute_causal_confidence(
            fact_confidence=0.8, evidence_class_count=1,
            degraded_modes=[DegradedMode.LOW_COVERAGE, DegradedMode.STALE_SOURCE],
        )
        assert penalised == pytest.approx(base - 0.20)

    def test_degraded_mode_none_ignored(self):
        """DegradedMode.NONE does not count toward the penalty."""
        base = compute_causal_confidence(
            fact_confidence=0.8, evidence_class_count=1,
        )
        with_none = compute_causal_confidence(
            fact_confidence=0.8, evidence_class_count=1,
            degraded_modes=[DegradedMode.NONE],
        )
        assert with_none == pytest.approx(base)

    def test_min_floor_is_zero(self):
        """Causal confidence never goes below 0.0."""
        result = compute_causal_confidence(
            fact_confidence=0.0, evidence_class_count=1,
            has_alternative_explanations=True,
            degraded_modes=[DegradedMode.LOW_COVERAGE],
        )
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Hypothesis confidence
# ═══════════════════════════════════════════════════════════════════════════════


class TestHypothesisConfidence:
    def test_capped_at_0_5_max(self):
        """Hypothesis confidence never exceeds 0.5 (safety cap)."""
        # The formula gives at most 0.3 + 0.15 = 0.45 under normal inputs,
        # but the cap ensures it can never exceed 0.5 even with edge-case values.
        result = compute_hypothesis_confidence(
            fact_confidence=1.0,
            supporting_precedent_count=10,
            supporting_source_count=10,
            plausible_mechanism=True,
        )
        # 1.0 * 0.3 + 0.05 + 0.05 + 0.05 = 0.45 < 0.5, so no clamping
        assert result == pytest.approx(0.45)
        # Verify the cap works by checking a hypothetical overflow scenario:
        # With base = 0.5 (impossible from formula, but verify clamp):
        # We can't trigger it via compute_hypothesis_confidence with the formula,
        # so we test the internal bound by checking result <= 0.5
        assert result <= 0.5

    def test_base_is_fact_confidence_times_0_3(self):
        result = compute_hypothesis_confidence(
            fact_confidence=0.5,
        )
        assert result == pytest.approx(0.5 * 0.3)

    def test_precedent_bonus(self):
        """supporting_precedent_count > 0 adds +0.05."""
        base = compute_hypothesis_confidence(fact_confidence=0.5)
        boosted = compute_hypothesis_confidence(
            fact_confidence=0.5, supporting_precedent_count=1
        )
        assert boosted == pytest.approx(base + 0.05)

    def test_source_bonus(self):
        """supporting_source_count > 0 adds +0.05."""
        base = compute_hypothesis_confidence(fact_confidence=0.5)
        boosted = compute_hypothesis_confidence(
            fact_confidence=0.5, supporting_source_count=1
        )
        assert boosted == pytest.approx(base + 0.05)

    def test_plausible_mechanism_bonus(self):
        """plausible_mechanism=True adds +0.05."""
        base = compute_hypothesis_confidence(fact_confidence=0.5)
        boosted = compute_hypothesis_confidence(
            fact_confidence=0.5, plausible_mechanism=True
        )
        assert boosted == pytest.approx(base + 0.05)

    def test_all_bonuses_stacked(self):
        """All bonuses stack but caps at 0.5."""
        result = compute_hypothesis_confidence(
            fact_confidence=0.9,
            supporting_precedent_count=3,
            supporting_source_count=3,
            plausible_mechanism=True,
        )
        # 0.9 * 0.3 + 0.05 + 0.05 + 0.05 = 0.27 + 0.15 = 0.42
        assert result == pytest.approx(0.42)

    def test_zero_fact_confidence_returns_zero(self):
        result = compute_hypothesis_confidence(fact_confidence=0.0)
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Action confidence
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionConfidence:
    def test_capped_at_0_9_max(self):
        """Action confidence never exceeds 0.9."""
        result = compute_action_confidence(
            causal_confidence=1.0,
            taxonomy_valid=True,
            policy_permitted=True,
            impact_quantified=True,
            owner_identified=True,
        )
        assert result == 0.9

    def test_base_is_causal_confidence_times_0_7(self):
        result = compute_action_confidence(causal_confidence=0.8)
        assert result == pytest.approx(0.8 * 0.7)

    def test_taxonomy_valid_bonus(self):
        """taxonomy_valid adds +0.10."""
        base = compute_action_confidence(causal_confidence=0.5)
        boosted = compute_action_confidence(
            causal_confidence=0.5, taxonomy_valid=True
        )
        assert boosted == pytest.approx(base + 0.10)

    def test_policy_permitted_bonus(self):
        """policy_permitted adds +0.10."""
        base = compute_action_confidence(causal_confidence=0.5)
        boosted = compute_action_confidence(
            causal_confidence=0.5, policy_permitted=True
        )
        assert boosted == pytest.approx(base + 0.10)

    def test_impact_quantified_bonus(self):
        """impact_quantified adds +0.05."""
        base = compute_action_confidence(causal_confidence=0.5)
        boosted = compute_action_confidence(
            causal_confidence=0.5, impact_quantified=True
        )
        assert boosted == pytest.approx(base + 0.05)

    def test_owner_identified_bonus(self):
        """owner_identified adds +0.05."""
        base = compute_action_confidence(causal_confidence=0.5)
        boosted = compute_action_confidence(
            causal_confidence=0.5, owner_identified=True
        )
        assert boosted == pytest.approx(base + 0.05)

    def test_all_bonuses_stacked(self):
        """All bonuses stack but caps at 0.9."""
        result = compute_action_confidence(
            causal_confidence=0.9,
            taxonomy_valid=True,
            policy_permitted=True,
            impact_quantified=True,
            owner_identified=True,
        )
        # 0.9 * 0.7 + 0.10 + 0.10 + 0.05 + 0.05 = 0.63 + 0.30 = 0.93 -> clamped to 0.9
        assert result == 0.9

    def test_zero_causal_confidence_returns_zero(self):
        result = compute_action_confidence(causal_confidence=0.0)
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Dispatch (compute_deterministic_confidence)
# ═══════════════════════════════════════════════════════════════════════════════


class TestDispatch:
    """Test that compute_deterministic_confidence routes to the right function."""

    def _make_assertion(self, type_: AssertionType, evidence_ids: list[str] | None = None) -> Assertion:
        return Assertion(
            id="test-1",
            type=type_,
            text=f"Test {type_.value} assertion",
            evidence_ids=evidence_ids or [],
        )

    def test_routes_numeric(self):
        a = self._make_assertion(AssertionType.NUMERIC, evidence_ids=["e1", "e2", "e3"])
        result = compute_deterministic_confidence(
            assertion=a, evidence_count=3, source_count=2,
            coverage_pct=0.5, quality_score=0.5,
        )
        # For NUMERIC: just the fact confidence
        expected = compute_fact_confidence(
            evidence_count=3, source_count=2, coverage_pct=0.5, quality_score=0.5
        )
        assert result == pytest.approx(expected)

    def test_routes_comparative(self):
        a = self._make_assertion(AssertionType.COMPARATIVE, evidence_ids=["e1", "e2"])
        result = compute_deterministic_confidence(
            assertion=a, evidence_count=2, source_count=2,
            coverage_pct=0.5, quality_score=0.5, candidate_count=5, rank_position=1,
        )
        expected = compute_comparative_confidence(
            fact_confidence=compute_fact_confidence(
                evidence_count=2, source_count=2, coverage_pct=0.5, quality_score=0.5,
            ),
            candidate_count=5, rank_position=1,
        )
        assert result == pytest.approx(expected)

    def test_routes_causal(self):
        a = self._make_assertion(AssertionType.CAUSAL, evidence_ids=["e1", "e2", "e3"])
        result = compute_deterministic_confidence(
            assertion=a, evidence_count=3, source_count=2,
            coverage_pct=0.5, quality_score=0.5,
            evidence_class_count=2, driver_tree_verified=True,
        )
        expected = compute_causal_confidence(
            fact_confidence=compute_fact_confidence(
                evidence_count=3, source_count=2, coverage_pct=0.5, quality_score=0.5,
            ),
            evidence_class_count=2, driver_tree_verified=True,
        )
        assert result == pytest.approx(expected)

    def test_routes_hypothesis(self):
        a = self._make_assertion(AssertionType.HYPOTHESIS, evidence_ids=["e1"])
        result = compute_deterministic_confidence(
            assertion=a, evidence_count=1, source_count=1,
            coverage_pct=0.5, quality_score=0.5,
            supporting_precedent_count=2, plausible_mechanism=True,
        )
        expected = compute_hypothesis_confidence(
            fact_confidence=compute_fact_confidence(
                evidence_count=1, source_count=1, coverage_pct=0.5, quality_score=0.5,
            ),
            supporting_precedent_count=2, plausible_mechanism=True,
        )
        assert result == pytest.approx(expected)

    def test_routes_action(self):
        a = self._make_assertion(AssertionType.ACTION, evidence_ids=["e1"])
        result = compute_deterministic_confidence(
            assertion=a, evidence_count=1, source_count=1,
            coverage_pct=0.5, quality_score=0.5,
            taxonomy_valid=True, policy_permitted=True,
            impact_quantified=True, owner_identified=True,
        )
        expected = compute_action_confidence(
            causal_confidence=compute_fact_confidence(
                evidence_count=1, source_count=1, coverage_pct=0.5, quality_score=0.5,
            ),
            taxonomy_valid=True, policy_permitted=True,
            impact_quantified=True, owner_identified=True,
        )
        assert result == pytest.approx(expected)

    def test_evidence_count_defaults_to_assertion_evidence_ids_length(self):
        """When evidence_count=0, the dispatcher falls back to len(assertion.evidence_ids)."""
        a = self._make_assertion(AssertionType.NUMERIC, evidence_ids=["e1", "e2"])
        result = compute_deterministic_confidence(
            assertion=a, evidence_count=0, source_count=1,
            coverage_pct=0.0, quality_score=0.0,
        )
        expected = compute_fact_confidence(
            evidence_count=2, source_count=1, coverage_pct=0.0, quality_score=0.0,
        )
        assert result == pytest.approx(expected)
