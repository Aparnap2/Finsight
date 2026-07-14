from datetime import datetime, timezone
from backend.models.state import PipelineState, RootCauseFinding, CommentaryDraft, CommentarySection


def generate_commentary(
    root_causes: list[RootCauseFinding],
    variances: list[dict],
) -> CommentaryDraft:
    sections = [
        CommentarySection(
            section_type="executive_summary",
            content="Analysis pending — commentary will be generated after root-cause investigation.",
            cited_data_points=[],
        ),
        CommentarySection(
            section_type="revenue",
            content="Revenue analysis pending.",
            cited_data_points=[],
        ),
        CommentarySection(
            section_type="cost",
            content="Cost analysis pending.",
            cited_data_points=[],
        ),
    ]
    return CommentaryDraft(
        sections=sections,
        generated_at=datetime.now(timezone.utc).isoformat(),
        version=1,
        status="draft",
    )


def commentary_node(state: PipelineState) -> dict:
    root_causes = state.get("root_causes", [])
    variances = state.get("variances", [])
    draft = generate_commentary(root_causes, variances)
    return {"commentary_draft": draft, "current_step": "commentary_complete"}
