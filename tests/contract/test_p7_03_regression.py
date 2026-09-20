"""P7-03 regression: P7-01 and P7-02 contracts must remain green."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from agents.authority.claims import AuthorityBoundary
from agents.authority.evidence import AuthorityError, EvidenceRecord, EvidenceRegistry
from agents.runtime import RuntimeFactory

NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
DIGEST_A = "a" * 64


def _registry() -> EvidenceRegistry:
    rec = EvidenceRecord(
        source_id="src-ledger-001",
        evidence_id="ev-ledger-001",
        captured_at=NOW - timedelta(seconds=60),
        digest=DIGEST_A,
        provenance="p6_evidence_store",
        ttl_seconds=3600,
    )
    return EvidenceRegistry({"ev-ledger-001": rec})


class TestP701Regression:
    """P7-01 must still deny 13 and require HMAC."""

    def test_p701_deny_list_still_13(self) -> None:
        assert len(AuthorityBoundary.DENIED_ACTIONS) == 13
        for verb in AuthorityBoundary.DENIED_ACTIONS:
            with pytest.raises(AuthorityError):
                AuthorityBoundary().attempt(verb)

    def test_p701_hmac_still_enforced(self) -> None:
        from agents.authority.evidence import EvidenceReference

        reg = _registry()
        # Fabricated without HMAC must be rejected via registry.
        fabricated = EvidenceReference(
            source_id="src-ledger-001",
            evidence_id="ev-ledger-001",
            captured_at=NOW - timedelta(seconds=60),
            digest=DIGEST_A,
            provenance="p6_evidence_store",
            ttl_seconds=3600,
        )
        with pytest.raises(AuthorityError):
            reg.validate_reference(fabricated, NOW)
        # Registry-issued must pass.
        ref = reg.create_reference("ev-ledger-001")
        reg.validate_reference(ref, NOW)


class TestP702Regression:
    """P7-02 runtime must still be capability-gated and factory-bound."""

    def test_p702_runtime_still_gated(self) -> None:
        from agents.runtime import AgentRuntime, RuntimeContext

        reg = _registry()
        boundary = AuthorityBoundary()
        ctx = RuntimeContext(
            situation_id="sit-reg-001",
            company_id="meridian",
            now=NOW,
            registry=reg,
            boundary=boundary,
        )
        rt = AgentRuntime(ctx)
        # Denied capability still refused.
        with pytest.raises(AuthorityError):
            rt.dispatch("approve", {})  # type: ignore[arg-type]
        # Allowed still works.
        refs = rt.read(("ev-ledger-001",))
        assert refs[0].evidence_id == "ev-ledger-001"

    def test_p702_factory_still_required_for_strict_path(self) -> None:
        reg = _registry()
        boundary = AuthorityBoundary()
        factory = RuntimeFactory()
        ctx = factory.create_context(
            situation_id="sit-reg-002",
            now=NOW,
            registry=reg,
            boundary=boundary,
        )
        rt = factory.create_runtime(ctx)
        handoff = rt.propose(
            proposal_type="advisory_note",
            evidence_ids=("ev-ledger-001",),
            uncertainty="U",
            rationale="R",
        )
        assert handoff.situation_id == "sit-reg-002"
        # Direct context without factory token must be rejected when validated.
        from agents.runtime import RuntimeContext

        direct = RuntimeContext(
            situation_id="sit-reg-002",
            company_id="meridian",
            now=NOW,
            registry=reg,
            boundary=boundary,
        )
        with pytest.raises(AuthorityError):
            factory.validate_context(direct)
