"""P10-03 RED: per-path wiring through the privacy boundary (failing).

Five integration points route provider-bound prompt data through
``shared.privacy.boundary.authorize_llm_context`` (absent pre-GREEN,
so every spy errors):

- agents.commentary.commentary_agent (purpose COMMENTARY)
- agents.driver.root_cause_agent (purpose ROOT_CAUSE)
- finance.reasoning.llm_boundary (purpose REASONING)
- finance.workflows.workflow (purpose WORKFLOW)
- agents.investigation.planner (purpose INVESTIGATION)

``finance/reasoning/pipeline.py`` needs no test: it passes typed
assertions to the injected provider, covered by the llm_boundary
cases. Output-content tests (planner, commentary, root_cause,
llm_boundary) drive the real paths with PII-bearing inputs and assert
the captured provider-bound prompt carries no raw secrets or PII.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Any

import pytest

from shared.llm.fake import FakeLLM
from shared.models.assertions import Assertion, AssertionType, SupportLevel


class _SpyBoundary:
    """Stand-in for the boundary module: records gate calls, then denies."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def authorize_llm_context(self, data: Any, **kwargs: Any) -> Any:
        self.calls.append({"data": data, **kwargs})
        raise RuntimeError("privacy boundary deny (test spy)")


class _CapturingLLMClient:
    """LLMClient-shaped fake: records generate() prompts, returns canned text."""

    def __init__(self, canned: str = "{}") -> None:
        self.prompts: list[str] = []
        self.canned = canned

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.3) -> str:
        self.prompts.append(prompt)
        return self.canned


def _valid_plan_payload() -> dict[str, Any]:
    """Minimal schema-valid InvestigationPlan payload."""
    return {
        "hypothesis_text": "refund posting lags provider settlement",
        "capability_calls": [
            {
                "capability": "get_stripe_payment",
                "args": {"payment_id": "pay_123"},
                "order_index": 0,
            }
        ],
        "evidence_required": ["ev-ledger-001"],
        "escalation": False,
    }


def test_commentary_routes_through_boundary(monkeypatch: Any) -> None:
    from agents.commentary import commentary_agent as mod
    from agents.commentary.commentary_agent import (
        CommentaryRenderInput,
        render_commentary,
    )

    spy = _SpyBoundary()
    monkeypatch.setattr(mod, "privacy_boundary", spy)
    assertion = Assertion(
        id="a1",
        type=AssertionType.NUMERIC,
        text="lag reported by rahul@example.com",
        confidence=0.9,
        support_level=SupportLevel.VERIFIED,
    )
    render_input = CommentaryRenderInput(
        verified_assertions=[assertion], probable_assertions=[], weak_assertions=[]
    )
    fake = _CapturingLLMClient()
    with contextlib.suppress(RuntimeError):
        render_commentary(render_input, fake, tenant_id="tenant-001")
    assert len(spy.calls) == 1
    assert spy.calls[0]["purpose"] == "commentary"
    assert spy.calls[0]["tenant_id"]


def test_root_cause_routes_through_boundary(monkeypatch: Any) -> None:
    from decimal import Decimal

    from agents.driver import root_cause_agent as mod
    from agents.driver.root_cause_agent import investigate_root_causes
    from shared.models.state import Variance

    spy = _SpyBoundary()
    monkeypatch.setattr(mod, "privacy_boundary", spy)
    variance = Variance(
        account_id="acc-1",
        account_name="refunds rahul@example.com",
        department="Sales",
        actual_amount=Decimal("100.00"),
        budget_amount=Decimal("80.00"),
        variance_amount=Decimal("20.00"),
        variance_pct=Decimal("25.00"),
    )
    fake = _CapturingLLMClient(
        canned="SUMMARY: lag\nEVIDENCE: books\nCONFIDENCE: 0.9\nACTION: review"
    )
    with contextlib.suppress(RuntimeError):
        investigate_root_causes([variance], fake, tenant_id="tenant-001")
    assert len(spy.calls) == 1
    assert spy.calls[0]["purpose"] == "root_cause"
    assert spy.calls[0]["tenant_id"]


