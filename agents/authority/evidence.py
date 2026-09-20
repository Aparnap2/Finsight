"""Evidence pointers: read-only references with explicit freshness guards.

P6 ``finance/evidence`` and ``finance/facts`` remain the normative store;
this module only carries caller-supplied pointers (source id, capture
time, TTL) plus frozen references to P6-established facts. No mutation
API, no network, no wall-clock inside stored state.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
"""Lowercase sha256 hex digest pattern for fact digests."""


class AuthorityError(ValueError):
    """Typed refusal for any forbidden-authority or escape attempt.

    Raised with no partial effect: callers must treat it as a hard
    deny, never as a signal to retry with elevated privilege.
    """


def _require_tz_aware(value: datetime, field: str) -> datetime:
    """Return value when tz-aware, else raise AuthorityError."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise AuthorityError(f"{field} must be timezone-aware.")
    return value


def _require_non_blank(value: str, field: str) -> str:
    """Return value when a non-blank string, else raise AuthorityError."""
    if not isinstance(value, str) or not value.strip():
        raise AuthorityError(f"{field} must be a non-blank string.")
    return value


@dataclass(frozen=True)
class AuthoritativeFact:
    """Frozen reference to a P6-established fact (pointer plus digest).

    Carries no mutation API: frozen dataclass, no setters, no promotion
    helpers. Agents may cite it, never alter it.
    """

    source_id: str
    digest: str
    captured_at: datetime

    def __post_init__(self) -> None:
        """Validate pointer shape and digest format."""
        _require_non_blank(self.source_id, "source_id")
        if not isinstance(self.digest, str) or not _SHA256_RE.match(self.digest):
            raise AuthorityError("digest must be 64-char lowercase hex sha256.")
        _require_tz_aware(self.captured_at, "captured_at")
        logger.debug("AuthoritativeFact cited: %s", self.source_id)


@dataclass(frozen=True)
class EvidenceReference:
    """Pointer to evidence with caller-supplied capture time and TTL.

    Zero wall-clock inside stored state: freshness is always evaluated
    against an explicit ``now`` supplied by the caller.
    """

    source_id: str
    captured_at: datetime
    ttl_seconds: int

    def __post_init__(self) -> None:
        """Validate pointer shape (non-blank id, tz-aware time, positive TTL)."""
        _require_non_blank(self.source_id, "source_id")
        _require_tz_aware(self.captured_at, "captured_at")
        if isinstance(self.ttl_seconds, bool) or not isinstance(self.ttl_seconds, int):
            raise AuthorityError("ttl_seconds must be an int.")
        if self.ttl_seconds <= 0:
            raise AuthorityError("ttl_seconds must be positive.")

    def is_stale(self, now: datetime) -> bool:
        """Return True when ``now`` is at or past capture time plus TTL."""
        _require_tz_aware(now, "now")
        return now >= self.captured_at + timedelta(seconds=self.ttl_seconds)

    def require_fresh(self, now: datetime) -> None:
        """Raise AuthorityError when the pointer is stale at ``now``."""
        if self.is_stale(now):
            raise AuthorityError(f"Evidence {self.source_id!r} is stale.")
        logger.debug("Evidence fresh: %s", self.source_id)


__all__ = ["AuthoritativeFact", "AuthorityError", "EvidenceReference"]
