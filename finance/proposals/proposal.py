"""Immutable ResolutionProposal value object (P3.3, proposal phase only).

A ``Proposal`` authorizes nothing: it is a frozen draft that policy plus
HITL approval must precede before any Execution. The triple
(``proposal_id``, ``version``, ``content_hash``) is the pin target for
the approval phase, reusing the exact field names carried by
``finance.exceptions.approval.ApprovalPin`` (``proposal_id``,
``proposal_version``, ``content_hash``): the pin's ``proposal_version``
maps to this object's ``version``.

Only the Python standard library is used. This module imports nothing
from ``apps/``, ``agents/``, or ``shared/``.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


class ProposalAction(StrEnum):
    """Frozen resolution actions the builder may emit."""

    CREATE_CORRECTING_ENTRY = "CREATE_CORRECTING_ENTRY"
    VOID_DUPLICATE = "VOID_DUPLICATE"


def _require_decimal(field_name: str, value: object) -> Decimal:
    """Validate Decimal-only money, rejecting ``float``/``bool``.

    Args:
        field_name: Field name used in error messages.
        value: Raw value to validate.

    Returns:
        The value narrowed to ``Decimal``.

    Raises:
        TypeError: If the value is ``float`` or ``bool``.
        ValueError: If the value is not a finite ``Decimal``.
    """
    if isinstance(value, (bool, float)):
        raise TypeError(
            f"Field '{field_name}' must be Decimal, got {type(value).__name__}: "
            "float/bool money is rejected, use decimal.Decimal."
        )
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(
            f"Field '{field_name}' must be a finite Decimal, got {type(value).__name__}."
        )
    return value


def _require_id(field_name: str, value: object) -> str:
    """Validate a non-empty identifier and return it stripped."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Field '{field_name}' must be a non-empty string.")
    return value.strip()


def _coerce_action(value: object) -> ProposalAction:
    """Coerce a raw string to ``ProposalAction``, rejecting unknowns."""
    if isinstance(value, ProposalAction):
        return value
    if isinstance(value, str):
        try:
            return ProposalAction(value.strip().upper())
        except ValueError as exc:
            raise ValueError(f"Unknown proposal action {value!r}.") from exc
    raise TypeError(
        f"Field 'action' must be a ProposalAction or action name, got {type(value).__name__}."
    )


