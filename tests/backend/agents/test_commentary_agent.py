"""Tests for the commentary rendering layer.

Tests focus on the assertion-based rendering architecture:
- CommentaryRenderInput partitioning and construction
- Prompt building with proper constraints
- Fallback rendering without LLM
- Post-rendering validation behavior
"""

from unittest.mock import MagicMock, patch
from decimal import Decimal

from backend.models.assertions import Assertion, AssertionType, SupportLevel
from backend.agents.commentary_agent import (
    CommentaryRenderInput,
    build_render_prompt,
    render_commentary,
    _fallback_render,
    _format_assertions,
    _format_degraded_modes,
)
from backend.agents.llm_client import LLMClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assertion(
    text: str,
    type_: AssertionType = AssertionType.NUMERIC,
    support: SupportLevel = SupportLevel.VERIFIED,
    confidence: float = 0.95,
    id_: str | None = None,
) -> Assertion:
    return Assertion(
        id=id_ or f"test-{hash(text)}",
        type=type_,
        text=text,
        support_level=support,
        confidence=confidence,
    )


def _make_verified(text: str, **kw) -> Assertion:
    return _make_assertion(text, support=SupportLevel.VERIFIED, **kw)


def _make_probable(text: str, **kw) -> Assertion:
    return _make_assertion(text, support=SupportLevel.PROBABLE, confidence=0.65, **kw)


def _make_weak(text: str, **kw) -> Assertion:
    return _make_assertion(text, support=SupportLevel.WEAK, confidence=0.35, **kw)


# ---------------------------------------------------------------------------
# CommentaryRenderInput
# ---------------------------------------------------------------------------


class TestCommentaryRenderInput:
    """Tests for CommentaryRenderInput — the typed gateway for assertion data."""

    def test_commentary_render_input_partitions_by_support(self):
        """Assertions are partitioned into verified/probable/weak by support_level."""
        verified = [_make_verified("Revenue increased 12%")]
        probable = [_make_probable("Cost pressure from supplier price hikes")]
        weak = [_make_weak("Possible FX impact")]
        weak_insufficient = _make_assertion(
            "Unclear impact from new tariff",
            support=SupportLevel.INSUFFICIENT,
            confidence=0.2,
        )

        inp = CommentaryRenderInput(
            verified_assertions=verified,
            probable_assertions=probable,
            weak_assertions=[weak_insufficient] + weak,
        )

        assert inp.verified_assertions == verified
        assert inp.probable_assertions == probable
        assert inp.weak_assertions == [weak_insufficient] + weak
        assert len(inp.all_assertions) == 4

    def test_commentary_render_input_from_assertion_list(self):
        """from_assertion_list partitions a flat list correctly."""
        v = _make_verified("Revenue up 10%")
        p = _make_probable("Supply chain disruption")
        w = _make_weak("FX headwind hypothesis")
        ins = _make_assertion(
            "Unclear regulatory effect",
            support=SupportLevel.INSUFFICIENT,
            confidence=0.1,
        )

        inp = CommentaryRenderInput.from_assertion_list(
            assertions=[v, p, w, ins],
            period="2026-Q2",
            entity_name="TestCorp",
        )

        assert inp.verified_assertions == [v]
        assert inp.probable_assertions == [p]
        assert len(inp.weak_assertions) == 2  # WEAK + INSUFFICIENT
        assert w in inp.weak_assertions
        assert ins in inp.weak_assertions
        assert inp.period == "2026-Q2"
        assert inp.entity_name == "TestCorp"

    def test_commentary_render_input_from_assertion_list_empty(self):
        """from_assertion_list with empty list produces empty partitions."""
        inp = CommentaryRenderInput.from_assertion_list([])
        assert inp.verified_assertions == []
        assert inp.probable_assertions == []
        assert inp.weak_assertions == []

    def test_commentary_render_input_properties(self):
        """all_assertions and has_degraded_modes properties work correctly."""
        v = _make_verified("Fact 1")
        p = _make_probable("Cause 1")

        # With degraded modes
        inp1 = CommentaryRenderInput(
            verified_assertions=[v],
            probable_assertions=[p],
            weak_assertions=[],
            degraded_modes=["missing_fx", "low_coverage"],
        )
        assert inp1.has_degraded_modes is True
        assert len(inp1.all_assertions) == 2

        # Without degraded modes
        inp2 = CommentaryRenderInput(
            verified_assertions=[v],
            probable_assertions=[],
            weak_assertions=[],
            degraded_modes=None,
        )
        assert inp2.has_degraded_modes is False
        assert len(inp2.all_assertions) == 1

        # Empty
        inp3 = CommentaryRenderInput(
            verified_assertions=[],
            probable_assertions=[],
            weak_assertions=[],
        )
        assert inp3.has_degraded_modes is False
        assert inp3.all_assertions == []

    def test_commentary_render_input_default_sections(self):
        """Default required_sections includes executive_summary and variance_analysis."""
        inp = CommentaryRenderInput(
            verified_assertions=[],
            probable_assertions=[],
            weak_assertions=[],
        )
        assert "executive_summary" in inp.required_sections
        assert "variance_analysis" in inp.required_sections
        assert len(inp.required_sections) == 2


