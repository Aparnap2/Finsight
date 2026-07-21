"""Tests for backward-compatible commentary API (generate_commentary / commentary_node).

These tests ensure the LangGraph node and generate_commentary wrapper
still work correctly with the new assertion-based rendering layer.
"""

from unittest.mock import MagicMock
from backend.agents.commentary_agent import (
    generate_commentary,
    commentary_node,
    CommentaryRenderInput,
)
from backend.models.state import CommentaryDraft, RootCauseFinding, PipelineState
from backend.models.assertions import Assertion, AssertionType, SupportLevel
from backend.agents.llm_client import LLMClient


def _make_state(**overrides) -> PipelineState:
    base: PipelineState = {
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
    base.update(overrides)
    return base


def test_generate_commentary_returns_draft():
    draft = generate_commentary([], [])
    assert isinstance(draft, CommentaryDraft)
    assert draft.status == "draft"
    assert draft.version == 1


def test_commentary_has_executive_summary():
    """The wrapper always produces at least an executive_summary section."""
    draft = generate_commentary([], [])
    section_types = [s.section_type for s in draft.sections]
    assert "executive_summary" in section_types


def test_commentary_generated_at_present():
    draft = generate_commentary([], [])
    assert draft.generated_at is not None
    assert "2026" in draft.generated_at


def test_commentary_node_returns_draft():
    state = _make_state(
        root_causes=[
            RootCauseFinding(
                variance_id="4001",
                summary="Test finding",
                confidence_score=0.8,
            )
        ]
    )
    result = commentary_node(state)
    assert result["commentary_draft"] is not None
    assert result["current_step"] == "commentary_complete"


def test_commentary_uses_llm_when_provided():
    """When LLMClient is provided with assertions, generate is called."""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.generate.return_value = (
        "## Executive Summary\nRevenue declined 12% due to deal slippage.\n"
        "## Variance Analysis\nRevenue variance of $5M.\n"
    )

    root_causes = [
        RootCauseFinding(
            variance_id="v1",
            summary="Revenue shortfall",
            confidence_score=0.85,
            recommended_action="Investigate deal pipeline",
            assertions=[
                Assertion(
                    id="a1",
                    type=AssertionType.NUMERIC,
                    text="Revenue declined 12% due to deal slippage in EMEA region",
                    support_level=SupportLevel.VERIFIED,
                    confidence=0.85,
                )
            ],
        )
    ]
    draft = generate_commentary(root_causes, [], llm_client=mock_llm)
    assert isinstance(draft, CommentaryDraft)
    mock_llm.generate.assert_called()


def test_commentary_falls_back_without_llm():
    """Without LLM, commentary uses the deterministic fallback renderer."""
    draft = generate_commentary([], [])
    assert isinstance(draft, CommentaryDraft)
    text = draft.sections[0].content
    assert "Financial Commentary" in text


def test_commentary_node_with_assertions_and_period():
    """commentary_node passes period and entity from state to the renderer."""
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.generate.return_value = (
        "## Executive Summary\nRevenue up 15% to $60M in Q2 2026.\n"
        "## Variance Analysis\nRevenue increased 15% to $60M.\n"
    )

    assertions = [
        Assertion(
            id="a1",
            type=AssertionType.NUMERIC,
            text="Revenue up 15% to $60M",
            support_level=SupportLevel.VERIFIED,
            confidence=0.92,
        )
    ]
    state = _make_state(
        period="2026-Q2",
        entity_id="ACME",
        root_causes=[
            RootCauseFinding(
                variance_id="v1",
                summary="Revenue growth",
                assertions=assertions,
                confidence_score=0.92,
            )
        ],
    )
    result = commentary_node(state, llm_client=mock_llm)
    draft = result["commentary_draft"]
    text = " ".join(s.content for s in draft.sections)
    assert "Revenue up 15% to $60M" in text
    # Mock LLM returned two sections; both should be present
    section_types = [s.section_type for s in draft.sections]
    assert "executive_summary" in section_types
    assert "variance_analysis" in section_types


import os
import pytest
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"),
    reason="OPENROUTER_API_KEY not set",
)
def test_commentary_real_llm_call():
    """Integration test with a real LLM through the renderer.

    This test constructs CommentaryRenderInput directly to test the
    full render_commentary path with an OpenAI client.
    """
    from backend.agents.commentary_agent import render_commentary

    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )

    # Wrap OpenAI client to match generate() interface
    class _LLMAdapter:
        def __init__(self, client: OpenAI):
            self._client = client
            self._model = "gpt-4o-mini"  # lightweight model

        def generate(self, prompt: str, max_tokens: int = 1024) -> str:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""

    adapter = _LLMAdapter(client)

    inp = CommentaryRenderInput(
        verified_assertions=[
            Assertion(
                id="a1",
                type=AssertionType.NUMERIC,
                text="Cloud infrastructure costs up 35% due to unplanned scaling",
                support_level=SupportLevel.VERIFIED,
                confidence=0.8,
            ),
            Assertion(
                id="a2",
                type=AssertionType.NUMERIC,
                text="Revenue shortfall from delayed EMEA enterprise deals",
                support_level=SupportLevel.VERIFIED,
                confidence=0.75,
            ),
        ],
        probable_assertions=[],
        weak_assertions=[],
    )

    text = render_commentary(inp, llm_client=adapter)
    assert isinstance(text, str)
    assert len(text) > 20
