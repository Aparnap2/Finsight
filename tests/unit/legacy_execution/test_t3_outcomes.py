"""T3 outcome tests for P6-07 deterministic execution (RED first, TDD).

Covers ingestion (E6), the execution record (idempotency + R-1-R-8),
the verification handoff (contract section 8), the E1-E6 pipeline, the
FS-231 golden path, and the adversarial scenarios applicable to T3
stages. T1-covered scenarios (forged/expired/wrong-batch/prefix/size)
are asserted as pipeline refusal propagation, never reimplemented.

Sibling seams (T1 reservation/intent, T2 artifact/transport) are absent
on this track, so tests inject minimal local stand-ins through the
pipeline stage protocols plus a FakeS3 result reader. Fixed timestamps
only; no LLM, no network, no wall clock. All money is Decimal.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from finance.approval.refusals import ApprovalRefused
from finance.legacy.protocol import (
    _batch_id_to_compact,
    _compute_checksum,
    build_result_key,
)
from finance.legacy_execution.handoff import build_handoff
from finance.legacy_execution.ingestion import (
    EXEC_CONTROL_TOTAL_MISMATCH,
    EXEC_RESULT_CORRUPT,
    EXEC_RESULT_UNKNOWN,
    RESULT_POLL_WINDOW_SECONDS,
    ArtifactView,
    IngestionOutcome,
    IngestionRefused,
    OutcomeLabel,
    ReceiptView,
    ingest_result,
    outcome_fingerprint,
    reconcile_late_result,
)
from finance.legacy_execution.pipeline import (
    ExecutionContext,
    IntentView,
    PipelineRefused,
    ReservationGrant,
    run_execution,
)
from finance.legacy_execution.record import (
    ExecutionRecordStore,
    RecordCollision,
    RecordTransitionError,
)
from finance.legacy_execution.reservation import ReservationStore

# ---------------------------------------------------------------------------
# Fixed fixtures (no clock, no network)
# ---------------------------------------------------------------------------

T0 = datetime(2026, 9, 16, 10, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 9, 16, 10, 5, 0, tzinfo=UTC)
TLATE = datetime(2026, 9, 16, 11, 0, 0, tzinfo=UTC)

EXECUTION_ID = "idem_fs231_p607"
COMPANY_ID = "meridian"
SITUATION_ID = "FS-2026-0916-00231"
BATCH_ID = "LEGACY-20260916-0043"
FILE_NAME = "CORRECTION_20260916_231.DAT"
OUTBOUND_KEY = f"{COMPANY_ID}/{BATCH_ID}/{FILE_NAME}"
CONTROL = Decimal("10000.00")
BINDING = "bind_fs231_abcdef"
AUTHZ_ID = "authz_fs231_01"
PROPOSAL_HASH = "ph_fs231_99"
PROPOSAL_VERSION = 3
EXPIRES_AT = datetime(2026, 9, 17, 10, 0, 0, tzinfo=UTC)


def make_result_line(batch_id: str, sequence: int, code: str, detail: str) -> str:
    """Build one 80-char RESULT line with a valid checksum (test helper)."""
    compact = _batch_id_to_compact(batch_id)
    body = (
        "01"
        + compact
        + str(sequence).zfill(8)
        + code
        + detail.ljust(50)[:50]
    )
    assert len(body) == 76
    return body + _compute_checksum(body)


def result_file_bytes(lines: list[str]) -> bytes:
    """Serialise RESULT lines with one terminal newline (exact PUT bytes)."""
    return ("\n".join(lines) + "\n").encode("ascii")


class FakeS3:
    """Minimal in-memory result bucket (no network)."""

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        """Seed the bucket with key-to-bytes objects."""
        self.objects: dict[str, bytes] = dict(objects or {})
        self.reads: list[str] = []

    def read_result(self, key: str) -> bytes | None:
        """Return object bytes or None when the RESULT has not landed."""
        self.reads.append(key)
        return self.objects.get(key)


def make_artifact(
    control: Decimal = CONTROL,
    amounts: dict[int, Decimal] | None = None,
    record_count: int = 1,
    payload: bytes = b"OUTBOUND-FS231-BYTES",
) -> ArtifactView:
    """Build the T2 artifact seam shape for one FS-231-style batch."""
    return ArtifactView(
        execution_id=EXECUTION_ID,
        batch_id=BATCH_ID,
        file_name=FILE_NAME,
        record_count=record_count,
        control_total=control,
        file_bytes=payload,
        outbound_sha256=hashlib.sha256(payload).hexdigest(),
        amounts_by_sequence=amounts if amounts is not None else {1: control},
    )


def make_receipt(payload: bytes = b"OUTBOUND-FS231-BYTES") -> ReceiptView:
    """Build the T2 transport receipt seam shape."""
    return ReceiptView(
        execution_id=EXECUTION_ID,
        batch_id=BATCH_ID,
        key=OUTBOUND_KEY,
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_count=len(payload),
        timestamp=T0,
    )


def result_key() -> str:
    """Derive the RESULT key exactly as the contract seam requires."""
    return build_result_key(COMPANY_ID, BATCH_ID, "20260916")


def ingest_ac(store: FakeS3 | None = None) -> IngestionOutcome:
    """Ingest the FS-231 golden single-AC RESULT (shared happy path)."""
    bucket = store or FakeS3(
        {result_key(): result_file_bytes([make_result_line(BATCH_ID, 1, "AC", "POSTED")])}
    )
    return ingest_result(
        bucket,
        make_receipt(),
        artifact=make_artifact(),
        company_id=COMPANY_ID,
        now=T1,
        window_start=T0,
    )


# ---------------------------------------------------------------------------
# Ingestion: verbatim per-record outcomes (X29-X30)
# ---------------------------------------------------------------------------


def test_verbatim_ac_recording() -> None:
    """AC lines are recorded as given with hash, counts, and totals."""
    outcome = ingest_ac()
    assert outcome.outcome == OutcomeLabel.ACCEPTED
    assert outcome.accepted_count == 1
    assert outcome.rejected_count == 0
    assert outcome.duplicate_count == 0
    assert outcome.accepted_total == Decimal("10000.00")
    assert outcome.rejected_total == Decimal("0.00")
    assert outcome.per_record[0].code == "AC"
    assert outcome.per_record[0].detail == "POSTED"
    assert outcome.result_sha256 == hashlib.sha256(
        result_file_bytes([make_result_line(BATCH_ID, 1, "AC", "POSTED")])
    ).hexdigest()
    assert outcome.unknown_flag is False
    assert outcome.code is None


def test_verbatim_rj_invalid_account_code_preserved() -> None:
    """RJ reasons (e.g. INVALID_ACCOUNT_CODE) are preserved verbatim."""
    line = make_result_line(BATCH_ID, 1, "RJ", "INVALID_ACCOUNT_CODE")
    bucket = FakeS3({result_key(): result_file_bytes([line])})
    outcome = ingest_result(
        bucket, make_receipt(), artifact=make_artifact(),
        company_id=COMPANY_ID, now=T1, window_start=T0,
    )
    assert outcome.outcome == OutcomeLabel.REJECTED
    assert outcome.per_record[0].code == "RJ"
    assert outcome.per_record[0].detail == "INVALID_ACCOUNT_CODE"
    assert outcome.rejected_count == 1
    assert outcome.rejected_total == Decimal("10000.00")
    assert outcome.accepted_total == Decimal("0.00")


def test_verbatim_du_recorded_never_double_counts() -> None:
    """Ledger DU lines are verbatim and never double-count amounts (X38)."""
    lines = [
        make_result_line(BATCH_ID, 1, "AC", "POSTED"),
        make_result_line(BATCH_ID, 2, "DU", "ALREADY SEEN 00000001"),
    ]
    bucket = FakeS3({result_key(): result_file_bytes(lines)})
    artifact = make_artifact(
        record_count=2,
        amounts={1: Decimal("6000.00"), 2: Decimal("4000.00")},
    )
    outcome = ingest_result(
        bucket, make_receipt(), artifact=artifact,
        company_id=COMPANY_ID, now=T1, window_start=T0,
    )
    assert outcome.duplicate_count == 1
    assert outcome.per_record[1].code == "DU"
    assert outcome.per_record[1].detail == "ALREADY SEEN 00000001"
    # DU amount excluded from accepted/rejected totals (never double-count).
    assert outcome.accepted_total == Decimal("6000.00")
    assert outcome.rejected_total == Decimal("0.00")
    assert outcome.outcome == OutcomeLabel.ACCEPTED


def test_partial_preserved_never_auto_retried() -> None:
    """Mixed AC/RJ is PARTIAL; re-ingest returns the identical outcome."""
    lines = [
        make_result_line(BATCH_ID, 1, "AC", "POSTED"),
        make_result_line(BATCH_ID, 2, "RJ", "INVALID_ACCOUNT_CODE"),
    ]
    raw = result_file_bytes(lines)
    bucket = FakeS3({result_key(): raw})
    artifact = make_artifact(
        record_count=2,
        amounts={1: Decimal("6000.00"), 2: Decimal("4000.00")},
    )
    first = ingest_result(
        bucket, make_receipt(), artifact=artifact,
        company_id=COMPANY_ID, now=T1, window_start=T0,
    )
    second = ingest_result(
        bucket, make_receipt(), artifact=artifact,
        company_id=COMPANY_ID, now=T1, window_start=T0,
    )
    assert first.outcome == OutcomeLabel.PARTIAL
    assert first.accepted_total == Decimal("6000.00")
    assert first.rejected_total == Decimal("4000.00")
    # Byte-identical replay: no retry, no mutation, same fingerprint.
    assert outcome_fingerprint(first) == outcome_fingerprint(second)


def test_control_mismatch_records_rejected_in_full() -> None:
    """X37: total skew records REJECTED with no partial acceptance (D8)."""
    line = make_result_line(BATCH_ID, 1, "AC", "POSTED")
    bucket = FakeS3({result_key(): result_file_bytes([line])})
    # Amounts attribute 9999.99 against the 10000.00 OUTBOUND control.
    artifact = make_artifact(amounts={1: Decimal("9999.99")})
    outcome = ingest_result(
        bucket, make_receipt(), artifact=artifact,
        company_id=COMPANY_ID, now=T1, window_start=T0,
    )
    assert outcome.outcome == OutcomeLabel.REJECTED
    assert outcome.code == EXEC_CONTROL_TOTAL_MISMATCH
    assert outcome.accepted_count == 0
    assert outcome.accepted_total == Decimal("0.00")
    assert outcome.rejected_total == CONTROL


def test_unknown_on_missing_in_window() -> None:
    """X39: absent RESULT records UNKNOWN with the poll deadline (no clock)."""
    outcome = ingest_result(
        FakeS3({}), make_receipt(), artifact=make_artifact(),
        company_id=COMPANY_ID, now=T1, window_start=T0,
    )
    assert outcome.outcome == OutcomeLabel.UNKNOWN
    assert outcome.unknown_flag is True
    assert outcome.code == EXEC_RESULT_UNKNOWN
    assert outcome.result_sha256 is None
    assert outcome.result_key is None
    assert outcome.poll_deadline == T0 + timedelta(seconds=RESULT_POLL_WINDOW_SECONDS)


def test_late_result_reconciles_preserving_history() -> None:
    """X40: late RESULT supersedes by pointer; UNKNOWN entry never edited."""
    store = ExecutionRecordStore()
    unknown = ingest_result(
        FakeS3({}), make_receipt(), artifact=make_artifact(),
        company_id=COMPANY_ID, now=T1, window_start=T0,
    )
    row, _ = store.claim(
        EXECUTION_ID, binding_digest=BINDING, company_id=COMPANY_ID,
        situation_id=SITUATION_ID, batch_id=BATCH_ID, expires_at=EXPIRES_AT,
    )
    row = store.attach_receipt(row.execution_id, make_receipt())
    row = store.attach_outcome(row.execution_id, unknown)
    before = row.outcome
    assert before is not None and before.outcome == OutcomeLabel.UNKNOWN

    line = make_result_line(BATCH_ID, 1, "AC", "POSTED")
    late = reconcile_late_result(
        FakeS3({result_key(): result_file_bytes([line])}),
        make_receipt(), artifact=make_artifact(), company_id=COMPANY_ID,
        now=TLATE, window_start=T0, prior_unknown=unknown,
    )
    row = store.attach_outcome(row.execution_id, late)
    assert row.outcome is not None and row.outcome.outcome == OutcomeLabel.ACCEPTED
    assert len(row.history) == 1
    assert row.history[0].outcome == OutcomeLabel.UNKNOWN
    # The UNKNOWN entry itself is preserved, never edited.
    assert row.history[0] == before


def test_reconcile_requires_prior_unknown() -> None:
    """Late reconcile without a prior UNKNOWN is a programming error."""
    with pytest.raises(ValueError, match="prior_unknown"):
        reconcile_late_result(
            FakeS3({}), make_receipt(), artifact=make_artifact(),
            company_id=COMPANY_ID, now=TLATE, window_start=T0,
            prior_unknown=ingest_ac(),
        )


# ---------------------------------------------------------------------------
# Ingestion refusals: corrupt results (X36, D6, D13)
# ---------------------------------------------------------------------------


def test_corrupt_checksum_refuses() -> None:
    """D13: a bad line checksum refuses with EXEC_RESULT_CORRUPT."""
    good = make_result_line(BATCH_ID, 1, "AC", "POSTED")
    flipped = "0" if good[76] != "0" else "1"
    bad = good[:76] + flipped + good[77:]
    assert len(bad) == 80
    bucket = FakeS3({result_key(): result_file_bytes([bad])})
    with pytest.raises(IngestionRefused) as exc:
        ingest_result(
            bucket, make_receipt(), artifact=make_artifact(),
            company_id=COMPANY_ID, now=T1, window_start=T0,
        )
    assert exc.value.code == EXEC_RESULT_CORRUPT


def test_short_line_refuses() -> None:
    """D13: non-80-char lines refuse identically; nothing is recorded."""
    bucket = FakeS3({result_key(): b"TOO-SHORT\n"})
    with pytest.raises(IngestionRefused) as exc:
        ingest_result(
            bucket, make_receipt(), artifact=make_artifact(),
            company_id=COMPANY_ID, now=T1, window_start=T0,
        )
    assert exc.value.code == EXEC_RESULT_CORRUPT


def test_missing_sequences_refuse_as_corrupt() -> None:
    """D6: RESULT omitting an OUTBOUND sequence refuses (never partial)."""
    line = make_result_line(BATCH_ID, 2, "AC", "POSTED")
    bucket = FakeS3({result_key(): result_file_bytes([line])})
    artifact = make_artifact(
        record_count=2,
        amounts={1: Decimal("6000.00"), 2: Decimal("4000.00")},
    )
    with pytest.raises(IngestionRefused) as exc:
        ingest_result(
            bucket, make_receipt(), artifact=artifact,
            company_id=COMPANY_ID, now=T1, window_start=T0,
        )
    assert exc.value.code == EXEC_RESULT_CORRUPT


def test_batch_skew_refuses() -> None:
    """X35: RESULT batch mismatch refuses with EXEC_RESULT_CORRUPT."""
    line = make_result_line("LEGACY-20260916-0044", 1, "AC", "POSTED")
    bucket = FakeS3({result_key(): result_file_bytes([line])})
    with pytest.raises(IngestionRefused) as exc:
        ingest_result(
            bucket, make_receipt(), artifact=make_artifact(),
            company_id=COMPANY_ID, now=T1, window_start=T0,
        )
    assert exc.value.code == EXEC_RESULT_CORRUPT


def test_seam_mismatch_refuses() -> None:
    """Artifact/receipt binding skew refuses before any RESULT read."""
    receipt = make_receipt().model_copy(update={"batch_id": "LEGACY-20260916-0099"})
    with pytest.raises(IngestionRefused) as exc:
        ingest_result(
            FakeS3({}), receipt, artifact=make_artifact(),
            company_id=COMPANY_ID, now=T1, window_start=T0,
        )
    assert exc.value.code == EXEC_RESULT_CORRUPT


# ---------------------------------------------------------------------------
# Record store: idempotency + replay matrix R-1-R-8 (X41-X44, A2-A3)
# ---------------------------------------------------------------------------


def claim_row(store: ExecutionRecordStore, **over: Any) -> Any:
    """Claim the FS-231 row with overridable fields."""
    params: dict[str, Any] = {
        "binding_digest": BINDING, "company_id": COMPANY_ID,
        "situation_id": SITUATION_ID, "batch_id": BATCH_ID,
        "expires_at": EXPIRES_AT,
    }
    params.update(over)
    return store.claim(EXECUTION_ID, **params)


def test_r1_pre_put_replay_returns_same_row() -> None:
    """R-1: same claim pre-PUT wins once; loser reads the winner's row."""
    store = ExecutionRecordStore()
    first, created = claim_row(store)
    second, created_again = claim_row(store)
    assert created is True
    assert created_again is False
    assert first == second
    assert store.claimed(EXECUTION_ID) == first


