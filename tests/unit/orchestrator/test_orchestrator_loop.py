"""D5: Harness engineering tests — bounded replan, HITL escalation, provider failure.

Covers InvestigateOrchestrator through the frozen loop: planner→verifier→
executor with bounded replans, provider failures, health gates, and
deterministic proposal synthesis. Fully deterministic: FakeLLM scripted
payloads, no network, no money arithmetic.

Style: Arrange-Act-Assert per test, typed, deterministic.
"""

from __future__ import annotations

import socket
import time
import urllib.request
from typing import Any

import pytest

from agents.capabilities.executor import CapabilityExecutor
from agents.investigation.request import InvestigationRequest
from agents.orchestrator.orchestrator import InvestigateOrchestrator
from agents.orchestrator.types import OrchestrationResult
from agents.verification.verifier import Verifier
from shared.llm.errors import ProviderError, ProviderUnavailableError
from shared.llm.fake import FakeLLM
from shared.llm.types import InvestigationPrompt, ModelMetadata, ProviderCallLog, ProviderHealth

_HYPOTHESIS = "Possible refund posting lag between processor and ledger records."
_TENANT = "tenant-acme"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block real sockets so every test stays deterministic."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network forbidden in orchestrator loop tests")

    monkeypatch.setattr(socket, "socket", _explode)
    monkeypatch.setattr(urllib.request, "urlopen", _explode)


def _make_request() -> InvestigationRequest:
    """Build a valid deterministic request."""
    return InvestigationRequest(
        exception_id="exc-loop-001",
        exception_type="I-REFUND-LAG",
        tenant_id="tenant-001",
        actor="user-001",
        evidence_ids=("ev-ledger-001", "ev-processor-002"),
        context_window="refund posting lag probe",
        round_budget=3,
    )


def _valid_plan_payload() -> dict[str, Any]:
    """Schema-valid InvestigationPlan payload for FakeLLM."""
    return {
        "hypothesis_text": _HYPOTHESIS,
        "capability_calls": [
            {
                "capability": "get_stripe_payment",
                "args": {"payment_id": "pay_123"},
                "order_index": 0,
            },
        ],
        "evidence_required": ["ev-ledger-001"],
        "escalation": False,
    }


def _bad_plan_payload() -> dict[str, Any]:
    """Plan that fails the verifier (off-allowlist capability)."""
    return {
        "hypothesis_text": _HYPOTHESIS,
        "capability_calls": [
            {
                "capability": "read_database",
                "args": {"table": "ledger"},
                "order_index": 0,
            },
        ],
        "evidence_required": ["ev-ledger-001"],
        "escalation": False,
    }


def _authoritative_plan_payload() -> dict[str, Any]:
    """Plan that fails the verifier (authoritative wording)."""
    return {
        "hypothesis_text": "The lag is verified in the ledger.",
        "capability_calls": [
            {
                "capability": "get_stripe_payment",
                "args": {"payment_id": "pay_123"},
                "order_index": 0,
            },
        ],
        "evidence_required": ["ev-ledger-001"],
        "escalation": False,
    }


class _CyclingFakeLLM:
    """FakeLLM variant that cycles through scripted payloads per call."""

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self._payloads = payloads
        self._index = 0
        self.journal: list[ProviderCallLog] = []
        self._healthy = True

    def health_check(self) -> ProviderHealth:
        if self._healthy:
            return ProviderHealth(ok=True, latency_ms=0.0)
        return ProviderHealth(ok=False, latency_ms=0.0, reason="fake unhealthy")

    def model_metadata(self) -> ModelMetadata:
        return ModelMetadata(provider="fake", model="cycling-fake")

    def generate_structured(self, prompt: InvestigationPrompt | str, response_schema: type) -> Any:
        start = time.monotonic()
        if isinstance(prompt, InvestigationPrompt):
            input_chars = len(prompt.user_prompt) + len(prompt.system_prompt)
        else:
            input_chars = len(prompt)
        if self._index >= len(self._payloads):
            exc = ProviderError("no more scripted responses")
            self.journal.append(
                ProviderCallLog(
                    provider="fake",
                    model="cycling-fake",
                    success=False,
                    latency_ms=0,
                    input_chars=input_chars,
                    output_chars=None,
                    error_kind="ProviderError",
                )
            )
            raise exc
        payload = self._payloads[self._index]
        self._index += 1
        try:
            from shared.llm.provider import validate_structured_output

            result = validate_structured_output(payload, response_schema)
            self.journal.append(
                ProviderCallLog(
                    provider="fake",
                    model="cycling-fake",
                    success=True,
                    latency_ms=(time.monotonic() - start) * 1000,
                    input_chars=input_chars,
                    output_chars=len(str(payload)),
                    error_kind=None,
                )
            )
            return result
        except Exception as exc:
            self.journal.append(
                ProviderCallLog(
                    provider="fake",
                    model="cycling-fake",
                    success=False,
                    latency_ms=(time.monotonic() - start) * 1000,
                    input_chars=input_chars,
                    output_chars=None,
                    error_kind=type(exc).__name__,
                )
            )
            raise

    @property
    def call_journal(self) -> list[ProviderCallLog]:
        return self.journal


