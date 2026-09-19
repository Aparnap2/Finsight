"""T1 consumption tests: reservation, intent projection, guard adapter (P6-07 E1/E2).

RED-first suite for track T1. Covers X7-X17 plus A2: forged/expired/
wrong-batch tokens refused with exact codes, seal verified through the
compare path with an explicit caller-supplied seal context, replay-read
returns the recorded outcome without work, intent is an exact projection
(no drift, closed vocabulary), the guard adapter maps all six gate
fields, and paise-level drift refuses. Standalone: no sibling T2/T3
modules required.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from finance.approval.authorization import (
    AuthorizationToken,
    mint_authorization,
    verify_authorization,
)
from finance.approval.decision import (
    ApprovalDecision,
    DecisionOutcome,
    ProposalSnapshot,
    compute_proposal_hash,
    decide,
)
from finance.approval.refusals import ApprovalRefused, RefusalCode
from shared.safety.execution_guard import ExecutionGuard

ACTION = "REPROCESS_LEGACY_RECORD"
AMOUNT = Decimal("10000")
ACCOUNT = "4812"
COMPANY = "meridian"
SITUATION = "FS-2026-0916-00231"
BATCH = "LEGACY-20260916-0043"
SEAL = b"test-seal-key-000000000000000001"
WRONG_SEAL = b"wrong-seal-key-0000000000000002"

ISSUED_AT = datetime(2026, 9, 16, 10, 0, tzinfo=UTC)
EXPIRES_AT = ISSUED_AT + timedelta(hours=1)


def _snapshot(
    *,
    amount: Decimal = AMOUNT,
    account: str = ACCOUNT,
    action: str = ACTION,
) -> ProposalSnapshot:
    """Build the FS-231 proposal snapshot bound to the execution identity."""
    evidence = ("ev-fs231-ledger",)
    return ProposalSnapshot(
        situation_id=SITUATION,
        company_id=COMPANY,
        action=action,
        amount=amount,
        account_code=account,
        evidence_refs=evidence,
        hypothesis_ref="hyp-fs231",
        proposal_hash=compute_proposal_hash(
            situation_id=SITUATION,
            action=action,
            amount=amount,
            account_code=account,
            evidence_refs=evidence,
            hypothesis_ref="hyp-fs231",
            proposal_version=1,
        ),
        proposal_version=1,
        proposer_id="analyst-1",
        is_legacy=True,
        period="2026-09",
    )


def _decide(snapshot: ProposalSnapshot) -> ApprovalDecision:
    """Run the G1-G6 decision gate for the FS-231 snapshot."""
    return decide(
        snapshot,
        decision_id="dec-fs231-v1",
        approver="manager-1",
        approver_role="manager",
        auth_proof="proof-manager-1",
        outcome=DecisionOutcome.APPROVE,
        decided_at=ISSUED_AT,
        actor_situation_id=SITUATION,
        closed_periods=(),
    )


def _mint(
    decision: ApprovalDecision,
    snapshot: ProposalSnapshot,
    *,
    action: str | None = None,
    batch: str | None = BATCH,
) -> AuthorizationToken:
    """Mint a G7 token for the decision (proposal cross-check optional)."""
    return mint_authorization(
        decision,
        action=action or snapshot.action,
        amount_exact=snapshot.amount,
        account_code=snapshot.account_code,
        issued_at=ISSUED_AT,
        expires_at=EXPIRES_AT,
        seal_key=SEAL,
        scope_batch=batch,
        proposal=snapshot if action is None else None,
    )


def _verify(
    token: AuthorizationToken,
    *,
    amount: Decimal = AMOUNT,
    batch: str | None = BATCH,
    at: datetime = ISSUED_AT,
    seal_key: bytes = SEAL,
) -> None:
    """Verify a token against the FS-231 presented context (X7 inputs)."""
    verify_authorization(
        token,
        company_id=COMPANY,
        situation_id=SITUATION,
        proposal_hash=token.proposal_hash,
        proposal_version=token.proposal_version,
        action=ACTION,
        amount_exact=amount,
        account_code=ACCOUNT,
        scope_batch=batch,
        at=at,
        seal_key=seal_key,
    )


def test_forged_token_refused_with_token_forged() -> None:
    """X52/D1: edited token bytes (10000 -> 12000) refuse with TOKEN_FORGED."""
    token = _mint(_decide(_snapshot()), _snapshot())
    forged = token.model_copy(update={"amount_exact": Decimal("12000")})
    with pytest.raises(ApprovalRefused) as exc_info:
        _verify(forged, amount=Decimal("12000"))
    assert exc_info.value.code is RefusalCode.TOKEN_FORGED


def test_wrong_seal_key_refused_via_compare_path() -> None:
    """X8: seal recomputed with a caller-supplied wrong key never passes."""
    token = _mint(_decide(_snapshot()), _snapshot())
    with pytest.raises(ApprovalRefused) as exc_info:
        _verify(token, seal_key=WRONG_SEAL)
    assert exc_info.value.code is RefusalCode.TOKEN_FORGED


def test_expired_token_refused_with_authorization_expired() -> None:
    """X53/D2: use past expires_at refuses; renewal is a fresh decision."""
    token = _mint(_decide(_snapshot()), _snapshot())
    with pytest.raises(ApprovalRefused) as exc_info:
        _verify(token, at=EXPIRES_AT + timedelta(seconds=1))
    assert exc_info.value.code is RefusalCode.AUTHORIZATION_EXPIRED


def test_wrong_batch_token_reuse_refused_with_scope_escape() -> None:
    """X54/D3: scope_batch B43 token presented for B44 refuses at E1."""
    token = _mint(_decide(_snapshot()), _snapshot())
    with pytest.raises(ApprovalRefused) as exc_info:
        _verify(token, batch="LEGACY-20260916-0044")
    assert exc_info.value.code is RefusalCode.AUTHORIZATION_SCOPE_ESCAPE


def test_replay_returns_recorded_outcome_without_work() -> None:
    """X12/X42/A2: loser of the claim race reads the outcome, runs nothing."""
    from finance.legacy_execution.reservation import ReservationStore

    token = _mint(_decide(_snapshot()), _snapshot())
    store = ReservationStore()
    binding = {
        "binding_digest": token.binding_digest,
        "company_id": token.company_id,
        "situation_id": token.situation_id,
    }
    first = store.claim_execution(token.idempotency_key, binding)
    assert first.status == "CLAIMED"
    assert first.outcome is None

    store.record_outcome(token.idempotency_key, "ACCEPTED")
    second = store.claim_execution(token.idempotency_key, binding)
    assert second.status == "REPLAY"
    assert second.outcome == "ACCEPTED"


def test_crash_resume_receipt_lookup() -> None:
    """A2: RESERVED row is queryable by execution_id; unknown ids miss."""
    from finance.legacy_execution.reservation import ReservationStore

    token = _mint(_decide(_snapshot()), _snapshot())
    store = ReservationStore()
    assert store.receipt_status("idem-missing") is None
    store.claim_execution(
        token.idempotency_key,
        {
            "binding_digest": token.binding_digest,
            "company_id": token.company_id,
            "situation_id": token.situation_id,
        },
    )
    row = store.receipt_status(token.idempotency_key)
    assert row is not None
    assert row.state == "RESERVED"
    assert row.execution_id == token.idempotency_key


def test_intent_projection_exactness() -> None:
    """X14: intent copies token fields verbatim; execution_id == key."""
    from finance.legacy_execution.intent import derive_intent

    token = _mint(_decide(_snapshot()), _snapshot())
    intent = derive_intent(token)
    assert intent.action == token.action
    assert intent.amount_exact == token.amount_exact
    assert intent.account_code == token.account_code
    assert intent.company_id == token.company_id
    assert intent.situation_id == token.situation_id
    assert intent.scope_batch == token.scope_batch
    assert intent.idempotency_key == token.idempotency_key
    assert intent.execution_id == token.idempotency_key
    assert intent.proposal_hash == token.proposal_hash
    assert intent.proposal_version == token.proposal_version


def test_intent_closed_vocabulary_violation_refuses() -> None:
    """X15: a non-allowlisted action refuses with scope escape."""
    from finance.legacy_execution.intent import derive_intent

    snapshot = _snapshot(action="REFUND_CUSTOMER")
    token = _mint(_decide(snapshot), snapshot, action="REFUND_CUSTOMER")
    with pytest.raises(ApprovalRefused) as exc_info:
        derive_intent(token)
    assert exc_info.value.code is RefusalCode.AUTHORIZATION_SCOPE_ESCAPE


def test_intent_paise_drift_refuses() -> None:
    """X15: one paise of drift between token and presented amount refuses."""
    from finance.legacy_execution.intent import derive_intent

    token = _mint(_decide(_snapshot()), _snapshot())
    derive_intent(token, presented_amount=AMOUNT)
    with pytest.raises(ApprovalRefused) as exc_info:
        derive_intent(token, presented_amount=Decimal("10000.01"))
    assert exc_info.value.code is RefusalCode.AUTHORIZATION_SCOPE_ESCAPE


def test_intent_scope_batch_override_mismatch_refuses() -> None:
    """X17: an override batch differing from the token pin refuses."""
    from finance.legacy_execution.intent import derive_intent

    token = _mint(_decide(_snapshot()), _snapshot())
    derive_intent(token, scope_batch_override=BATCH)
    with pytest.raises(ApprovalRefused) as exc_info:
        derive_intent(token, scope_batch_override="LEGACY-20260916-0044")
    assert exc_info.value.code is RefusalCode.AUTHORIZATION_SCOPE_ESCAPE


def test_guard_adapter_maps_all_six_gates() -> None:
    """E1-guard seam: produced command passes ExecutionGuard.check clean."""
    from finance.legacy_execution.guard_adapter import run_guards, token_to_command

    token = _mint(_decide(_snapshot()), _snapshot())
    command = token_to_command(token)
    assert command.exception_id == token.situation_id
    assert command.idempotency_key == token.idempotency_key
    assert command.amount == token.amount_exact
    assert command.decision == "APPROVED"
    decision = run_guards(command)
    assert decision.allowed is True
    assert decision.unsafe == 0
    assert ExecutionGuard().check(command).allowed is True


def test_guard_adapter_from_intent_maps_all_six_gates() -> None:
    """Intent-sourced command carries the same six pinned gate fields."""
    from finance.legacy_execution.guard_adapter import intent_to_command, run_guards
    from finance.legacy_execution.intent import derive_intent

    token = _mint(_decide(_snapshot()), _snapshot())
    intent = derive_intent(token)
    command = intent_to_command(intent, authorization_id=token.authorization_id)
    assert command.exception_id == intent.situation_id
    assert command.idempotency_key == intent.idempotency_key
    assert command.amount == intent.amount_exact
    decision = run_guards(command)
    assert decision.allowed is True
    assert decision.unsafe == 0
