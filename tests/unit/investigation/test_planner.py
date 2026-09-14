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


# ---------------------------------------------------------------------------
# D1: Tool Calling — additional gap tests
# ---------------------------------------------------------------------------


def test_subset_of_capabilities_selected(no_sockets: None) -> None:
    """Arrange plan with only 2 of 5 capabilities; Act; Assert accepted."""
    del no_sockets
    payload = _valid_payload()
    payload["capability_calls"] = [
        {"capability": "get_stripe_payment", "args": {"payment_id": "p1"}, "order_index": 0},
        {"capability": "search_gmail", "args": {"query": "refund"}, "order_index": 1},
    ]
    planner, _ = _fake_planner(payload)
    plan = planner.plan(_make_request())
    assert len(plan.capability_calls) == 2


def test_non_string_args_value_rejected(no_sockets: None) -> None:
    """Arrange args with int value; Act; Assert PlanRejectedError."""
    del no_sockets
    payload = _valid_payload()
    payload["capability_calls"] = [
        {"capability": "get_stripe_payment", "args": {"payment_id": 123}, "order_index": 0},
    ]
    planner, _ = _fake_planner(payload)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())


def test_order_index_mismatch_rejected_by_pydantic(no_sockets: None) -> None:
    """Arrange wrong order_index (2 instead of 0); Act; Assert PlannerError."""
    del no_sockets
    payload = _valid_payload()
    payload["capability_calls"] = [
        {"capability": "get_stripe_payment", "args": {"payment_id": "p1"}, "order_index": 2},
    ]
    planner, _ = _fake_planner(payload)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())


def test_empty_capability_calls_rejected(no_sockets: None) -> None:
    """Arrange zero capability calls; Act; Assert PlannerError."""
    del no_sockets
    payload = _valid_payload()
    payload["capability_calls"] = []
    planner, _ = _fake_planner(payload)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())


def test_blank_args_key_rejected_by_pydantic(no_sockets: None) -> None:
    """Arrange blank args key; Act; Assert PlannerError."""
    del no_sockets
    payload = _valid_payload()
    payload["capability_calls"] = [
        {"capability": "get_stripe_payment", "args": {"": "value"}, "order_index": 0},
    ]
    planner, _ = _fake_planner(payload)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())


def test_all_five_capabilities_in_order(no_sockets: None) -> None:
    """Arrange all 5 allowlisted capabilities; Act; Assert dense 0-4 ordering."""
    del no_sockets
    payload = _valid_payload()
    payload["capability_calls"] = [
        {"capability": "get_stripe_payment", "args": {"payment_id": "p1"}, "order_index": 0},
        {"capability": "get_stripe_refunds", "args": {"payment_id": "p1"}, "order_index": 1},
        {"capability": "get_qb_transaction", "args": {"entry_id": "e1"}, "order_index": 2},
        {"capability": "get_expected_state", "args": {"payment_id": "p1"}, "order_index": 3},
        {"capability": "search_gmail", "args": {"query": "receipt"}, "order_index": 4},
    ]
    planner, _ = _fake_planner(payload)
    plan = planner.plan(_make_request())
    assert len(plan.capability_calls) == 5
    assert [c.order_index for c in plan.capability_calls] == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# D2: Hypothesis Quality — additional gap tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hypothesis",
    [
        "Possible refund posting lag between processor and ledger.",
        "Suspected timing difference in settlement records.",
        "May be a fee calculation discrepancy.",
    ],
    ids=["possible", "suspected", "may-be"],
)
def test_hedging_hypothesis_accepted(no_sockets: None, hypothesis: str) -> None:
    """Arrange hedging wording; Act; Assert plan accepted."""
    del no_sockets
    planner, _ = _fake_planner(_valid_payload(hypothesis=hypothesis))
    plan = planner.plan(_make_request())
    assert plan.hypothesis_text == hypothesis


