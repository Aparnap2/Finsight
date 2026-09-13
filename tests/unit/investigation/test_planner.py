"""P4.2 planner tests: typed plans, structural rejections, P3 fallback.

Covers the one-shot typed investigation planner over the injected LLM
seam: valid requests yield ordered typed plans, malformed or
out-of-policy candidates are rejected without executing anything, and
every planner failure leaves the deterministic P3 reconciliation path
usable. Fully deterministic: FakeLLM scripted payloads and stubbed
Groq transports only, real sockets disabled, no money arithmetic here
(Decimal legs appear solely in the P3-fallback fixture below).
"""

from __future__ import annotations

import ast
import json
import socket
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from agents.investigation.errors import PlannerError, PlanRejectedError
from agents.investigation.plan import (
    MAX_CAPABILITY_CALLS,
    MAX_HYPOTHESIS_CHARS,
    InvestigationPlan,
)
from agents.investigation.planner import Planner, render_investigation_prompt
from agents.investigation.request import InvestigationRequest
from finance.reconciliation.models import (
    ExceptionCode,
    MaterialityVerdict,
    PaymentRecord,
    PaymentStatus,
    ReconciliationOutcome,
)
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance
from shared.llm.errors import ProviderError, ProviderUnavailableError
from shared.llm.fake import FakeLLM
from shared.llm.groq import GroqProvider

_HYPOTHESIS = "Possible refund posting lag between processor and ledger records."
_NO_EXECUTION_ATTRS = (
    "execute",
    "execute_capability",
    "run_capability",
    "invoke",
    "call_api",
    "write_database",
    "read_database",
)


@pytest.fixture
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explode on any real socket or urlopen use (no network in these tests)."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network use forbidden in planner tests")

    monkeypatch.setattr(socket, "socket", _explode)
    monkeypatch.setattr(urllib.request, "urlopen", _explode)


def _make_request(
    evidence_ids: tuple[str, ...] = ("ev-ledger-001", "ev-processor-002"),
    allowlist: tuple[str, ...] | None = None,
) -> InvestigationRequest:
    """Assemble a valid deterministic planner request."""
    if allowlist is None:
        return InvestigationRequest(
            exception_id="exc-planner-001",
            exception_type="I-REFUND-LAG",
            evidence_ids=evidence_ids,
            context_window="refund posting lag probe",
            round_budget=3,
        )
    return InvestigationRequest(
        exception_id="exc-planner-001",
        exception_type="I-REFUND-LAG",
        evidence_ids=evidence_ids,
        context_window="refund posting lag probe",
        capability_allowlist=allowlist,
        round_budget=3,
    )


def _valid_payload(
    evidence_id: str = "ev-ledger-001",
    hypothesis: str = _HYPOTHESIS,
) -> dict[str, Any]:
    """Build a schema-valid candidate plan payload."""
    return {
        "hypothesis_text": hypothesis,
        "capability_calls": [
            {
                "capability": "get_stripe_payment",
                "args": {"payment_id": "pay_123"},
                "order_index": 0,
            },
            {
                "capability": "search_gmail",
                "args": {"query": "refund receipt"},
                "order_index": 1,
            },
        ],
        "evidence_required": [evidence_id],
        "escalation": False,
    }


def _fake_planner(payload: dict[str, Any] | str) -> tuple[Planner, FakeLLM]:
    """Bind a Planner to a FakeLLM scripted with ``payload``."""
    fake = FakeLLM(scripted={"InvestigationPlan": payload})
    return Planner(fake), fake


def _groq_planner(payload: dict[str, Any]) -> tuple[Planner, GroqProvider]:
    """Bind a Planner to a GroqProvider stubbed to return ``payload``."""
    content = json.dumps(payload)

    def _transport(
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
        timeout_s: float,
    ) -> dict[str, Any]:
        assert url.endswith("/chat/completions")
        assert body["model"] == "stub-model"
        assert headers["Authorization"].startswith("Bearer ")
        assert timeout_s > 0
        return {"choices": [{"message": {"content": content}}]}

    provider = GroqProvider(
        model="stub-model",
        base_url="https://stub.invalid",
        api_key="test-key",
        transport=_transport,
    )
    return Planner(provider), provider