def test_r2_post_put_replay_is_idempotent() -> None:
    """R-2: same receipt twice attaches once; no second PUT is implied."""
    store = ExecutionRecordStore()
    claim_row(store)
    receipt = make_receipt()
    one = store.attach_receipt(EXECUTION_ID, receipt)
    two = store.attach_receipt(EXECUTION_ID, receipt)
    assert one == two
    assert two.receipt_sha256 == receipt.sha256


def test_r3_ledger_du_resolves_to_original() -> None:
    """R-3/A3b: ledger DU returns the original outcome; totals unchanged."""
    store = ExecutionRecordStore()
    claim_row(store)
    store.attach_receipt(EXECUTION_ID, make_receipt())
    original = ingest_ac()
    store.attach_outcome(EXECUTION_ID, original)
    resolved = store.resolve_ledger_duplicate(EXECUTION_ID)
    assert resolved == original
    assert resolved.accepted_total == Decimal("10000.00")


def test_r4_new_batch_attempt_refused() -> None:
    """R-4/X21: a second batch id for one key refuses AUTHORIZATION_REPLAYED."""
    store = ExecutionRecordStore()
    claim_row(store)
    with pytest.raises(ApprovalRefused) as exc:
        store.claim(
            EXECUTION_ID, binding_digest=BINDING, company_id=COMPANY_ID,
            situation_id=SITUATION_ID, batch_id="LEGACY-20260916-0044",
            expires_at=EXPIRES_AT,
        )
    assert exc.value.code.value == "AUTHORIZATION_REPLAYED"
    with pytest.raises(ApprovalRefused) as exc2:
        store.refuse_new_batch(EXECUTION_ID, "LEGACY-20260916-0044")
    assert exc2.value.code.value == "AUTHORIZATION_REPLAYED"


