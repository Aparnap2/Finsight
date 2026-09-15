"""Deterministic reasoning pipeline.

Flow::

    evidence → assertions (finance.assertion_pipeline)
             → confidence scoring (finance.reasoning.confidence)
             → LLM commentary request (structured, finance.reasoning.llm_boundary)
             → report assembly (finance.reasoning.report)

The pipeline never passes raw data to the commentary provider — only typed
:class:`~shared.models.assertions.Assertion` objects (which reference
evidence by id, never embedding raw evidence items).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from finance.assertion_pipeline import (
    build_causal_assertion,
    build_comparative_assertion,
    run_assertion_pipeline,
)
from finance.evidence.models import EvidenceItem
from finance.reasoning.confidence import score_assertion
from finance.reasoning.llm_boundary import (
    CommentaryProvider,
    NullCommentaryProvider,
)
from finance.reasoning.report import ProvenanceEntry, ReasoningReport
from shared.models.assertions import Assertion
from shared.utils.tools.tool_result import ToolResult

_ToolSourceType = Literal[
    "financial_fact", "operational_metric", "policy_doc", "precedent"
]

# Evidence source type -> ToolResult source type (the four allowed values).
_SOURCE_TYPE_MAP: dict[str, _ToolSourceType] = {
    "kpi": "financial_fact",
    "variance": "financial_fact",
    "transaction": "financial_fact",
    "gl": "financial_fact",
    "financial_fact": "financial_fact",
    "driver": "operational_metric",
    "headcount": "operational_metric",
    "operational_metric": "operational_metric",
    "manual": "operational_metric",
    "policy_doc": "policy_doc",
    "precedent": "precedent",
}

# Evidence confidence string -> numeric quality proxy for ToolResult synthesis.
_EVIDENCE_QUALITY: dict[str, float] = {
    "high": 0.9,
    "medium": 0.7,
    "low": 0.4,
    "tentative": 0.25,
}


class ReasoningContext(BaseModel):
    """Immutable input context for a reasoning pipeline run."""

    model_config = ConfigDict(frozen=True)

    tenant_id: str = "default"
    period: str = ""
    entity_name: str = ""
    audience: str = "analyst"
    materiality_threshold: Decimal = Decimal("10000")
    degraded_modes: list[str] = []


def _assign_evidence_ids(evidence: list[EvidenceItem]) -> list[str]:
    """Assign deterministic, unique evidence ids preserving input order.

    The base id is ``<source_type>:<source_id>``; duplicate source
    references get an occurrence suffix (``#1``, ``#2``, ...).
    """
    seen: dict[str, int] = {}
    ids: list[str] = []
    for item in evidence:
        base = f"{item.source_type}:{item.source_id}"
        seen[base] = seen.get(base, 0) + 1
        count = seen[base]
        ids.append(base if count == 1 else f"{base}#{count - 1}")
    return ids


def _tool_source_type(source_type: str) -> _ToolSourceType:
    """Map an evidence source type onto the ToolResult source type enum."""
    return _SOURCE_TYPE_MAP.get(source_type, "operational_metric")


def _evidence_to_tool_result(
    evidence_item: EvidenceItem, ev_id: str, tenant_id: str
) -> ToolResult:
    """Synthesize a ToolResult carrying the evidence item's quality metadata."""
    quality = _EVIDENCE_QUALITY.get(evidence_item.confidence, 0.5)
    return ToolResult(
        data=[{"evidence_id": ev_id}],
        row_count=1,
        coverage_pct=quality,
        quality_score=quality,
        freshness_seconds=None,
        schema_version="1.0",
        source_diversity=1,
        source_type=_tool_source_type(evidence_item.source_type),
        retrieval_scope="factual",
        tenant_id=tenant_id,
        required_filters_present=True,
        insufficient_data=evidence_item.confidence in ("low", "tentative"),
        degraded_mode=None,
        query_fingerprint=None,
    )


def _unique_assertion_id(used: set[str], base: str) -> str:
    """Return a globally unique assertion id derived from *base*."""
    candidate = base
    counter = 1
    while candidate in used:
        candidate = f"{base}#{counter}"
        counter += 1
    used.add(candidate)
    return candidate


def _build_assertions(
    evidence: list[EvidenceItem],
    ids: list[str],
    context: ReasoningContext,
) -> tuple[list[Assertion], dict[str, list[str]]]:
    """Build assertions from evidence via ``finance.assertion_pipeline``.

    Evidence is grouped by source id so each assertion links back to the
    exact evidence items that support it. Returns ``(assertions, linkage)``
    where linkage maps assertion id -> supporting evidence ids.
    """
    groups: dict[str, list[EvidenceItem]] = {}
    group_ids: dict[str, list[str]] = {}
    for item, ev_id in zip(evidence, ids, strict=True):
        groups.setdefault(item.source_id, []).append(item)
        group_ids.setdefault(item.source_id, []).append(ev_id)

    assertions: list[Assertion] = []
    linkage: dict[str, list[str]] = {}
    used_ids: set[str] = set()
    candidates: list[dict[str, Any]] = []

    for source_id in groups:
        items = groups[source_id]
        ids_for_group = group_ids[source_id]
        tool_results = [
            _evidence_to_tool_result(item, ev_id, context.tenant_id)
            for item, ev_id in zip(items, ids_for_group, strict=True)
        ]
        value = next(
            (item.source_value for item in items if item.source_value is not None),
            None,
        )
        zero = Decimal("0")
        variance = {
            "account_name": source_id,
            "actual_amount": value if value is not None else zero,
            "budget_amount": zero,
            "variance_amount": value if value is not None else zero,
            "variance_pct": zero,
        }
        result = run_assertion_pipeline(
            variances=[variance],
            tool_results={"gl": tool_results, "headcount": []},
        )
        for assertion in result.assertions:
            assertion.evidence_ids = list(ids_for_group)
            unique_id = _unique_assertion_id(used_ids, assertion.id)
            assertion.id = unique_id
            linkage[unique_id] = list(ids_for_group)
            assertions.append(assertion)
        if value is not None:
            candidates.append({"account_id": source_id, "variance_amount": value})

    # COMPARATIVE assertion across groups once >= 2 have comparable values.
    if len(candidates) >= 2:
        comparative = build_comparative_assertion(
            subject="variance",
            candidates=candidates,
            value_field="variance_amount",
        )
        if comparative is not None:
            all_ids = [ev_id for group in group_ids.values() for ev_id in group]
            comparative.evidence_ids = all_ids
            unique_id = _unique_assertion_id(used_ids, comparative.id)
            comparative.id = unique_id
            linkage[unique_id] = all_ids
            assertions.append(comparative)

    # CAUSAL assertions for evidence that indicates a driver relationship.
    for source_id in groups:
        for item, ev_id in zip(groups[source_id], group_ids[source_id], strict=True):
            if item.source_type not in {"driver", "causal"}:
                continue
            causal = build_causal_assertion(
                cause=source_id,
                effect="variance",
                driver_tree_edges=[{"from": source_id, "to": "variance"}],
                evidence_classes=1,
                has_alternative=False,
            )
            if causal is not None:
                causal.evidence_ids = [ev_id]
                unique_id = _unique_assertion_id(used_ids, causal.id)
                causal.id = unique_id
                linkage[unique_id] = [ev_id]
                assertions.append(causal)

    return assertions, linkage


def _evidence_for(
    evidence: list[EvidenceItem], ids: list[str], wanted: list[str]
) -> list[EvidenceItem]:
    """Return the evidence items whose assigned ids are in *wanted*."""
    by_id = dict(zip(ids, evidence, strict=True))
    return [by_id[i] for i in wanted if i in by_id]


def _build_provenance(
    ids: list[str],
    assertions: list[Assertion],
    linkage: dict[str, list[str]],
    confidence: dict[str, Decimal],
    degraded: bool,
) -> list[ProvenanceEntry]:
    """Build the lineage trail: every evidence id flows through each stage."""
    entries: list[ProvenanceEntry] = []
    for ev_id in ids:
        entries.append(ProvenanceEntry(evidence_id=ev_id, step="evidence_collected"))

    for assertion in assertions:
        linked = linkage.get(assertion.id) or ids
        for ev_id in linked:
            entries.append(
                ProvenanceEntry(
                    evidence_id=ev_id,
                    assertion_id=assertion.id,
                    step="assertion_created",
                )
            )
        for ev_id in linked:
            score = confidence.get(assertion.id)
            detail = f"confidence={score}" if score is not None else "confidence=n/a"
            entries.append(
                ProvenanceEntry(
                    evidence_id=ev_id,
                    assertion_id=assertion.id,
                    step="confidence_scored",
                    detail=detail,
                )
            )

    for ev_id in ids:
        entries.append(
            ProvenanceEntry(
                evidence_id=ev_id,
                step="report_assembled",
                detail=f"degraded={degraded}",
            )
        )
    return entries


def run_reasoning_pipeline(
    evidence: list[EvidenceItem],
    context: ReasoningContext | None = None,
    commentary_provider: CommentaryProvider | None = None,
) -> ReasoningReport:
    """Run the deterministic reasoning pipeline end-to-end.

    Stages:
    1. deterministic evidence ids are assigned (order-preserving);
    2. assertions are built via ``finance.assertion_pipeline``;
    3. confidence is scored per assertion (``Decimal``, [0, 1]);
    4. commentary is requested from the provider — assertions only, never
       raw data;
    5. the report is assembled with a full provenance trail.

    Args:
        evidence: Evidence items that anchor every claim in the report.
        context: Run context (tenant, period, entity, thresholds).
        commentary_provider: Optional provider; defaults to the
            deterministic :class:`NullCommentaryProvider` (degraded mode,
            no LLM).

    Returns:
        A frozen :class:`ReasoningReport`.
    """
    ctx = context if context is not None else ReasoningContext()
    provider = (
        commentary_provider
        if commentary_provider is not None
        else NullCommentaryProvider()
    )

    ids = _assign_evidence_ids(evidence)
    assertions, linkage = _build_assertions(evidence, ids, ctx)

    confidence: dict[str, Decimal] = {}
    for assertion in assertions:
        linked_evidence = _evidence_for(
            evidence, ids, linkage.get(assertion.id, [])
        )
        confidence[assertion.id] = score_assertion(
            assertion, linked_evidence, ctx.materiality_threshold
        )

    commentary = provider.generate(assertions)

    degraded = bool(
        getattr(provider, "degraded", isinstance(provider, NullCommentaryProvider))
    )

    provenance = _build_provenance(ids, assertions, linkage, confidence, degraded)

    return ReasoningReport(
        evidence_ids=ids,
        assertions=assertions,
        confidence=confidence,
        commentary=commentary,
        provenance=provenance,
        degraded=degraded,
        generated_at=datetime.now(UTC),
    )
