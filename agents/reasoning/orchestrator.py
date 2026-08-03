"""Reasoning orchestration — wraps the pipeline into commentary drafts.

Wraps ``finance.reasoning.run_reasoning_pipeline`` into the orchestration
layer's ``CommentaryDraft`` shape so existing commentary consumers can use
the deterministic reasoning pipeline unchanged.

Layer rules: agents → finance → shared. This module imports only
``finance`` and ``shared`` — never ``apps``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from finance.evidence.models import EvidenceItem
from finance.reasoning import (
    ReasoningContext,
    ReasoningReport,
    run_reasoning_pipeline,
)
from finance.reasoning.llm_boundary import (
    NullCommentaryProvider,
    StructuredCommentaryProvider,
)
from shared.models.state import CommentaryDraft, CommentarySection


def run_reasoning_commentary(
    evidence: list[EvidenceItem],
    context: ReasoningContext,
    llm_client: object | None = None,
) -> CommentaryDraft:
    """Run the reasoning pipeline and return a ``CommentaryDraft``.

    Args:
        evidence: Evidence items anchoring the report's claims.
        context: Reasoning run context (period, entity, thresholds).
        llm_client: Optional injected LLM client exposing
            ``generate(prompt: str) -> str``. When None, the deterministic
            Null provider is used — no LLM, degraded mode.

    Returns:
        A typed :class:`CommentaryDraft` ready for commentary consumers.
    """
    if llm_client is None:
        provider: NullCommentaryProvider | StructuredCommentaryProvider = NullCommentaryProvider()
    else:
        provider = StructuredCommentaryProvider(
            llm_client=llm_client,
            context={
                "entity_name": context.entity_name,
                "period": context.period,
                "audience": context.audience,
            },
        )
    report = run_reasoning_pipeline(evidence, context, provider)
    return _to_commentary_draft(report)


def _to_commentary_draft(report: ReasoningReport) -> CommentaryDraft:
    """Convert a reasoning report into the commentary draft shape."""
    sections = _parse_sections(report.commentary)
    if not sections:
        sections = [
            CommentarySection(
                section_type="executive_summary", content=report.commentary
            )
        ]
    return CommentaryDraft(
        sections=sections,
        assertions_used=[assertion.id for assertion in report.assertions],
        generated_at=datetime.now(UTC).isoformat(),
        version=1,
        status="draft",
    )


_HEADING_RE = re.compile(r"^## (.+)$", re.MULTILINE)


def _parse_sections(text: str) -> list[CommentarySection]:
    """Parse ``## Heading`` sections from rendered commentary.

    Content before the first heading (the structured summary) is captured
    as an ``executive_summary`` section.
    """
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [
            CommentarySection(
                section_type="executive_summary", content=text.strip()
            )
        ]

    sections: list[CommentarySection] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(
            CommentarySection(section_type="executive_summary", content=preamble)
        )
    for index, match in enumerate(matches):
        heading = match.group(1).strip().lower().replace(" ", "_")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[match.end() : end].strip()
        if content:
            sections.append(
                CommentarySection(section_type=heading, content=content)
            )
    return sections