def _build_orchestrator(
    fake: Any,
    *,
    max_replans: int = 2,
) -> InvestigateOrchestrator:
    """Build an orchestrator with a minimal stub executor."""
    from agents.capabilities.capabilities import AdapterBundle
    from finance.accounting.mock import MockQuickBooksAdapter
    from finance.reconciliation.ledger_resolution import InMemoryLedgerRepository

    bundle = AdapterBundle(
        stripe_payments={},
        qb_adapter=MockQuickBooksAdapter(),
        ledger_repository=InMemoryLedgerRepository.from_records([]),
        gmail_corpus={},
    )
    executor = CapabilityExecutor(bundle)
    verifier = Verifier(max_replans=max_replans)
    return InvestigateOrchestrator(
        llm=fake,
        capability_executor=executor,
        verifier=verifier,
    )


class TestHappyPath:
    """Valid plan on first attempt yields ACCEPTED_CANDIDATE."""

    def test_valid_plan_accepted_on_first_attempt(self) -> None:
        """Arrange FakeLLM with valid plan; Act run; Assert ACCEPTED_CANDIDATE."""
        fake = FakeLLM(scripted={"InvestigationPlan": _valid_plan_payload()})
        orch = _build_orchestrator(fake)
        request = _make_request()
        result = orch.run(request, _TENANT)
        assert isinstance(result, OrchestrationResult)
        assert result.status == "ACCEPTED_CANDIDATE"
        assert result.attempts == 1
        assert result.is_hitl is False
        assert result.request_id == "exc-loop-001"
        assert len(result.verdicts) == 1
        assert result.verdicts[0].status == "ACCEPTED"

    def test_valid_plan_yields_capability_outcomes(self) -> None:
        """Arrange FakeLLM + valid plan; Act run; Assert capability outcomes."""
        fake = FakeLLM(scripted={"InvestigationPlan": _valid_plan_payload()})
        orch = _build_orchestrator(fake)
        result = orch.run(_make_request(), _TENANT)
        assert len(result.capability_outcomes) == 1
        assert result.capability_outcomes[0].capability == "get_stripe_payment"


class TestReplan:
    """Verifier rejection triggers bounded replan."""

    def test_bad_plan_then_good_plan_replans(self) -> None:
        """Arrange bad then valid plan; Act run; Assert accepted on attempt 2."""
        fake = _CyclingFakeLLM([_bad_plan_payload(), _valid_plan_payload()])
        orch = _build_orchestrator(fake, max_replans=2)
        request = _make_request()
        result = orch.run(request, _TENANT)
        assert result.status == "ACCEPTED_CANDIDATE"
        assert result.attempts == 2
        assert result.is_hitl is False
        assert len(result.verdicts) == 2

    def test_authoritative_plan_then_good_plan_replans(self) -> None:
        """Arrange authoritative then valid; Act; Assert accepted on attempt 2."""
        fake = _CyclingFakeLLM([_authoritative_plan_payload(), _valid_plan_payload()])
        orch = _build_orchestrator(fake, max_replans=2)
        result = orch.run(_make_request(), _TENANT)
        assert result.status == "ACCEPTED_CANDIDATE"
        assert result.attempts == 2


class TestBudgetExhaustion:
    """All-bad plans exhaust the budget and escalate to HITL."""

    def test_always_bad_plan_exhausts_budget(self) -> None:
        """Arrange always-bad plan; Act run; Assert REPLAN_EXHAUSTED_HITL."""
        fake = FakeLLM(scripted={"InvestigationPlan": _bad_plan_payload()})
        orch = _build_orchestrator(fake, max_replans=2)
        result = orch.run(_make_request(), _TENANT)
        assert result.status == "REPLAN_EXHAUSTED_HITL"
        assert result.is_hitl is True
        assert result.attempts == 3  # max_replans + 1
        assert len(result.verdicts) == 3
        assert result.hitl_reason is not None

    def test_zero_replans_immediate_hitl(self) -> None:
        """Arrange max_replans=0; Act; Assert immediate HITL after 1 attempt."""
        fake = FakeLLM(scripted={"InvestigationPlan": _bad_plan_payload()})
        orch = _build_orchestrator(fake, max_replans=0)
        result = orch.run(_make_request(), _TENANT)
        assert result.status == "REPLAN_EXHAUSTED_HITL"
        assert result.attempts == 1
        assert result.is_hitl is True


