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
    closed = _proven_closed()
    repo.save(closed)
    with pytest.raises(TerminalStateError):
        repo.save(_proven_closed())
    with pytest.raises(TerminalStateError):
        repo.save(_situation(status=SituationStatus.DETECTED), expected_version=1)
    assert repo.get_for_company("meridian", SID_1) == closed


def test_terminal_refusal_precedes_stale_version(repo: SituationRepository) -> None:
    """Terminal check wins over version logic on closed rows."""
    repo.save(
        _situation(status=SituationStatus.REJECTED).model_copy(
            update={"rejection_reason": "duplicate proposal version"}
        )
    )
    with pytest.raises(TerminalStateError):
        repo.save(_situation(status=SituationStatus.DETECTED), expected_version=99)
    assert issubclass(TerminalStateError, ValueError)


def _proven_closed() -> FinancialSituation:
    """CLOSED aggregate carrying the full D1 close proof (FS-231)."""
    from finance.domain.verification import VerificationReport, VerificationVerdict

    recorded = _situation(status=SituationStatus.VERIFYING).record_verification(
        Decimal("992500")
    )
    report = VerificationReport(
        situation_id=SID_1,
        execution_id="LEGACY-20260916-0042",
        legacy_total_after=Decimal("992500"),
        variance_after=Decimal("0"),
        verdict=VerificationVerdict.VERIFIED,
        checked_at=AT_1,
    )
    return recorded.transition_to(SituationStatus.CLOSED, at=AT_1, verification=report)


def _bare_closed() -> FinancialSituation:
    """CLOSED aggregate with no proof at all (the persistence backdoor)."""
    return _situation(status=SituationStatus.CLOSED)


def test_fresh_closed_without_verification_rejected(
    repo: SituationRepository,
) -> None:
    """1. A proof-less CLOSED snapshot cannot be persisted."""
    with pytest.raises(ValueError, match="VerificationReport"):
        repo.save(_bare_closed())
    assert repo.get_for_company("meridian", SID_1) is None


def test_fresh_closed_with_failed_report_rejected(
    repo: SituationRepository,
) -> None:
    """2. A FAILED verdict never earns CLOSED, even with full shape."""
    from finance.domain.verification import VerificationReport, VerificationVerdict

    base = _proven_closed().model_copy(update={"status": SituationStatus.VERIFYING})
    failed = VerificationReport(
        situation_id=SID_1,
        execution_id="LEGACY-20260916-0042",
        legacy_total_after=Decimal("992500"),
        variance_after=Decimal("0"),
        verdict=VerificationVerdict.FAILED,
        checked_at=AT_1,
    )
    bad = base.model_copy(update={
        "status": SituationStatus.CLOSED,
        "verification": failed,
        "closed_at": AT_1,
        "verified_total": Decimal("992500"),
    })
    with pytest.raises(ValueError, match="unaccepted"):
        repo.save(bad)
    assert repo.get_for_company("meridian", SID_1) is None


def test_fresh_closed_with_wrong_situation_rejected(
    repo: SituationRepository,
) -> None:
    """3. A report bound to another situation cannot close this one."""
    from finance.domain.verification import VerificationReport, VerificationVerdict

    base = _proven_closed().model_copy(update={"status": SituationStatus.VERIFYING})
    foreign = VerificationReport(
        situation_id="FS-2026-0916-00999",
        execution_id="LEGACY-20260916-0042",
        legacy_total_after=Decimal("992500"),
        variance_after=Decimal("0"),
        verdict=VerificationVerdict.VERIFIED,
        checked_at=AT_1,
    )
    bad = base.model_copy(update={
        "status": SituationStatus.CLOSED,
        "verification": foreign,
        "closed_at": AT_1,
        "verified_total": Decimal("992500"),
    })
    with pytest.raises(ValueError, match="another situation"):
        repo.save(bad)
    assert repo.get_for_company("meridian", SID_1) is None


def test_fresh_closed_with_over_tolerance_residual_rejected(
    repo: SituationRepository,
) -> None:
    """4. Residual 101 exceeds tolerance 100: no close."""
    from finance.domain.verification import VerificationReport, VerificationVerdict

    base = _proven_closed().model_copy(update={"status": SituationStatus.VERIFYING})
    loose = VerificationReport(
        situation_id=SID_1,
        execution_id="LEGACY-20260916-0042",
        legacy_total_after=Decimal("992500"),
        variance_after=Decimal("101"),
        verdict=VerificationVerdict.VERIFIED,
        checked_at=AT_1,
    )
    bad = base.model_copy(update={
        "status": SituationStatus.CLOSED,
        "verification": loose,
        "closed_at": AT_1,
        "verified_total": Decimal("992500"),
    })
    with pytest.raises(ValueError, match="tolerance"):
        repo.save(bad)
    assert repo.get_for_company("meridian", SID_1) is None


def test_fresh_closed_without_closed_at_rejected(
    repo: SituationRepository,
) -> None:
    """5. Proof without a close timestamp still cannot persist CLOSED."""
    from finance.domain.verification import VerificationReport, VerificationVerdict

    base = _proven_closed().model_copy(update={"status": SituationStatus.VERIFYING})
    report = VerificationReport(
        situation_id=SID_1,
        execution_id="LEGACY-20260916-0042",
        legacy_total_after=Decimal("992500"),
        variance_after=Decimal("0"),
        verdict=VerificationVerdict.VERIFIED,
        checked_at=AT_1,
    )
    bad = base.model_copy(update={
        "status": SituationStatus.CLOSED,
        "verification": report,
        "closed_at": None,
        "verified_total": Decimal("992500"),
    })
    with pytest.raises(ValueError, match="closed_at"):
        repo.save(bad)
    assert repo.get_for_company("meridian", SID_1) is None


def test_fresh_closed_with_accepted_report_persisted(
    repo: SituationRepository,
) -> None:
    """6. The proven close persists and rehydrates with its proof intact."""
    closed = _proven_closed()
    assert repo.save(closed) == 1
    loaded = repo.get_for_company("meridian", SID_1)
    assert loaded == closed
    assert loaded is not None and loaded.verification is not None
    assert loaded.verification.verdict.value == "VERIFIED"
    assert loaded.verified_total == Decimal("992500")
    assert loaded.closed_at == AT_1


def test_nonterminal_to_closed_without_proof_impossible() -> None:
    """7. The aggregate transition path cannot close without verification."""
    with pytest.raises(ValueError, match="Cannot close"):
        _situation(status=SituationStatus.VERIFYING).transition_to(
            SituationStatus.CLOSED
        )


def test_persisted_closed_rejects_any_save(repo: SituationRepository) -> None:
    """8. A proven CLOSED row still refuses every further save (D5)."""
    repo.save(_proven_closed())
    with pytest.raises(TerminalStateError):
        repo.save(_situation(status=SituationStatus.DETECTED))
    loaded = repo.get_for_company("meridian", SID_1)
    assert loaded is not None and loaded.status is SituationStatus.CLOSED


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
