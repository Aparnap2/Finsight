"""Refusal codes and the refusal signal for P6-06 approval gates.

The :class:`RefusalCode` values from contract section 4 (A19) are reproduced
verbatim: gate order G1-G7 decides, and the first matching refusal wins. The
additional engine-level members (``UNKNOWN_DECIDER_ROLE``,
``TIER_ESCALATION_REQUIRED``, ``PIN_SKEW_HASH``, ``PIN_SKEW_VERSION``,
``DUPLICATE_DECISION``, ``DECISION_REJECTED``, ``TOKEN_FORGED``) cover cases
the contract leaves silent; ``TIER_ESCALATION_REQUIRED`` and
``PIN_SKEW_VERSION`` are reserved vocabulary for P6-07 diagnostics while the
G4/G6-G7 gates surface the spec codes per A19.
"""

from __future__ import annotations

from enum import StrEnum


class RefusalCode(StrEnum):
    """Machine-readable refusal codes for the G1-G7 gate chain."""

    UNAUTHENTICATED_ACTOR = "UNAUTHENTICATED_ACTOR"
    """G1: auth proof missing, invalid, or expired (A5)."""

    APPROVE_RIGHT_DENIED = "APPROVE_RIGHT_DENIED"
    """G2: known role without approve rights: analyst, payment-ops, auditor, agent."""

    SELF_APPROVAL_DENIED = "SELF_APPROVAL_DENIED"
    """G2: proposer approved their own proposal; separation of duties (A7)."""

    CROSS_CASE_REFUSED = "CROSS_CASE_REFUSED"
    """G3/G7: actor or token bound to a different company or case (A8, A18)."""

    OVER_TIER_AMOUNT = "OVER_TIER_AMOUNT"
    """G4: decision below the required refund tier; escalate via fresh decision (A9)."""

    LEGACY_DIRECTOR_REQUIRED = "LEGACY_DIRECTOR_REQUIRED"
    """G4: legacy correction above the manager band needs a director (A10)."""

    CLOSED_PERIOD_BLOCKED = "CLOSED_PERIOD_BLOCKED"
    """G4: correction targets a closed period; no override exists (A11)."""

    INVALID_ACCOUNT_CODE = "INVALID_ACCOUNT_CODE"
    """G4: account code missing, blank, or outside AccountMappings (A12)."""

    UNVALIDATED_PROPOSAL = "UNVALIDATED_PROPOSAL"
    """G5: hash recomputation failed, no evidence, or forbidden fields (A13)."""

    PROPOSAL_DRIFT_REFUSED = "PROPOSAL_DRIFT_REFUSED"
    """G5/G6: validated amount or evidence drifted before decision (A13)."""

    PROPOSAL_VERSION_SWAPPED = "PROPOSAL_VERSION_SWAPPED"
    """G6/G7: approval pin no longer matches the live proposal version (A15)."""

    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    """G7: token presented after expires_at; renewal is a fresh decision (A18)."""

    AUTHORIZATION_REPLAYED = "AUTHORIZATION_REPLAYED"
    """G7: already-consumed authorization presented again; enforced by P6-07 (A18)."""

    AUTHORIZATION_SCOPE_ESCAPE = "AUTHORIZATION_SCOPE_ESCAPE"
    """G7: token presented outside its bound scope limits (A18)."""

    UNKNOWN_DECIDER_ROLE = "UNKNOWN_DECIDER_ROLE"
    """G2 engine code: role outside the A6 matrix fails closed with precision."""

    TIER_ESCALATION_REQUIRED = "TIER_ESCALATION_REQUIRED"
    """Reserved engine vocabulary for escalation-path diagnostics (P6-07).

    G4 surfaces ``OVER_TIER_AMOUNT`` or ``LEGACY_DIRECTOR_REQUIRED`` per A19;
    this member names the required follow-up without replacing the refusal.
    """

    PIN_SKEW_HASH = "PIN_SKEW_HASH"
    """G7 engine code: same-version presentation against a different pinned hash."""

    PIN_SKEW_VERSION = "PIN_SKEW_VERSION"
    """Reserved engine vocabulary for version-skew diagnostics (P6-07).

    G6/G7 surfaces ``PROPOSAL_VERSION_SWAPPED`` per A19; this member names
    the fine-grained skew without replacing the refusal.
    """

    DUPLICATE_DECISION = "DUPLICATE_DECISION"
    """G6 engine code: a second differing decision on the same pin (A14, A16)."""

    DECISION_REJECTED = "DECISION_REJECTED"
    """G7 engine code: a REJECT outcome mints no authorization (negative path)."""

    TOKEN_FORGED = "TOKEN_FORGED"
    """G7 engine code: token binding digest fails verification (A17 integrity)."""


class ApprovalRefused(Exception):  # noqa: N818 -- contract refusal signal, not an error
    """Gate refusal signal: stop the chain, emit the code, change no state.

    Attributes:
        code: The machine-readable refusal code.
        gate: The gate id (``G1``-``G7``) that refused.
        message: Human-readable reason for the audit entry.
    """

    def __init__(self, code: RefusalCode, gate: str, message: str) -> None:
        """Record the refusing gate, code, and reason.

        Args:
            code: The machine-readable refusal code.
            gate: The gate id (``G1``-``G7``) that refused.
            message: Human-readable reason for the audit entry.
        """
        super().__init__(f"[{gate}/{code.value}] {message}")
        self.code = code
        self.gate = gate
        self.message = message