def _leg(
    payment_id: str,
    gross: Decimal,
    fee: Decimal,
    refund: Decimal,
    net: Decimal,
) -> PaymentRecord:
    """Build one deterministic Decimal-only P3 fallback fixture leg."""
    return PaymentRecord(
        payment_id=payment_id,
        provider="stripe",
        provider_event_id=f"evt-{payment_id}",
        idempotency_key="key-planner-fallback",
        gross=gross,
        fee=fee,
        refund=refund,
        net=net,
        currency="USD",
        status=PaymentStatus.SETTLED,
        occurred_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        tenant_id="tenant-acme",
    )


def test_valid_request_yields_typed_plan_with_ordered_calls(
    no_sockets: None,
) -> None:
    """Arrange a valid request; Act plan via FakeLLM; Assert typed ordered plan."""
    del no_sockets
    request = _make_request()
    planner, fake = _fake_planner(_valid_payload())
    plan = planner.plan(request)
    assert isinstance(plan, InvestigationPlan)
    assert plan.hypothesis_text == _HYPOTHESIS
    assert [c.order_index for c in plan.capability_calls] == [0, 1]
    assert plan.capability_calls[0].capability == "get_stripe_payment"
    assert plan.capability_calls[0].args == {"payment_id": "pay_123"}
    assert plan.capability_calls[1].capability == "search_gmail"
    assert set(plan.evidence_required) <= set(request.evidence_ids)
    assert plan.escalation is False
    assert len(fake.journal) == 1
    assert fake.journal[0].success is True
    first = render_investigation_prompt(request)
    second = render_investigation_prompt(request)
    assert first == second


@pytest.mark.parametrize(
    "payload",
    ["not json at all", {"bogus": True}, {"hypothesis_text": 123}],
    ids=["non-json-string", "wrong-shape-dict", "wrong-field-type"],
)
def test_malformed_llm_output_raises_planner_error(
    no_sockets: None, payload: dict[str, Any] | str
) -> None:
    """Arrange bad provider output; Act plan; Assert PlannerError, no plan."""
    del no_sockets
    planner, fake = _fake_planner(payload)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())
    assert len(fake.journal) == 1
    assert fake.journal[0].success is False


def test_unknown_fields_rejected_as_planner_error(no_sockets: None) -> None:
    """Arrange extra field; Act plan; Assert boundary PlannerError, not silent."""
    del no_sockets
    payload = _valid_payload()
    payload["rogue_field"] = True
    planner, fake = _fake_planner(payload)
    with pytest.raises(PlannerError) as exc_info:
        planner.plan(_make_request())
    assert not isinstance(exc_info.value, PlanRejectedError)
    assert len(fake.journal) == 1
    assert fake.journal[0].success is False


def test_unsupported_capability_rejected_without_execution(
    no_sockets: None,
) -> None:
    """Arrange read_database call; Act plan; Assert rejected, one call, no exec."""
    del no_sockets
    payload = _valid_payload()
    payload["capability_calls"] = [
        {"capability": "read_database", "args": {"table": "ledger"}, "order_index": 0},
    ]
    planner, fake = _fake_planner(payload)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())
    assert len(fake.journal) == 1
    for attr in _NO_EXECUTION_ATTRS:
        assert not hasattr(planner, attr), f"planner must not expose {attr}"


def test_off_snapshot_capability_rejected_as_plan_rejected(
    no_sockets: None,
) -> None:
    """Arrange in-vocab call outside snapshot; Act; Assert PlanRejectedError."""
    del no_sockets
    request = _make_request(allowlist=("get_stripe_payment",))
    planner, fake = _fake_planner(_valid_payload())
    with pytest.raises(PlanRejectedError):
        planner.plan(request)
    assert len(fake.journal) == 1
    assert fake.journal[0].success is True


@pytest.mark.parametrize(
    "capability", ["write_database", "call_api"], ids=["write-database", "call-api"]
)
def test_write_like_capabilities_rejected(no_sockets: None, capability: str) -> None:
    """Arrange write-like call; Act plan; Assert rejected with a single call."""
    del no_sockets
    payload = _valid_payload()
    payload["capability_calls"] = [
        {"capability": capability, "args": {"target": "ledger"}, "order_index": 0},
    ]
    planner, fake = _fake_planner(payload)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())
    assert len(fake.journal) == 1


def test_unbounded_call_count_rejected(no_sockets: None) -> None:
    """Arrange nine ordered calls; Act plan; Assert rejected above the bound."""
    del no_sockets
    payload = _valid_payload()
    payload["capability_calls"] = [
        {
            "capability": "get_stripe_payment",
            "args": {"payment_id": f"pay_{i:03d}"},
            "order_index": i,
        }
        for i in range(MAX_CAPABILITY_CALLS + 1)
    ]
    planner, fake = _fake_planner(payload)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())
    assert len(fake.journal) == 1


