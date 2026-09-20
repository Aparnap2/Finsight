"""Runtime context and request envelope — caller-supplied, registry-bound."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agents.authority.claims import AgentCapability, AuthorityBoundary
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
    plane — the agent never supplies them. Only ``RuntimeFactory``
    produces a validated instance (HMAC-bound).
    """

    situation_id: str
    company_id: str
    now: datetime
    registry: EvidenceRegistry
    boundary: AuthorityBoundary
    _factory_token: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate context shape (not authority — authority is the HMAC)."""
        _require_non_blank(self.situation_id, "situation_id")
        _require_non_blank(self.company_id, "company_id")
        if self.company_id != "meridian":
            raise AuthorityError("company_id must be 'meridian' in this slice.")
        _require_tz_aware(self.now, "now")
        if not isinstance(self.registry, EvidenceRegistry):
            raise AuthorityError("registry must be an EvidenceRegistry.")
        if not isinstance(self.boundary, AuthorityBoundary):
            raise AuthorityError("boundary must be an AuthorityBoundary.")


class RuntimeFactory:
    """Trusted factory that is the sole issuer of ``RuntimeContext``.

    Holds a per-factory secret; the HMAC binds every field so the
    agent cannot mint or mutate a context, and the request envelope
    never carries ``registry`` or ``boundary``.
    """

    def __init__(self) -> None:
        """Create a factory with a fresh secret."""
        self._secret: str = uuid.uuid4().hex

    def _hmac_context(self, ctx: RuntimeContext) -> str:
        """HMAC binding every field of a context to the secret."""
        payload = (
            f"{ctx.situation_id}:{ctx.company_id}:{ctx.now.isoformat()}"
        ).encode()
        return hmac.new(self._secret.encode(), payload, hashlib.sha256).hexdigest()

    def create_context(
        self,
        *,
        situation_id: str,
        company_id: str = "meridian",
        now: datetime,
        registry: EvidenceRegistry,
        boundary: AuthorityBoundary,
    ) -> RuntimeContext:
        """Issue an HMAC-bound context (deterministic plane only)."""
        tmp = RuntimeContext(
            situation_id=situation_id,
            company_id=company_id,
            now=now,
            registry=registry,
            boundary=boundary,
            _factory_token="",
        )
        token = self._hmac_context(tmp)
        return RuntimeContext(
            situation_id=situation_id,
            company_id=company_id,
            now=now,
            registry=registry,
            boundary=boundary,
            _factory_token=token,
        )

    def validate_context(self, ctx: RuntimeContext) -> None:
        """Raise AuthorityError unless ctx was issued by this factory."""
        if not isinstance(ctx, RuntimeContext):
            raise AuthorityError("context must be a RuntimeContext.")
        expected = self._hmac_context(ctx)
        if ctx._factory_token != expected:
            raise AuthorityError("RuntimeContext not issued by deterministic factory.")

    def create_runtime(
        self,
        context: RuntimeContext,
        *,
        model: Any | None = None,
    ) -> Any:
        """Create an ``AgentRuntime`` bound to a validated context."""
        self.validate_context(context)
        # Import here to avoid circular import.
        from agents.runtime.runtime import AgentRuntime

        return AgentRuntime(context, model=model, _factory=self)


@dataclass(frozen=True)
class RuntimeRequest:
    """Typed request envelope for a capability dispatch.

    ``capability`` is an ``AgentCapability`` value; ``inputs`` is a
    plain mapping that will be validated via P7-01 validators.
    ``evidence_ids`` must be a tuple of non-blank strings and a
    subset of the registry's known ids; the runtime resolves them via
    the registry — raw metadata never becomes authority. The envelope
    never carries ``registry`` or ``boundary`` — those are context-bound.
    Construction-time validation ensures an invalid request object
    cannot exist; dispatch then consumes the already-valid request.
    """

    capability: AgentCapability
    inputs: Mapping[str, Any]
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate envelope shape and reject registry injection."""
        if not isinstance(self.capability, AgentCapability):
            raise AuthorityError("capability must be an AgentCapability.")
        if not isinstance(self.inputs, Mapping):
            raise AuthorityError("inputs must be a mapping.")
        if not isinstance(self.evidence_ids, tuple):
            raise AuthorityError("evidence_ids must be a tuple.")
        for eid in self.evidence_ids:
            _require_non_blank(eid, "evidence_ids item")
        # The request must never carry registry or boundary — those are
        # context-bound and injected by the deterministic plane.
        for forbidden in (
            "registry",
            "boundary",
            "evidence_registry",
            "authority_boundary",
        ):
            if forbidden in self.inputs:
                raise AuthorityError(f"Request must not carry {forbidden!r}.")