def test_r5_r6_unknown_window_replay_then_late_reconcile() -> None:
    """R-5/R-6: replays during the gap return UNKNOWN until reconciled."""
    store = ExecutionRecordStore()
    claim_row(store)
    unknown = ingest_result(
        FakeS3({}), make_receipt(), artifact=make_artifact(),
        company_id=COMPANY_ID, now=T1, window_start=T0,
    )
    store.attach_outcome(EXECUTION_ID, unknown)
    gap_read = store.replay(EXECUTION_ID)
    assert gap_read is not None and gap_read.outcome == OutcomeLabel.UNKNOWN
    assert gap_read.unknown_flag is True


def test_r7_drifted_binding_refuses_scope_escape() -> None:
    """R-7: drifted amount/code binding refuses AUTHORIZATION_SCOPE_ESCAPE."""
    store = ExecutionRecordStore()
    claim_row(store)
    with pytest.raises(ApprovalRefused) as exc:
        store.replay(EXECUTION_ID, binding_digest="bind_tampered_12000")
    assert exc.value.code.value == "AUTHORIZATION_SCOPE_ESCAPE"


def test_r8_replay_after_expiry_refuses() -> None:
    """R-8: presentation past expires_at refuses AUTHORIZATION_EXPIRED."""
    store = ExecutionRecordStore()
    claim_row(store)
    with pytest.raises(ApprovalRefused) as exc:
        store.replay(EXECUTION_ID, at=EXPIRES_AT + timedelta(seconds=1))
    assert exc.value.code.value == "AUTHORIZATION_EXPIRED"


