"""Controlled P4.5 orchestrator E2E (FakeLLM primary, no network, zero mutation).

Covers: replan->accept with/without proposal, budget exhausted HITL,
parity FakeLLM/Groq stub, zero-mutation guards (AST + P1 reconcile +
no state/approval/execution/CLOSED), provider failure, executor
rejection as bounded replan. AAA, typed, deterministic, 100-col.
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

from agents.capabilities.capabilities import AdapterBundle
from agents.capabilities.executor import CapabilityExecutor
from agents.investigation.plan import InvestigationPlan
from agents.investigation.request import InvestigationRequest
from agents.orchestrator.orchestrator import InvestigateOrchestrator
from agents.verification.verifier import Verifier
from finance.accounting.mock import MockQuickBooksAdapter
from finance.exceptions.aggregate import ExceptionAggregate
from finance.exceptions.states import ExceptionState
from finance.proposals.builder import build_proposal
from finance.reconciliation.ledger_resolution import InMemoryLedgerRepository
from finance.reconciliation.models import (
    ExceptionCode,
    PaymentRecord,
    PaymentStatus,
)
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance
from shared.llm.errors import ProviderUnavailableError
from shared.llm.fake import FakeLLM
from shared.llm.groq import GroqProvider
from shared.llm.provider import validate_structured_output
from shared.llm.types import InvestigationPrompt, ModelMetadata, ProviderCallLog, ProviderHealth

_TENANT = "tenant-acme"
_EVIDENCE = ("ev-1", "ev-2")
_EXCEPTION_ID = "exc-orch-001"
_RECON_ID = "recon-orch-001"
_AT = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
_HYPOTHESIS = "Possible refund lag between processor and ledger records."
_TOLERANCE = ReconciliationTolerance(absolute=Decimal("0.00"), percent=Decimal("0.00"))


@pytest.fixture
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block live sockets and urlopen for deterministic offline runs."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network forbidden in e2e orchestrator tests")

    monkeypatch.setattr(socket, "socket", _explode)
    monkeypatch.setattr(urllib.request, "urlopen", _explode)


def _make_request(
    evidence_ids: tuple[str, ...] = _EVIDENCE,
    exception_id: str = _EXCEPTION_ID,
) -> InvestigationRequest:
    """Build a valid frozen investigation request."""
    return InvestigationRequest(
        exception_id=exception_id,
        exception_type=ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG.value,
        evidence_ids=evidence_ids,
        context_window="refund lag probe",
        round_budget=3,
    )


def _valid_payload(
    evidence_id: str = "ev-1",
    hypothesis: str = _HYPOTHESIS,
) -> dict[str, Any]:
    """Return a schema-valid grounded candidate plan payload."""
    return {
        "hypothesis_text": hypothesis,
        "capability_calls": [
            {
                "capability": "get_stripe_payment",
                "args": {"payment_id": "pay_123"},
                "order_index": 0,
            },
        ],
        "evidence_required": [evidence_id],
        "escalation": False,
    }


def _verified_wording_payload() -> dict[str, Any]:
    """Payload that planner flags: authoritative wording (verified)."""
    return _valid_payload(
        hypothesis="The refund lag is verified in the ledger records.",
    )


def _credential_payload() -> dict[str, Any]:
    """Valid-for-verifier but executor-rejected via credential pattern."""
    return {
        "hypothesis_text": _HYPOTHESIS,
        "capability_calls": [
            {
                "capability": "get_stripe_payment",
                "args": {"payment_id": "pay_123", "note": "api_key sk-12345"},
                "order_index": 0,
            },
        ],
        "evidence_required": ["ev-1"],
        "escalation": False,
    }


def _payment_record(
    payment_id: str,
    gross: Decimal,
    fee: Decimal,
    refund: Decimal,
    net: Decimal,
    *,
    tenant_id: str = _TENANT,
) -> PaymentRecord:
    """Build a deterministic Decimal-only payment leg fixture."""
    return PaymentRecord(
        payment_id=payment_id,
        provider="stripe",
        provider_event_id=f"evt-{payment_id}",
        idempotency_key=f"idem-{payment_id}",
        gross=gross,
        fee=fee,
        refund=refund,
        net=net,
        currency="USD",
        status=PaymentStatus.SETTLED,
        occurred_at=_AT,
        tenant_id=tenant_id,
    )


def _bundle_with_payment(
    payment_id: str = "pay_123",
    tenant_id: str = _TENANT,
) -> tuple[AdapterBundle, MockQuickBooksAdapter]:
    """Build a minimal deterministic read-only bundle for the executor."""
    from finance.stripe.adapter import payment_from_charge

    charge = {
        "id": "evt-charge-1",
        "type": "charge.succeeded",
        "created": 1750000000,
        "data": {
            "object": {
                "id": payment_id,
                "amount": 10000,
                "currency": "usd",
                "created": 1750000000,
                "application_fee_amount": 250,
            }
        },
    }
    payment = payment_from_charge(charge, tenant_id=tenant_id)
    adapter = MockQuickBooksAdapter()
    repo = InMemoryLedgerRepository.from_records([payment.to_record()])
    # Ensure stripe_payments seeded for get_stripe_payment capability.
    bundle = AdapterBundle(
        stripe_payments={(tenant_id, payment_id): payment},
        qb_adapter=adapter,
        ledger_repository=repo,
        gmail_corpus={},
    )
    return bundle, adapter


def _proposal_snapshot_and_records() -> tuple[ExceptionAggregate, tuple[PaymentRecord, ...]]:
    """Build a sealed snapshot at EVIDENCE_VERIFIED and canonical legs."""
    agg = ExceptionAggregate.create(
        exception_id=_EXCEPTION_ID,
        tenant_id=_TENANT,
        reconciliation_result_id=_RECON_ID,
        exception_type=ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG,
        severity="HIGH",
        created_at=_AT,
    )
    agg = agg.transition_to(ExceptionState.INVESTIGATING, agg.state_version, actor="t")
    agg = agg.transition_to(
        ExceptionState.EVIDENCE_READY, agg.state_version, actor="t", evidence_ids=list(_EVIDENCE)
    )
    agg = agg.transition_to(ExceptionState.EVIDENCE_VERIFIED, agg.state_version, actor="t")
    # Canonical legs: processor net 35000 vs stale 50000 diff 15000
    processor = _payment_record(
        "pay-proc-50k",
        Decimal("50000.00"),
        Decimal("0.00"),
        Decimal("15000.00"),
        Decimal("35000.00"),
    )
    ledger = _payment_record(
        "pay-ledger-50k",
        Decimal("50000.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("50000.00"),
    )
    # Ensure same payment id semantics not required; builder checks tenant/currency only.
    # For proposal diff it uses net diff, so align tenant and currency.
    # The stripe adapter fold uses pay_123; keep proposal legs distinct.
    return agg, (processor, ledger)


def _processor_ledger_for_p1() -> tuple[PaymentRecord, PaymentRecord]:
    """Return processor/ledger legs for P1 zero-mutation oracle."""
    processor = _payment_record(
        "pay-p1-proc",
        Decimal("50000.00"),
        Decimal("0.00"),
        Decimal("15000.00"),
        Decimal("35000.00"),
    )
    ledger = _payment_record(
        "pay-p1-ledger",
        Decimal("50000.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("50000.00"),
    )
    return processor, ledger


class _SequencedFakeLLM:
    """Scripted LLMProvider that dequeues a payload per generate_structured call."""

    def __init__(
        self,
        payloads: list[dict[str, Any] | str],
        *,
        healthy: bool = True,
        model: str = "fake-seq",
        failures: list[BaseException | None] | None = None,
    ) -> None:
        self._payloads = list(payloads)
        self._failures = list(failures) if failures is not None else [None] * len(payloads)
        self._healthy = healthy
        self._model = model
        self._cursor = 0
        self.journal: list[ProviderCallLog] = []
        self.call_journal = self.journal

    def health_check(self) -> ProviderHealth:
        """Return scripted liveness without network."""
        if self._healthy:
            return ProviderHealth(ok=True, latency_ms=0.0)
        return ProviderHealth(ok=False, latency_ms=0.0, reason="fake unhealthy")

    def model_metadata(self) -> ModelMetadata:
        """Return fake model identity."""
        return ModelMetadata(provider="fake", model=self._model)

    def generate_structured[T: Any](  # type: ignore[no-untyped-def]
        self, prompt: InvestigationPrompt | str, response_schema: type[T]
    ) -> T:
        """Return the next queued payload after strict boundary validation."""
        # Keep input_chars accounting similar to FakeLLM for audit.
        input_chars = (
            len(prompt.user_prompt) + len(prompt.system_prompt)
            if isinstance(prompt, InvestigationPrompt)
            else len(str(prompt))
        )
        idx = self._cursor
        self._cursor += 1
        # Determine if this slot is a scripted failure.
        failure: BaseException | None = None
        if idx < len(self._failures):
            failure = self._failures[idx]
        if failure is not None:
            self.journal.append(
                ProviderCallLog(
                    provider="fake",
                    model=self._model,
                    success=False,
                    latency_ms=0.0,
                    input_chars=input_chars,
                    output_chars=None,
                    error_kind=type(failure).__name__,
                )
            )
            raise failure
        payload = self._payloads[-1] if idx >= len(self._payloads) else self._payloads[idx]  # noqa: SIM108
        try:
            result = validate_structured_output(payload, response_schema)
        except Exception as exc:  # noqa: BLE001
            self.journal.append(
                ProviderCallLog(
                    provider="fake",
                    model=self._model,
                    success=False,
                    latency_ms=0.0,
                    input_chars=input_chars,
                    output_chars=len(str(payload)) if isinstance(payload, str) else None,
                    error_kind=type(exc).__name__,
                )
            )
            raise
        self.journal.append(
            ProviderCallLog(
                provider="fake",
                model=self._model,
                success=True,
                latency_ms=0.0,
                input_chars=input_chars,
                output_chars=len(str(payload)),
                error_kind=None,
            )
        )
        return result


def _groq_single_payload_transport(
    payload: dict[str, Any],
) -> Any:
    """Return a transport stub that always returns ``payload`` as JSON."""

    def _transport(  # noqa: E501
        url: str, body: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        assert url.endswith("/chat/completions")
        assert body["model"] == "stub-model"
        assert headers["Authorization"].startswith("Bearer ")
        assert timeout > 0
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    return _transport


def _groq_sequenced_transport(
    payloads: list[dict[str, Any]],
) -> Any:
    """Return a transport that dequeues payloads per call."""

    cursor = {"idx": 0}

    def _transport(  # noqa: E501
        url: str, body: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        assert url.endswith("/chat/completions")
        idx = cursor["idx"]
        cursor["idx"] += 1
        chosen = payloads[-1] if idx >= len(payloads) else payloads[idx]  # noqa: SIM108
        return {"choices": [{"message": {"content": json.dumps(chosen)}}]}

    return _transport


def _assert_zero_mutations(
    before_result: Any,
    after_result: Any,
    adapter_before: int,
    adapter_after: int,
    snapshot_before: ExceptionAggregate | None,
    snapshot_after: ExceptionAggregate | None,
    orch_result: Any,
) -> None:
    """Assert zero financial/P3/approval/execution/CLOSED mutations (AAA assert)."""
    # P1 reconcile identical
    assert before_result == after_result
    # No finance mutation: adapter entry count unchanged, no new writes
    assert adapter_after == adapter_before
    # P3 state mutations ==0 if snapshot supplied
    if snapshot_before is not None and snapshot_after is not None:
        assert snapshot_after.state == snapshot_before.state
        assert snapshot_after.state_version == snapshot_before.state_version
        assert snapshot_after.evidence_ids == snapshot_before.evidence_ids
    # Approvals/execution records ==0: orchestrator never creates them
    assert orch_result.proposal_candidate is None or orch_result.proposal_candidate.version == 1
    # CLOSED never emitted by orchestrator (status is ACCEPTED_CANDIDATE or HITL)
    assert orch_result.status != "CLOSED"
    assert orch_result.status in (  # noqa: E501
        "ACCEPTED_CANDIDATE",
        "REPLAN_EXHAUSTED_HITL",
        "PROVIDER_FAILURE_HITL",
    )


# ---------------------------------------------------------------------------
# 1. REJECTED_REPLAN -> ACCEPTED with and without proposal
# ---------------------------------------------------------------------------


def test_rejected_then_accepted_without_proposal_yields_candidate(
    no_sockets: None,
) -> None:
    """Arrange invalid then valid payload; Act run; Assert ACCEPTED_CANDIDATE."""
    # Arrange.
    del no_sockets
    processor, ledger = _processor_ledger_for_p1()
    before = reconcile(processor, ledger, _TOLERANCE)
    bundle, adapter = _bundle_with_payment()
    adapter_before = adapter.entry_count
    verifier = Verifier(max_replans=2)
    executor = CapabilityExecutor(bundle)
    seq = _SequencedFakeLLM([_verified_wording_payload(), _valid_payload()])
    orch = InvestigateOrchestrator(seq, executor, verifier)
    request = _make_request()
    # Act.
    result = orch.run(request, _TENANT)
    # Assert.
    assert result.status == "ACCEPTED_CANDIDATE"
    assert result.attempts == 2
    assert len(result.verdicts) == 2
    assert result.verdicts[0].status == "REJECTED_REPLAN"
    assert result.verdicts[1].status == "ACCEPTED"
    assert result.plan is not None
    assert isinstance(result.plan, InvestigationPlan)
    assert len(result.capability_outcomes) == 1
    assert result.proposal_candidate is None
    assert result.hitl_reason is None
    after = reconcile(processor, ledger, _TOLERANCE)
    _assert_zero_mutations(before, after, adapter_before, adapter.entry_count, None, None, result)


def test_rejected_then_accepted_with_proposal_yields_versioned_hash(
    no_sockets: None,
) -> None:
    """Arrange invalid then valid; Act with snapshot+records; Assert Proposal fields."""
    # Arrange.
    del no_sockets
    processor, ledger = _processor_ledger_for_p1()
    before = reconcile(processor, ledger, _TOLERANCE)
    bundle, adapter = _bundle_with_payment()
    adapter_before = adapter.entry_count
    snapshot, records = _proposal_snapshot_and_records()
    snapshot_before = snapshot
    verifier = Verifier(max_replans=2)
    executor = CapabilityExecutor(bundle)
    seq = _SequencedFakeLLM([_verified_wording_payload(), _valid_payload(evidence_id="ev-1")])
    orch = InvestigateOrchestrator(seq, executor, verifier, proposal_builder=build_proposal)
    request = _make_request(evidence_ids=_EVIDENCE)
    # Act.
    result = orch.run(request, _TENANT, exception_snapshot=snapshot, canonical_records=records)
    # Assert.
    assert result.status == "ACCEPTED_CANDIDATE"
    assert result.attempts == 2
    assert result.verdicts[0].status == "REJECTED_REPLAN"
    assert result.verdicts[1].status == "ACCEPTED"
    assert result.plan is not None
    assert len(result.capability_outcomes) == 1
    proposal = result.proposal_candidate
    assert proposal is not None
    assert proposal.exception_id == _EXCEPTION_ID
    assert proposal.version == 1
    assert proposal.requires_hitl is True
    assert proposal.supersedes is None
    assert isinstance(proposal.amount, Decimal)
    assert proposal.amount == Decimal("15000.00")
    assert proposal.verifies() is True
    assert len(proposal.content_hash) == 64
    assert proposal.evidence_ids == result.plan.evidence_required  # type: ignore[union-attr]
    after = reconcile(processor, ledger, _TOLERANCE)
    _assert_zero_mutations(
        before, after, adapter_before, adapter.entry_count, snapshot_before, snapshot, result
    )


# ---------------------------------------------------------------------------
# 2. Budget exhausted -> HITL, no capability execution
# ---------------------------------------------------------------------------


def test_budget_exhausted_hitl_includes_budget_exhausted(
    no_sockets: None,
) -> None:
    """Arrange 3 rejects with budget 2; Act; Assert HITL with budget_exhausted."""
    # Arrange.
    del no_sockets
    processor, ledger = _processor_ledger_for_p1()
    before = reconcile(processor, ledger, _TOLERANCE)
    bundle, adapter = _bundle_with_payment()
    adapter_before = adapter.entry_count
    verifier = Verifier(max_replans=2)
    executor = CapabilityExecutor(bundle)
    # Three invalid payloads: each will be planner-rejected (verified wording).
    seq = _SequencedFakeLLM(
        [_verified_wording_payload(), _verified_wording_payload(), _verified_wording_payload()]
    )
    orch = InvestigateOrchestrator(seq, executor, verifier)
    request = _make_request()
    # Act.
    result = orch.run(request, _TENANT)
    # Assert.
    assert result.status == "REPLAN_EXHAUSTED_HITL"
    assert result.attempts == 3
    assert len(result.verdicts) == 3
    assert all(v.status in ("REJECTED_REPLAN", "ESCALATE_HITL") for v in result.verdicts)
    # Last verdict carries budget_exhausted marker (verifier escalates) or hitl_reason does.
    last_reasons = " ".join(result.verdicts[-1].reasons)
    assert "budget_exhausted" in last_reasons or "budget exhausted" in (result.hitl_reason or "")
    assert result.capability_outcomes == ()
    assert result.proposal_candidate is None
    assert result.hitl_reason is not None
    after = reconcile(processor, ledger, _TOLERANCE)
    _assert_zero_mutations(before, after, adapter_before, adapter.entry_count, None, None, result)


# ---------------------------------------------------------------------------
# 3. Parity FakeLLM vs Groq stub
# ---------------------------------------------------------------------------


def test_parity_fake_and_groq_yield_equal_results(
    no_sockets: None,
) -> None:
    """Arrange same scripted payload; Act via Fake and Groq; Assert equal results."""
    # Arrange.
    del no_sockets
    processor, ledger = _processor_ledger_for_p1()
    before = reconcile(processor, ledger, _TOLERANCE)
    payload = _valid_payload()
    request = _make_request()
    # Fake path.
    bundle_f, adapter_f = _bundle_with_payment()
    verifier = Verifier(max_replans=2)
    executor_f = CapabilityExecutor(bundle_f)
    fake = FakeLLM(scripted={"InvestigationPlan": payload})
    orch_f = InvestigateOrchestrator(fake, executor_f, verifier)
    before_f = adapter_f.entry_count
    # Groq path.
    bundle_g, adapter_g = _bundle_with_payment()
    executor_g = CapabilityExecutor(bundle_g)
    groq = GroqProvider(
        model="stub-model",
        base_url="https://stub.invalid",
        api_key="test-key",
        transport=_groq_single_payload_transport(payload),
    )
    # Health probe uses live urlopen (blocked by no_sockets); stub it to healthy.
    groq.health_check = lambda: ProviderHealth(ok=True, latency_ms=0.0)  # type: ignore[method-assign]
    orch_g = InvestigateOrchestrator(groq, executor_g, verifier)
    before_g = adapter_g.entry_count
    # Act.
    result_f = orch_f.run(request, _TENANT)
    result_g = orch_g.run(request, _TENANT)
    # Assert.
    assert result_f.status == result_g.status == "ACCEPTED_CANDIDATE"
    assert result_f.attempts == result_g.attempts == 1
    assert result_f.verdicts == result_g.verdicts
    assert result_f.plan == result_g.plan
    assert len(result_f.capability_outcomes) == len(result_g.capability_outcomes) == 1
    assert result_f.capability_outcomes[0].capability == result_g.capability_outcomes[0].capability
    assert result_f.proposal_candidate == result_g.proposal_candidate is None
    after = reconcile(processor, ledger, _TOLERANCE)
    _assert_zero_mutations(before, after, before_f, adapter_f.entry_count, None, None, result_f)
    _assert_zero_mutations(before, after, before_g, adapter_g.entry_count, None, None, result_g)


# ---------------------------------------------------------------------------
# 4. Zero-mutation guards (also AST scan)
# ---------------------------------------------------------------------------


def test_orchestrator_imports_no_finance_execution_or_apps() -> None:
    """Arrange orchestrator source; Act AST scan; Assert no forbidden imports."""
    # Arrange.
    path = Path(__file__).resolve().parents[2] / "agents" / "orchestrator" / "orchestrator.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # Act.
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    # Assert.
    assert modules, "expected orchestrator imports to scan"
    assert (
        not [  # noqa: E501
            m for m in modules if m == "finance.execution" or m.startswith("finance.execution.")
        ]
    )
    assert (
        not [  # noqa: E501
            m for m in modules if m == "finance.approvals" or m.startswith("finance.approvals.")
        ]
    )
    assert not [m for m in modules if m == "apps" or m.startswith("apps.")]
    # Also ensure status never equals CLOSED string literal in types.
    types_path = Path(__file__).resolve().parents[2] / "agents" / "orchestrator" / "types.py"
    types_src = types_path.read_text(encoding="utf-8")
    assert '"CLOSED"' not in types_src
    assert "'CLOSED'" not in types_src


def test_zero_mutation_guard_after_every_run_via_p1_oracle(
    no_sockets: None,
) -> None:
    """Arrange run; Act; Assert P1 oracle identical and no state mutation."""
    # Arrange.
    del no_sockets
    processor, ledger = _processor_ledger_for_p1()
    before = reconcile(processor, ledger, _TOLERANCE)
    bundle, adapter = _bundle_with_payment()
    adapter_before = adapter.entry_count
    snapshot, _ = _proposal_snapshot_and_records()
    snapshot_before_version = snapshot.state_version
    snapshot_before_state = snapshot.state
    verifier = Verifier(max_replans=2)
    executor = CapabilityExecutor(bundle)
    fake = FakeLLM(scripted={"InvestigationPlan": _valid_payload()})
    orch = InvestigateOrchestrator(fake, executor, verifier)
    request = _make_request()
    # Act.
    result = orch.run(request, _TENANT, exception_snapshot=snapshot, canonical_records=None)
    # Assert.
    after = reconcile(processor, ledger, _TOLERANCE)
    assert before == after
    assert adapter.entry_count == adapter_before
    assert snapshot.state_version == snapshot_before_version
    assert snapshot.state == snapshot_before_state
    assert result.status == "ACCEPTED_CANDIDATE"
    assert result.status != "CLOSED"


# ---------------------------------------------------------------------------
# 5. Provider failure path
# ---------------------------------------------------------------------------


def test_provider_unhealthy_returns_provider_failure_hitl(
    no_sockets: None,
) -> None:
    """Arrange unhealthy FakeLLM; Act; Assert PROVIDER_FAILURE_HITL with 0 attempts."""
    # Arrange.
    del no_sockets
    processor, ledger = _processor_ledger_for_p1()
    before = reconcile(processor, ledger, _TOLERANCE)
    bundle, adapter = _bundle_with_payment()
    adapter_before = adapter.entry_count
    verifier = Verifier(max_replans=2)
    executor = CapabilityExecutor(bundle)
    fake = FakeLLM(healthy=False, scripted={"InvestigationPlan": _valid_payload()})
    orch = InvestigateOrchestrator(fake, executor, verifier)
    request = _make_request()
    # Act.
    result = orch.run(request, _TENANT)
    # Assert.
    assert result.status == "PROVIDER_FAILURE_HITL"
    assert result.attempts == 0
    assert result.plan is None
    assert result.capability_outcomes == ()
    assert result.hitl_reason is not None
    assert "provider" in result.hitl_reason.lower()
    after = reconcile(processor, ledger, _TOLERANCE)
    _assert_zero_mutations(before, after, adapter_before, adapter.entry_count, None, None, result)


def test_provider_timeout_maps_to_hitl_without_infinite_loop(
    no_sockets: None,
) -> None:
    """Arrange transport TimeoutError; Act; Assert HITL bounded without loop."""
    # Arrange.
    del no_sockets
    processor, ledger = _processor_ledger_for_p1()
    before = reconcile(processor, ledger, _TOLERANCE)
    bundle, adapter = _bundle_with_payment()
    adapter_before = adapter.entry_count
    verifier = Verifier(max_replans=2)
    executor = CapabilityExecutor(bundle)
    # FakeLLM that raises ProviderUnavailableError (TimeoutError maps to this).
    seq = _SequencedFakeLLM(
        [_valid_payload(), _valid_payload(), _valid_payload()],
        failures=[
            ProviderUnavailableError("stub timeout"),
            ProviderUnavailableError("stub timeout"),
            ProviderUnavailableError("stub timeout"),
        ],
    )
    orch = InvestigateOrchestrator(seq, executor, verifier)
    request = _make_request()
    # Act.
    result = orch.run(request, _TENANT)
    # Assert.
    assert result.status in ("REPLAN_EXHAUSTED_HITL", "PROVIDER_FAILURE_HITL")
    assert result.attempts == 3  # budget 2 => 3 attempts, bounded
    assert result.capability_outcomes == ()
    assert result.proposal_candidate is None
    assert result.hitl_reason is not None
    after = reconcile(processor, ledger, _TOLERANCE)
    _assert_zero_mutations(before, after, adapter_before, adapter.entry_count, None, None, result)


def test_groq_transport_timeout_maps_to_hitl(
    no_sockets: None,
) -> None:
    """Arrange Groq transport TimeoutError; Act; Assert HITL bounded."""
    # Arrange.
    del no_sockets
    processor, ledger = _processor_ledger_for_p1()
    before = reconcile(processor, ledger, _TOLERANCE)
    bundle, adapter = _bundle_with_payment()
    adapter_before = adapter.entry_count
    verifier = Verifier(max_replans=2)
    executor = CapabilityExecutor(bundle)

    def _failing_transport(  # noqa: E501
        url: str, body: dict[str, Any], headers: dict[str, str], timeout: float
    ) -> dict[str, Any]:
        raise TimeoutError("groq stub timeout")

    groq = GroqProvider(
        model="stub-model",
        base_url="https://stub.invalid",
        api_key="test-key",
        transport=_failing_transport,
        max_retries=1,
    )
    orch = InvestigateOrchestrator(groq, executor, verifier)
    request = _make_request()
    # Act.
    result = orch.run(request, _TENANT)
    # Assert.
    assert result.status in ("REPLAN_EXHAUSTED_HITL", "PROVIDER_FAILURE_HITL")
    assert result.attempts <= 3
    assert result.capability_outcomes == ()
    after = reconcile(processor, ledger, _TOLERANCE)
    _assert_zero_mutations(before, after, adapter_before, adapter.entry_count, None, None, result)


# ---------------------------------------------------------------------------
# 6. Executor whole-run rejection as bounded replan
# ---------------------------------------------------------------------------


def test_executor_rejection_treated_as_replan_bounded(
    no_sockets: None,
) -> None:
    """Arrange executor rejects via credential smuggle; Act; Assert replan then accept."""
    # Arrange.
    del no_sockets
    processor, ledger = _processor_ledger_for_p1()
    before = reconcile(processor, ledger, _TOLERANCE)
    bundle, adapter = _bundle_with_payment()
    adapter_before = adapter.entry_count
    verifier = Verifier(max_replans=2)
    executor = CapabilityExecutor(bundle)
    seq = _SequencedFakeLLM([_credential_payload(), _valid_payload()])
    orch = InvestigateOrchestrator(seq, executor, verifier)
    request = _make_request()
    # Act.
    result = orch.run(request, _TENANT)
    # Assert.
    assert result.status == "ACCEPTED_CANDIDATE"
    assert result.attempts == 2
    # First verdict ACCEPTED (verifier passed), second is executor_rejected REJECTED,
    # third is ACCEPTED after valid payload. Total verdicts = 3 (including executor).
    assert len(result.verdicts) == 3
    assert result.verdicts[0].status == "ACCEPTED"
    assert result.verdicts[1].status == "REJECTED_REPLAN"
    assert "executor_rejected" in result.verdicts[1].reasons[0]
    assert result.verdicts[2].status == "ACCEPTED"
    assert result.plan is not None
    assert len(result.capability_outcomes) == 1
    # Whole-run rejection yielded zero partial execution on that attempt.
    # Adapter should have zero writes (read-only).
    assert adapter.entry_count == adapter_before
    after = reconcile(processor, ledger, _TOLERANCE)
    _assert_zero_mutations(before, after, adapter_before, adapter.entry_count, None, None, result)


def test_executor_rejection_exhausts_to_hitl_when_all_rejected(
    no_sockets: None,
) -> None:
    """Arrange every valid plan carries credential; Act; Assert HITL budget exhausted."""
    # Arrange.
    del no_sockets
    processor, ledger = _processor_ledger_for_p1()
    before = reconcile(processor, ledger, _TOLERANCE)
    bundle, adapter = _bundle_with_payment()
    adapter_before = adapter.entry_count
    verifier = Verifier(max_replans=2)
    executor = CapabilityExecutor(bundle)
    seq = _SequencedFakeLLM([_credential_payload(), _credential_payload(), _credential_payload()])
    orch = InvestigateOrchestrator(seq, executor, verifier)
    request = _make_request()
    # Act.
    result = orch.run(request, _TENANT)
    # Assert.
    assert result.status == "REPLAN_EXHAUSTED_HITL"
    assert result.attempts == 3
    assert result.capability_outcomes == ()
    assert "budget exhausted" in (result.hitl_reason or "").lower()
    after = reconcile(processor, ledger, _TOLERANCE)
    _assert_zero_mutations(before, after, adapter_before, adapter.entry_count, None, None, result)
