"""P10-07 RED: deterministic incident lifecycle (failing: no module).

Contract under review:

- Closed vocabularies: severity (LOW/MEDIUM/HIGH/CRITICAL), category
  (DATA_LEAK, TENANT_ISOLATION, SECRET_EXPOSURE, PROMPT_INJECTION,
  AUTHORITY_ESCALATION, RETENTION, AVAILABILITY, INTEGRITY), states
  (DETECTED/TRIAGED/CONTAINED/INVESTIGATING/RECOVERING/CLOSED).
- Forward-only transitions; closure requires an outcome
  (RESOLVED/FALSE_POSITIVE/ACCEPTED_RISK); illegal moves raise.
- Deterministic ownership: every transition records actor + sequence;
  incidents are frozen, evidence append-only and immutable.
- Idempotent report: same incident_id replays (occurrence count grows),
  never duplicates; different payload, same id = same incident.
- Tenant-scoped registry reads; cross-tenant invisibility.
- Notification decision matrix keyed by severity × category (skeleton:
  decision record only, no provider integrations).
- PII/secrets scrubbed from title/evidence at creation; actor/tenant
  preserved for accountability.
- Runbook-declared categories ⊆ taxonomy (doc sync, no drift).

Pure unit tests, fixed data, no I/O, deterministic (sequence-ordered).
"""

from __future__ import annotations

import pytest


def _report(**overrides):  # type: ignore[no-untyped-def]
    """Report one incident through the (missing) registry factory."""
    from shared.privacy.incidents import IncidentRegistry

    kwargs = {
        "incident_id": "inc-001",
        "tenant_id": "tenant-acme",
        "category": "DATA_LEAK",
        "severity": "HIGH",
        "title": "test incident",
        "owner": "owner-1",
        "reporter": "detector-1",
    }
    kwargs.update(overrides)
    return IncidentRegistry().report(**kwargs)


class TestTaxonomy:
    def test_vocabularies_closed(self) -> None:
        from shared.privacy import incidents as mod

        assert {s.value for s in mod.IncidentSeverity} == {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }
        assert {c.value for c in mod.IncidentCategory} == {
            "DATA_LEAK",
            "TENANT_ISOLATION",
            "SECRET_EXPOSURE",
            "PROMPT_INJECTION",
            "AUTHORITY_ESCALATION",
            "RETENTION",
            "AVAILABILITY",
            "INTEGRITY",
        }
        assert {s.value for s in mod.IncidentState} == {
            "DETECTED",
            "TRIAGED",
            "CONTAINED",
            "INVESTIGATING",
            "RECOVERING",
            "CLOSED",
        }
        assert {o.value for o in mod.IncidentOutcome} == {
            "RESOLVED",
            "FALSE_POSITIVE",
            "ACCEPTED_RISK",
        }


class TestLifecycle:
    def test_full_walk_to_closed(self) -> None:
        incident = _report()
        assert incident.state.value == "DETECTED"
        incident = incident.triage(actor="owner-1")
        assert incident.state.value == "TRIAGED"
        incident = incident.contain(actor="owner-1", action="revoked key")
        assert incident.state.value == "CONTAINED"
        incident = incident.investigate(actor="owner-1")
        assert incident.state.value == "INVESTIGATING"
        incident = incident.recover(actor="owner-1")
        assert incident.state.value == "RECOVERING"
        incident = incident.close(actor="owner-1", outcome="RESOLVED")
        assert incident.state.value == "CLOSED"
        assert incident.outcome == "RESOLVED"

    def test_illegal_transition_raises(self) -> None:
        from shared.privacy.incidents import IncidentTransitionError

        incident = _report()
        with pytest.raises(IncidentTransitionError):
            incident.close(actor="owner-1", outcome="RESOLVED")

    def test_close_requires_outcome(self) -> None:
        from shared.privacy.incidents import IncidentTransitionError

        incident = _report()
        incident = incident.triage(actor="owner-1")
        incident = incident.contain(actor="owner-1", action="x")
        incident = incident.investigate(actor="owner-1")
        incident = incident.recover(actor="owner-1")
        with pytest.raises(IncidentTransitionError):
            incident.close(actor="owner-1", outcome="")


