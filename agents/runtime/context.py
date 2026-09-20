"""Runtime context and request envelope — caller-supplied, registry-bound."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agents.authority.claims import AuthorityBoundary
from agents.authority.evidence import AuthorityError, EvidenceRegistry


def _require_non_blank(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthorityError(f"{field} must be a non-blank string.")
    return value


def _require_tz_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AuthorityError(f"{field} must be timezone-aware.")
    return value


@dataclass(frozen=True)
class RuntimeContext:
    """Execution context carried through the runtime boundary.

    All fields are caller-supplied; no wall-clock reads. The
    ``registry`` and ``boundary`` are injected by the deterministic
    plane — the agent never supplies them.
    """

    situation_id: str
    company_id: str
    now: datetime
    registry: EvidenceRegistry
    boundary: AuthorityBoundary

    def __post_init__(self) -> None:
        """Validate context shape."""
        _require_non_blank(self.situation_id, "situation_id")
        _require_non_blank(self.company_id, "company_id")
        if self.company_id != "meridian":
            raise AuthorityError("company_id must be 'meridian' in this slice.")
        _require_tz_aware(self.now, "now")
        if not isinstance(self.registry, EvidenceRegistry):
            raise AuthorityError("registry must be an EvidenceRegistry.")
        if not isinstance(self.boundary, AuthorityBoundary):
            raise AuthorityError("boundary must be an AuthorityBoundary.")


@dataclass(frozen=True)
class RuntimeRequest:
    """Typed request envelope for a capability dispatch.

    ``capability`` is an ``AgentCapability`` value; ``inputs`` is a
    plain mapping that will be validated via P7-01 validators.
    ``evidence_ids`` must be a subset of the registry's known ids;
    the runtime resolves them via the registry — raw metadata never
    becomes authority.
    """

    capability: str
    inputs: Mapping[str, Any]
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate envelope shape (not authority)."""
        _require_non_blank(self.capability, "capability")
        if not isinstance(self.inputs, Mapping):
            raise AuthorityError("inputs must be a mapping.")
        if not isinstance(self.evidence_ids, tuple):
            raise AuthorityError("evidence_ids must be a tuple.")
