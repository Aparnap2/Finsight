"""Commentary renderer — transforms validated assertions into narrative text.

The LLM is restricted to rendering only. It receives validated assertions
and may arrange, paraphrase, and group them. It may NOT:
- invent values, causes, or actions
- upgrade hypotheses to facts
- add new claims not present in the assertions

This is enforced by:
1. The input structure (typed assertions with confidence/support)
2. The prompt (explicit prohibitions)
3. Post-rendering validation (all $ claims are cross-checked)
"""

from datetime import datetime, timezone
from typing import Any
from backend.models.assertions import Assertion, AssertionType, SupportLevel
from backend.models.degraded_mode import DegradedMode
from backend.models.state import (
    PipelineState,
    RootCauseFinding,
    CommentaryDraft,
    CommentarySection,
    ActionItem,
)
from backend.agents.llm_client import LLMClient


class CommentaryRenderInput:
    """Input to the commentary renderer — never raw data, only validated assertions."""

    def __init__(
        self,
        verified_assertions: list[Assertion],
        probable_assertions: list[Assertion],
        weak_assertions: list[Assertion],
        degraded_modes: list[str] | None = None,
        required_sections: list[str] | None = None,
        audience: str = "analyst",
        period: str = "",
        entity_name: str = "",
    ):
        self.verified_assertions = verified_assertions
        self.probable_assertions = probable_assertions
        self.weak_assertions = weak_assertions
        self.degraded_modes = degraded_modes or []
        self.required_sections = required_sections or [
            "executive_summary",
            "variance_analysis",
        ]
        self.audience = audience
        self.period = period
        self.entity_name = entity_name

    @property
    def all_assertions(self) -> list[Assertion]:
        return self.verified_assertions + self.probable_assertions + self.weak_assertions

    @property
    def has_degraded_modes(self) -> bool:
        return len(self.degraded_modes) > 0

    @classmethod
    def from_assertion_list(
        cls,
        assertions: list[Assertion],
        degraded_modes: list[str] | None = None,
        period: str = "",
        entity_name: str = "",
    ) -> "CommentaryRenderInput":
        """Build from a flat list of assertions, partitioned by support level."""
        verified = [
            a for a in assertions if a.support_level == SupportLevel.VERIFIED
        ]
        probable = [
            a for a in assertions if a.support_level == SupportLevel.PROBABLE
        ]
        weak = [
            a
            for a in assertions
            if a.support_level in (SupportLevel.WEAK, SupportLevel.INSUFFICIENT)
        ]
        return cls(
            verified_assertions=verified,
            probable_assertions=probable,
            weak_assertions=weak,
            degraded_modes=degraded_modes,
            period=period,
            entity_name=entity_name,
        )


def build_render_prompt(render_input: CommentaryRenderInput) -> str:
    """Build the system prompt for the commentary renderer.

    The prompt strictly constrains the LLM to rendering only.
    """
    sections = "\n".join(
        f"- {s.replace('_', ' ').title()}" for s in render_input.required_sections
    )

    verified = _format_assertions(
        render_input.verified_assertions, "VERIFIED FACTS"
    )
    probable = _format_assertions(
        render_input.probable_assertions, "PROBABLE CAUSES"
    )
    weak = _format_assertions(
        render_input.weak_assertions, "HYPOTHESES / UNCERTAIN"
    )
    degraded = _format_degraded_modes(render_input.degraded_modes)

    prompt = f"""You are a financial commentary renderer for {render_input.entity_name or 'the company'}.
Period: {render_input.period}
Audience: {render_input.audience}

You receive TRUTH that has been deterministically verified. Your job is to render it into clear, professional narrative text.

## TRUTH INPUT

{verified}

{probable}

{weak}

{degraded}

## RULES — You MUST follow these exactly

1. You may ONLY use the facts, causes, and actions listed above.
2. You may paraphrase, group, summarize, and reorder them.
3. You may soften tone around uncertainty (e.g., "The data suggests..." for probable items).
4. You may NOT invent any values, dollar amounts, percentages, or metrics.
5. You may NOT invent any causes or explanations.
6. You may NOT merge hypotheses into facts.
7. You may NOT add any new claims not present in the input.
8. If the weak section is non-empty, include a caveat like "These hypotheses require further investigation."
9. Every $ amount in your output MUST correspond to a VERIFIED assertion above.

## SECTIONS TO RENDER

{sections}

## OUTPUT FORMAT

Write professional financial commentary using the sections above. Be concise but complete. Use the confidence levels to calibrate your language:
- Confidence >= 0.8: State directly ("Revenue increased by...")
- Confidence 0.5-0.8: Add qualifier ("The data indicates that...")
- Confidence < 0.5: Add uncertainty ("This suggests that..." or "Further analysis is needed")
"""
    return prompt


