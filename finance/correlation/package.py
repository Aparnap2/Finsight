"""Idempotent evidence packages: the P4-ready unit of correlation.

``assemble_package`` binds one collection plus its chain into a
fingerprint-stable package keyed by ``(tenant, batch, hashes)``:
identical inputs yield byte-identical packages, changed hashes under
known ids surface as conflicts (never silent overwrites), and absent
legs produce an explicit ``INCOMPLETE`` shape with a named missing
set. ``to_store_dict`` renders rows the P4 ``build_context`` accepts.
"""

from __future__ import annotations

import re
from hashlib import sha256

from pydantic import BaseModel, ConfigDict

from finance.correlation.chain import EvidenceChain
from finance.correlation.collector import CollectedEvidence
from finance.correlation.converter import truncate_content

_CAUSAL_PATTERN = re.compile(
    r"\b(caused|causes|causing|proves|prove|proving|root cause)\b",
    re.IGNORECASE,
)
"""Causal-upgrade wording refused in package summaries."""


class MissingLeg(BaseModel):
    """One named absent leg that keeps a package incomplete."""

    model_config = ConfigDict(frozen=True, strict=True)

    source_system: str
    """The absent authority, e.g. cobol_legacy."""

    key: str
    """The batch or window key that was unreadable."""

    reason: str
    """Machine reason, e.g. LEGACY_RESULT_UNREADABLE."""


class EvidencePackage(BaseModel):
    """One deterministic, fingerprint-stable evidence package."""

    model_config = ConfigDict(frozen=True, strict=True)

    package_id: str
    """Tenant:batch:fingerprint-prefix identity."""

    tenant_id: str
    """Owning tenant (always meridian in this phase)."""

    case_id: str
    """Owning case."""

    batch_id: str
    """Collection window."""

    evidence_ids: tuple[str, ...]
    """Sorted evidence ids covered by the package."""

    missing: tuple[MissingLeg, ...] = ()
    """Named absent legs; empty means complete."""

    complete: bool = True
    """False exactly when missing legs exist (never fabricated)."""

    fingerprint: str
    """sha256 over tenant/case/batch/ids/chain/missing."""


def _package_fingerprint(
    *,
    tenant_id: str,
    case_id: str,
    batch_id: str,
    evidence_ids: tuple[str, ...],
    head_hash: str,
    missing: tuple[MissingLeg, ...],
) -> str:
    """Fold the package identity inputs into one stable digest."""
    missing_part = "|".join(
        f"{leg.source_system}:{leg.key}:{leg.reason}" for leg in missing
    )
    return sha256(
        "|".join(
            [tenant_id, case_id, batch_id, ",".join(evidence_ids), head_hash]
        ).encode("utf-8")
        + b"\x00"
        + missing_part.encode("utf-8")
    ).hexdigest()


def assemble_package(
    *,
    tenant_id: str,
    case_id: str,
    batch_id: str,
    collected: CollectedEvidence,
    chain: EvidenceChain,
    missing: tuple[MissingLeg, ...] = (),
) -> EvidencePackage:
    """Bind one collection plus its chain into a stable package.

    Args:
        tenant_id: Owning tenant.
        case_id: Owning case.
        batch_id: Collection window.
        collected: The deterministic collection to bind.
        chain: The edge set over the collected ids.
        missing: Named absent legs (package incomplete when non-empty).

    Returns:
        The frozen package; identical inputs always yield the
        byte-identical package (same fingerprint and package id).
    """
    fingerprint = _package_fingerprint(
        tenant_id=tenant_id,
        case_id=case_id,
        batch_id=batch_id,
        evidence_ids=collected.evidence_ids,
        head_hash=chain.head_hash,
        missing=missing,
    )
    return EvidencePackage(
        package_id=f"{tenant_id}:{batch_id}:{fingerprint[:16]}",
        tenant_id=tenant_id,
        case_id=case_id,
        batch_id=batch_id,
        evidence_ids=collected.evidence_ids,
        missing=missing,
        complete=len(missing) == 0,
        fingerprint=fingerprint,
    )


def to_store_dict(
    *,
    package: EvidencePackage,
    collected: CollectedEvidence,
) -> dict[str, dict[str, object]]:
    """Render P4 ``build_context`` rows for every packaged id.

    Content is the deterministically truncated store text (full hash
    preserved); provenance renders as ``adapter:endpoint:correlation``.
    """
    registry = collected.to_registry()
    contents = collected.to_contents()
    rows: dict[str, dict[str, object]] = {}
    for eid in package.evidence_ids:
        item = registry[eid]
        provenance = item.provenance
        rows[eid] = {
            "tenant_id": package.tenant_id,
            "case_id": package.case_id,
            "source_type": item.source_type,
            "source_id": item.source_id,
            "content": truncate_content(contents[eid]),
            "content_hash": item.content_hash,
            "retrieved_at": item.retrieved_at,
            "provenance": (
                f"{provenance.adapter}:{provenance.endpoint}:"
                f"{provenance.correlation_id}"
                if provenance is not None
                else ""
            ),
        }
    return rows


def check_summary(text: str) -> str:
    """Accept a package summary, refusing causal-upgrade wording.

    Args:
        text: Proposed summary text.

    Returns:
        The text unchanged when it stays correlational.

    Raises:
        ValueError: On caused/proves/root-cause wording (CAUSAL_UPGRADE).
    """
    if _CAUSAL_PATTERN.search(text) is not None:
        raise ValueError(
            "CAUSAL_UPGRADE: summaries may correlate evidence, never "
            "declare causation or proof."
        )
    return text
