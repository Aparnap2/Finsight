from unittest.mock import MagicMock
from backend.agents.commentary_agent import generate_commentary, commentary_node
from backend.models.state import CommentaryDraft, RootCauseFinding, PipelineState


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


def test_commentary_has_required_sections():
    draft = generate_commentary([], [])
    section_types = [s.section_type for s in draft.sections]
    assert "executive_summary" in section_types
    assert "revenue" in section_types
    assert "cost" in section_types


def test_commentary_generated_at_present():
    draft = generate_commentary([], [])
    assert draft.generated_at is not None
    assert "2026" in draft.generated_at


def test_commentary_node_returns_draft():
    state = _make_state(
        root_causes=[
            RootCauseFinding(
                variance_id="4001", summary="Test finding",
                confidence_score=0.8,
            )
        ]
    )
    result = commentary_node(state)
    assert result["commentary_draft"] is not None
    assert result["current_step"] == "commentary_complete"


def test_commentary_uses_llm_when_provided():
    mock_llm = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Revenue declined 12% due to deal slippage in EMEA region."))]
    mock_llm.chat.completions.create.return_value = mock_response

    root_causes = [
        RootCauseFinding(
            variance_id="v1", summary="Revenue shortfall",
            confidence_score=0.85,
            recommended_action="Investigate deal pipeline",
        )
    ]
    draft = generate_commentary(root_causes, [], llm_client=mock_llm)
    assert isinstance(draft, CommentaryDraft)
    mock_llm.chat.completions.create.assert_called()


def test_commentary_falls_back_without_llm():
    draft = generate_commentary([], [])
    has_placeholder = any("pending" in s.content.lower() for s in draft.sections)
    assert has_placeholder, "Without LLM, commentary should have placeholder content"


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
    client = OpenAI(
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )
    root_causes = [
        RootCauseFinding(
            variance_id="7000", summary="Cloud infrastructure costs up 35% due to unplanned scaling",
            confidence_score=0.8,
            recommended_action="Review AWS cost explorer for right-sizing opportunities",
        ),
        RootCauseFinding(
            variance_id="4001", summary="Revenue shortfall from delayed EMEA enterprise deals",
            confidence_score=0.75,
            recommended_action="Accelerate deal closings with updated proposals",
        ),
    ]
    draft = generate_commentary(root_causes, [], llm_client=client)
    assert isinstance(draft, CommentaryDraft)
    assert len(draft.sections) >= 3, f"Expected >=3 sections, got {len(draft.sections)}"
    section_types = [s.section_type for s in draft.sections]
    assert "executive_summary" in section_types
    for s in draft.sections:
        assert len(s.content) > 10, f"Section {s.section_type} too short"
