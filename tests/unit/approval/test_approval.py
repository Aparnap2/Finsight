"""RED scenarios for the P6-06 policy-approval-authorization engine.

Covers the 13 RED scenarios from ``docs/architecture/P6-06_APPROVAL_CONTRACT.md``
section 6 (R1-R13, requirements A21-A33) plus the FS-231 golden walk (A20),
the policy-NO negative path, forged-token refusal, deterministic replay,
freeze delegation to ``require_proposal_frozen``, and the legacy-never-AUTO
rule. All timestamps are caller-supplied fixed values: no wall-clock, no
network, no LLM, no lifecycle transitions, no execution.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from finance.approval import (
    ApprovalDecision,
    ApprovalRefused,
    AuthorizationToken,
    DecisionOutcome,
    ProposalSnapshot,
    RefusalCode,
    approval_id_for,
    assert_pin_frozen,
    assert_single_decision,
    compute_proposal_hash,
    decide,
    idempotency_key_for,
    mint_authorization,
    required_authority,
    role_may_approve,
    verify_authorization,
)
from finance.business_rules.meridian import RefundAuthority
from finance.domain.financial_situation import FinancialSituation

TEST_SEAL = b"p6-06-test-seal-key-231"
"""TEST-ONLY seal key (never production; never logged or persisted)."""

FS231 = "FS-2026-0916-00231"
FS232 = "FS-2026-0916-00232"
ACTION = "REPROCESS_LEGACY_RECORD"
ACCOUNT = "4812"
EVIDENCE = ("ev-ledger-001", "ev-provider-002")
HYPOTHESIS = "hyp-fs231-root-cause"
PROPOSER = "anita"
MANAGER = "meera"
DIRECTOR = "rao"
PROOF = "slack-sig-fs231-ok"
DECIDED_AT = datetime(2026, 9, 16, 10, 0, 0, tzinfo=UTC)
ISSUED_AT = datetime(2026, 9, 16, 11, 0, 0, tzinfo=UTC)
EXPIRES_AT = datetime(2026, 9, 23, 11, 0, 0, tzinfo=UTC)
OPEN_PERIOD = "2026-09"
CLOSED = ("2026-08",)


def _hash_for(
    amount: Decimal = Decimal("10000"),
    version: int = 1,
    evidence: tuple[str, ...] = EVIDENCE,
    account: str = ACCOUNT,
) -> str:
    """Compute the canonical proposal hash for the FS-231 shape."""
    return compute_proposal_hash(
        situation_id=FS231,
        action=ACTION,
        amount=amount,
        account_code=account,
        evidence_refs=evidence,
        hypothesis_ref=HYPOTHESIS,
        proposal_version=version,
    )


def _snapshot(
    amount: Decimal = Decimal("10000"),
    version: int = 1,
    evidence: tuple[str, ...] = EVIDENCE,
    account: str = ACCOUNT,
    is_legacy: bool = True,
    period: str = OPEN_PERIOD,
    proposal_hash: str | None = None,
) -> ProposalSnapshot:
    """Build a consistent FS-231 proposal snapshot (hash matches fields)."""
    return ProposalSnapshot(
        situation_id=FS231,
        company_id="meridian",
        action=ACTION,
        amount=amount,
        account_code=account,
        evidence_refs=evidence,
        hypothesis_ref=HYPOTHESIS,
        proposal_hash=proposal_hash or _hash_for(amount, version, evidence, account),
        proposal_version=version,
        proposer_id=PROPOSER,
        is_legacy=is_legacy,
        period=period,
    )


def _decide(
    snapshot: ProposalSnapshot,
    *,
    approver: str = MANAGER,
    role: str = "manager",
    proof: str | None = PROOF,
    outcome: DecisionOutcome = DecisionOutcome.APPROVE,
    decision_id: str = "dec-fs231-v1",
) -> ApprovalDecision:
    """Run the G1-G6 decision gate on a snapshot with FS-231 bindings."""
    return decide(
        snapshot,
        decision_id=decision_id,
        approver=approver,
        approver_role=role,
        auth_proof=proof,
        outcome=outcome,
        decided_at=DECIDED_AT,
        actor_situation_id=FS231,
        closed_periods=CLOSED,
    )


def _mint(
    decision: ApprovalDecision,
    snapshot: ProposalSnapshot,
    batch: str | None = None,
) -> AuthorizationToken:
    """Mint a G7 token bound to the snapshot execution identity."""
    return mint_authorization(
        decision,
        action=snapshot.action,
        amount_exact=snapshot.amount,
        account_code=snapshot.account_code,
        issued_at=ISSUED_AT,
        expires_at=EXPIRES_AT,
        seal_key=TEST_SEAL,
        scope_batch=batch,
        proposal=snapshot,
    )


def _verify(
    token: AuthorizationToken,
    *,
    situation_id: str = FS231,
    at: datetime = ISSUED_AT,
    amount: Decimal = Decimal("10000"),
    batch: str | None = None,
) -> None:
    """Verify a token against the FS-231 execution identity."""
    verify_authorization(
        token,
        company_id="meridian",
        situation_id=situation_id,
        proposal_hash=token.proposal_hash,
        proposal_version=token.proposal_version,
        action=ACTION,
        amount_exact=amount,
        account_code=ACCOUNT,
        scope_batch=batch,
        at=at,
        seal_key=TEST_SEAL,
    )


def test_fs231_golden_manager_approval_mints_bound_token() -> None:
    """A20: Rs 10,000 legacy correction approves at MANAGER with hash-v1 pin."""
    snapshot = _snapshot()
    decision = _decide(snapshot)
    assert decision.outcome is DecisionOutcome.APPROVE
    assert decision.proposal_hash == _hash_for()
    assert decision.proposal_version == 1
    assert decision.approval_id == approval_id_for("dec-fs231-v1", decision.proposal_hash, 1)

    token = _mint(decision, snapshot)
    assert token.proposal_hash == decision.proposal_hash
    assert token.proposal_version == 1
    assert token.amount_exact == Decimal("10000")
    assert token.account_code == ACCOUNT
    assert token.situation_id == FS231
    assert token.company_id == "meridian"
    assert token.idempotency_key == idempotency_key_for("meridian", token.proposal_hash, 1)
    assert token.idempotency_key == decision.idempotency_key
    assert token.expires_at > token.issued_at
    _verify(token)


def test_r1_self_approval_refused() -> None:
    """A21: the v1 proposer cannot approve their own v1 even as manager."""
    snapshot = _snapshot()
    with pytest.raises(ApprovalRefused) as exc_info:
        _decide(snapshot, approver=PROPOSER, role="manager")
    assert exc_info.value.code is RefusalCode.SELF_APPROVAL_DENIED
    assert exc_info.value.gate == "G2"


def test_r2_tier_escalation_manager_over_band_refused_director_approves() -> None:
    """A22: manager APPROVE on Rs 60,000 refused; a fresh director decides."""
    snapshot = _snapshot(amount=Decimal("60000"), is_legacy=False)
    snapshot = snapshot.model_copy(update={"proposal_hash": _hash_for(Decimal("60000"))})
    with pytest.raises(ApprovalRefused) as exc_info:
        _decide(snapshot, approver=MANAGER, role="manager")
    assert exc_info.value.code is RefusalCode.OVER_TIER_AMOUNT
    assert exc_info.value.gate == "G4"

    fresh = decide(
        snapshot,
        decision_id="dec-fs231-v1-director",
        approver=DIRECTOR,
        approver_role="director",
        auth_proof=PROOF,
        outcome=DecisionOutcome.APPROVE,
        decided_at=DECIDED_AT,
        actor_situation_id=FS231,
        closed_periods=CLOSED,
    )
    assert fresh.outcome is DecisionOutcome.APPROVE
    token = _mint(fresh, snapshot)
    assert token.amount_exact == Decimal("60000")


def test_r3_stale_version_authorization_void() -> None:
    """A23: the v1 authorization presented for v2 is refused; v2 needs fresh G1-G6."""
    snapshot = _snapshot()
    token = _mint(_decide(snapshot), snapshot)
    v2_hash = _hash_for(version=2)
    with pytest.raises(ApprovalRefused) as exc_info:
        verify_authorization(
            token,
            company_id="meridian",
            situation_id=FS231,
            proposal_hash=v2_hash,
            proposal_version=2,
            action=ACTION,
            amount_exact=Decimal("10000"),
            account_code=ACCOUNT,
            scope_batch=None,
            at=ISSUED_AT,
            seal_key=TEST_SEAL,
        )
    assert exc_info.value.code is RefusalCode.PROPOSAL_VERSION_SWAPPED


def test_r4_replayed_decision_returns_same_token() -> None:
    """A24: identical replay mints no second authorization (byte-identical)."""
    snapshot = _snapshot()
    decision = _decide(snapshot)
    first = _mint(decision, snapshot)
    second = _mint(decision, snapshot)
    assert first.authorization_id == second.authorization_id
    assert first.model_dump_json() == second.model_dump_json()
    assert assert_single_decision(decision, decision) == decision


def test_r5_expired_authorization_refused() -> None:
    """A25: token use after expires_at is refused; renewal is a fresh decision."""
    snapshot = _snapshot()
    token = _mint(_decide(snapshot), snapshot)
    with pytest.raises(ApprovalRefused) as exc_info:
        _verify(token, at=EXPIRES_AT + timedelta(seconds=1))
    assert exc_info.value.code is RefusalCode.AUTHORIZATION_EXPIRED
    assert exc_info.value.gate == "G7"


def test_r6_cross_case_reuse_refused() -> None:
    """A26: the FS-231 token presented for FS-232 refuses CROSS_CASE_REFUSED first."""
    snapshot = _snapshot()
    token = _mint(_decide(snapshot), snapshot)
    with pytest.raises(ApprovalRefused) as exc_info:
        _verify(token, situation_id=FS232)
    assert exc_info.value.code is RefusalCode.CROSS_CASE_REFUSED


def test_r7_closed_period_refused_despite_director() -> None:
    """A27: a correction into a closed period is refused; no director waiver."""
    snapshot = _snapshot(period="2026-08")
    with pytest.raises(ApprovalRefused) as exc_info:
        _decide(snapshot, approver=DIRECTOR, role="director")
    assert exc_info.value.code is RefusalCode.CLOSED_PERIOD_BLOCKED
    assert exc_info.value.gate == "G4"


def test_r8_legacy_correction_requires_director_above_band() -> None:
    """A28: Rs 60,000 legacy via manager refused; legacy never AUTO below band."""
    snapshot = _snapshot(amount=Decimal("60000"), is_legacy=True)
    snapshot = snapshot.model_copy(update={"proposal_hash": _hash_for(Decimal("60000"))})
    with pytest.raises(ApprovalRefused) as exc_info:
        _decide(snapshot, approver=MANAGER, role="manager")
    assert exc_info.value.code is RefusalCode.LEGACY_DIRECTOR_REQUIRED

    assert required_authority(Decimal("100"), is_legacy=True) is RefundAuthority.MANAGER
    assert required_authority(Decimal("100"), is_legacy=False) is RefundAuthority.AUTO


def test_r9_auditor_approval_refused() -> None:
    """A29: an auditor APPROVE is refused; auditors stay read-only."""
    with pytest.raises(ApprovalRefused) as exc_info:
        _decide(_snapshot(), approver="audit-adi", role="auditor")
    assert exc_info.value.code is RefusalCode.APPROVE_RIGHT_DENIED
    assert exc_info.value.gate == "G2"


def test_r10_agent_approval_refused() -> None:
    """A30: the service identity can propose candidates but never approve."""
    with pytest.raises(ApprovalRefused) as exc_info:
        _decide(_snapshot(), approver="finsight-agent", role="agent")
    assert exc_info.value.code is RefusalCode.APPROVE_RIGHT_DENIED
    assert exc_info.value.gate == "G2"


def test_r11_amount_tamper_refused_as_unvalidated() -> None:
    """A31: amount drift with a stale hash fails recomputation: UNVALIDATED_PROPOSAL."""
    snapshot = _snapshot()
    tampered = snapshot.model_copy(update={"amount": Decimal("12000")})
    with pytest.raises(ApprovalRefused) as exc_info:
        _decide(tampered)
    assert exc_info.value.code is RefusalCode.UNVALIDATED_PROPOSAL


def test_r11_bound_amount_drift_refused() -> None:
    """A31: amount differing from the P6-05 bound amount: PROPOSAL_DRIFT_REFUSED."""
    snapshot = _snapshot()
    with pytest.raises(ApprovalRefused) as exc_info:
        decide(
            snapshot,
            decision_id="dec-fs231-v1",
            approver=MANAGER,
            approver_role="manager",
            auth_proof=PROOF,
            outcome=DecisionOutcome.APPROVE,
            decided_at=DECIDED_AT,
            actor_situation_id=FS231,
            closed_periods=CLOSED,
            expected_amount=Decimal("12000"),
        )
    assert exc_info.value.code is RefusalCode.PROPOSAL_DRIFT_REFUSED


def test_r12_scope_escape_refused() -> None:
    """A32: a batch authorization presented for another batch is refused."""
    snapshot = _snapshot()
    token = _mint(_decide(snapshot), snapshot, batch="LEGACY-20260916-0042")
    with pytest.raises(ApprovalRefused) as exc_info:
        _verify(token, batch="LEGACY-20260916-0043")
    assert exc_info.value.code is RefusalCode.AUTHORIZATION_SCOPE_ESCAPE


def test_r13_input_hygiene_trio() -> None:
    """A33: no proof -> G1; unknown account -> G4; no evidence -> G5."""
    with pytest.raises(ApprovalRefused) as exc_info:
        _decide(_snapshot(), proof=None)
    assert exc_info.value.code is RefusalCode.UNAUTHENTICATED_ACTOR
    assert exc_info.value.gate == "G1"

    bad_account = _snapshot(account="9999")
    with pytest.raises(ApprovalRefused) as exc_info:
        _decide(bad_account)
    assert exc_info.value.code is RefusalCode.INVALID_ACCOUNT_CODE
    assert exc_info.value.gate == "G4"

    no_evidence = ProposalSnapshot(
        situation_id=FS231,
        company_id="meridian",
        action=ACTION,
        amount=Decimal("10000"),
        account_code=ACCOUNT,
        evidence_refs=(),
        hypothesis_ref=HYPOTHESIS,
        proposal_hash=_hash_for(evidence=()),
        proposal_version=1,
        proposer_id=PROPOSER,
        is_legacy=True,
        period=OPEN_PERIOD,
    )
    with pytest.raises(ApprovalRefused) as exc_info:
        _decide(no_evidence)
    assert exc_info.value.code is RefusalCode.UNVALIDATED_PROPOSAL
    assert exc_info.value.gate == "G5"


def test_forged_token_refused() -> None:
    """A17: a token whose binding digest no longer verifies is forged."""
    snapshot = _snapshot()
    token = _mint(_decide(snapshot), snapshot)
    tampered = token.model_copy(update={"amount_exact": Decimal("12000")})
    with pytest.raises(ApprovalRefused) as exc_info:
        _verify(tampered, amount=Decimal("12000"))
    assert exc_info.value.code is RefusalCode.TOKEN_FORGED


def test_pin_skew_same_version_hash_mismatch_refused() -> None:
    """Same-version presentation against a different pinned hash is refused."""
    snapshot = _snapshot()
    token = _mint(_decide(snapshot), snapshot)
    with pytest.raises(ApprovalRefused) as exc_info:
        verify_authorization(
            token,
            company_id="meridian",
            situation_id=FS231,
            proposal_hash="0" * 64,
            proposal_version=1,
            action=ACTION,
            amount_exact=Decimal("10000"),
            account_code=ACCOUNT,
            scope_batch=None,
            at=ISSUED_AT,
            seal_key=TEST_SEAL,
        )
    assert exc_info.value.code is RefusalCode.PIN_SKEW_HASH


def test_post_approval_mutation_refused_via_freeze() -> None:
    """D2 freeze delegates to require_proposal_frozen: pin swap past approval fails."""
    from finance.domain.financial_situation import SituationStatus

    baseline = FinancialSituation(
        situation_id=FS231,
        expected=Decimal("982500"),
        razorpay_net=Decimal("972500"),
        quickbooks=Decimal("982500"),
        legacy=Decimal("982500"),
        status=SituationStatus.APPROVED,
        proposal_hash=_hash_for(),
        proposal_version=1,
    )
    same = baseline.model_copy(update={})
    assert assert_pin_frozen(same, baseline) is None

    swapped = baseline.model_copy(update={"proposal_hash": "1" * 64})
    with pytest.raises(ApprovalRefused) as exc_info:
        assert_pin_frozen(swapped, baseline)
    assert exc_info.value.code is RefusalCode.PROPOSAL_VERSION_SWAPPED

    bumped = baseline.model_copy(update={"proposal_version": 2})
    with pytest.raises(ApprovalRefused) as exc_info:
        assert_pin_frozen(bumped, baseline)
    assert exc_info.value.code is RefusalCode.PROPOSAL_VERSION_SWAPPED


def test_negative_path_policy_no_mints_no_token() -> None:
    """Policy-NO: a REJECT decision yields a decision object and zero authorization."""
    rejected = _decide(_snapshot(), outcome=DecisionOutcome.REJECT)
    assert rejected.outcome is DecisionOutcome.REJECT
    with pytest.raises(ApprovalRefused) as exc_info:
        mint_authorization(
            rejected,
            action=ACTION,
            amount_exact=Decimal("10000"),
            account_code=ACCOUNT,
            issued_at=ISSUED_AT,
            expires_at=EXPIRES_AT,
            seal_key=TEST_SEAL,
        )
    assert exc_info.value.code is RefusalCode.DECISION_REJECTED
    assert exc_info.value.gate == "G7"


def test_differing_second_decision_refused() -> None:
    """A14/A16: a second differing decision on the same pin is refused."""
    snapshot = _snapshot()
    first = _decide(snapshot, decision_id="dec-first")
    second = _decide(snapshot, decision_id="dec-second", outcome=DecisionOutcome.REJECT)
    with pytest.raises(ApprovalRefused) as exc_info:
        assert_single_decision(first, second)
    assert exc_info.value.code is RefusalCode.DUPLICATE_DECISION


def test_unknown_role_refused() -> None:
    """A role outside the A6 matrix fails closed with its own code."""
    with pytest.raises(ApprovalRefused) as exc_info:
        _decide(_snapshot(), approver="mallory", role="cfo")
    assert exc_info.value.code is RefusalCode.UNKNOWN_DECIDER_ROLE
    assert exc_info.value.gate == "G2"


def test_cross_case_decision_refused() -> None:
    """A8: an actor bound to FS-232 cannot decide the FS-231 proposal."""
    snapshot = _snapshot()
    with pytest.raises(ApprovalRefused) as exc_info:
        decide(
            snapshot,
            decision_id="dec-fs231-v1",
            approver=MANAGER,
            approver_role="manager",
            auth_proof=PROOF,
            outcome=DecisionOutcome.APPROVE,
            decided_at=DECIDED_AT,
            actor_situation_id=FS232,
            closed_periods=CLOSED,
        )
    assert exc_info.value.code is RefusalCode.CROSS_CASE_REFUSED
    assert exc_info.value.gate == "G3"


def test_tier_helpers_follow_meridian_bands() -> None:
    """Tiers delegate to MeridianBusinessRules: 5k/50k bands, director covers all."""
    assert required_authority(Decimal("4999.99"), is_legacy=False) is RefundAuthority.AUTO
    assert required_authority(Decimal("5000"), is_legacy=False) is RefundAuthority.MANAGER
    assert required_authority(Decimal("50000"), is_legacy=False) is RefundAuthority.MANAGER
    assert required_authority(Decimal("50000.01"), is_legacy=False) is RefundAuthority.DIRECTOR
    assert role_may_approve("manager", RefundAuthority.MANAGER) is True
    assert role_may_approve("manager", RefundAuthority.DIRECTOR) is False
    assert role_may_approve("director", RefundAuthority.DIRECTOR) is True
    assert role_may_approve("analyst", RefundAuthority.AUTO) is False


def test_naive_decided_at_rejected_at_shape_boundary() -> None:
    """A14: naive timestamps never become decisions (Pydantic boundary refusal)."""
    snapshot = _snapshot()
    with pytest.raises(ValidationError):
        ApprovalDecision(
            decision_id="dec-naive",
            situation_id=FS231,
            company_id="meridian",
            proposal_hash=snapshot.proposal_hash,
            proposal_version=1,
            proposer_id=PROPOSER,
            approver=MANAGER,
            approver_role="manager",
            outcome=DecisionOutcome.APPROVE,
            decided_at=datetime(2026, 9, 16, 10, 0, 0),
        )


def test_mint_rejects_inverted_expiry_window() -> None:
    """G7 mint requires a forward expiry window (shape guard, no clock read)."""
    snapshot = _snapshot()
    decision = _decide(snapshot)
    with pytest.raises(ValueError, match="expires_at"):
        mint_authorization(
            decision,
            action=ACTION,
            amount_exact=Decimal("10000"),
            account_code=ACCOUNT,
            issued_at=ISSUED_AT,
            expires_at=ISSUED_AT,
            seal_key=TEST_SEAL,
        )


def test_fabricated_token_from_scratch_rejected() -> None:
    """No minted token: recomputing the public digest still fails verify.

    The attacker knows every bound field and the digest algorithm, but
    not the server-held seal key. Authenticity (MAC) rejects what
    integrity (digest) alone cannot distinguish.
    """
    from finance.approval import binding_digest_for

    forged = AuthorizationToken(
        authorization_id="authz_attacker",
        proposal_hash=_hash_for(),
        proposal_version=1,
        company_id="meridian",
        situation_id=FS231,
        action=ACTION,
        amount_exact=Decimal("10000"),
        account_code=ACCOUNT,
        idempotency_key="idem-attacker",
        issued_at=ISSUED_AT,
        expires_at=EXPIRES_AT,
        amount_ceiling=Decimal("10000"),
        scope_batch=None,
        binding_digest=binding_digest_for(
            authorization_id="authz_attacker",
            company_id="meridian",
            situation_id=FS231,
            proposal_hash=_hash_for(),
            proposal_version=1,
            action=ACTION,
            amount_exact=Decimal("10000"),
            account_code=ACCOUNT,
            idempotency_key="idem-attacker",
            issued_at=ISSUED_AT,
            expires_at=EXPIRES_AT,
            scope_batch=None,
        ),
        auth_mac="0" * 64,
    )
    with pytest.raises(ApprovalRefused) as exc_info:
        verify_authorization(
            forged,
            company_id="meridian",
            situation_id=FS231,
            proposal_hash=_hash_for(),
            proposal_version=1,
            action=ACTION,
            amount_exact=Decimal("10000"),
            account_code=ACCOUNT,
            scope_batch=None,
            at=ISSUED_AT,
            seal_key=TEST_SEAL,
        )
    assert exc_info.value.code is RefusalCode.TOKEN_FORGED


def test_wrong_seal_key_rejected() -> None:
    """A token sealed under another key fails with the true seal."""
    token = _mint(_decide(_snapshot()), _snapshot())
    with pytest.raises(ApprovalRefused) as exc_info:
        verify_authorization(
            token,
            company_id="meridian",
            situation_id=FS231,
            proposal_hash=token.proposal_hash,
            proposal_version=token.proposal_version,
            action=ACTION,
            amount_exact=Decimal("10000"),
            account_code=ACCOUNT,
            scope_batch=None,
            at=ISSUED_AT,
            seal_key=b"wrong-seal-key-000",
        )
    assert exc_info.value.code is RefusalCode.TOKEN_FORGED


def test_empty_seal_key_refused() -> None:
    """Minting or verifying without a secret is refused, never silent."""
    decision = _decide(_snapshot())
    with pytest.raises(ValueError, match="seal_key"):
        mint_authorization(
            decision,
            action=ACTION,
            amount_exact=Decimal("10000"),
            account_code=ACCOUNT,
            issued_at=ISSUED_AT,
            expires_at=EXPIRES_AT,
            seal_key=b"",
        )
    token = _mint(decision, _snapshot())
    with pytest.raises(ValueError, match="seal_key"):
        verify_authorization(
            token,
            company_id="meridian",
            situation_id=FS231,
            proposal_hash=token.proposal_hash,
            proposal_version=token.proposal_version,
            action=ACTION,
            amount_exact=Decimal("10000"),
            account_code=ACCOUNT,
            scope_batch=None,
            at=ISSUED_AT,
            seal_key=b"",
        )