# ---------------------------------------------------------------------------
# build_render_prompt
# ---------------------------------------------------------------------------


class TestBuildRenderPrompt:
    """Tests for the prompt builder — the constraint layer for LLM rendering."""

    def test_build_render_prompt_includes_all_sections(self):
        """Prompt contains all required sections as rendering targets."""
        v = _make_verified("Revenue increased 12% to $50M")
        p = _make_probable("Volume decline in EMEA region")
        inp = CommentaryRenderInput(
            verified_assertions=[v],
            probable_assertions=[p],
            weak_assertions=[],
            entity_name="Acme Corp",
            period="2026-Q2",
        )

        prompt = build_render_prompt(inp)

        assert "Acme Corp" in prompt
        assert "2026-Q2" in prompt
        assert "VERIFIED FACTS" in prompt
        assert "PROBABLE CAUSES" in prompt
        assert "HYPOTHESES / UNCERTAIN" in prompt
        assert "Executive Summary" in prompt
        assert "Variance Analysis" in prompt
        assert "Revenue increased 12% to $50M" in prompt
        assert "Volume decline in EMEA region" in prompt
        assert "You may NOT invent any values" in prompt
        assert "You may NOT merge hypotheses into facts" in prompt

    def test_build_render_prompt_no_assertions(self):
        """Prompt handles empty assertion lists gracefully."""
        inp = CommentaryRenderInput(
            verified_assertions=[],
            probable_assertions=[],
            weak_assertions=[],
            entity_name="Test",
            period="2026-Q2",
        )

        prompt = build_render_prompt(inp)

        assert "VERIFIED FACTS" in prompt
        assert "PROBABLE CAUSES" in prompt
        assert "HYPOTHESES / UNCERTAIN" in prompt
        assert "(none)" in prompt
        assert "Test" in prompt

    def test_build_render_prompt_includes_degraded_modes(self):
        """Degraded modes are included in the prompt when present."""
        inp = CommentaryRenderInput(
            verified_assertions=[],
            probable_assertions=[],
            weak_assertions=[],
            degraded_modes=["missing_fx", "low_coverage"],
        )

        prompt = build_render_prompt(inp)

        assert "DEGRADED MODES" in prompt
        assert "Missing Fx" in prompt
        assert "Low Coverage" in prompt
        assert "Data quality is reduced" in prompt

    def test_build_render_prompt_confidence_language_guidance(self):
        """Prompt includes confidence-based language calibration rules."""
        inp = CommentaryRenderInput(
            verified_assertions=[_make_verified("Fact")],
            probable_assertions=[],
            weak_assertions=[],
        )

        prompt = build_render_prompt(inp)

        assert "Confidence >= 0.8" in prompt
        assert "Confidence 0.5-0.8" in prompt
        assert "Confidence < 0.5" in prompt

    def test_build_render_prompt_weak_caveat_rule(self):
        """Prompt includes caveat requirement when weak assertions present."""
        inp = CommentaryRenderInput(
            verified_assertions=[_make_verified("Fact")],
            probable_assertions=[],
            weak_assertions=[_make_weak("Hypothesis")],
        )

        prompt = build_render_prompt(inp)

        assert "include a caveat" in prompt
        assert "require further investigation" in prompt

    def test_build_render_prompt_custom_sections(self):
        """Custom required_sections appear in the prompt."""
        inp = CommentaryRenderInput(
            verified_assertions=[_make_verified("Fact")],
            probable_assertions=[],
            weak_assertions=[],
            required_sections=["executive_summary", "risk_assessment", "outlook"],
        )

        prompt = build_render_prompt(inp)

        assert "Executive Summary" in prompt
        assert "Risk Assessment" in prompt
        assert "Outlook" in prompt


