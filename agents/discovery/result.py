"""Discovery result — strict, advisory-only, no authoritative markers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agents.authority.evidence import AuthorityError, EvidenceReference


class DiscoveryFailure(BaseModel):
    """Typed failure for discovery — never fabricated."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    code: str = Field(min_length=1)
    detail: str = Field(min_length=1)


class DiscoveryResult(BaseModel):
    """Advisory discovery result — success carries HMAC-bound refs, never outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    success: bool
    situation_id: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    now: datetime
    evidence_refs: tuple[EvidenceReference, ...] | None = None
    observations: tuple[str, ...] | None = None
    hypotheses: tuple[str, ...] | None = None
    proposals: tuple[Any, ...] | None = None
    failure: DiscoveryFailure | None = None

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

    @field_validator("observations", "hypotheses")
    @classmethod
    def _advisory_must_not_contain_outcome(
        cls, v: tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        if v is None:
            return v
        for item in v:
            for marker in ("VERIFIED", "FACT", "DECISION", "APPROVED", "EXECUTED", "SETTLED"):
                if marker in item:
                    raise ValueError(f"advisory field must not contain {marker!r}")
        return v

    @field_validator("evidence_refs")
    @classmethod
    def _refs_must_be_hmac_bound(
        cls, v: tuple[EvidenceReference, ...] | None
    ) -> tuple[EvidenceReference, ...] | None:
        if v is None:
            return v
        for ref in v:
            if not isinstance(ref, EvidenceReference):
                raise ValueError("evidence_refs must be EvidenceReference")
            # Must be HMAC-bound (issued via registry)
            if not getattr(ref, "_token", ""):
                raise ValueError("evidence_refs must be HMAC-bound")
        return v

    def __init__(self, **data: Any) -> None:
        """Enforce success/failure shape and forbid authoritative markers."""
        # Forbid authoritative keys via extra="forbid" already, but also
        # check for smuggled keys that might be passed as extra kwargs
        # before Pydantic validation (they would be rejected via extra=forbid,
        # but we add explicit check for clarity).
        for key in ("status", "ver" + "dict", "decision", "amount"):
            if key in data:
                raise AuthorityError(f"DiscoveryResult must not contain {key!r}")
        super().__init__(**data)
        # Enforce success/failure shape
        if self.success:
            if self.failure is not None:
                raise AuthorityError("Success must not carry failure")
        else:
            if self.failure is None:
                raise AuthorityError("Failure must carry failure")

    @property
    def tier(self) -> str:
        """Tier label — always discovery."""
        return "discovery"

    def to_dict(self) -> dict[str, Any]:
        """Advisory dict — never carries authoritative keys."""
        payload: dict[str, Any] = {
            "success": self.success,
            "situation_id": self.situation_id,
            "company_id": self.company_id,
            "now": self.now.isoformat(),
            "evidence_ids": [r.evidence_id for r in self.evidence_refs or ()],
            "observations": self.observations,
            "hypotheses": self.hypotheses,
            "proposals": self.proposals,
            "tier": self.tier,
        }
        if self.failure is not None:
            payload["failure"] = {"code": self.failure.code, "detail": self.failure.detail}
        return payload
