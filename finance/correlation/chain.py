"""Evidence chains: CORRELATED_WITH edges with stable digests.

Edges record that two items were collected together for one case —
never causation, proof, or verification. Causal labels are refused
wherever an edge label is accepted. Same-source diverging content
coexists with explicit conflict markers; nothing is merged or
silenced.
"""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from finance.evidence.models import EvidenceItem

_CORRELATED_WITH = "CORRELATED_WITH"
"""The only permitted edge label."""

_FORBIDDEN_LABELS = frozenset({"CAUSED_BY", "PROVES", "VERIFIES"})
"""Causal labels refused fail-closed (checked by substring too)."""


def _check_label(label: str) -> str:
    """Accept only CORRELATED_WITH (exact); refuse causal labels."""
    if label != _CORRELATED_WITH or any(
        forbidden in label for forbidden in _FORBIDDEN_LABELS
    ):
        raise ValueError(
            "edge label must be CORRELATED_WITH; causal labels "
            f"(CAUSED_BY/PROVES/VERIFIES) are forbidden, got {label!r}."
        )
    return label


def _pair_digest(first_id: str, second_id: str) -> str:
    """Return the stable sha256 digest over one ordered id pair."""
    return sha256(f"{first_id}\x00{second_id}".encode()).hexdigest()


def _fold_digests(digests: list[str]) -> str:
    """Fold edge digests in order into one head hash."""
    return sha256("".join(digests).encode("utf-8")).hexdigest()


class ChainEdge(BaseModel):
    """One ordered correlation edge between two evidence ids."""

    model_config = ConfigDict(frozen=True, strict=True)

    from_id: str
    """Source evidence id of the edge."""

    to_id: str
    """Target evidence id of the edge."""

    label: str = _CORRELATED_WITH
    """Always CORRELATED_WITH; anything causal is refused."""

    digest: str = ""
    """sha256 over the ordered pair; computed when blank."""

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: str) -> str:
        """Enforce the CORRELATED_WITH-only vocabulary."""
        return _check_label(value)

    @field_validator("digest", mode="before")
    @classmethod
    def _fill_digest(cls, value: object, info: ValidationInfo) -> str:
        """Derive the pair digest when the caller leaves it blank."""
        if isinstance(value, str) and value:
            return value
        first = info.data.get("from_id", "")
        second = info.data.get("to_id", "")
        if isinstance(first, str) and isinstance(second, str) and first and second:
            return _pair_digest(first, second)
        return ""


def make_edge(first_id: str, second_id: str, label: str = _CORRELATED_WITH) -> ChainEdge:
    """Build one edge, refusing causal labels fail-closed."""
    return ChainEdge(
        from_id=first_id,
        to_id=second_id,
        label=_check_label(label),
        digest=_pair_digest(first_id, second_id),
    )


class ConflictMarker(BaseModel):
    """One preserved disagreement: same source, diverging content."""

    model_config = ConfigDict(frozen=True, strict=True)

    code: str = "CONFLICTING_EVIDENCE"
    """Machine marker code."""

    ids: tuple[str, ...]
    """The diverging evidence ids (sorted, at least two)."""

    hashes: tuple[str, ...]
    """One content hash per id, in id order."""

    rule: str
    """Human-readable rule naming why both sides are preserved."""

    @field_validator("ids")
    @classmethod
    def _validate_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require at least two diverging ids."""
        if len(value) < 2:
            raise ValueError("conflict markers need at least two ids.")
        return value


class EvidenceChain(BaseModel):
    """One ordered edge set with conflict markers and a head hash."""

    model_config = ConfigDict(frozen=True, strict=True)

    edges: tuple[ChainEdge, ...] = ()
    """Consecutive CORRELATED_WITH edges over sorted ids."""

    markers: tuple[ConflictMarker, ...] = ()
    """Preserved disagreements; never merged or silenced."""

    head_hash: str = ""
    """Fold over edge digests in order (empty chain folds to sha256(''))."""


def detect_conflicts(
    registry: Mapping[str, EvidenceItem],
    contents: Mapping[str, str],
) -> list[ConflictMarker]:
    """Flag same-source ids whose contents diverge.

    Args:
        registry: Evidence id to item mapping.
        contents: Evidence id to full content mapping.

    Returns:
        One marker per diverging source group (empty when clean).
    """
    groups: dict[str, list[str]] = {}
    for eid, item in registry.items():
        groups.setdefault(item.source_id, []).append(eid)
    markers: list[ConflictMarker] = []
    for source_id in sorted(groups):
        ids = sorted(groups[source_id])
        bodies = {contents.get(eid, "") for eid in ids}
        if len(bodies) > 1:
            markers.append(
                ConflictMarker(
                    ids=tuple(ids),
                    hashes=tuple(registry[eid].content_hash or "" for eid in ids),
                    rule=(
                        f"source {source_id} has {len(bodies)} diverging "
                        "bodies: preserve both, never overwrite."
                    ),
                )
            )
    return markers


def build_chain(
    evidence_ids: tuple[str, ...] | list[str],
    registry: Mapping[str, EvidenceItem] | None = None,
) -> EvidenceChain:
    """Build the canonical edge set over sorted ids.

    Args:
        evidence_ids: Evidence ids in any order (sorted canonically).
        registry: Optional id-to-item mapping; when given, same-source
            divergences surface as conflict markers.

    Returns:
        The chain with consecutive CORRELATED_WITH edges and markers.
    """
    ordered = tuple(sorted(evidence_ids))
    edges = tuple(
        make_edge(first, second)
        for first, second in zip(ordered, ordered[1:], strict=False)
    )
    markers: tuple[ConflictMarker, ...] = ()
    if registry is not None:
        contents = {
            eid: registry[eid].claim for eid in ordered if eid in registry
        }
        markers = tuple(detect_conflicts(registry, contents))
    return EvidenceChain(
        edges=edges,
        markers=markers,
        head_hash=_fold_digests([edge.digest for edge in edges]),
    )