@pytest.mark.parametrize("kind", ["too-many-args", "oversize-arg-value"])
def test_oversize_args_rejected(no_sockets: None, kind: str) -> None:
    """Arrange unbounded args mapping; Act plan; Assert PlannerError."""
    del no_sockets
    payload = _valid_payload()
    if kind == "too-many-args":
        payload["capability_calls"] = [
            {
                "capability": "get_stripe_payment",
                "args": {f"key_{i}": "value" for i in range(9)},
                "order_index": 0,
            },
        ]
    else:
        payload["capability_calls"] = [
            {
                "capability": "get_stripe_payment",
                "args": {"payment_id": "x" * 513},
                "order_index": 0,
            },
        ]
    planner, fake = _fake_planner(payload)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())
    assert len(fake.journal) == 1


def test_empty_evidence_required_rejected(no_sockets: None) -> None:
    """Arrange empty evidence_required; Act plan; Assert PlannerError."""
    del no_sockets
    payload = _valid_payload()
    payload["evidence_required"] = []
    planner, fake = _fake_planner(payload)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())
    assert len(fake.journal) == 1


@pytest.mark.parametrize("kind", ["empty", "overlong"])
def test_malformed_hypothesis_shape_rejected(no_sockets: None, kind: str) -> None:
    """Arrange blank/overlong hypothesis; Act plan; Assert PlannerError."""
    del no_sockets
    hypothesis = "" if kind == "empty" else "h" * (MAX_HYPOTHESIS_CHARS + 1)
    planner, fake = _fake_planner(_valid_payload(hypothesis=hypothesis))
    with pytest.raises(PlannerError):
        planner.plan(_make_request())
    assert len(fake.journal) == 1


@pytest.mark.parametrize(
    "hypothesis",
    [
        "The refund lag is verified in the ledger records.",
        "The refund cause is confirmed by the ledger records.",
        "Suspected drift of $150.00 between processor and ledger.",
        "Suspected drift of 150.00 between processor and ledger.",
    ],
    ids=["verified", "confirmed", "dollar-amount", "plain-amount"],
)
def test_authoritative_hypothesis_rejected(no_sockets: None, hypothesis: str) -> None:
    """Arrange authoritative wording; Act; Assert PlanRejectedError, never fixed."""
    del no_sockets
    planner, fake = _fake_planner(_valid_payload(hypothesis=hypothesis))
    with pytest.raises(PlanRejectedError):
        planner.plan(_make_request())
    assert len(fake.journal) == 1


def test_evidence_subset_enforced_unknown_id_rejected(no_sockets: None) -> None:
    """Arrange evidence outside request set; Act; Assert PlanRejectedError."""
    del no_sockets
    planner, fake = _fake_planner(_valid_payload(evidence_id="ev-unknown-999"))
    with pytest.raises(PlanRejectedError):
        planner.plan(_make_request())
    assert len(fake.journal) == 1


def test_claim_kinds_stay_hypothesis_side(no_sockets: None) -> None:
    """Arrange valid plan; Act; Assert no factual-claim markers in the output."""
    del no_sockets
    planner, fake = _fake_planner(_valid_payload())
    plan = planner.plan(_make_request())
    lowered = plan.hypothesis_text.lower()
    assert "verif" not in lowered
    assert "confirm" not in lowered
    assert "proven" not in lowered
    assert "factual" not in lowered
    assert set(InvestigationPlan.model_fields) == {
        "hypothesis_text",
        "capability_calls",
        "evidence_required",
        "escalation",
    }
    assert "VERIFIED" not in plan.model_dump_json()
    assert len(fake.journal) == 1


def test_causal_hypothesis_never_becomes_verified_fact(no_sockets: None) -> None:
    """Arrange causal hypothesis; Act; Assert no verified-state flags in output."""
    del no_sockets
    hypothesis = "Possible cause is refund lag; needs evidence review to decide."
    planner, _ = _fake_planner(_valid_payload(hypothesis=hypothesis))
    plan = planner.plan(_make_request())
    dumped = plan.model_dump_json()
    assert "EVIDENCE_VERIFIED" not in dumped
    assert "EXECUTION_VERIFIED" not in dumped
    assert "VERIFIED" not in plan.hypothesis_text.upper()