def test_preexisting_collision_escalates() -> None:
    """A2: same execution id under a different binding escalates loudly."""
    store = ExecutionRecordStore()
    claim_row(store)
    with pytest.raises(RecordCollision):
        claim_row(store, binding_digest="bind_foreign Cannoli")


def test_receipt_byte_skew_escalates_never_reserializes() -> None:
    """A2 recovery probe: differing bytes refuse; no silent rewrite occurs."""
    store = ExecutionRecordStore()
    claim_row(store)
    store.attach_receipt(EXECUTION_ID, make_receipt())
    other = make_receipt(b"DIFFERENT-BYTES").model_copy(
        update={"key": OUTBOUND_KEY, "batch_id": BATCH_ID}
    )
    with pytest.raises(RecordTransitionError):
        store.attach_receipt(EXECUTION_ID, other)
    assert store.claimed(EXECUTION_ID) is not None
    kept = store.claimed(EXECUTION_ID)
    assert kept is not None and kept.receipt_sha256 == make_receipt().sha256


def test_second_outcome_without_unknown_path_refused() -> None:
    """Exactly-once: a second distinct outcome is refused; replay-read wins."""
    store = ExecutionRecordStore()
    claim_row(store)
    first = ingest_ac()
    store.attach_outcome(EXECUTION_ID, first)
    same = store.attach_outcome(EXECUTION_ID, first)
    assert outcome_fingerprint(same.outcome) == outcome_fingerprint(first)
    lines = [
        make_result_line(BATCH_ID, 1, "AC", "POSTED"),
        make_result_line(BATCH_ID, 2, "RJ", "INVALID_ACCOUNT_CODE"),
    ]
    other = ingest_result(
        FakeS3({result_key(): result_file_bytes(lines)}),
        make_receipt(),
        artifact=make_artifact(
            record_count=2,
            amounts={1: Decimal("6000.00"), 2: Decimal("4000.00")},
        ),
        company_id=COMPANY_ID, now=T1, window_start=T0,
    )
    with pytest.raises(RecordTransitionError):
        store.attach_outcome(EXECUTION_ID, other)


