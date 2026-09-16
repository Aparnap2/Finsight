"""Real LLM smoke tests — validates Groq provider against the P4 boundary.

Requires: FINSIGHT_ALLOW_LIVE_LLM=1 uv run python -m pytest tests/evals/llm/ -v

These tests answer: "Can Groq produce outputs that survive our frozen
deterministic boundary?"  They do NOT replace the 1787+ deterministic tests.
"""

from __future__ import annotations

import os

import pytest

# Gate: require explicit opt-in
_allow_live = os.environ.get("FINSIGHT_ALLOW_LIVE_LLM", "")

# Skip all tests in this file unless gated. live_llm marks quota-consuming
# tests so the default suite stays zero-quota: pytest -m "not live_llm".
pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(
        not _allow_live,
        reason="Live LLM tests require FINSIGHT_ALLOW_LIVE_LLM=1",
    ),
    pytest.mark.evals,
]


@pytest.fixture(scope="module")
def live_provider():
    """Create a real Groq provider (one instance per module)."""
    from shared.llm.config import resolve_config
    from shared.llm.openai_compatible import OpenAICompatibleProvider

    config = resolve_config()
    provider = OpenAICompatibleProvider(config)
    health = provider.health_check()
    if not health.ok:
        pytest.skip(f"Groq provider unhealthy: {health.reason}")
    return provider


@pytest.fixture(scope="module")
def live_planner(live_provider):
    """Create a real Planner bound to the live provider."""
    from agents.investigation.planner import Planner

    return Planner(live_provider)


@pytest.fixture(scope="module")
def partial_refund_request():
    """Canonical PARTIAL_REFUND_ACCOUNTING_LAG request."""
    from agents.investigation.request import InvestigationRequest

    return InvestigationRequest(
        exception_id="smoke-partial-refund-001",
        exception_type="PARTIAL_REFUND_ACCOUNTING_LAG",
        tenant_id="tenant-001",
        actor="user-001",
        evidence_ids=("ev_stripe_charge_001", "ev_qb_ledger_002"),
        context_window="Charge: 50000 INR. Refund: 15000 INR. Expected: 35000. Ledger shows 50000.",
        capability_allowlist=(
            "get_stripe_payment",
            "get_stripe_refunds",
            "get_qb_transaction",
            "get_expected_state",
            "search_gmail",
        ),
        round_budget=3,
    )


@pytest.fixture(scope="module")
def duplicate_entry_request():
    """Canonical DUPLICATE_LEDGER_ENTRY request."""
    from agents.investigation.request import InvestigationRequest

    return InvestigationRequest(
        exception_id="smoke-duplicate-001",
        exception_type="DUPLICATE_LEDGER_ENTRY",
        tenant_id="tenant-001",
        actor="user-001",
        evidence_ids=("ev_qb_txn_a", "ev_qb_txn_b", "ev_stripe_ch_001"),
        context_window=(
            "Two QB entries reference Stripe charge ch_001. One matches exactly. Other is 2x."
        ),
        capability_allowlist=(
            "get_stripe_payment",
            "get_stripe_refunds",
            "get_qb_transaction",
            "get_expected_state",
            "search_gmail",
        ),
        round_budget=3,
    )


class TestGroqProviderSmoke:
    """Layer 1: Provider contract with real Groq."""

    def test_health_check(self, live_provider) -> None:
        health = live_provider.health_check()
        assert health.ok is True
        assert health.latency_ms is not None and health.latency_ms > 0

    def test_model_metadata(self, live_provider) -> None:
        meta = live_provider.model_metadata()
        assert meta.provider == "groq"
        assert "gpt-oss" in meta.model or "qwen" in meta.model

    def test_generate_simple_json(self, live_provider) -> None:
        from pydantic import BaseModel

        class SimpleOut(BaseModel):
            status: str
            ok: bool

        result = live_provider.generate_structured(
            'Return JSON: {"status": "alive", "ok": true}', SimpleOut
        )
        assert result.status == "alive"
        assert result.ok is True


class TestPlannerSmoke:
    """Layer 2: Real Planner with real Groq."""

    def test_partial_refund_plan(self, live_planner, partial_refund_request) -> None:
        from agents.investigation.plan import InvestigationPlan

        plan = live_planner.plan(partial_refund_request)
        assert isinstance(plan, InvestigationPlan)
        assert len(plan.hypothesis_text.strip()) > 0
        assert len(plan.capability_calls) >= 1
        assert len(plan.evidence_required) >= 1

        # Verify all capabilities are in allowlist
        allowed = set(partial_refund_request.capability_allowlist)
        for call in plan.capability_calls:
            assert call.capability in allowed

        # Verify evidence_required is subset of request evidence
        known = set(partial_refund_request.evidence_ids)
        for eid in plan.evidence_required:
            assert eid in known

        print(f"\n  Hypothesis: {plan.hypothesis_text[:120]}...")
        print(f"  Capabilities: {[c.capability for c in plan.capability_calls]}")
        print(f"  Evidence: {plan.evidence_required}")

    def test_duplicate_entry_plan(self, live_planner, duplicate_entry_request) -> None:
        from agents.investigation.plan import InvestigationPlan

        plan = live_planner.plan(duplicate_entry_request)
        assert isinstance(plan, InvestigationPlan)
        assert len(plan.capability_calls) >= 1
        assert len(plan.evidence_required) >= 1

        print(f"\n  Hypothesis: {plan.hypothesis_text[:120]}...")
        print(f"  Capabilities: {[c.capability for c in plan.capability_calls]}")

    def test_plan_passes_verifier(self, live_planner, partial_refund_request) -> None:
        """Full boundary: Planner → Verifier with real LLM output."""
        from agents.verification.verifier import Verifier

        plan = live_planner.plan(partial_refund_request)
        verifier = Verifier(max_replans=2, confidence_cap=0.85)
        verdict = verifier.verify(plan, set(partial_refund_request.evidence_ids), 0)

        print(f"\n  Verdict: {verdict.status}")
        print(f"  Reasons: {verdict.reasons}")
        # We accept either ACCEPTED or REJECTED_REPLAN — both prove the boundary works
        assert verdict.status in ("ACCEPTED", "REJECTED_REPLAN")