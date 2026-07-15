from datetime import datetime, timezone
from backend.models.state import PipelineState, RootCauseFinding, CommentaryDraft, CommentarySection


def _build_prompt(root_causes: list[RootCauseFinding], variances: list[dict]) -> str:
    rc_text = "\n".join(
        f"- {rc.summary} (confidence: {rc.confidence_score})"
        for rc in root_causes
    ) or "None"
    return (
        "You are a senior FP&A analyst writing monthly commentary for the CFO.\n"
        "Respond in EXACTLY this format — no markdown, no headers, no extra text:\n\n"
        "EXECUTIVE_SUMMARY: <2-3 sentences overview of month performance>\n"
        "REVENUE: <1-2 sentences on revenue vs budget>\n"
        "COST: <1-2 sentences on cost drivers>\n"
        "CASH: <1 sentence on cash position>\n"
        "RISKS: <1-2 sentences on key risks>\n"
        "ACTIONS: <1-2 sentences on next steps>\n\n"
        "--- ROOT CAUSES ---\n"
        f"{rc_text}\n"
        "-------------------\n"
        "Respond now:"
    )


def _parse_llm_response(text: str) -> list[CommentarySection]:
    import re
    sections = []
    section_map = {
        "EXECUTIVE_SUMMARY": "executive_summary",
        "REVENUE": "revenue",
        "COST": "cost",
        "CASH": "cash",
        "RISKS": "risks",
        "ACTIONS": "actions",
    }
    for key, section_type in section_map.items():
        m = re.search(rf'{key}:\s*(.+?)(?=\n[A-Z_]+:|\Z)', text, re.IGNORECASE | re.DOTALL)
        if m:
            content = m.group(1).strip()
            if content:
                sections.append(CommentarySection(
                    section_type=section_type,
                    content=content,
                ))
    return sections


def generate_commentary(
    root_causes: list[RootCauseFinding],
    variances: list[dict],
    llm_client=None,
) -> CommentaryDraft:
    if llm_client:
        prompt = _build_prompt(root_causes, variances)
        response = llm_client.chat.completions.create(
            model="google/gemma-4-26b-a4b-it:free",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            temperature=0.3,
        )
        text = response.choices[0].message.content
        sections = _parse_llm_response(text)
        if not sections:
            sections = [
                CommentarySection(section_type="executive_summary", content=text),
            ]
    else:
        sections = [
            CommentarySection(
                section_type="executive_summary",
                content="Analysis pending — commentary will be generated after root-cause investigation.",
            ),
            CommentarySection(
                section_type="revenue",
                content="Revenue analysis pending.",
            ),
            CommentarySection(
                section_type="cost",
                content="Cost analysis pending.",
            ),
        ]
    return CommentaryDraft(
        sections=sections,
        generated_at=datetime.now(timezone.utc).isoformat(),
        version=1,
        status="draft",
    )


def commentary_node(state: PipelineState, llm_client=None) -> dict:
    root_causes = state.get("root_causes", [])
    variances = state.get("variances", [])
    draft = generate_commentary(root_causes, variances, llm_client=llm_client)
    return {"commentary_draft": draft, "current_step": "commentary_complete"}
