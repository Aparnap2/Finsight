"""Evidence pointers: opaque, authority-derived references with HMAC provenance.

P6 ``finance/evidence`` and ``finance/facts`` remain the normative store;
this module only carries opaque pointers produced by a deterministic
accessor (``EvidenceRegistry``). Raw caller metadata never becomes
authority — it is validated against the registry's expected record,
including an HMAC that binds every field to a per-registry secret.
No mutation API, no network, no wall-clock inside stored state.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
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
class EvidenceRecord:
    """Authoritative record held by the deterministic accessor.

    Never supplied by the agent; the registry owns these.
    """

    source_id: str
    evidence_id: str
    captured_at: datetime
    digest: str
    provenance: str
    ttl_seconds: int

    def __post_init__(self) -> None:
        """Validate record shape."""
        _require_non_blank(self.source_id, "source_id")
        _require_non_blank(self.evidence_id, "evidence_id")
        _require_tz_aware(self.captured_at, "captured_at")
        if not isinstance(self.digest, str) or not _SHA256_RE.match(self.digest):
            raise AuthorityError("digest must be 64-char lowercase hex sha256.")
        _require_non_blank(self.provenance, "provenance")
        if isinstance(self.ttl_seconds, bool) or not isinstance(
            self.ttl_seconds, int
        ):
            raise AuthorityError("ttl_seconds must be an int.")
        if self.ttl_seconds <= 0:
            raise AuthorityError("ttl_seconds must be positive.")


@dataclass(frozen=True)
class AuthoritativeFact:
    """Frozen reference to a P6-established fact (opaque, HMAC-bound).

    Carries no mutation API: frozen dataclass, no setters, no promotion
    helpers. Agents may cite it, never mint it. Only
    ``EvidenceRegistry.create_fact`` produces a validated instance.
    """

    source_id: str
    evidence_id: str
    captured_at: datetime
    digest: str
    provenance: str
    _token: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate pointer shape and digest format (not authority)."""
        _require_non_blank(self.source_id, "source_id")
        _require_non_blank(self.evidence_id, "evidence_id")
        if not isinstance(self.digest, str) or not _SHA256_RE.match(self.digest):
            raise AuthorityError("digest must be 64-char lowercase hex sha256.")
        _require_tz_aware(self.captured_at, "captured_at")
        _require_non_blank(self.provenance, "provenance")
        logger.debug("AuthoritativeFact cited: %s", self.source_id)