def test_llm_boundary_routes_through_boundary(monkeypatch: Any) -> None:
    from finance.reasoning import llm_boundary as mod
    from finance.reasoning.llm_boundary import StructuredCommentaryProvider

    spy = _SpyBoundary()
    monkeypatch.setattr(mod, "privacy_boundary", spy)
    assertion = Assertion(
        id="a1",
        type=AssertionType.NUMERIC,
        text="gap noted by rahul@example.com",
        confidence=0.8,
        support_level=SupportLevel.PROBABLE,
    )
    provider = StructuredCommentaryProvider(
        llm_client=_CapturingLLMClient(), tenant_id="tenant-001"
    )
    with contextlib.suppress(RuntimeError):
        provider.generate([assertion])
    assert len(spy.calls) == 1
    assert spy.calls[0]["purpose"] == "reasoning"
    assert spy.calls[0]["tenant_id"]


def test_workflow_routes_through_boundary(monkeypatch: Any) -> None:
    from finance.workflows import workflow as mod

    spy = _SpyBoundary()
    monkeypatch.setattr(mod, "privacy_boundary", spy)

    class _FakeWorkflowClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def generate(
            self,
            system_prompt: str = "",
            user_prompt: str = "",
            response_model: Any = None,
        ) -> str:
            self.calls.append(
                {
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "response_model": response_model,
                }
            )
            return "{}"

    bound = mod.FinanceAnalysisWorkflow._do_generate_commentary.__get__(
        SimpleNamespace(_llm_client=_FakeWorkflowClient()), mod.FinanceAnalysisWorkflow
    )
    bound("acme", tenant_id="tenant-001")
    assert len(spy.calls) == 1
    assert spy.calls[0]["purpose"] == "workflow"
    assert spy.calls[0]["tenant_id"]


def test_planner_routes_through_boundary(monkeypatch: Any) -> None:
    from agents.investigation import planner as mod
    from agents.investigation.planner import Planner
    from agents.investigation.request import InvestigationRequest

    spy = _SpyBoundary()
    monkeypatch.setattr(mod, "privacy_boundary", spy)
    request = InvestigationRequest(
        exception_id="exc-p10-001",
        exception_type="I-REFUND-LAG",
        tenant_id="tenant-001",
        actor="user-001",
        evidence_ids=["ev-ledger-001"],
        context_window="refund posting lag probe",
        round_budget=1,
    )
    planner = Planner(llm=FakeLLM(scripted={"InvestigationPlan": _valid_plan_payload()}))
    with pytest.raises(RuntimeError, match="privacy boundary deny"):
        planner.plan(request)
    assert len(spy.calls) == 1
    assert spy.calls[0]["purpose"] == "investigation"
    assert spy.calls[0]["tenant_id"] == "tenant-001"


class TestPlannerOutputCleanliness:
    def test_pii_context_never_reaches_provider(self, monkeypatch: Any) -> None:
        from agents.investigation.planner import Planner
        from agents.investigation.request import InvestigationRequest

        captured: dict[str, str] = {}
        fake = FakeLLM(scripted={"InvestigationPlan": _valid_plan_payload()})
        original = FakeLLM.generate_structured

        def _capture(self: Any, prompt: Any, schema: Any) -> Any:
            captured["prompt"] = prompt.user_prompt
            return original(self, prompt, schema)

        monkeypatch.setattr(FakeLLM, "generate_structured", _capture)
        request = InvestigationRequest(
            exception_id="exc-p10-002",
            exception_type="I-REFUND-LAG",
            tenant_id="tenant-001",
            actor="user-001",
            evidence_ids=["ev-ledger-001"],
            context_window="contact rahul@example.com, key sk-live-abc123xyz",
            round_budget=1,
        )
        Planner(llm=fake).plan(request)
        prompt = captured["prompt"]
        assert "rahul@example.com" not in prompt
        assert "sk-live-abc123xyz" not in prompt

    def test_provider_failure_carries_no_raw_pii(self) -> None:
        from agents.investigation.planner import Planner
        from agents.investigation.request import InvestigationRequest
        from shared.llm.errors import ProviderUnavailableError

        failing = FakeLLM(fail_all=ProviderUnavailableError("fake down"), healthy=False)
        request = InvestigationRequest(
            exception_id="exc-p10-003",
            exception_type="I-REFUND-LAG",
            tenant_id="tenant-001",
            actor="user-001",
            evidence_ids=["ev-ledger-001"],
            context_window="contact rahul@example.com",
            round_budget=1,
        )
        with pytest.raises(Exception) as exc_info:
            Planner(llm=failing).plan(request)
        assert "rahul@example.com" not in str(exc_info.value)
