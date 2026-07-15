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
