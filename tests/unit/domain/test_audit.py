"""Unit tests for the P6-02 audit contract (finance/domain/audit.py).

Covers event determinism, tz-aware enforcement, append-only guarantees,
and the optional hash-chain against the P6-01 base aggregate only. Zero
network, no LLM, deterministic datetimes throughout.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance.domain.audit import AuditEvent, AuditLog, emit_for_transition
from finance.domain.financial_situation import FinancialSituation, SituationStatus

SITUATION_ID = "FS-2026-0916-00231"
"""Golden FinancialSituation id from the process-model worked example."""

BASE_AT = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
"""Deterministic tz-aware anchor for emitted events."""


def _fs231(status: SituationStatus) -> FinancialSituation:
    """Build the golden FS-231 aggregate (variance exactly 10000)."""
    return FinancialSituation(
        situation_id=SITUATION_ID,
        company_id="meridian",
        expected=Decimal("1000000"),
        razorpay_net=Decimal("972500"),
        quickbooks=Decimal("982500"),
        legacy=Decimal("982500"),
        status=status,
    )


def _at(minutes: int = 0) -> datetime:
    """Return a tz-aware instant offset from the anchor."""
    return BASE_AT + timedelta(minutes=minutes)


def _other_situation(status: SituationStatus) -> FinancialSituation:
    """Build a second case (FS-...-00232) to test per-situation filtering."""
    return FinancialSituation(
        situation_id="FS-2026-0916-00232",
        company_id="meridian",
        expected=Decimal("500000"),
        razorpay_net=Decimal("495000"),
        quickbooks=Decimal("495000"),
        legacy=Decimal("495000"),
        status=status,
    )


def _emit(
    before: SituationStatus = SituationStatus.DETECTED,
    after: SituationStatus = SituationStatus.TRIAGED,
    at: datetime | None = None,
    actor: str = "finsight-test-harness",
) -> AuditEvent:
    """Emit one audit event for a single-step transition."""
    return emit_for_transition(
        _fs231(before), _fs231(after), at=at or BASE_AT, actor=actor
    )


def test_emit_is_deterministic_same_inputs_same_event_id() -> None:
    """Identical inputs always yield the identical event id."""
    first = _emit()
    second = _emit()
    assert first.event_id == second.event_id
    assert first == second


def test_event_id_matches_sha256_preimage() -> None:
    """The id is the hex sha256 of situation_id + from + to + at."""
    at = _at()
    event = _emit(at=at)
    preimage = "|".join(
        (SITUATION_ID, "DETECTED", "TRIAGED", at.isoformat())
    )
    assert event.event_id == hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def test_event_id_changes_when_at_changes() -> None:
    """A different instant is a different record: ids must differ."""
    assert _emit(at=_at(0)).event_id != _emit(at=_at(1)).event_id


def test_event_id_changes_when_endpoints_change() -> None:
    """Different from/to pairs hash differently for the same instant."""
    first = _emit(SituationStatus.DETECTED, SituationStatus.TRIAGED)
    second = _emit(SituationStatus.TRIAGED, SituationStatus.INVESTIGATING)
    assert first.event_id != second.event_id


def test_tz_naive_at_rejected() -> None:
    """Naive timestamps are rejected both via emit and direct construction."""
    naive = datetime(2026, 9, 16, 10, 0)
    with pytest.raises(ValidationError, match="tz-aware"):
        _emit(at=naive)
    with pytest.raises(ValidationError, match="tz-aware"):
        AuditEvent(
            event_id="abc123",
            situation_id=SITUATION_ID,
            company_id="meridian",
            from_status=SituationStatus.DETECTED,
            to_status=SituationStatus.TRIAGED,
            at=naive,
            actor="finsight-test-harness",
        )


def test_blank_actor_rejected() -> None:
    """Empty or whitespace-only actors are rejected."""
    with pytest.raises(ValueError, match="actor"):
        _emit(actor="")
    with pytest.raises(ValueError, match="actor"):
        _emit(actor="   ")


def test_variance_snapshot_records_post_transition_variance() -> None:
    """The event pins the after-snapshot variance (10000 for FS-231)."""
    event = _emit()
    assert event.variance_snapshot == Decimal("10000")
    assert isinstance(event.variance_snapshot, Decimal)


def test_emit_is_pure_and_leaves_inputs_untouched() -> None:
    """Emitting records nothing and never mutates the snapshots."""
    before = _fs231(SituationStatus.DETECTED)
    after = _fs231(SituationStatus.TRIAGED)
    before_dump = before.model_dump()
    after_dump = after.model_dump()
    event = emit_for_transition(before, after, at=BASE_AT, actor="harness")
    assert before.model_dump() == before_dump
    assert after.model_dump() == after_dump
    assert event.from_status is SituationStatus.DETECTED
    assert event.to_status is SituationStatus.TRIAGED
    assert event.at == BASE_AT


def test_log_append_only_ordered_readback() -> None:
    """Appends read back in order as an immutable tuple."""
    log = AuditLog()
    first = log.append(_emit(at=_at(0)))
    second = log.append(
        _emit(SituationStatus.TRIAGED, SituationStatus.INVESTIGATING, at=_at(1))
    )
    assert len(log) == 2
    assert log.all_events() == (first, second)
    assert isinstance(log.all_events(), tuple)
    assert [e.to_status for e in log] == [
        SituationStatus.TRIAGED,
        SituationStatus.INVESTIGATING,
    ]


def test_log_has_no_delete_or_mutate_api() -> None:
    """Append-only means no delete/remove/clear/pop/setitem exists."""
    log = AuditLog()
    log.append(_emit())
    for name in ("delete", "remove", "clear", "pop", "purge", "__delitem__"):
        assert not hasattr(log, name), f"AuditLog must not expose {name}"
    assert len(log) == 1


def test_log_events_are_frozen_and_readback_immutable() -> None:
    """Recorded events cannot be rewritten in place."""
    log = AuditLog()
    stored = log.append(_emit())
    with pytest.raises(ValidationError):
        stored.actor = "mallory"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        log.all_events().append(_emit())  # type: ignore[attr-defined]
    assert log.all_events()[0].actor == "finsight-test-harness"


def test_log_rejects_non_events() -> None:
    """Only AuditEvent instances may be appended."""
    log = AuditLog()
    with pytest.raises(TypeError, match="AuditEvent"):
        log.append("not-an-event")  # type: ignore[arg-type]
    assert len(log) == 0


def test_events_for_filters_per_situation() -> None:
    """Per-situation read-back isolates one case from the shared log."""
    log = AuditLog()
    log.append(_emit())
    log.append(
        emit_for_transition(
            _other_situation(SituationStatus.DETECTED),
            _other_situation(SituationStatus.TRIAGED),
            at=_at(1),
            actor="finsight-test-harness",
        )
    )
    assert len(log.events_for(SITUATION_ID)) == 1
    assert len(log.events_for("FS-2026-0916-00232")) == 1
    assert len(log) == 2


def test_chain_verifies_for_linked_appends() -> None:
    """Default appends auto-link prev_hash, so the chain verifies."""
    log = AuditLog()
    log.append(_emit(at=_at(0)))
    log.append(
        _emit(SituationStatus.TRIAGED, SituationStatus.INVESTIGATING, at=_at(1))
    )
    log.append(
        _emit(SituationStatus.INVESTIGATING, SituationStatus.CORRELATED, at=_at(2))
    )
    events = log.all_events()
    assert events[0].prev_hash == ""
    assert events[1].prev_hash == events[0].event_id
    assert events[2].prev_hash == events[1].event_id
    assert log.verify_chain() is True


def test_broken_chain_detected() -> None:
    """A forged prev_hash breaks verification."""
    log = AuditLog()
    log.append(_emit(at=_at(0)))
    forged = AuditEvent(
        event_id=_emit(
            SituationStatus.TRIAGED, SituationStatus.INVESTIGATING, at=_at(1)
        ).event_id,
        situation_id=SITUATION_ID,
        company_id="meridian",
        from_status=SituationStatus.TRIAGED,
        to_status=SituationStatus.INVESTIGATING,
        at=_at(1),
        actor="finsight-test-harness",
        variance_snapshot=Decimal("10000"),
        prev_hash="0" * 64,
    )
    log.append(forged)
    assert log.verify_chain() is False


def test_empty_and_single_event_chains_verify_vacuously() -> None:
    """Zero or one record has no link to break."""
    assert AuditLog().verify_chain() is True
    solo = AuditLog()
    solo.append(_emit())
    assert solo.verify_chain() is True