@dataclass(frozen=True)
class EvidenceReference:
    """Opaque pointer to evidence, HMAC-bound to the issuing registry.

    Zero wall-clock inside stored state: freshness is always evaluated
    against an explicit ``now`` supplied by the caller. The ``_token``
    binds every field to the registry's secret; any caller-asserted
    field change invalidates the token, so the agent cannot mint or
    mutate a reference merely by knowing a source ID.
    """

    source_id: str
    evidence_id: str
    captured_at: datetime
    digest: str
    provenance: str
    ttl_seconds: int
    _token: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate pointer shape (not authority — authority is the HMAC)."""
        _require_non_blank(self.source_id, "source_id")
        _require_non_blank(self.evidence_id, "evidence_id")
        _require_tz_aware(self.captured_at, "captured_at")
        if not isinstance(self.digest, str) or not _SHA256_RE.match(self.digest):
            raise AuthorityError("digest must be 64-char lowercase hex sha256.")
        _require_non_blank(self.provenance, "provenance")
        if isinstance(self.ttl_seconds, bool) or not isinstance(
            self.ttl_seconds, int
        ):
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
            raise AuthorityError(f"Evidence {self.evidence_id!r} is stale.")
        logger.debug("Evidence fresh: %s", self.evidence_id)


class EvidenceRegistry:
    """Deterministic evidence-access boundary.

    Holds authoritative ``EvidenceRecord``s and issues opaque
    ``EvidenceReference`` / ``AuthoritativeFact`` pointers whose
    HMAC proves they were issued by this accessor. The agent never
    supplies the registry; it is injected by the deterministic plane.
    """

    def __init__(
        self,
        records: Mapping[str, EvidenceRecord],
        *,
        accessible_ids: set[str] | frozenset[str] | None = None,
    ) -> None:
        """Store records keyed by ``evidence_id``; accessible defaults to all."""
        self._records: dict[str, EvidenceRecord] = dict(records)
        if accessible_ids is None:
            self._accessible: set[str] = set(self._records.keys())
        else:
            self._accessible = set(accessible_ids)
        self._secret: str = uuid.uuid4().hex

    def is_known(self, evidence_id: str) -> bool:
        """Return True when the evidence_id is in the registry."""
        return evidence_id in self._records

    def is_accessible(self, evidence_id: str) -> bool:
        """Return True when the caller may cite this evidence_id."""
        return evidence_id in self._accessible

    def get_record(self, evidence_id: str) -> EvidenceRecord:
        """Return the authoritative record or raise AuthorityError."""
        try:
            return self._records[evidence_id]
        except KeyError as exc:
            raise AuthorityError(f"Unknown evidence {evidence_id!r}.") from exc

    def _hmac_ref(self, rec: EvidenceRecord) -> str:
        """HMAC binding every field of an evidence record to the secret."""
        payload = (
            f"{rec.source_id}:{rec.evidence_id}:{rec.captured_at.isoformat()}"
            f":{rec.digest}:{rec.provenance}:{rec.ttl_seconds}"
        ).encode()
        return hmac.new(self._secret.encode(), payload, hashlib.sha256).hexdigest()

    def _hmac_fact(self, fact: AuthoritativeFact) -> str:
        """HMAC binding every field of a fact to the secret."""
        payload = (
            f"{fact.source_id}:{fact.evidence_id}:{fact.captured_at.isoformat()}"
            f":{fact.digest}:{fact.provenance}"
        ).encode()
        return hmac.new(self._secret.encode(), payload, hashlib.sha256).hexdigest()

    def create_reference(self, evidence_id: str) -> EvidenceReference:
        """Issue an opaque, HMAC-bound reference for a known, accessible record."""
        rec = self.get_record(evidence_id)
        if not self.is_accessible(evidence_id):
            raise AuthorityError(f"Inaccessible evidence {evidence_id!r}.")
        token = self._hmac_ref(rec)
        return EvidenceReference(
            source_id=rec.source_id,
            evidence_id=rec.evidence_id,
            captured_at=rec.captured_at,
            digest=rec.digest,
            provenance=rec.provenance,
            ttl_seconds=rec.ttl_seconds,
            _token=token,
        )

    def create_fact(
        self,
        *,
        source_id: str,
        evidence_id: str,
        captured_at: datetime,
        digest: str,
        provenance: str = "p6_fact_store",
    ) -> AuthoritativeFact:
        """Issue an opaque, HMAC-bound fact pointer (deterministic accessor only)."""
        fact = AuthoritativeFact(
            source_id=source_id,
            evidence_id=evidence_id,
            captured_at=captured_at,
            digest=digest,
            provenance=provenance,
            _token="",
        )
        token = self._hmac_fact(fact)
        return AuthoritativeFact(
            source_id=source_id,
            evidence_id=evidence_id,
            captured_at=captured_at,
            digest=digest,
            provenance=provenance,
            _token=token,
        )

    def validate_reference(self, ref: EvidenceReference, now: datetime) -> None:
        """Raise AuthorityError unless ref was issued by this registry and is fresh.

        Checks: known, accessible, HMAC matches current fields (so any
        caller-asserted mutation invalidates), and freshness at ``now``.
        """
        _require_tz_aware(now, "now")
        rec = self.get_record(ref.evidence_id)
        if not self.is_accessible(ref.evidence_id):
            raise AuthorityError(f"Inaccessible evidence {ref.evidence_id!r}.")
        expected = self._hmac_ref(rec)
        # Recompute HMAC from the *presented* ref fields and compare to
        # the ref's own token — any field change breaks the binding.
        presented_rec = EvidenceRecord(
            source_id=ref.source_id,
            evidence_id=ref.evidence_id,
            captured_at=ref.captured_at,
            digest=ref.digest,
            provenance=ref.provenance,
            ttl_seconds=ref.ttl_seconds,
        )
        presented_token = self._hmac_ref(presented_rec)
        if ref._token != expected or ref._token != presented_token:
            raise AuthorityError(
                f"Evidence {ref.evidence_id!r} not issued by deterministic accessor."
            )
        # Fields must exactly match the authoritative record.
        if (
            ref.source_id != rec.source_id
            or ref.captured_at != rec.captured_at
            or ref.digest != rec.digest
            or ref.provenance != rec.provenance
            or ref.ttl_seconds != rec.ttl_seconds
        ):
            raise AuthorityError(
                f"Evidence {ref.evidence_id!r} metadata mismatch — possible fabrication."
            )
        ref.require_fresh(now)

    def validate_fact(self, fact: AuthoritativeFact) -> None:
        """Raise AuthorityError unless fact was issued by this registry."""
        expected = self._hmac_fact(fact)
        if fact._token != expected:
            raise AuthorityError(
                f"Fact {fact.evidence_id!r} not issued by deterministic accessor."
            )


__all__ = [
    "AuthoritativeFact",
    "AuthorityError",
    "EvidenceRecord",
    "EvidenceReference",
    "EvidenceRegistry",
]