def test_replay_is_byte_identical() -> None:
    """X41: any number of presentations returns the same recorded outcome."""
    store = ExecutionRecordStore()
    claim_row(store)
    recorded = ingest_ac()
    store.attach_outcome(EXECUTION_ID, recorded)
    for _ in range(3):
        assert outcome_fingerprint(store.replay(EXECUTION_ID)) == outcome_fingerprint(
            recorded
        )


# ---------------------------------------------------------------------------
# Handoff: section 8 integrity carrier (data, never a verdict)
# ---------------------------------------------------------------------------


def test_handoff_unknown_uses_nulls_not_zeros() -> None:
    """X46: absent RESULT leaves result fields null with unknown_flag true."""
    store = ExecutionRecordStore()
    claim_row(store)
    unknown = ingest_result(
        FakeS3({}), make_receipt(), artifact=make_artifact(),
        company_id=COMPANY_ID, now=T1, window_start=T0,
    )
    row = store.attach_outcome(EXECUTION_ID, unknown)
    assert row.outcome is not None
    handoff = build_handoff(
        record=row, outcome=row.outcome, receipt=make_receipt(),
        artifact=make_artifact(), authorization_id=AUTHZ_ID,
        proposal_hash=PROPOSAL_HASH, proposal_version=PROPOSAL_VERSION,
        recorded_at=T1,
    )
    assert handoff.unknown_flag is True
    assert handoff.outcome == "UNKNOWN"
    assert handoff.result_key is None
    assert handoff.result_sha256 is None
    assert handoff.accepted_total is None
    assert handoff.rejected_total is None