def compute_content_hash(
    *,
    proposal_id: str,
    exception_id: str,
    version: int,
    action: ProposalAction | str,
    amount: Decimal,
    debit_account: str,
    credit_account: str,
    evidence_ids: tuple[str, ...],
    rationale: str,
    requires_hitl: bool = True,
    supersedes: str | None = None,
) -> str:
    """Compute the sha256 hash over the canonical proposal fields.

    Args:
        proposal_id: Deterministic proposal identity (tenant-namespaced).
        exception_id: Owning exception aggregate identity.
        version: Proposal version (>= 1).
        action: Resolution action enum or name.
        amount: Deterministically recomputed Decimal amount.
        debit_account: Debit leg account.
        credit_account: Credit leg account.
        evidence_ids: Cited evidence identifiers in order.
        rationale: Human-readable rule-based rationale.
        requires_hitl: Must be True (spec: proposals never self-authorize).
        supersedes: Previous version's content hash, or None for v1.

    Returns:
        Lowercase sha256 hex digest of the canonical field encoding.
    """
    action_value = action.value if isinstance(action, ProposalAction) else str(action)
    canonical = "|".join(
        [
            proposal_id,
            exception_id,
            str(version),
            action_value,
            str(amount),
            debit_account,
            credit_account,
            ",".join(evidence_ids),
            rationale,
            str(requires_hitl),
            supersedes or "",
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Proposal:
    """Frozen resolution draft; authorizes nothing until approved.

    ``content_hash`` binds every hashed field: any mutation must go
    through ``mutate_proposal`` (new version, new hash), never an edit.
    ``supersedes`` chains history by holding the previous version's
    ``content_hash`` (None for v1). ``requires_hitl`` is always True.
    """

    proposal_id: str
    exception_id: str
    version: int
    action: ProposalAction
    amount: Decimal
    debit_account: str
    credit_account: str
    evidence_ids: tuple[str, ...]
    rationale: str
    content_hash: str = ""
    requires_hitl: bool = True
    supersedes: str | None = None

    def __post_init__(self) -> None:
        """Enforce identifiers, vocabularies, Decimal-only money, and hash."""
        object.__setattr__(self, "proposal_id", _require_id("proposal_id", self.proposal_id))
        object.__setattr__(self, "exception_id", _require_id("exception_id", self.exception_id))
        object.__setattr__(self, "action", _coerce_action(self.action))
        version = self.version
        if not isinstance(version, int) or isinstance(version, bool):
            raise TypeError("Field 'version' must be an int.")
        if version < 1:
            raise ValueError(f"Field 'version' must be >= 1, got {version}.")
        _require_decimal("amount", self.amount)
        object.__setattr__(self, "debit_account", _require_id("debit_account", self.debit_account))
        object.__setattr__(
            self, "credit_account", _require_id("credit_account", self.credit_account)
        )
        raw_evidence = self.evidence_ids
        if isinstance(raw_evidence, list):
            coerced = tuple(raw_evidence)
        elif isinstance(raw_evidence, tuple):
            coerced = raw_evidence
        else:
            raise TypeError("Field 'evidence_ids' must be a tuple or list of str.")
        for evidence_id in coerced:
            if not isinstance(evidence_id, str) or not evidence_id.strip():
                raise ValueError("Every entry of 'evidence_ids' must be non-empty str.")
        object.__setattr__(self, "evidence_ids", coerced)
        if not isinstance(self.rationale, str) or not self.rationale.strip():
            raise ValueError("Field 'rationale' must be a non-empty string.")
        if self.requires_hitl is not True:
            raise ValueError("Field 'requires_hitl' must be True: proposals never self-authorize.")
        if self.supersedes is not None:
            if not isinstance(self.supersedes, str) or not self.supersedes.strip():
                raise ValueError("Field 'supersedes' must be a non-empty string or null.")
            if _HASH_PATTERN.fullmatch(self.supersedes.strip()) is None:
                raise ValueError("Field 'supersedes' must be a sha256 hex digest or null.")
            object.__setattr__(self, "supersedes", self.supersedes.strip())
        pending_hash: Any = self.content_hash
        if not isinstance(pending_hash, str):
            raise TypeError("Field 'content_hash' must be a string.")
        if not pending_hash:
            computed = compute_content_hash(
                proposal_id=self.proposal_id,
                exception_id=self.exception_id,
                version=self.version,
                action=self.action,
                amount=self.amount,
                debit_account=self.debit_account,
                credit_account=self.credit_account,
                evidence_ids=self.evidence_ids,
                rationale=self.rationale,
                requires_hitl=self.requires_hitl,
                supersedes=self.supersedes,
            )
            object.__setattr__(self, "content_hash", computed)
        elif _HASH_PATTERN.fullmatch(pending_hash.strip()) is None:
            raise ValueError("Field 'content_hash' must be a sha256 hex digest.")

    @property
    def proposal_version(self) -> int:
        """Alias matching ``ApprovalPin.proposal_version`` for pin binding.

        The approval triple (``proposal_id``, ``proposal_version``,
        ``content_hash``) pins this object's (``proposal_id``,
        ``version``, ``content_hash``); this property exposes the middle
        coordinate under the pin's exact field name.
        """
        return self.version

    def pin_triple(self) -> tuple[str, int, str]:
        """Return the (``proposal_id``, ``proposal_version``, ``content_hash``) triple."""
        return (self.proposal_id, self.proposal_version, self.content_hash)

    def verifies(self) -> bool:
        """Return True when the stored hash matches the canonical fields."""
        expected = compute_content_hash(
            proposal_id=self.proposal_id,
            exception_id=self.exception_id,
            version=self.version,
            action=self.action,
            amount=self.amount,
            debit_account=self.debit_account,
            credit_account=self.credit_account,
            evidence_ids=self.evidence_ids,
            rationale=self.rationale,
            requires_hitl=self.requires_hitl,
            supersedes=self.supersedes,
        )
        return hmac.compare_digest(expected, self.content_hash)
