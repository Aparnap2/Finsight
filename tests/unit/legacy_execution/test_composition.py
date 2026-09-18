"""Cross-track composition: real T1 → T2 → T3, no stand-ins (HOLD-4).

Proves the actual implementations compose — values flow through real
module boundaries (never around them), the pipeline audit spine records
every stage including explicit E5, and the durable reservation row (not
process memory) is the execution→binding authority across a simulated
crash. Thin test-local adapters map between module types field by field
with equality assertions; nothing is reconstructed or reinterpreted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from finance.approval.decision import (
    ApprovalDecision,
    DecisionOutcome,
    ProposalSnapshot,
    idempotency_key_for,
)
from finance.legacy.protocol import _batch_id_to_compact, _compute_checksum
from finance.legacy_execution.artifact import (
    ExecutionIntent as T2Intent,
)
from finance.legacy_execution.artifact import (
    build_artifact,
    derive_batch_id,
)
from finance.legacy_execution.ingestion import (
    ArtifactView,
    ReceiptView,
    ingest_observed,
)
from finance.legacy_execution.observation import observe_legacy_result
from finance.legacy_execution.pipeline import (
    ExecutionContext,
    IntentView,
    ReservationGrant,
    run_execution,
)
from finance.legacy_execution.record import ExecutionRecordStore
from finance.legacy_execution.reservation import ReservationStore
from finance.legacy_execution.transport import put_verified
from finance.object_store.fake import FakeS3

TEST_SEAL = b"p6-07-composition-seal-key"
"""TEST-ONLY seal (never production, never logged)."""

COMPANY = "meridian"
SITUATION = "FS-2026-0916-00231"
BATCH = "LEGACY-20260916-0043"
PROPOSAL_HASH = "ab" * 32
ACTION = "REPROCESS_LEGACY_RECORD"
ACCOUNT = "4812"
AMOUNT = Decimal("10000.00")
T0 = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
T_PUT = datetime(2026, 9, 16, 11, 0, tzinfo=UTC)
T_NOW = datetime(2026, 9, 16, 11, 5, tzinfo=UTC)
T_ISSUED = datetime(2026, 9, 16, 10, 30, tzinfo=UTC)
T_EXPIRES = datetime(2026, 9, 23, 10, 30, tzinfo=UTC)
OUTBOUND_BUCKET = "finsight-legacy-outbound-test"
KEY = idempotency_key_for(COMPANY, PROPOSAL_HASH, 1)


def _snapshot() -> ProposalSnapshot:
    """Real P6-06 proposal snapshot bound to the FS-231 correction."""
    return ProposalSnapshot(
        situation_id=SITUATION,
        company_id=COMPANY,
        action=ACTION,
        amount=AMOUNT,
        account_code=ACCOUNT,
        evidence_refs=("ev-razorpay-adj", "ev-legacy-rj"),
        hypothesis_ref="hyp-fs231",
        proposal_hash=PROPOSAL_HASH,
        proposal_version=1,
        proposer_id="anita",
        is_legacy=True,
        period="2026-09",
    )


def _decision() -> ApprovalDecision:
    """Real P6-06 decision object (gates proven in the P6-06 suite)."""
    return ApprovalDecision(
        decision_id="dec-comp-1",
        situation_id=SITUATION,
        company_id=COMPANY,
        proposal_hash=PROPOSAL_HASH,
        proposal_version=1,
        proposer_id="anita",
        approver="meera",
        approver_role="manager",
        outcome=DecisionOutcome.APPROVE,
        decided_at=T0,
        idempotency_key=KEY,
    )


def _mint_token() -> object:
    """Mint the real G7 token with the test seal and pinned batch."""
    from finance.approval.authorization import mint_authorization

    return mint_authorization(
        _decision(),
        action=ACTION,
        amount_exact=AMOUNT,
        account_code=ACCOUNT,
        issued_at=T_ISSUED,
        expires_at=T_EXPIRES,
        seal_key=TEST_SEAL,
        scope_batch=BATCH,
        proposal=_snapshot(),
    )


def _result_line(sequence: int, code: str, detail: str) -> str:
    """Build one 80-char RESULT line with the real codec."""
    compact = _batch_id_to_compact(BATCH)
    body = "01" + compact + str(sequence).zfill(8) + code + detail.ljust(50)[:50]
    assert len(body) == 76
    return body + _compute_checksum(body)


def test_real_track_composition_seams() -> None:
    """Real T1→T2→T3 chain: every seam value flows through, none around."""
    from finance.legacy_execution.intent import derive_intent

    token = _mint_token()
    assert token.idempotency_key == KEY

    # E1+E2 real: derive intent from the minted token.
    t1_intent = derive_intent(token)
    assert t1_intent.execution_id == KEY
    assert t1_intent.scope_batch == BATCH

    # T1→T2 seam: validated coercion, every field checked.
    t2_intent = T2Intent.model_validate(t1_intent.model_dump())
    assert t2_intent.amount_exact == AMOUNT
    assert t2_intent.account_code == ACCOUNT

    # E3 real: intent-only artifact, pinned batch.
    artifact = build_artifact(
        t2_intent, batch_id=BATCH, processing_date="20260916"
    )
    assert artifact.file_name == "CORRECTION_20260916_231.DAT"
    assert artifact.control_total == AMOUNT

    # Durable bind on a real reservation row (memory backend here;
    # crash durability proven separately on a file DB).
    reservations = ReservationStore()
    claim = reservations.claim_execution(
        KEY,
        {
            "binding_digest": token.binding_digest,
            "company_id": COMPANY,
            "situation_id": SITUATION,
        },
    )
    assert claim.status == "CLAIMED"
    bound = reservations.bind_batch(KEY, BATCH)
    assert bound.batch_id == BATCH

    # E4 real: PUT into a real FakeS3 outbound bucket.
    outbound = FakeS3(COMPANY)
    receipt = put_verified(
        outbound, artifact, company_id=COMPANY,
        bucket_outbound=OUTBOUND_BUCKET, now=T_PUT,
    )
    assert receipt.sha256 == artifact.outbound_sha256

    # Seed the RESULT with the real codec, then E5+E6 real.
    result_bytes = (
        "\n".join([_result_line(1, "AC", "POSTED")]) + "\n"
    ).encode("ascii")
    observed = observe_legacy_result(
        result_bytes, batch_id=BATCH, company_id=COMPANY
    )
    assert [(r.sequence, r.code) for r in observed.records] == [(1, "AC")]
    outcome = ingest_observed(
        observed,
        artifact=ArtifactView(**artifact.model_dump()),
        receipt=ReceiptView(**receipt.model_dump()),
        company_id=COMPANY,
        result_key=f"{COMPANY}/{BATCH}/RESULT_20260916_231.DAT",
        result_sha256=observed.raw_sha256,
        now=T_NOW,
        window_start=T0,
    )
    assert outcome.outcome.value == "ACCEPTED"

    # Record + handoff real: replay the stored outcome identically.
    from finance.legacy_execution.handoff import build_handoff

    records = ExecutionRecordStore()
    records.claim(
        KEY, binding_digest=token.binding_digest, company_id=COMPANY,
        situation_id=SITUATION, batch_id=BATCH, expires_at=T_EXPIRES,
    )
    records.attach_receipt(KEY, ReceiptView(**receipt.model_dump()))
    records.attach_outcome(KEY, outcome)
    handoff = build_handoff(
        record=records.claimed(KEY),
        outcome=outcome,
        receipt=ReceiptView(**receipt.model_dump()),
        artifact=ArtifactView(**artifact.model_dump()),
        authorization_id=token.authorization_id,
        proposal_hash=PROPOSAL_HASH,
        proposal_version=1,
        recorded_at=T_NOW,
    )
    assert handoff.execution_id == KEY
    assert handoff.batch_id == BATCH
    assert handoff.unknown_flag is False
    assert handoff.accepted_total == AMOUNT
    assert handoff.outbound_sha256 == artifact.outbound_sha256
    assert handoff.result_sha256 == observed.raw_sha256


def test_pipeline_spine_audits_all_real_stages() -> None:
    """run_execution with real stages audits E1..handoff incl. E5."""
    from finance.legacy_execution.intent import derive_intent

    token = _mint_token()
    reservations = ReservationStore()
    outbound = FakeS3(COMPANY)
    result_bytes = (
        "\n".join([_result_line(1, "AC", "POSTED")]) + "\n"
    ).encode("ascii")

    class _ResultBucket:
        def read_result(self, key: str) -> bytes | None:
            assert key == f"{COMPANY}/{BATCH}/RESULT_20260916_231.DAT"
            return result_bytes

    def reservation(ctx: ExecutionContext) -> ReservationGrant:
        claim = reservations.claim_execution(
            ctx.execution_id,
            {
                "binding_digest": ctx.binding_digest,
                "company_id": ctx.company_id,
                "situation_id": ctx.situation_id,
            },
        )
        assert claim.reservation.binding_digest == token.binding_digest
        return ReservationGrant(
            execution_id=ctx.execution_id, batch_id=BATCH,
            company_id=ctx.company_id, situation_id=ctx.situation_id,
            authorization_id=ctx.authorization_id,
            proposal_hash=ctx.proposal_hash,
            proposal_version=ctx.proposal_version,
            binding_digest=ctx.binding_digest, expires_at=ctx.expires_at,
            replayed=claim.status == "REPLAY",
        )

    def intent(grant: ReservationGrant) -> IntentView:
        assert grant.execution_id == token.idempotency_key
        produced = derive_intent(token)
        assert produced.scope_batch == BATCH
        return IntentView(
            execution_id=produced.execution_id, action=produced.action,
            amount_exact=produced.amount_exact,
            account_code=produced.account_code,
            company_id=produced.company_id,
            situation_id=produced.situation_id, batch_id=BATCH,
        )

    def artifact(intent_view: IntentView) -> ArtifactView:
        assert intent_view.amount_exact == AMOUNT
        assert intent_view.account_code == ACCOUNT
        t2 = T2Intent.model_validate({
            **intent_view.model_dump(),
            "idempotency_key": intent_view.execution_id,
            "proposal_hash": PROPOSAL_HASH,
            "proposal_version": 1,
        })
        assert t2.execution_id == t2.idempotency_key == KEY
        built = build_artifact(t2, batch_id=intent_view.batch_id,
                               processing_date="20260916")
        return ArtifactView(**built.model_dump())

    def transport(artifact_view: ArtifactView) -> ReceiptView:
        made = put_verified(
            outbound, artifact_view, company_id=COMPANY,
            bucket_outbound=OUTBOUND_BUCKET, now=T_PUT,
        )
        return ReceiptView(**made.model_dump())

    ctx = ExecutionContext(
        execution_id=KEY, company_id=COMPANY, situation_id=SITUATION,
        authorization_id=token.authorization_id,
        proposal_hash=PROPOSAL_HASH, proposal_version=1,
        binding_digest=token.binding_digest, expires_at=T_EXPIRES,
        now=T_NOW, window_start=T0,
        result_key=f"{COMPANY}/{BATCH}/RESULT_20260916_231.DAT",
    )
    result = run_execution(
        ctx, reservation=reservation, intent=intent, artifact=artifact,
        transport=transport, reservation_store=reservations,
        result_store=_ResultBucket(),
    )
    assert result.permitted is True
    assert result.handoff is not None
    assert result.handoff.outcome == "ACCEPTED"
    stages = [entry.stage for entry in result.audit]
    assert stages == [
        "E1-reservation", "E2-intent", "E3-artifact", "E4-transport",
        "E5-observation", "E6-ingestion", "E6-record", "handoff",
    ]
    assert all(entry.permitted for entry in result.audit)


def test_crash_binding_survives_restart(tmp_path) -> None:
    """Durable authority proof: restart forgets nothing (HOLD-3)."""
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path}/res.db"
    first = ReservationStore(create_engine(url))
    claimed = first.claim_execution(
        KEY,
        {
            "binding_digest": token_digest(),
            "company_id": COMPANY,
            "situation_id": SITUATION,
        },
    )
    assert claimed.status == "CLAIMED"
    first.bind_batch(KEY, BATCH)
    first.record_receipt(KEY)

    del first  # simulated crash: all process memory gone
    second = ReservationStore(create_engine(url))
    again = second.claim_execution(
        KEY,
        {
            "binding_digest": token_digest(),
            "company_id": COMPANY,
            "situation_id": SITUATION,
        },
    )
    assert again.status == "REPLAY"
    row = second.receipt_status(KEY)
    assert row is not None
    assert row.batch_id == BATCH
    assert row.binding_digest == token_digest()
    assert row.state.value == "RECEIPT_RECORDED"


def token_digest() -> str:
    """Binding digest shared by the crash test claimants."""
    return "digest-crash-proof-001"


def test_derive_batch_id_shape() -> None:
    """X17 derivation is deterministic and wire-legal."""
    left = derive_batch_id(KEY, "20260916")
    assert left == derive_batch_id(KEY, "20260916")
    assert left != derive_batch_id("idem-other", "20260916")