class TestProviderFailure:
    """Provider errors escalate to HITL without infinite loops."""

    def test_provider_error_always_exhausts(self) -> None:
        """Arrange fail_all=ProviderError; Act; Assert HITL."""
        fake = FakeLLM(fail_all=ProviderError("provider down"))
        orch = _build_orchestrator(fake, max_replans=2)
        result = orch.run(_make_request(), _TENANT)
        assert result.status == "REPLAN_EXHAUSTED_HITL"
        assert result.is_hitl is True
        assert result.attempts >= 1

    def test_provider_unavailable_always_exhausts(self) -> None:
        """Arrange fail_all=ProviderUnavailableError; Act; Assert HITL."""
        fake = FakeLLM(fail_all=ProviderUnavailableError("unavailable"))
        orch = _build_orchestrator(fake, max_replans=2)
        result = orch.run(_make_request(), _TENANT)
        assert result.status == "REPLAN_EXHAUSTED_HITL"
        assert result.is_hitl is True

    def test_provider_unhealthy_no_llm_call(self) -> None:
        """Arrange unhealthy provider; Act; Assert PROVIDER_FAILURE_HITL, 0 attempts."""
        fake = FakeLLM(healthy=False)
        orch = _build_orchestrator(fake, max_replans=2)
        result = orch.run(_make_request(), _TENANT)
        assert result.status == "PROVIDER_FAILURE_HITL"
        assert result.is_hitl is True
        assert result.attempts == 0
        assert result.hitl_reason is not None
        assert "provider unhealthy" in result.hitl_reason.lower()


class TestProviderJournal:
    """Provider call journal is collected correctly."""

    def test_journal_collected_on_success(self) -> None:
        """Arrange valid plan; Act run; Assert journal has one entry."""
        fake = FakeLLM(scripted={"InvestigationPlan": _valid_plan_payload()})
        orch = _build_orchestrator(fake)
        result = orch.run(_make_request(), _TENANT)
        assert len(result.provider_journal) == 1
        assert result.provider_journal[0].success is True

    def test_journal_collected_on_exhaustion(self) -> None:
        """Arrange always-bad; Act run; Assert journal has multiple entries."""
        fake = FakeLLM(scripted={"InvestigationPlan": _bad_plan_payload()})
        orch = _build_orchestrator(fake, max_replans=1)
        result = orch.run(_make_request(), _TENANT)
        assert len(result.provider_journal) >= 2


class TestInputValidation:
    """Orchestrator rejects bad constructor and run inputs."""

    def test_none_llm_raises(self) -> None:
        """Arrange None llm; Act; Assert TypeError."""
        with pytest.raises(TypeError, match="llm must be"):
            InvestigateOrchestrator(llm=None, capability_executor=None, verifier=None)  # type: ignore[arg-type]

    def test_none_request_raises(self) -> None:
        """Arrange None request; Act; Assert TypeError."""
        fake = FakeLLM(scripted={"InvestigationPlan": _valid_plan_payload()})
        orch = _build_orchestrator(fake)
        with pytest.raises(TypeError, match="request must be"):
            orch.run(None, _TENANT)  # type: ignore[arg-type]

    def test_blank_tenant_raises(self) -> None:
        """Arrange blank tenant; Act; Assert ValueError."""
        fake = FakeLLM(scripted={"InvestigationPlan": _valid_plan_payload()})
        orch = _build_orchestrator(fake)
        with pytest.raises(ValueError, match="tenant_id must be non-blank"):
            orch.run(_make_request(), "  ")


class TestStatusProperties:
    """is_hitl property is correct for each status."""

    def test_accepted_candidate_not_hitl(self) -> None:
        """Arrange valid plan; Act run; Assert is_hitl is False."""
        fake = FakeLLM(scripted={"InvestigationPlan": _valid_plan_payload()})
        orch = _build_orchestrator(fake)
        result = orch.run(_make_request(), _TENANT)
        assert result.status == "ACCEPTED_CANDIDATE"
        assert result.is_hitl is False

    def test_exhausted_is_hitl(self) -> None:
        """Arrange always-bad; Act; Assert is_hitl is True."""
        fake = FakeLLM(scripted={"InvestigationPlan": _bad_plan_payload()})
        orch = _build_orchestrator(fake, max_replans=0)
        result = orch.run(_make_request(), _TENANT)
        assert result.status == "REPLAN_EXHAUSTED_HITL"
        assert result.is_hitl is True

    def test_provider_failure_is_hitl(self) -> None:
        """Arrange unhealthy; Act; Assert is_hitl is True."""
        fake = FakeLLM(healthy=False)
        orch = _build_orchestrator(fake)
        result = orch.run(_make_request(), _TENANT)
        assert result.status == "PROVIDER_FAILURE_HITL"
        assert result.is_hitl is True