# ---------------------------------------------------------------------------
# _format_assertions and _format_degraded_modes
# ---------------------------------------------------------------------------


class TestFormatUtilities:
    """Tests for formatting helpers used in prompt building."""

    def test_format_assertions_shows_none_when_empty(self):
        result = _format_assertions([], "TEST HEADER")
        assert "TEST HEADER" in result
        assert "(none)" in result

    def test_format_assertions_includes_type_and_confidence(self):
        a = _make_verified("Revenue $50M", confidence=0.92)
        result = _format_assertions([a], "FACTS")
        assert "[numeric]" in result
        assert "Revenue $50M" in result
        assert "confidence=0.92" in result
        assert "support=verified" in result

    def test_format_assertions_multiple_assertions(self):
        a1 = _make_verified("Fact 1")
        a2 = _make_probable("Cause 1")
        result = _format_assertions([a1, a2], "ITEMS")
        assert "Fact 1" in result
        assert "Cause 1" in result
        assert "ITEMS" in result

    def test_format_degraded_modes_shows_none_when_empty(self):
        result = _format_degraded_modes([])
        assert "DEGRADED MODES" in result
        assert "(none)" in result

    def test_format_degraded_modes_shows_items(self):
        result = _format_degraded_modes(["missing_fx", "low_coverage"])
        assert "Missing Fx" in result
        assert "Low Coverage" in result
        assert "Data quality is reduced" in result


# ---------------------------------------------------------------------------
# _fallback_render
# ---------------------------------------------------------------------------