def test_handoff_carries_both_hashes_and_no_verdict() -> None:
    """X47: handoff carries both digests; it asserts no verdict anywhere."""
    outcome = ingest_ac()
    handoff = build_handoff(
        record=claim_row(ExecutionRecordStore())[0], outcome=outcome,
        receipt=make_receipt(), artifact=make_artifact(),
        authorization_id=AUTHZ_ID, proposal_hash=PROPOSAL_HASH,
        proposal_version=PROPOSAL_VERSION, recorded_at=T1,
    )
    assert handoff.outbound_sha256 == make_artifact().outbound_sha256
    assert handoff.result_sha256 == outcome.result_sha256
    assert handoff.unknown_flag is False
    assert handoff.outcome == "ACCEPTED"
    dumped = handoff.model_dump_json()
    assert "VERIFIED" not in dumped and "FAILED" not in dumped


# ---------------------------------------------------------------------------
# Pipeline: E1-E6 order, short-circuit, FS-231 golden (X5, X48-X51)
# ---------------------------------------------------------------------------

def claimed_store() -> ReservationStore:
    """Reservation store with the golden execution pre-claimed (E1 done)."""
    from finance.legacy_execution.reservation import ReservationBinding

    store = ReservationStore()
    store.claim_execution(
        EXECUTION_ID,
        ReservationBinding(
            binding_digest=BINDING, company_id=COMPANY_ID,
            situation_id=SITUATION_ID,
        ),
    )
    return store



