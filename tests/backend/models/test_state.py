from backend.models.state import PipelineState, Variance, RootCauseFinding, CommentaryDraft, Scenario


def test_variance_creation():
    v = Variance(
        account_id="4000",
        account_name="Revenue - Product X",
        department="Sales",
        actual_amount=100000,
        budget_amount=120000,
        variance_amount=-20000,
        variance_pct=-16.67,
        is_material=True,
        classification="timing",
        confidence_score=0.85,
    )
    assert v.is_material is True
    assert v.variance_pct == -16.67


def test_pipeline_state_creation():
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
    assert state["variances"] == []


def test_commentary_draft_sections():
    cd = CommentaryDraft(
        sections=[],
        generated_at="2026-07-01T00:00:00Z",
        version=1,
        status="draft",
    )
    assert cd.status == "draft"