def test_escalation_true_accepted(no_sockets: None) -> None:
    """Arrange escalation=True; Act; Assert accepted with escalation flag."""
    del no_sockets
    payload = _valid_payload()
    payload["escalation"] = True
    planner, _ = _fake_planner(payload)
    plan = planner.plan(_make_request())
    assert plan.escalation is True


def test_hypothesis_at_max_length_accepted(no_sockets: None) -> None:
    """Arrange hypothesis at exactly MAX_HYPOTHESIS_CHARS; Act; Assert accepted."""
    del no_sockets
    hypothesis = "h" * MAX_HYPOTHESIS_CHARS
    planner, _ = _fake_planner(_valid_payload(hypothesis=hypothesis))
    plan = planner.plan(_make_request())
    assert len(plan.hypothesis_text) == MAX_HYPOTHESIS_CHARS


def test_hypothesis_one_over_max_rejected(no_sockets: None) -> None:
    """Arrange hypothesis at MAX+1 chars; Act; Assert PlannerError."""
    del no_sockets
    hypothesis = "h" * (MAX_HYPOTHESIS_CHARS + 1)
    planner, _ = _fake_planner(_valid_payload(hypothesis=hypothesis))
    with pytest.raises(PlannerError):
        planner.plan(_make_request())


def test_causal_hypothesis_without_authority_accepted(no_sockets: None) -> None:
    """Arrange causal verb without authoritative framing; Act; Assert accepted."""
    del no_sockets
    hypothesis = "Possible root cause is a refund posting delay."
    planner, _ = _fake_planner(_valid_payload(hypothesis=hypothesis))
    plan = planner.plan(_make_request())
    assert "root cause" in plan.hypothesis_text.lower()


# ---------------------------------------------------------------------------
# D3: Recall / Evidence — additional gap tests
# ---------------------------------------------------------------------------


def test_multiple_evidence_ids_all_in_request(no_sockets: None) -> None:
    """Arrange 2 evidence ids all in request; Act; Assert subset enforced."""
    del no_sockets
    payload = _valid_payload()
    payload["evidence_required"] = ["ev-ledger-001", "ev-processor-002"]
    request = _make_request(evidence_ids=("ev-ledger-001", "ev-processor-002"))
    planner, _ = _fake_planner(payload)
    plan = planner.plan(request)
    assert set(plan.evidence_required) <= set(request.evidence_ids)


def test_evidence_not_in_request_rejected(no_sockets: None) -> None:
    """Arrange evidence id not in request; Act; Assert PlanRejectedError."""
    del no_sockets
    payload = _valid_payload(evidence_id="ev-unknown-999")
    planner, _ = _fake_planner(payload)
    with pytest.raises(PlanRejectedError, match="outside the request set"):
        planner.plan(_make_request())


def test_overlong_evidence_id_rejected_by_pydantic(no_sockets: None) -> None:
    """Arrange evidence id >128 chars; Act; Assert PlannerError."""
    del no_sockets
    payload = _valid_payload(evidence_id="e" * 129)
    planner, _ = _fake_planner(payload)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())


def test_blank_evidence_id_rejected_by_pydantic(no_sockets: None) -> None:
    """Arrange blank evidence id; Act; Assert PlannerError."""
    del no_sockets
    payload = _valid_payload(evidence_id="   ")
    planner, _ = _fake_planner(payload)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())


def test_duplicate_evidence_ids_rejected_by_pydantic(no_sockets: None) -> None:
    """Arrange duplicate evidence ids; Act; Assert PlannerError."""
    del no_sockets
    payload = _valid_payload()
    payload["evidence_required"] = ["ev-ledger-001", "ev-ledger-001"]
    planner, _ = _fake_planner(payload)
    with pytest.raises(PlannerError):
        planner.plan(_make_request())


# ---------------------------------------------------------------------------
# D4: RAG / Context — additional gap tests
# ---------------------------------------------------------------------------


