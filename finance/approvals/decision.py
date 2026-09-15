"""HITL approval decision value objects (T2, decision phase only).

``ApprovalCommand`` is the single decision input; ``ApprovalRecord`` is the
immutable decision fact persisted alongside the exception CAS. The record
pins the exact proposal triple (``proposal_id``, ``proposal_version``,
``content_hash``) reusing ``finance.exceptions.approval.ApprovalPin`` field
names, so skew between approval time and proposal HEAD is detectable.

Only the Python standard library plus ``finance.*`` are used. This module
imports nothing from ``apps/``, ``agents/``, or ``shared/``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


class ApprovalDecision(StrEnum):
    """Terminal HITL verdicts; no other value is a decision."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


def _require_id(field_name: str, value: object) -> str:
    """Validate a non-empty identifier and return it stripped."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _require_version(field_name: str, value: object) -> int:
    """Validate a 1-based version integer."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"Field '{field_name}' must be an int.")
    if value < 1:
        raise ValueError(f"Field '{field_name}' must be >= 1, got {value}.")
    return value


def _require_hash(field_name: str, value: object) -> str:
    """Validate a sha256 hex digest and return it stripped."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{field_name}' must be a non-empty string.")
    digest = value.strip()
    if _HASH_PATTERN.fullmatch(digest) is None:
        raise ValueError(f"Field '{field_name}' must be a sha256 hex digest.")
    return digest


def _coerce_decision(value: object) -> ApprovalDecision:
    """Coerce a raw string to ``ApprovalDecision``, rejecting unknowns."""
    if isinstance(value, ApprovalDecision):
        return value
    if isinstance(value, str):
        try:
            return ApprovalDecision(value.strip().upper())
        except ValueError as exc:
            raise ValueError(f"Unknown approval decision {value!r}.") from exc
    raise TypeError(
        "Field 'decision' must be an ApprovalDecision or decision name, "
        f"got {type(value).__name__}."
    )


def approval_id_for(idempotency_key: str) -> str:
    """Derive a deterministic approval id from the idempotency key.

    Args:
        idempotency_key: Caller-supplied idempotency key (non-empty).

    Returns:
        ``appr_<16 hex>`` stable for identical keys, so replays address
        the same record instead of minting duplicates.
    """
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"appr_{digest[:16]}"


@dataclass(frozen=True)
class ApprovalCommand:
    """One HITL decision request against an awaiting exception aggregate.

    The command carries no money and no action: ``amount``/``action``
    fields are rejected (the API layer enforces this with a 422). Policy
    reads money from the pinned proposal, never from the caller.
    """

    exception_id: str
    proposal_id: str
    proposal_version: int
    proposal_content_hash: str
    approver_id: str
    decision: ApprovalDecision
    idempotency_key: str
    expected_state_version: int

    def __post_init__(self) -> None:
        """Enforce identifiers, triple shape, decision vocabulary, versions."""
        object.__setattr__(self, "exception_id", _require_id("exception_id", self.exception_id))
        object.__setattr__(self, "proposal_id", _require_id("proposal_id", self.proposal_id))
        object.__setattr__(
            self, "proposal_version", _require_version("proposal_version", self.proposal_version)
        )
        object.__setattr__(
            self,
            "proposal_content_hash",
            _require_hash("proposal_content_hash", self.proposal_content_hash),
        )
        object.__setattr__(self, "approver_id", _require_id("approver_id", self.approver_id))
        object.__setattr__(self, "decision", _coerce_decision(self.decision))
        object.__setattr__(
            self, "idempotency_key", _require_id("idempotency_key", self.idempotency_key)
        )
        object.__setattr__(
            self,
            "expected_state_version",
            _require_version("expected_state_version", self.expected_state_version),
        )

    def pin_triple(self) -> tuple[str, int, str]:
        """Return the pinned (``proposal_id``, ``proposal_version``, ``content_hash``)."""
        return (self.proposal_id, self.proposal_version, self.proposal_content_hash)


@dataclass(frozen=True)
class ApprovalRecord:
    """Immutable fact of one terminal HITL decision.

    ``approval_id`` is deterministic over ``idempotency_key`` (see
    :func:`approval_id_for`); ``state_version`` is the exception aggregate
    version immediately after the decision CAS (``expected + 1``).
    ``created_at`` is tz-aware UTC.
    """

    approval_id: str
    exception_id: str
    proposal_id: str
    proposal_version: int
    content_hash: str
    decision: ApprovalDecision
    approver_id: str
    idempotency_key: str
    state_version: int
    created_at: datetime

    def __post_init__(self) -> None:
        """Enforce identifiers, triple shape, decision, versions, and time."""
        object.__setattr__(self, "approval_id", _require_id("approval_id", self.approval_id))
        object.__setattr__(self, "exception_id", _require_id("exception_id", self.exception_id))
        object.__setattr__(self, "proposal_id", _require_id("proposal_id", self.proposal_id))
        object.__setattr__(
            self, "proposal_version", _require_version("proposal_version", self.proposal_version)
        )
        object.__setattr__(self, "content_hash", _require_hash("content_hash", self.content_hash))
        object.__setattr__(self, "decision", _coerce_decision(self.decision))
        object.__setattr__(self, "approver_id", _require_id("approver_id", self.approver_id))
        object.__setattr__(
            self, "idempotency_key", _require_id("idempotency_key", self.idempotency_key)
        )
        object.__setattr__(
            self, "state_version", _require_version("state_version", self.state_version)
        )
        created: Any = self.created_at
        if not isinstance(created, datetime):
            raise TypeError("Field 'created_at' must be a datetime.")
        if created.tzinfo is None or created.tzinfo.utcoffset(created) is None:
            raise ValueError("Field 'created_at' must be tz-aware.")

    @classmethod
    def create(
        cls,
        *,
        cmd: ApprovalCommand,
        state_version: int,
        created_at: datetime | None = None,
    ) -> ApprovalRecord:
        """Build the record for a gate-passed command.

        Args:
            cmd: The validated decision command.
            state_version: Post-CAS aggregate version (``expected + 1``).
            created_at: Fixed clock for tests; defaults to UTC now.

        Returns:
            A frozen record with a deterministic id over the key.
        """
        return cls(
            approval_id=approval_id_for(cmd.idempotency_key),
            exception_id=cmd.exception_id,
            proposal_id=cmd.proposal_id,
            proposal_version=cmd.proposal_version,
            content_hash=cmd.proposal_content_hash,
            decision=cmd.decision,
            approver_id=cmd.approver_id,
            idempotency_key=cmd.idempotency_key,
            state_version=state_version,
            created_at=created_at if created_at is not None else datetime.now(UTC),
        )

    def pin_triple(self) -> tuple[str, int, str]:
        """Return the pinned (``proposal_id``, ``proposal_version``, ``content_hash``)."""
        return (self.proposal_id, self.proposal_version, self.content_hash)