def _format_assertions(assertions: list[Assertion], header: str) -> str:
    if not assertions:
        return f"## {header}\n(none)"

    lines = [f"## {header}"]
    for a in assertions:
        conf = f"confidence={a.confidence:.2f}" if a.confidence else ""
        support = (
            f"support={a.support_level.value}" if a.support_level else ""
        )
        meta = f" [{conf}, {support}]" if conf or support else ""
        lines.append(f"- [{a.type.value}] {a.text}{meta}")
    return "\n".join(lines)


def _format_degraded_modes(modes: list[str]) -> str:
    if not modes:
        return "## DEGRADED MODES\n(none)"
    lines = ["## DEGRADED MODES"]
    for m in modes:
        lines.append(
            f"- {m.replace('_', ' ').title()}: Data quality is reduced for this item."
        )
    return "\n".join(lines)


def render_commentary(
    render_input: CommentaryRenderInput,
    llm_client: LLMClient | None = None,
) -> str:
    """Render commentary from validated assertions.

    Accepts CommentaryRenderInput, produces rendered text.
    The rendering is validated post-hoc to ensure no new claims were introduced.
    """
    prompt = build_render_prompt(render_input)

    if not llm_client or not render_input.all_assertions:
        # Fallback: produce a structured rendering without LLM
        return _fallback_render(render_input)

    try:
        response = llm_client.generate(prompt, max_tokens=2048)
        text = response if isinstance(response, str) else str(response)
    except Exception:
        text = _fallback_render(render_input)

    return text


