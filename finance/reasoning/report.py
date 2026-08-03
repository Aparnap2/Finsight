"""Reasoning report models.

The :class:`ReasoningReport` is the typed, immutable output of the
reasoning pipeline: the evidence that was consumed, the assertions
produced, the deterministic confidence scores, the rendered commentary,
and a provenance/lineage trail linking every evidence item to the stages
it flowed through.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from shared.models.assertions import Assertion


class ProvenanceEntry(BaseModel):
    """A single lineage event in the reasoning trail.

    Each entry records one transition of an evidence item (or of an
    assertion derived from it) through the pipeline stages.
    """

    evidence_id: str
    assertion_id: str | None = None
    step: str
    detail: str = ""


class ReasoningReport(BaseModel):
    """Immutable output of the reasoning pipeline.

    Attributes:
        evidence_ids: Identifiers of every input evidence item, in order.
        assertions: Typed assertions produced by the assertion pipeline.
        confidence: Mapping of assertion id to ``Decimal`` confidence in
            [0, 1].
        commentary: Rendered narrative commentary (LLM or deterministic).
        provenance: Ordered lineage trail of evidence through the pipeline.
        degraded: True when commentary was produced without an LLM
            (degraded mode).
        generated_at: UTC timestamp of report assembly.
    """

    model_config = ConfigDict(frozen=True)

    evidence_ids: list[str]
    assertions: list[Assertion]
    confidence: dict[str, Decimal]
    commentary: str
    provenance: list[ProvenanceEntry]
    degraded: bool
    generated_at: datetime