def golden_stages(puts: list[str], ran: list[str]) -> dict[str, Any]:
    """T1/T2 stand-ins: deterministic reservation/intent/artifact/transport."""

    def reservation(ctx: ExecutionContext) -> ReservationGrant:
        ran.append("reservation")
        return ReservationGrant(
            execution_id=ctx.execution_id, batch_id=BATCH_ID,
            company_id=ctx.company_id, situation_id=ctx.situation_id,
            authorization_id=ctx.authorization_id,
            proposal_hash=ctx.proposal_hash,
            proposal_version=ctx.proposal_version,
            binding_digest=ctx.binding_digest, expires_at=ctx.expires_at,
            replayed=False,
        )

    def intent(grant: ReservationGrant) -> IntentView:
        ran.append("intent")
        return IntentView(
            execution_id=grant.execution_id, action="REPROCESS_LEGACY_RECORD",
            amount_exact=Decimal("10000.00"), account_code="4812",
            company_id=grant.company_id, situation_id=grant.situation_id,
            batch_id=grant.batch_id,
        )

    def artifact(intent_view: IntentView) -> ArtifactView:
        ran.append("artifact")
        assert intent_view.amount_exact == Decimal("10000.00")
        assert intent_view.account_code == "4812"
        return make_artifact()

    def transport(artifact_view: ArtifactView) -> ReceiptView:
        ran.append("transport")
        puts.append(artifact_view.batch_id)
        return make_receipt(artifact_view.file_bytes)

    return {
        "reservation": reservation, "intent": intent,
        "artifact": artifact, "transport": transport,
        "reservation_store": claimed_store(),
    }


def golden_context() -> ExecutionContext:
    """FS-231 execution context with fixed timestamps."""
    return ExecutionContext(
        execution_id=EXECUTION_ID, company_id=COMPANY_ID,
        situation_id=SITUATION_ID, authorization_id=AUTHZ_ID,
        proposal_hash=PROPOSAL_HASH, proposal_version=PROPOSAL_VERSION,
        binding_digest=BINDING, expires_at=EXPIRES_AT,
        now=T1, window_start=T0,
    )


def test_fs231_golden_end_to_end_accepted() -> None:
    """X49-X51: 10000.00/4812 correction ingests to an ACCEPTED handoff."""
    line = make_result_line(BATCH_ID, 1, "AC", "POSTED")
    bucket = FakeS3({result_key(): result_file_bytes([line])})
    puts: list[str] = []
    ran: list[str] = []
    result = run_execution(
        golden_context(), result_store=bucket, **golden_stages(puts, ran),
    )
    assert result.permitted is True
    assert result.code is None
    assert result.handoff is not None
    assert result.handoff.outcome == "ACCEPTED"
    assert result.handoff.unknown_flag is False
    assert result.handoff.control_total == Decimal("10000.00")
    assert result.handoff.accepted_total == Decimal("10000.00")
    assert result.handoff.rejected_count == 0
    assert result.handoff.result_sha256 == hashlib.sha256(
        result_file_bytes([line])
    ).hexdigest()
    assert result.handoff.batch_id == BATCH_ID
    assert puts == [BATCH_ID]  # exactly one PUT (X41)
    # `ran` tracks the injected T1/T2 stand-ins; the audit proves all 7 steps.
    assert ran == ["reservation", "intent", "artifact", "transport"]
    stages = [entry.stage for entry in result.audit]
    assert stages == ["E1-reservation", "E2-intent", "E3-artifact",
                      "E4-transport", "E5-observation", "E6-ingestion",
                      "E6-record", "handoff"]
    assert all(entry.permitted for entry in result.audit)


def test_pipeline_short_circuits_on_first_refusal() -> None:
    """X5: the first refusing stage stops the chain; later stages never run."""
    ran: list[str] = []
    stages = golden_stages([], ran)

    def refused_artifact(intent_view: IntentView) -> ArtifactView:
        ran.append("artifact")
        raise PipelineRefused("E3-artifact", "EXEC_ARTIFACT_REFUSED", "empty batch")

    stages["artifact"] = refused_artifact
    result = run_execution(golden_context(), result_store=FakeS3({}), **stages)
    assert result.permitted is False
    assert result.code == "EXEC_ARTIFACT_REFUSED"
    assert result.refused_stage == "E3-artifact"
    assert result.handoff is None
    assert "transport" not in ran and "ingestion" not in ran
    assert result.audit[-1].permitted is False
    assert result.audit[-1].code == "EXEC_ARTIFACT_REFUSED"


