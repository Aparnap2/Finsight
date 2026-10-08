"""Deterministic incident lifecycle (P10-07).

In-memory state machine only: no persistence, no integrations, no SIEM.
Incident registry persistence is not part of P10-07 and is a
post-release/follow-up capability.

Semantics:

- Closed vocabularies for severity, category, state, outcome.
- Forward-only transitions; CLOSED is terminal (recurrence is a new
  incident referencing the prior id in evidence).
- Closure requires a non-empty outcome; anything else raises.
- Rejected transitions change nothing: same state, same audit trail
  (atomicity is tested, not just the exception type).
- Frozen incidents; audit entries sequence-ordered (never wall-clock).
- Idempotent report: same id replays with an occurrence counter and
  never duplicates or overwrites.
- Tenant-scoped reads; cross-tenant invisibility.
- Title/evidence scrubbed at creation via the approved secrets
  primitives; actor/tenant preserved for accountability.
- Notification matrix emits decision records only.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from shared.safety.secrets import scrub_text

__all__ = [
    "Incident",
    "IncidentCategory",
    "IncidentEvent",
    "IncidentOutcome",
    "IncidentRegistry",
    "IncidentSeverity",
    "IncidentState",
    "IncidentTransitionError",
    "NotificationDecision",
    "notification_decision",
]


class IncidentTransitionError(Exception):
    """Raised when a transition is illegal; state and audit are unchanged."""


class IncidentSeverity(StrEnum):
    """Closed severity vocabulary (matches repo severity words)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentCategory(StrEnum):
    """Closed incident-category vocabulary."""

    DATA_LEAK = "DATA_LEAK"
    TENANT_ISOLATION = "TENANT_ISOLATION"
    SECRET_EXPOSURE = "SECRET_EXPOSURE"
    PROMPT_INJECTION = "PROMPT_INJECTION"
    AUTHORITY_ESCALATION = "AUTHORITY_ESCALATION"
    RETENTION = "RETENTION"
    AVAILABILITY = "AVAILABILITY"
    INTEGRITY = "INTEGRITY"


class IncidentState(StrEnum):
    """Closed lifecycle states; forward-only, CLOSED terminal."""

    DETECTED = "DETECTED"
    TRIAGED = "TRIAGED"
    CONTAINED = "CONTAINED"
    INVESTIGATING = "INVESTIGATING"
    RECOVERING = "RECOVERING"
    CLOSED = "CLOSED"


class IncidentOutcome(StrEnum):
    """Closed closure outcomes; required, never empty."""

    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"
    ACCEPTED_RISK = "ACCEPTED_RISK"


_TRANSITIONS: dict[IncidentState, IncidentState] = {
    IncidentState.DETECTED: IncidentState.TRIAGED,
    IncidentState.TRIAGED: IncidentState.CONTAINED,
    IncidentState.CONTAINED: IncidentState.INVESTIGATING,
    IncidentState.INVESTIGATING: IncidentState.RECOVERING,
    IncidentState.RECOVERING: IncidentState.CLOSED,
}


@dataclass(frozen=True)
class IncidentEvent:
    """One immutable audit entry, ordered by sequence (not wall clock)."""

    incident_id: str
    sequence: int
    from_state: IncidentState
    to_state: IncidentState
    actor: str
    detail: str = ""
    occurred_at: datetime | None = None