def test_empty_context_window_accepted(no_sockets: None) -> None:
    """Arrange empty context; Act; Assert valid plan produced."""
    del no_sockets
    request = InvestigationRequest(
        exception_id="exc-ctx-001",
        exception_type="I-REFUND-LAG",
        evidence_ids=("ev-ledger-001",),
        context_window="",
        round_budget=3,
    )
    planner, _ = _fake_planner(_valid_payload())
    plan = planner.plan(request)
    assert plan.hypothesis_text.strip()


def test_max_context_window_accepted(no_sockets: None) -> None:
    """Arrange 4000-char context; Act; Assert valid plan produced."""
    del no_sockets
    request = InvestigationRequest(
        exception_id="exc-ctx-002",
        exception_type="I-REFUND-LAG",
        evidence_ids=("ev-ledger-001",),
        context_window="x" * 4000,
        round_budget=3,
    )
    planner, _ = _fake_planner(_valid_payload())
    plan = planner.plan(request)
    assert plan.hypothesis_text.strip()


def test_context_truncation_flag_set(no_sockets: None) -> None:
    """Arrange 5000-char context; Act; Assert truncation flag and prompt note."""
    del no_sockets
    request = InvestigationRequest(
        exception_id="exc-ctx-003",
        exception_type="I-REFUND-LAG",
        evidence_ids=("ev-ledger-001",),
        context_window="x" * 5000,
        round_budget=3,
    )
    assert request.context_truncated is True
    assert len(request.context_window) == 4000
    prompt = render_investigation_prompt(request)
    assert "truncated" in prompt.user_prompt.lower()


def test_short_context_accepted(no_sockets: None) -> None:
    """Arrange 10-char context; Act; Assert valid plan produced."""
    del no_sockets
    request = InvestigationRequest(
        exception_id="exc-ctx-004",
        exception_type="I-REFUND-LAG",
        evidence_ids=("ev-ledger-001",),
        context_window="short ctx",
        round_budget=3,
    )
    planner, _ = _fake_planner(_valid_payload())
    plan = planner.plan(request)
    assert plan.hypothesis_text.strip()


def test_prompt_determinism_same_request(no_sockets: None) -> None:
    """Arrange two identical requests; Act render twice; Assert byte-identical."""
    del no_sockets
    request = _make_request()
    first = render_investigation_prompt(request)
    second = render_investigation_prompt(request)
    assert first == second
    assert first.user_prompt == second.user_prompt
    assert first.system_prompt == second.system_prompt


# ---------------------------------------------------------------------------
# D9: Adversarial — additional gap tests (extending existing coverage)
# ---------------------------------------------------------------------------


def test_verifier_garbage_never_raises() -> None:
    """Arrange garbage input; Act verify; Assert verdict returned, never raises."""
    from agents.verification.verdict import Verdict
    from agents.verification.verifier import Verifier

    verifier = Verifier()
    for garbage in [None, 123, "plan", [], {}, object()]:
        verdict = verifier.verify(garbage, frozenset({"ev-001"}), 0)
        assert isinstance(verdict, Verdict)


def test_executor_forbidden_url_rejected() -> None:
    """Arrange URL in args; Act execute; Assert ExecutorRejectedError."""
    from agents.capabilities.capabilities import AdapterBundle
    from agents.capabilities.executor import CapabilityExecutor
    from agents.capabilities.types import ExecutorRejectedError
    from finance.accounting.mock import MockQuickBooksAdapter
    from finance.reconciliation.ledger_resolution import InMemoryLedgerRepository

    bundle = AdapterBundle(
        stripe_payments={},
        qb_adapter=MockQuickBooksAdapter(),
        ledger_repository=InMemoryLedgerRepository.from_records([]),
        gmail_corpus={},
    )
    executor = CapabilityExecutor(bundle)
    bad_plan = _raw_plan_from_calls(
        [
            ("get_stripe_payment", {"payment_id": "https://evil.com/steal"}, 0),
        ]
    )
    with pytest.raises(ExecutorRejectedError, match="URL"):
        executor.execute(bad_plan, "tenant-acme")