class TestFallbackRender:
    """Tests for the non-LLM fallback renderer."""

    def test_fallback_render_includes_all_sections(self):
        """Fallback render produces structured output with all standard sections."""
        v = _make_verified("Revenue increased 12% to $50M", type_=AssertionType.NUMERIC)
        p = _make_probable("Supply chain disruption", type_=AssertionType.CAUSAL)
        w = _make_weak("Possible FX impact", type_=AssertionType.HYPOTHESIS)

        inp = CommentaryRenderInput(
            verified_assertions=[v],
            probable_assertions=[p],
            weak_assertions=[w],
            period="2026-Q2",
            entity_name="Acme Corp",
        )

        text = _fallback_render(inp)

        assert "Financial Commentary — Acme Corp" in text
        assert "Period: 2026-Q2" in text
        assert "Executive Summary" in text
        assert "Variance Analysis" in text
        assert "Root Causes" in text
        assert "Areas for Further Investigation" in text
        assert "Revenue increased 12% to $50M" in text
        assert "Supply chain disruption" in text
        assert "Possible FX impact" in text

    def test_fallback_render_only_verified_assertions(self):
        """Fallback with only verified data omits cause/hypothesis sections."""
        v = _make_verified("Revenue increased 12%", type_=AssertionType.NUMERIC)
        v2 = _make_verified(
            "Costs decreased 5%", type_=AssertionType.COMPARATIVE
        )

        inp = CommentaryRenderInput(
            verified_assertions=[v, v2],
            probable_assertions=[],
            weak_assertions=[],
        )

        text = _fallback_render(inp)

        assert "Executive Summary" in text
        assert "Variance Analysis" in text
        assert "Root Causes" not in text
        assert "Areas for Further Investigation" not in text

    def test_fallback_render_with_degraded_modes(self):
        """Degraded modes section appears when modes are present."""
        v = _make_verified("Revenue $50M")

        inp = CommentaryRenderInput(
            verified_assertions=[v],
            probable_assertions=[],
            weak_assertions=[],
            degraded_modes=["missing_fx", "stale_source"],
        )

        text = _fallback_render(inp)

        assert "Data Quality Notes" in text
        assert "Missing Fx" in text
        assert "Stale Source" in text
        assert "Limited data availability" in text

    def test_fallback_render_no_assertions(self):
        """Fallback with no assertions produces minimal structure."""
        inp = CommentaryRenderInput(
            verified_assertions=[],
            probable_assertions=[],
            weak_assertions=[],
            entity_name="EmptyCorp",
        )

        text = _fallback_render(inp)

        assert "Financial Commentary — EmptyCorp" in text
        assert "Executive Summary" in text
        assert "Variance Analysis" in text
        # No content lines under the sections
        lines = text.split("\n")
        summary_idx = lines.index("## Executive Summary")
        variance_idx = lines.index("## Variance Analysis")
        # There should be content between headings, or empty lines
        summary_content = lines[summary_idx + 1 : variance_idx]
        assert all(l.strip() == "" for l in summary_content if l.strip())

    def test_fallback_render_counts_material_variances(self):
        """Multiple NUMERIC assertions produce a count line in summary."""
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

    def test_fallback_render_probable_with_confidence(self):
        """Probable assertions include confidence percentage."""
        p = _make_probable("Price increase impact", type_=AssertionType.CAUSAL)

        inp = CommentaryRenderInput(
            verified_assertions=[_make_verified("Revenue change")],
            probable_assertions=[p],
            weak_assertions=[],
        )

        text = _fallback_render(inp)

        assert "65%" in text  # 0.65 formatted as 65%

    def test_fallback_render_hypothesis_count(self):
        """Weak assertions produce a hypothesis count in summary."""
        w1 = _make_weak("Hypothesis A")
        w2 = _make_weak("Hypothesis B")

        inp = CommentaryRenderInput(
            verified_assertions=[_make_verified("Fact")],
            probable_assertions=[],
            weak_assertions=[w1, w2],
        )

        text = _fallback_render(inp)

        assert "2 hypotheses require further investigation" in text


# ---------------------------------------------------------------------------
# render_commentary
# ---------------------------------------------------------------------------