@dataclass(frozen=True)
class Incident:
    """One frozen incident snapshot; transitions return new snapshots."""

    incident_id: str
    tenant_id: str
    category: IncidentCategory
    severity: IncidentSeverity
    title: str
    owner: str
    reporter: str
    state: IncidentState = IncidentState.DETECTED
    outcome: str = ""
    evidence: tuple[str, ...] = ()
    timeline: tuple[IncidentEvent, ...] = ()
    occurrences: int = 1

    def _transition(self, to_state: IncidentState, actor: str, detail: str = "") -> Incident:
        """Move one legal step, appending exactly one audit event."""
        expected = _TRANSITIONS.get(self.state)
        if expected is not to_state:
            raise IncidentTransitionError(
                f"illegal transition {self.state.value} -> {to_state.value} for {self.incident_id}"
            )
        event = IncidentEvent(
            incident_id=self.incident_id,
            sequence=len(self.timeline),
            from_state=self.state,
            to_state=to_state,
            actor=actor,
            detail=detail,
            occurred_at=datetime.now(UTC),
        )
        return dataclasses.replace(self, state=to_state, timeline=(*self.timeline, event))

    def triage(self, *, actor: str) -> Incident:
        """Record triage ownership."""
        return self._transition(IncidentState.TRIAGED, actor)

    def contain(self, *, actor: str, action: str = "") -> Incident:
        """Record containment of the active impact."""
        return self._transition(IncidentState.CONTAINED, actor, detail=action)

    def investigate(self, *, actor: str) -> Incident:
        """Record the start of scoped investigation."""
        return self._transition(IncidentState.INVESTIGATING, actor)

    def recover(self, *, actor: str) -> Incident:
        """Record the start of recovery/remediation."""
        return self._transition(IncidentState.RECOVERING, actor)

    def close(self, *, actor: str, outcome: str) -> Incident:
        """Close terminally with a required non-empty outcome."""
        if not outcome:
            raise IncidentTransitionError(
                f"closure of {self.incident_id} requires a non-empty outcome"
            )
        closed = self._transition(IncidentState.CLOSED, actor, detail=outcome)
        return dataclasses.replace(closed, outcome=outcome)


@dataclass(frozen=True)
class NotificationDecision:
    """Who must be told: decision record only, no integrations."""

    notify_owner: bool = True
    notify_board: bool = False
    notify_principals: bool = False


_BOARD_CATEGORIES = frozenset(
    {
        IncidentCategory.DATA_LEAK,
        IncidentCategory.TENANT_ISOLATION,
        IncidentCategory.SECRET_EXPOSURE,
    }
)


def notification_decision(incident: Incident) -> NotificationDecision:
    """Compute the notification decision from severity × category.

    CRITICAL severity always notifies the board; affected principals are
    notified for CRITICAL exfiltration-shaped categories. Everything else
    stays with the owner. Policy input, not derived truth.
    """
    if incident.severity is IncidentSeverity.CRITICAL:
        return NotificationDecision(
            notify_owner=True,
            notify_board=True,
            notify_principals=incident.category in _BOARD_CATEGORIES,
        )
    return NotificationDecision()


class IncidentRegistry:
    """In-memory incident store with idempotent report semantics."""

    def __init__(self) -> None:
        self._incidents: dict[str, Incident] = {}

    def report(
        self,
        *,
        incident_id: str,
        tenant_id: str,
        category: str,
        severity: str,
        title: str,
        owner: str,
        reporter: str,
        evidence: tuple[str, ...] | list[str] = (),
    ) -> Incident:
        """Create or replay an incident by id.

        Same id replays: occurrence counter grows, stored incident is
        otherwise untouched (supplied payload never overwrites). Blank
        ids/tenants are rejected; title and evidence are scrubbed at
        creation while actor/tenant stay verbatim for accountability.
        """
        if not incident_id or not incident_id.strip():
            raise ValueError("incident_id must be a non-empty string")
        if not tenant_id or not tenant_id.strip():
            raise ValueError("tenant_id must be a non-empty string")
        existing = self._incidents.get(incident_id)
        if existing is not None:
            replayed = dataclasses.replace(existing, occurrences=existing.occurrences + 1)
            self._incidents[incident_id] = replayed
            return replayed
        incident = Incident(
            incident_id=incident_id,
            tenant_id=tenant_id,
            category=IncidentCategory(category),
            severity=IncidentSeverity(severity),
            title=scrub_text(title),
            owner=owner,
            reporter=reporter,
            evidence=tuple(scrub_text(item) for item in evidence),
        )
        self._incidents[incident_id] = incident
        return incident

    def get(self, incident_id: str) -> Incident | None:
        """Return one incident by id, or None when unknown."""
        return self._incidents.get(incident_id)

    def for_tenant(self, tenant_id: str) -> list[Incident]:
        """List incidents owned by one tenant (cross-tenant invisible)."""
        return [
            incident for incident in self._incidents.values() if incident.tenant_id == tenant_id
        ]

    def count(self) -> int:
        """Return the number of stored incidents."""
        return len(self._incidents)