def test_bounded_plan_size_max_eight_calls(no_sockets: None) -> None:
    """Arrange eight ordered calls; Act; Assert accepted at exactly the bound."""
    del no_sockets
    assert MAX_CAPABILITY_CALLS == 8
    payload = _valid_payload()
    payload["capability_calls"] = [
        {
            "capability": "get_stripe_payment",
            "args": {"payment_id": f"pay_{i:03d}"},
            "order_index": i,
        }
        for i in range(MAX_CAPABILITY_CALLS)
    ]
    planner, _ = _fake_planner(payload)
    plan = planner.plan(_make_request())
    assert len(plan.capability_calls) == MAX_CAPABILITY_CALLS
    assert [c.order_index for c in plan.capability_calls] == list(range(8))


def test_provider_failure_propagates_as_planner_error(no_sockets: None) -> None:
    """Arrange failing unhealthy provider; Act; Assert caller-visible PlannerError."""
    del no_sockets
    fake = FakeLLM(fail_all=ProviderUnavailableError("fake down"), healthy=False)
    planner = Planner(fake)
    assert fake.health_check().ok is False
    with pytest.raises(PlannerError) as exc_info:
        planner.plan(_make_request())
    assert isinstance(exc_info.value.__cause__, ProviderError)
    assert len(fake.journal) == 1
    assert fake.journal[0].success is False
    assert fake.journal[0].error_kind == "ProviderUnavailableError"


def test_groq_transport_failure_maps_to_planner_error(no_sockets: None) -> None:
    """Arrange stub transport failure; Act; Assert PlannerError with no sockets."""
    del no_sockets

    def _failing_transport(
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
        timeout_s: float,
    ) -> dict[str, Any]:
        raise TimeoutError("stub transport down")

    provider = GroqProvider(
        model="stub-model",
        base_url="https://stub.invalid",
        api_key="test-key",
        timeout_s=1.0,
        max_retries=1,
        transport=_failing_transport,
    )
    planner = Planner(provider)
    with pytest.raises(PlannerError) as exc_info:
        planner.plan(_make_request())
    assert not isinstance(exc_info.value, PlanRejectedError)
    assert len(provider.call_log) == 1
    assert provider.call_log[-1].success is False


def test_deterministic_fallback_reconciles_after_planner_failure(
    no_sockets: None,
) -> None:
    """Arrange planner failure; Act P3 reconcile; Assert P3 path stays usable."""
    del no_sockets
    fake = FakeLLM(fail_all=ProviderUnavailableError("fake down"))
    planner = Planner(fake)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())
    processor = _leg(
        "proc-flagship",
        Decimal("50000.00"),
        Decimal("0.00"),
        Decimal("15000.00"),
        Decimal("35000.00"),
    )
    ledger = _leg(
        "ledger-flagship",
        Decimal("50000.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("50000.00"),
    )
    tolerance = ReconciliationTolerance()
    first = reconcile(processor, ledger, tolerance)
    second = reconcile(processor, ledger, tolerance)
    assert first == second
    assert first.outcome is ReconciliationOutcome.EXCEPTION
    assert first.exception_code == ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG.value
    assert first.difference == Decimal("15000.00")
    assert first.materiality is MaterialityVerdict.MATERIAL


def _imported_roots(source_path: Path) -> set[str]:
    """Collect top-level import roots from a source file via AST."""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_zero_p3_mutation_forbidden_import_scan() -> None:
    """Arrange planner sources; Act AST scan; Assert no finance/apps/frameworks."""
    package = Path(__file__).resolve().parents[3] / "agents" / "investigation"
    for module in ("planner.py", "plan.py", "request.py", "errors.py"):
        roots = _imported_roots(package / module)
        assert "finance" not in roots, f"{module} must not import finance"
        assert "apps" not in roots, f"{module} must not import apps"
    planner_roots = _imported_roots(package / "planner.py")
    for banned in ("langchain", "litellm", "groq", "openai", "httpx", "requests"):
        assert banned not in planner_roots
    planner = Planner(FakeLLM(scripted={"InvestigationPlan": _valid_payload()}))
    for attr in _NO_EXECUTION_ATTRS:
        assert not hasattr(planner, attr), f"planner must not expose {attr}"


def test_provider_independence_fake_and_groq_yield_equal_plans(
    no_sockets: None,
) -> None:
    """Arrange same payload on both seams; Act plan twice; Assert equal plans."""
    del no_sockets
    payload = _valid_payload()
    request = _make_request()
    fake_planner, _ = _fake_planner(dict(payload))
    groq_planner, _ = _groq_planner(dict(payload))
    assert fake_planner.plan(request) == groq_planner.plan(request)
