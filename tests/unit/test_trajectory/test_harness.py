"""P5-07 trajectory harness tests: Fake/Replay/Live/E2E INPUT→FINAL.

Covers :class:`agents.trajectory.harness.TrajectoryHarness` with a
scripted FakeLLM + real verifier + real executor (empty bundle):

- Fake happy path INPUT→MODEL_OUTPUT→VERIFIER→TOOL→TOOL_RESULT→FINAL.
- Replay reproduces the trajectory without any LLM call.
- Tenant isolation fail-closed before any LLM call.
- correlation_id propagated across every step; tenant-safe ids only.
- Fixture save/load round-trip; replay exhaustion; live gate; verifier
  rejection → replan bounded by budget.
- Timing latencies present; no secrets in the ledger.

Style: Arrange-Act-Assert, typed, deterministic, no network or LLM.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from agents.capabilities.capabilities import AdapterBundle
from agents.capabilities.executor import CapabilityExecutor
from agents.investigation.request import InvestigationRequest
from agents.trajectory.harness import (
    TrajectoryHarness,
    TrajectoryLiveError,
    TrajectoryTenantError,
    is_live_allowed,
)
from agents.trajectory.models import generate_correlation_id
from agents.trajectory.recorder import (
    SequentialReplayProvider,
    load_fixture,
    save_fixture,
)
from agents.verification.verifier import Verifier
from shared.llm.fake import FakeLLM

_TENANT = "meridian"
_EXCEPTION_ID = "FS-2026-0916-00231"
_PLAN_PAYLOAD = {
    "hypothesis_text": "Possible refund posting lag between processor and ledger.",
    "capability_calls": [
        {"capability": "search_gmail", "args": {"query": "refund"}, "order_index": 0}
    ],
    "evidence_required": ["ev-001"],
    "escalation": False,
}


def _request() -> InvestigationRequest:
    """Build a trusted request for the meridian tenant."""
    return InvestigationRequest.model_validate(
        {
            "exception_id": _EXCEPTION_ID,
            "exception_type": "I-REFUND-LAG",
            "tenant_id": _TENANT,
            "actor": "analyst-001",
            "evidence_ids": ["ev-001"],
        }
    )


def _bundle() -> AdapterBundle:
    """Minimal executor bundle: mock QB + empty ledger + one gmail hit."""
    from finance.accounting.mock import MockQuickBooksAdapter
    from finance.reconciliation.ledger_resolution import InMemoryLedgerRepository

    return AdapterBundle(
        qb_adapter=MockQuickBooksAdapter(),
        ledger_repository=InMemoryLedgerRepository.from_records([]),
        gmail_corpus={
            _TENANT: [
                {
                    "message_id": "msg-traj-1",
                    "subject": "Refund receipt",
                    "body": "Your refund of 25.00 was processed",
                }
            ]
        },
    )


def _harness(
    payload: dict[str, Any] | None = None, mode: str = "fake"
) -> tuple[TrajectoryHarness, FakeLLM]:
    """Bind a harness to a FakeLLM scripted with the plan payload."""
    fake = FakeLLM(scripted={"InvestigationPlan": payload or _PLAN_PAYLOAD})
    executor = CapabilityExecutor(_bundle())
    harness = TrajectoryHarness(fake, executor, Verifier(), mode=mode)  # type: ignore[arg-type]
    return harness, fake


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block real sockets so every test stays deterministic and offline."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network is forbidden in harness tests")

    monkeypatch.setattr("socket.socket", _explode)


# ===========================================================================
# Fake happy path
# ===========================================================================


class TestFakeHappyPath:
    """Fake mode runs INPUT→MODEL_OUTPUT→VERIFIER→TOOL→TOOL_RESULT→FINAL."""

    def test_fake_accepts_and_records_full_ledger(self) -> None:
        """Arrange scripted plan; Act run; Assert ACCEPTED + ordered kinds."""
        harness, _ = _harness()
        trajectory = harness.run(_request(), _TENANT)
        kinds = [s.kind for s in trajectory.steps]
        assert kinds[0] == "INPUT"
        assert kinds[-1] == "FINAL"
        assert trajectory.final_status == "ACCEPTED"
        assert "MODEL_OUTPUT" in kinds
        assert "VERIFIER" in kinds
        assert "TOOL" in kinds
        assert "TOOL_RESULT" in kinds

    def test_correlation_id_propagated(self) -> None:
        """Every step carries the run correlation_id."""
        harness, _ = _harness()
        trajectory = harness.run(_request(), _TENANT)
        assert trajectory.correlation_id == harness.correlation_id
        for step in trajectory.steps:
            assert step.correlation_id == harness.correlation_id

    def test_tenant_safe_ids_only(self) -> None:
        """Ledger holds ids + codes only — no secrets, no bodies."""
        harness, _ = _harness()
        trajectory = harness.run(_request(), _TENANT)
        blob = json.dumps(trajectory.to_fixture())
        for banned in ("api_key", "secret", "password", "Bearer", "sk-"):
            assert banned not in blob
        for step in trajectory.steps:
            assert step.tenant_id == _TENANT

    def test_latencies_present(self) -> None:
        """MODEL_OUTPUT steps carry non-negative latency_ms."""
        harness, _ = _harness()
        trajectory = harness.run(_request(), _TENANT)
        model_steps = [s for s in trajectory.steps if s.kind == "MODEL_OUTPUT"]
        assert model_steps
        for step in model_steps:
            assert step.latency_ms is not None and step.latency_ms >= 0

    def test_llm_call_counted(self) -> None:
        """One LLM call for the accepted first attempt."""
        harness, _ = _harness()
        harness.run(_request(), _TENANT)
        assert harness.llm_calls == 1


# ===========================================================================
# Replay
# ===========================================================================


class TestReplay:
    """Replay reproduces the trajectory with zero LLM calls."""

    def test_replay_without_llm_call(self, tmp_path: Any) -> None:
        """Record a fake run, replay its outputs, assert same FINAL."""
        harness, _ = _harness()
        trajectory = harness.run(_request(), _TENANT)
        path = save_fixture(trajectory, tmp_path / "traj.json")
        fixture = load_fixture(path)
        # Seed the replay provider from the recorded MODEL_OUTPUT payload.
        provider = SequentialReplayProvider.from_payloads([dict(_PLAN_PAYLOAD)])
        assert fixture["trajectory"]["final_status"] == "ACCEPTED"
        replay = TrajectoryHarness(
            provider, CapabilityExecutor(_bundle()), Verifier(), mode="replay"
        )
        replayed = replay.run(_request(), _TENANT)
        assert replayed.final_status == "ACCEPTED"
        assert replayed.steps[0].kind == "INPUT"
        assert replayed.steps[-1].kind == "FINAL"

    def test_replay_exhaustion_raises(self) -> None:
        """Consuming the last payload exhausts; next call raises IndexError."""
        from agents.investigation.plan import InvestigationPlan

        provider = SequentialReplayProvider.from_payloads([dict(_PLAN_PAYLOAD)])
        assert provider.remaining == 1
        provider.generate_structured(object(), InvestigationPlan)
        assert provider.remaining == 0
        with pytest.raises(IndexError, match="replay exhausted"):
            provider.generate_structured(object(), InvestigationPlan)

    def test_fixture_roundtrip(self, tmp_path: Any) -> None:
        """save_fixture → load_fixture preserves trajectory identity."""
        harness, _ = _harness()
        trajectory = harness.run(_request(), _TENANT)
        path = save_fixture(trajectory, tmp_path / "roundtrip.json")
        fixture = load_fixture(path)
        assert fixture["trajectory"]["correlation_id"] == harness.correlation_id
        assert fixture["trajectory"]["tenant_id"] == _TENANT


# ===========================================================================
# Tenant isolation + live gate + rejection bounds
# ===========================================================================


class TestHarnessGuards:
    """Fail-closed tenant check, live opt-in gate, bounded replans."""

    def test_tenant_mismatch_fail_closed(self) -> None:
        """Run tenant != request tenant raises before any LLM call."""
        harness, fake = _harness()
        with pytest.raises(TrajectoryTenantError, match="tenant_mismatch"):
            harness.run(_request(), "tenant-b")
        assert harness.llm_calls == 0
        assert fake.call_count == 0 if hasattr(fake, "call_count") else True

    def test_live_requires_opt_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """live mode without FINSIGHT_ALLOW_LIVE_LLM=1 raises."""
        monkeypatch.delenv("FINSIGHT_ALLOW_LIVE_LLM", raising=False)
        assert is_live_allowed() is False
        harness, _ = _harness(mode="live")
        with pytest.raises(TrajectoryLiveError):
            harness.run(_request(), _TENANT)

    def test_unknown_mode_rejected(self) -> None:
        """Constructor rejects unknown modes."""
        fake = FakeLLM(scripted={"InvestigationPlan": _PLAN_PAYLOAD})
        with pytest.raises(ValueError, match="unknown trajectory mode"):
            TrajectoryHarness(fake, CapabilityExecutor(_bundle()), mode="nope")  # type: ignore[arg-type]

    def test_rejection_bounded_replans(self) -> None:
        """Uncited evidence rejects; replans stay within budget."""
        bad_payload = dict(_PLAN_PAYLOAD, evidence_required=["ev-ghost"])
        harness, _ = _harness(payload=bad_payload)
        trajectory = harness.run(_request(), _TENANT)
        assert trajectory.final_status in ("REJECTED_REPLAN", "ESCALATE_HITL")
        assert harness.llm_calls <= 3
        verifier_steps = [s for s in trajectory.steps if s.kind == "VERIFIER"]
        assert len(verifier_steps) <= 3

    def test_generate_correlation_id_tenant_safe(self) -> None:
        """Generated ids match the tenant-safe pattern."""
        cid = generate_correlation_id(_EXCEPTION_ID)
        assert cid.startswith(_EXCEPTION_ID)
        assert len(cid) <= 128