@pytest.mark.parametrize(
    ("stage_name", "code"),
    [
        ("reservation", "TOKEN_FORGED"),  # D1 forged token (T1 contract)
        ("reservation", "AUTHORIZATION_EXPIRED"),  # D2 expired (T1 contract)
        ("intent", "AUTHORIZATION_SCOPE_ESCAPE"),  # D3 wrong batch (T1 contract)
        ("transport", "EXEC_HASH_MISMATCH"),  # D4 tampered bytes (T2 contract)
        ("transport", "EXEC_PREFIX_ESCAPE"),  # D10 prefix escape (T2 contract)
        ("artifact", "EXEC_ARTIFACT_REFUSED"),  # D11/D12 size/empty (T2 contract)
    ],
)
def test_sibling_refusals_propagate_unmodified(stage_name: str, code: str) -> None:
    """T1/T2-owned D-scenarios propagate through the pipeline verbatim."""
    ran: list[str] = []
    stages = golden_stages([], ran)

    def refusing(*args: Any, **kwargs: Any) -> Any:
        ran.append(stage_name)
        raise PipelineRefused(stage_name, code, f"sibling refused: {code}")

    stages[stage_name] = refusing
    result = run_execution(golden_context(), result_store=FakeS3({}), **stages)
    assert result.permitted is False
    assert result.code == code
    assert result.refused_stage == stage_name


def test_pipeline_maps_ingestion_corrupt_to_refusal() -> None:
    """D13 via pipeline: corrupt RESULT short-circuits at E5-observation."""
    bucket = FakeS3({result_key(): b"NOT-EIGHTY-CHARS\n"})
    puts: list[str] = []
    ran: list[str] = []
    result = run_execution(
        golden_context(), result_store=bucket, **golden_stages(puts, ran),
    )
    assert result.permitted is False
    assert result.code == EXEC_RESULT_CORRUPT
    assert result.refused_stage == "E5-observation"
    assert result.handoff is None
    assert "record" not in ran


def test_pipeline_records_unknown_handoff_when_result_missing() -> None:
    """X39 via pipeline: missing RESULT still emits an UNKNOWN handoff."""
    puts: list[str] = []
    ran: list[str] = []
    result = run_execution(
        golden_context(), result_store=FakeS3({}), **golden_stages(puts, ran),
    )
    assert result.permitted is True
    assert result.handoff is not None
    assert result.handoff.outcome == "UNKNOWN"
    assert result.handoff.unknown_flag is True
    assert result.handoff.result_sha256 is None


def test_pipeline_replay_returns_recorded_outcome_without_second_put() -> None:
    """D9/X42: second presentation replay-reads; exactly one PUT ever."""
    line = make_result_line(BATCH_ID, 1, "AC", "POSTED")
    bucket = FakeS3({result_key(): result_file_bytes([line])})
    record_store = ExecutionRecordStore()
    first_puts: list[str] = []
    first_ran: list[str] = []
    first = run_execution(
        golden_context(), result_store=bucket, record_store=record_store,
        **golden_stages(first_puts, first_ran),
    )
    assert first.permitted is True

    def replay_reservation(ctx: ExecutionContext) -> ReservationGrant:
        existing = record_store.claimed(ctx.execution_id)
        assert existing is not None and existing.outcome is not None
        raise PipelineRefused("E1-reservation", "AUTHORIZATION_REPLAYED",
                              "replay-read expects the recorded outcome")

    second = run_execution(
        golden_context(), result_store=bucket, record_store=record_store,
        **{**golden_stages([], []), "reservation": replay_reservation},
    )
    assert second.permitted is False
    assert second.code == "AUTHORIZATION_REPLAYED"
    assert first_puts == [BATCH_ID]  # still exactly one PUT total
    replayed = record_store.replay(EXECUTION_ID)
    assert replayed is not None
    assert first.handoff is not None
    assert replayed.accepted_total == first.handoff.accepted_total


def test_pipeline_unknown_code_constant() -> None:
    """UNKNOWN refusal vocabulary is stable for P6-08 consumers."""
    assert EXEC_RESULT_UNKNOWN == "EXEC_RESULT_UNKNOWN"