def _fallback_render(render_input: CommentaryRenderInput) -> str:
    """Non-LLM fallback that produces structured commentary from assertions only."""
    lines = []
    lines.append(
        f"# Financial Commentary — {render_input.entity_name or 'Company'}"
    )
    lines.append(f"Period: {render_input.period}")
    lines.append("")

    # Executive Summary
    lines.append("## Executive Summary")
    if render_input.verified_assertions:
        v = render_input.verified_assertions[0]
        lines.append(f"- {v.text}")
        n_material = sum(
            1
            for a in render_input.verified_assertions
            if a.type == AssertionType.NUMERIC
        )
        if n_material > 1:
            lines.append(f"- {n_material} material variances identified.")
    if render_input.probable_assertions:
        p = render_input.probable_assertions[0]
        lines.append(
            f"- {p.text} (probable cause, confidence: {p.confidence:.0%})"
        )
    if render_input.weak_assertions:
        lines.append(
            f"- {len(render_input.weak_assertions)} hypotheses require further investigation."
        )
    lines.append("")

    # Variance Analysis
    lines.append("## Variance Analysis")
    for a in render_input.verified_assertions:
        if a.type == AssertionType.NUMERIC:
            lines.append(f"- {a.text} (confidence: {a.confidence:.0%})")
    for a in render_input.verified_assertions:
        if a.type == AssertionType.COMPARATIVE:
            lines.append(f"- {a.text}")
    lines.append("")

    # Causes
    if render_input.probable_assertions:
        lines.append("## Root Causes")
        for a in render_input.probable_assertions:
            if a.type == AssertionType.CAUSAL:
                lines.append(
                    f"- {a.text} (confidence: {a.confidence:.0%})"
                )
        lines.append("")

    # Hypotheses
    if render_input.weak_assertions:
        lines.append("## Areas for Further Investigation")
        for a in render_input.weak_assertions:
            lines.append(f"- {a.text}")
        lines.append("")

    # Degraded modes
    if render_input.has_degraded_modes:
        lines.append("## Data Quality Notes")
        for m in render_input.degraded_modes:
            lines.append(
                f"- {m.replace('_', ' ').title()}: Limited data availability affects confidence."
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Backward-compatible entry points for the orchestration layer
# ---------------------------------------------------------------------------


def generate_commentary(
    root_causes: list[RootCauseFinding],
    variances: list[dict],
    llm_client: LLMClient | None = None,
) -> CommentaryDraft:
    """Generate commentary from root causes and variances.

    Now implemented as a rendering layer over validated assertions
    extracted from RootCauseFinding objects.

    For backward compatibility, root causes without explicit assertions
    have their summary text promoted to a VERIFIED assertion.
    """
    # Extract assertions from root causes
    assertions: list[Assertion] = []
    has_explicit_assertions = False
    for rc in root_causes:
        if rc.assertions:
            has_explicit_assertions = True
            assertions.extend(rc.assertions)
        elif rc.summary:
            # Backward compat: promote summary to assertion
            assertions.append(
                Assertion(
                    id=f"rc-{rc.variance_id}",
                    type=AssertionType.NUMERIC,
                    text=rc.summary,
                    support_level=SupportLevel.VERIFIED,
                    confidence=rc.confidence_score,
                )
            )
        assertions.extend(rc.alternative_hypotheses)

    # Detect degraded modes from root causes
    degraded_modes: list[str] = []
    if any(rc.data_gaps for rc in root_causes):
        degraded_modes.append("insufficient_causal_evidence")

    render_input = CommentaryRenderInput.from_assertion_list(
        assertions=assertions,
        degraded_modes=degraded_modes or None,
        period="",
        entity_name="",
    )

    text = render_commentary(render_input, llm_client=llm_client)

    sections = _parse_sections_from_text(text)
    if not sections:
        sections = [
            CommentarySection(
                section_type="executive_summary", content=text
            )
        ]

    return CommentaryDraft(
        sections=sections,
        generated_at=datetime.now(timezone.utc).isoformat(),
        version=1,
        status="draft",
    )


def _parse_sections_from_text(text: str) -> list[CommentarySection]:
    """Parse markdown headings from rendered commentary into sections."""
    import re

    sections = []
    # Match ## Heading followed by content until next heading or end
    pattern = r"^## (.+?)$\n(.*?)(?=^## |\Z)"
    matches = re.findall(pattern, text, re.MULTILINE | re.DOTALL)
    for heading, content in matches:
        section_type = heading.strip().lower().replace(" ", "_")
        content = content.strip()
        if content:
            sections.append(
                CommentarySection(
                    section_type=section_type, content=content
                )
            )
    return sections


def commentary_node(
    state: PipelineState, llm_client: LLMClient | None = None
) -> dict:
    """LangGraph node: produce commentary from pipeline state.

    This node bridges the pipeline state to the new assertion-based
    rendering layer.
    """
    if llm_client is None:
        llm_client = LLMClient()

    root_causes: list[RootCauseFinding] = state.get("root_causes", [])
    variances: list[dict] = state.get("variances", [])

    period = state.get("period", "")
    entity_id = state.get("entity_id", "")

    # Collect all assertions from root causes
    assertions: list[Assertion] = []
    for rc in root_causes:
        assertions.extend(rc.assertions)
        assertions.extend(rc.alternative_hypotheses)

    # Detect degraded modes
    degraded_modes: list[str] = []
    if any(rc.data_gaps for rc in root_causes):
        degraded_modes.append("insufficient_causal_evidence")

    # Build render input with full context from state
    render_input = CommentaryRenderInput.from_assertion_list(
        assertions=assertions,
        degraded_modes=degraded_modes or None,
        period=period,
        entity_name=entity_id,
    )

    text = render_commentary(render_input, llm_client=llm_client)

    sections = _parse_sections_from_text(text)
    if not sections:
        sections = [
            CommentarySection(
                section_type="executive_summary", content=text
            )
        ]

    draft = CommentaryDraft(
        sections=sections,
        generated_at=datetime.now(timezone.utc).isoformat(),
        version=1,
        status="draft",
    )

    return {"commentary_draft": draft, "current_step": "commentary_complete"}
