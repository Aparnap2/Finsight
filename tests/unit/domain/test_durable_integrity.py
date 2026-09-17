"""Durable integrity tests: versioned audit, agreement, terminal rest (D4-D6).

Covers ``finance/domain/situation_repository.py`` extensions: event
version binding (D4a), stored-transition agreement (D4b), durable
evidence/tamper fields + chain verification (D4c), terminal-at-rest
refusal (D5), and equal-byte short-circuit (D6). Zero network, no LLM.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from finance.domain.financial_situation import FinancialSituation, SituationStatus
from finance.domain.situation_repository import (
    ConcurrencyError,
    SituationRepository,
    SituationRow,
    TerminalStateError,
    canonical_payload_bytes,
)

SID_1 = "FS-2026-0916-00231"
"""Golden FS-231 case id."""

AT_1 = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
"""Caller-supplied audit instant (tz-aware datetime)."""


def _situation(status: SituationStatus = SituationStatus.DETECTED) -> FinancialSituation:
    """Build the golden FS-231 aggregate at ``status``."""
    return FinancialSituation(
        situation_id=SID_1,
        company_id="meridian",
        expected=Decimal("1000000"),
        razorpay_net=Decimal("972500"),
        quickbooks=Decimal("982500"),
        legacy=Decimal("982500"),
        status=status,
    )


def _audit(
    event_id: str,
    *,
    from_status: str = "DETECTED",
    to_status: str = "DETECTED",
    version: int = 1,
    at: datetime = AT_1,
) -> dict[str, object]:
    """Build one caller-side audit dict in the repository-owned shape."""
    return {
        "event_id": event_id,
        "situation_id": SID_1,
        "company_id": "meridian",
        "from_status": from_status,
        "to_status": to_status,
        "at": at,
        "actor": "case-worker",
        "version": version,
    }


@pytest.fixture(params=["memory", "sqlite"])
def repo(request: pytest.FixtureRequest) -> SituationRepository:
    """Fresh repository on each backend."""
    if request.param == "memory":
        return SituationRepository()
    return SituationRepository(create_engine("sqlite:///:memory:"))


def test_event_version_must_equal_new_bump(repo: SituationRepository) -> None:
    """Stale-versioned events are rejected, never rebound."""
    repo.save(_situation())
    with pytest.raises(ValueError, match="stale audit event"):
        repo.save(
            _situation(status=SituationStatus.TRIAGED),
            audit_events=[_audit(
                "EVT-STALE", from_status="DETECTED", to_status="TRIAGED",
                version=1,
            )],
        )
    assert repo.save(
        _situation(status=SituationStatus.TRIAGED),
        audit_events=[_audit(
            "EVT-OK", from_status="DETECTED", to_status="TRIAGED", version=2,
        )],
    ) == 2


def test_from_to_must_agree_with_stored_transition(
    repo: SituationRepository,
) -> None:
    """Events claiming TRIAGED→CLOSED over stored DETECTED are refused."""
    repo.save(_situation())
    with pytest.raises(ValueError, match="disagrees"):
        repo.save(
            _situation(status=SituationStatus.TRIAGED),
            audit_events=[_audit(
                "EVT-LIE", from_status="TRIAGED", to_status="CLOSED",
                version=2,
            )],
        )
    assert repo.get_for_company("meridian", SID_1) == _situation()


def test_terminal_rows_refuse_writes(repo: SituationRepository) -> None:
    """Stored CLOSED and REJECTED rows reject every further save."""
    closed = _situation(status=SituationStatus.CLOSED)
    repo.save(closed)
    with pytest.raises(TerminalStateError):
        repo.save(_situation(status=SituationStatus.CLOSED))
    with pytest.raises(TerminalStateError):
        repo.save(_situation(status=SituationStatus.DETECTED), expected_version=1)
    assert repo.get_for_company("meridian", SID_1) == closed


def test_terminal_refusal_precedes_stale_version(repo: SituationRepository) -> None:
    """Terminal check wins over version logic on closed rows."""
    repo.save(_situation(status=SituationStatus.REJECTED))
    with pytest.raises(TerminalStateError):
        repo.save(_situation(status=SituationStatus.DETECTED), expected_version=99)
    assert issubclass(TerminalStateError, ValueError)


def test_fresh_closed_create_allowed(repo: SituationRepository) -> None:
    """Creating a CLOSED row directly is permitted (records arrival)."""
    assert repo.save(_situation(status=SituationStatus.CLOSED)) == 1


def test_equal_bytes_short_circuit(repo: SituationRepository) -> None:
    """Identical re-save without events returns the version, no bump."""
    assert repo.save(_situation()) == 1
    assert repo.save(_situation()) == 1
    assert repo.save(_situation(status=SituationStatus.TRIAGED)) == 2
    assert repo.save(_situation(status=SituationStatus.TRIAGED)) == 2


def test_variance_snapshot_and_prev_hash_round_trip(
    repo: SituationRepository,
) -> None:
    """Durable evidence fields persist and rehydrate exactly."""
    repo.save(
        _situation(),
        audit_events=[{
            **_audit("EVT-EV"),
            "variance_snapshot": Decimal("10000"),
        }],
    )
    trail = repo.audit_trail("meridian", SID_1)
    assert len(trail) == 1
    assert trail[0].variance_snapshot == "10000"
    assert trail[0].prev_hash == ""
    assert repo.verify_durable_chain("meridian", SID_1) is True


def test_forged_prev_hash_detected(repo: SituationRepository) -> None:
    """Caller-forged links persist verbatim but fail chain verification."""
    repo.save(_situation(), audit_events=[_audit("EVT-A")])
    repo.save(
        _situation(status=SituationStatus.TRIAGED),
        audit_events=[{
            **_audit(
                "EVT-B", from_status="DETECTED", to_status="TRIAGED",
                version=2,
            ),
            "prev_hash": "0" * 64,
        }],
    )
    assert repo.verify_durable_chain("meridian", SID_1) is False


def test_old_p6_01_rows_rehydrate() -> None:
    """Seven-key P6-01 payloads load with extension defaults."""
    engine = create_engine("sqlite:///:memory:")
    repo = SituationRepository(engine)
    legacy_payload = json.dumps({
        "company_id": "meridian",
        "expected": "1000000",
        "legacy": "982500",
        "quickbooks": "982500",
        "razorpay_net": "972500",
        "situation_id": SID_1,
        "status": "DETECTED",
    })
    from sqlalchemy.orm import Session as OrmSession

    with OrmSession(engine) as session:
        session.add(SituationRow(
            company_id="meridian",
            situation_id=SID_1,
            status="DETECTED",
            version=1,
            payload=legacy_payload,
        ))
        session.commit()
    loaded = repo.get_for_company("meridian", SID_1)
    assert loaded == _situation()


def test_canonical_payload_covers_all_fields() -> None:
    """Payload carries the full 17-key shape plus nested verification keys."""
    text = canonical_payload_bytes(_situation()).decode("utf-8")
    data = json.loads(text)
    assert set(data) == {
        "closed_at", "company_id", "decider_role", "evidence_ids",
        "expected", "hypothesis_count", "legacy", "proposal_hash",
        "proposal_ref", "proposal_version", "quickbooks", "razorpay_net",
        "rejection_reason", "situation_id", "status", "verification",
        "verified_total",
    }
    assert data["verification"] is None


def test_audit_version_optional_volatile() -> None:
    """Volatile AuditEvent defaults version to None (existing flows kept)."""
    from finance.domain.audit import AuditEvent

    event = AuditEvent(
        event_id="e" * 64,
        situation_id=SID_1,
        from_status=SituationStatus.DETECTED,
        to_status=SituationStatus.TRIAGED,
        at=datetime(2026, 9, 16, 10, 0, tzinfo=UTC),
        actor="case-worker",
    )
    assert event.version is None
    with pytest.raises(ValueError, match="version"):
        AuditEvent(
            event_id="f" * 64,
            situation_id=SID_1,
            from_status=SituationStatus.DETECTED,
            to_status=SituationStatus.TRIAGED,
            at=datetime(2026, 9, 16, 10, 0, tzinfo=UTC),
            actor="case-worker",
            version=0,
        )


def test_stale_event_never_rebounds_silently(repo: SituationRepository) -> None:
    """ConcurrencyError stays distinct from audit ValueError paths."""
    repo.save(_situation())
    with pytest.raises(ConcurrencyError):
        repo.save(_situation(), expected_version=99)
