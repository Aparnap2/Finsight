"""Discovery request — strict, immutable, capability-bounded."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agents.authority.claims import AgentCapability
from agents.discovery.capabilities import DISCOVERY_ALLOWED_CAPABILITIES


class DiscoveryRequest(BaseModel):
    """Typed discovery request — explicit, immutable, no injection seams."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    situation_id: Annotated[str, Field(min_length=1, strip_whitespace=True)]
    company_id: Annotated[str, Field(min_length=1, strip_whitespace=True)]
    now: datetime
    allowed_evidence_ids: Annotated[tuple[str, ...], Field(min_length=1)]
    objective: Annotated[str, Field(min_length=1, strip_whitespace=True)]
    allowed_capabilities: tuple[AgentCapability, ...] = Field(default_factory=tuple)

    @field_validator("company_id")
    @classmethod
    def _company_must_be_meridian(cls, v: str) -> str:
        if v != "meridian":
            raise ValueError("company_id must be 'meridian'")
        return v

    @field_validator("now")
    @classmethod
    def _now_must_be_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return v

    @field_validator("situation_id", "objective")
    @classmethod
    def _must_be_non_blank(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("must be non-blank")
        return v

    @field_validator("allowed_evidence_ids")
    @classmethod
    def _evidence_ids_must_be_non_blank(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for eid in v:
            if not isinstance(eid, str) or not eid.strip():
                raise ValueError("allowed_evidence_ids items must be non-blank strings")
        # Must be unique and bounded (prevent abuse)
        if len(set(v)) != len(v):
            raise ValueError("allowed_evidence_ids must be unique")
        if len(v) > 32:
            raise ValueError("allowed_evidence_ids too many (max 32)")
        return v

    @field_validator("allowed_capabilities")
    @classmethod
    def _capabilities_must_be_allowlisted(
        cls, v: tuple[AgentCapability, ...]
    ) -> tuple[AgentCapability, ...]:
        for cap in v:
            if cap not in DISCOVERY_ALLOWED_CAPABILITIES:
                raise ValueError(f"capability {cap!r} not in discovery allowlist")
        return v


# Back-compat alias for tests that import ALLOWED_DISCOVERY_CAPABILITIES from request
ALLOWED_DISCOVERY_CAPABILITIES = DISCOVERY_ALLOWED_CAPABILITIES