class TestRenderCommentary:
    """Tests for the main render_commentary function."""

    def test_render_commentary_no_llm_uses_fallback(self):
        """Without LLM client, render_commentary uses fallback render."""
        inp = CommentaryRenderInput(
            verified_assertions=[_make_verified("Revenue up 10%")],
            probable_assertions=[],
            weak_assertions=[],
            entity_name="Test",
            period="2026-Q2",
        )

        result = render_commentary(inp, llm_client=None)

        assert isinstance(result, str)
        assert "Financial Commentary — Test" in result
        assert "Revenue up 10%" in result

    def test_render_commentary_no_assertions_uses_fallback(self):
        """With no assertions, even if LLM client given, uses fallback."""
        mock_llm = MagicMock(spec=LLMClient)

        inp = CommentaryRenderInput(
            verified_assertions=[],
            probable_assertions=[],
            weak_assertions=[],
        )

        result = render_commentary(inp, llm_client=mock_llm)

        # Should use fallback since all_assertions is empty
        assert isinstance(result, str)
        mock_llm.generate.assert_not_called()

    def test_render_commentary_with_llm_returns_text(self):
        """With LLM client and assertions, calls generate and returns text."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate.return_value = (
            "## Executive Summary\nRevenue increased 12%.\n\n"
            "## Variance Analysis\nRevenue variance of $5M.\n"
        )

        inp = CommentaryRenderInput(
            verified_assertions=[_make_verified("Revenue increased 12%")],
            probable_assertions=[],
            weak_assertions=[],
        )

        result = render_commentary(inp, llm_client=mock_llm)

        assert isinstance(result, str)
        mock_llm.generate.assert_called_once()
        assert "Executive Summary" in result
        assert "Revenue increased 12%" in result

    def test_render_commentary_llm_fallback_on_error(self):
        """When LLM call fails, falls back to deterministic rendering."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate.side_effect = RuntimeError("API failure")

        inp = CommentaryRenderInput(
            verified_assertions=[_make_verified("Revenue up 10%")],
            probable_assertions=[],
            weak_assertions=[],
            entity_name="SafeCorp",
        )

        result = render_commentary(inp, llm_client=mock_llm)

        assert isinstance(result, str)
        assert "Financial Commentary — SafeCorp" in result
        assert "Revenue up 10%" in result

    def test_render_commentary_prompt_passed_to_llm(self):
        """The built render prompt is correctly passed to the LLM."""
        mock_llm = MagicMock(spec=LLMClient)
        mock_llm.generate.return_value = "Rendered output"

        v = _make_verified("Revenue $50M")
        inp = CommentaryRenderInput(
            verified_assertions=[v],
            probable_assertions=[],
            weak_assertions=[],
            entity_name="PromptCheck",
        )

        render_commentary(inp, llm_client=mock_llm)

        prompt_arg = mock_llm.generate.call_args[0][0]
        assert "PromptCheck" in prompt_arg
        assert "Revenue $50M" in prompt_arg
        assert "You may NOT invent any values" in prompt_arg


# ---------------------------------------------------------------------------
# Integration: prompt → render cycle
# ---------------------------------------------------------------------------


class TestRenderCycle:
    """End-to-end rendering cycle from assertions to final text."""

    def test_full_cycle_no_llm(self):
        """Full cycle: from assertion list to rendered text via fallback."""
        assertions = [
            _make_verified(
                "Revenue increased 12.3% to $52.1M",
                type_=AssertionType.NUMERIC,
            ),
            _make_verified(
                "Cost of goods sold decreased 2.1%",
                type_=AssertionType.COMPARATIVE,
            ),
            _make_probable(
                "Volume improvement from new product launch",
                type_=AssertionType.CAUSAL,
            ),
            _make_weak(
                "FX tailwind from EUR/USD movement may have contributed",
                type_=AssertionType.HYPOTHESIS,
            ),
        ]

        inp = CommentaryRenderInput.from_assertion_list(
            assertions=assertions,
            degraded_modes=["preliminary_only"],
            period="2026-Q2",
            entity_name="Acme Corp",
        )

        text = render_commentary(inp, llm_client=None)

        assert "Financial Commentary — Acme Corp" in text
        assert "Period: 2026-Q2" in text
        assert "Revenue increased 12.3% to $52.1M" in text
        assert "Cost of goods sold decreased 2.1%" in text
        assert "Volume improvement from new product launch" in text
        assert "FX tailwind" in text
        assert "Data Quality Notes" in text
        assert "Preliminary Only" in text

    def test_full_cycle_all_verified(self):
        """Only verified assertions produce focused summary."""
        assertions = [
            _make_verified("Revenue $100M", type_=AssertionType.NUMERIC),
            _make_verified("Budget $95M", type_=AssertionType.NUMERIC),
        ]

        inp = CommentaryRenderInput.from_assertion_list(
            assertions=assertions,
            period="2026-Q2",
        )

        text = render_commentary(inp, llm_client=None)

        assert "Root Causes" not in text
        assert "Areas for Further Investigation" not in text
        assert "2 material variances identified" in text

    def test_full_cycle_only_hypotheses(self):
        """Only weak assertions produce caveats and no facts section content."""
        assertions = [
            _make_weak("Possible market shift", type_=AssertionType.HYPOTHESIS),
        ]

        inp = CommentaryRenderInput.from_assertion_list(
            assertions=assertions,
        )

        text = render_commentary(inp, llm_client=None)

        assert "Executive Summary" in text
        assert "1 hypotheses require further investigation" in text