def test_executor_sql_injection_rejected() -> None:
    """Arrange SQL injection in args; Act; Assert ExecutorRejectedError."""
    from agents.capabilities.capabilities import AdapterBundle
    from agents.capabilities.executor import CapabilityExecutor
    from agents.capabilities.types import ExecutorRejectedError
    from finance.accounting.mock import MockQuickBooksAdapter
    from finance.reconciliation.ledger_resolution import InMemoryLedgerRepository

    bundle = AdapterBundle(
        stripe_payments={},
        qb_adapter=MockQuickBooksAdapter(),
        ledger_repository=InMemoryLedgerRepository.from_records([]),
        gmail_corpus={},
    )
    executor = CapabilityExecutor(bundle)
    bad_plan = _raw_plan_from_calls(
        [
            ("get_stripe_payment", {"payment_id": "p1; DROP TABLE"}, 0),
        ]
    )
    with pytest.raises(ExecutorRejectedError, match="SQL"):
        executor.execute(bad_plan, "tenant-acme")


def test_executor_credential_pattern_rejected() -> None:
    """Arrange credential in args; Act; Assert ExecutorRejectedError."""
    from agents.capabilities.capabilities import AdapterBundle
    from agents.capabilities.executor import CapabilityExecutor
    from agents.capabilities.types import ExecutorRejectedError
    from finance.accounting.mock import MockQuickBooksAdapter
    from finance.reconciliation.ledger_resolution import InMemoryLedgerRepository

    bundle = AdapterBundle(
        stripe_payments={},
        qb_adapter=MockQuickBooksAdapter(),
        ledger_repository=InMemoryLedgerRepository.from_records([]),
        gmail_corpus={},
    )
    executor = CapabilityExecutor(bundle)
    bad_plan = _raw_plan_from_calls(
        [
            ("get_stripe_payment", {"payment_id": "sk-abc123secret"}, 0),
        ]
    )
    with pytest.raises(ExecutorRejectedError, match="credential"):
        executor.execute(bad_plan, "tenant-acme")


def test_executor_cross_tenant_rejected() -> None:
    """Arrange cross-tenant identifier; Act; Assert ExecutorRejectedError."""
    from agents.capabilities.capabilities import AdapterBundle
    from agents.capabilities.executor import CapabilityExecutor
    from agents.capabilities.types import ExecutorRejectedError
    from finance.accounting.mock import MockQuickBooksAdapter
    from finance.reconciliation.ledger_resolution import InMemoryLedgerRepository

    bundle = AdapterBundle(
        stripe_payments={},
        qb_adapter=MockQuickBooksAdapter(),
        ledger_repository=InMemoryLedgerRepository.from_records([]),
        gmail_corpus={},
    )
    executor = CapabilityExecutor(bundle)
    bad_plan = _raw_plan_from_calls(
        [
            ("get_stripe_payment", {"tenant_id": "other-tenant", "payment_id": "p1"}, 0),
        ]
    )
    with pytest.raises(ExecutorRejectedError, match="tenant"):
        executor.execute(bad_plan, "tenant-acme")


def _raw_plan_from_calls(
    calls: list[tuple[str, dict[str, str], int]],
) -> InvestigationPlan:
    """Build a plan via model_construct bypassing validation (adversarial)."""
    from agents.investigation.plan import CapabilityCall

    cc_calls = tuple(
        CapabilityCall.model_construct(capability=c, args=a, order_index=i) for c, a, i in calls
    )
    return InvestigationPlan.model_construct(
        hypothesis_text="adversarial probe",
        capability_calls=cc_calls,
        evidence_required=("ev-001",),
        escalation=False,
    )