class TestRejectedTransitionsChangeNothing:
    def test_illegal_move_preserves_state_and_audit(self) -> None:
        from shared.privacy.incidents import IncidentTransitionError

        incident = _report()
        before_state = incident.state
        before_timeline = incident.timeline
        with pytest.raises(IncidentTransitionError):
            incident.contain(actor="owner-1", action="x")
        assert incident.state is before_state
        assert incident.timeline == before_timeline

    def test_closed_rejects_everything_unchanged(self) -> None:
        from shared.privacy.incidents import IncidentTransitionError

        incident = _report()
        incident = incident.triage(actor="owner-1")
        incident = incident.contain(actor="owner-1", action="x")
        incident = incident.investigate(actor="owner-1")
        incident = incident.recover(actor="owner-1")
        closed = incident.close(actor="owner-1", outcome="RESOLVED")
        frozen_state = closed.state
        frozen_timeline = closed.timeline
        for attempt in (
            lambda: closed.triage(actor="owner-1"),
            lambda: closed.contain(actor="owner-1", action="x"),
            lambda: closed.investigate(actor="owner-1"),
            lambda: closed.recover(actor="owner-1"),
            lambda: closed.close(actor="owner-1", outcome="RESOLVED"),
        ):
            with pytest.raises(IncidentTransitionError):
                attempt()
        assert closed.state is frozen_state
        assert closed.timeline == frozen_timeline

    def test_audit_trail_appends_in_order(self) -> None:
        incident = _report()
        before = list(incident.timeline)
        incident = incident.triage(actor="owner-1")
        assert len(incident.timeline) == len(before) + 1
        assert [e.sequence for e in incident.timeline] == sorted(
            e.sequence for e in incident.timeline
        )
        assert incident.timeline[-1].actor == "owner-1"
        assert before == list(incident.timeline[:-1])


class TestIdempotency:
    def test_duplicate_signal_replays_not_duplicates(self) -> None:
        from shared.privacy.incidents import IncidentRegistry

        registry = IncidentRegistry()
        first = registry.report(
            incident_id="inc-dup",
            tenant_id="tenant-acme",
            category="AVAILABILITY",
            severity="LOW",
            title="flapping detector",
            owner="owner-1",
            reporter="detector-1",
        )
        second = registry.report(
            incident_id="inc-dup",
            tenant_id="tenant-acme",
            category="AVAILABILITY",
            severity="LOW",
            title="flapping detector",
            owner="owner-1",
            reporter="detector-1",
        )
        assert first.incident_id == second.incident_id
        assert second.occurrences == first.occurrences + 1
        assert registry.count() == 1

    def test_cross_tenant_invisible(self) -> None:
        from shared.privacy.incidents import IncidentRegistry

        registry = IncidentRegistry()
        registry.report(
            incident_id="inc-a",
            tenant_id="tenant-a",
            category="DATA_LEAK",
            severity="HIGH",
            title="a",
            owner="owner-a",
            reporter="detector-a",
        )
        assert [i.incident_id for i in registry.for_tenant("tenant-b")] == []
        assert [i.incident_id for i in registry.for_tenant("tenant-a")] == ["inc-a"]


class TestScrubbing:
    def test_title_and_evidence_scrubbed_actor_kept(self) -> None:
        from shared.privacy import incidents as mod

        registry = mod.IncidentRegistry()
        incident = registry.report(
            incident_id="inc-pii",
            tenant_id="tenant-acme",
            category="DATA_LEAK",
            severity="HIGH",
            title="leak involving rahul@example.com key sk-test-synthetic-secret-value",
            owner="owner-1",
            reporter="detector-1",
            evidence=["log line with rahul@example.com inside"],
        )
        assert "rahul@example.com" not in incident.title
        assert "sk-test-synthetic-secret-value" not in incident.title
        assert all("rahul@example.com" not in e for e in incident.evidence)
        assert incident.owner == "owner-1"
        assert incident.tenant_id == "tenant-acme"


class TestNotificationMatrix:
    def test_critical_leak_notifies_board_and_principals(self) -> None:
        from shared.privacy import incidents as mod

        incident = _report(category="DATA_LEAK", severity="CRITICAL")
        decision = mod.notification_decision(incident)
        assert decision.notify_owner is True
        assert decision.notify_board is True
        assert decision.notify_principals is True

    def test_low_availability_owner_only(self) -> None:
        from shared.privacy import incidents as mod

        incident = _report(category="AVAILABILITY", severity="LOW")
        decision = mod.notification_decision(incident)
        assert decision.notify_owner is True
        assert decision.notify_board is False
        assert decision.notify_principals is False


class TestRunbookSync:
    def test_runbook_categories_within_taxonomy(self) -> None:
        import re
        from pathlib import Path

        from shared.privacy import incidents as mod

        doc = Path(__file__).resolve().parents[3] / "docs" / "privacy" / "INCIDENT_RESPONSE.md"
        text = doc.read_text(encoding="utf-8")
        declared = set(re.findall(r"category:\s*([A-Z_]+)", text))
        allowed = {c.value for c in mod.IncidentCategory}
        assert declared, "runbook must declare categories"
        assert declared <= allowed, declared - allowed
