"""P4.3 capability executor tests: deterministic evidence-only execution.

Covers :class:`CapabilityExecutor.execute` without touching implementation
or specs: a valid five-tool plan executes one outcome per call with full
``ToolResult`` provenance, whole-run rejections (unknown/write-like
capabilities, malformed args, excess calls, cross-tenant identifiers,
provider SDK objects) perform zero executions, adapter timeouts and 5xx
stay bounded failures, duplicate calls execute once with a shared result
plus an audit note, fixture legs show zero financial mutation via an
identical P1 reconcile before/after, the executor imports no P3 execution
state (AST scan), and each of the five capabilities passes through its
typed seam (seeded Stripe folds, read-only QB ``get_entry``, ledger
triple lookup with the missing path, Gmail empty and seeded corpora).

Style: Arrange-Act-Assert per test, typed, deterministic, no network or
LLM. ``Decimal`` appears only to seed P3 fixture legs (never arithmetic).
"""

from __future__ import annotations

import ast
import socket
import urllib.request
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn

import pytest

import agents.capabilities.executor as executor_module
from agents.capabilities.capabilities import AdapterBundle
from agents.capabilities.executor import CapabilityExecutor
from agents.capabilities.types import ExecutorRejectedError
from agents.investigation.plan import CapabilityCall, InvestigationPlan
from finance.accounting.commands import CorrectingEntryCommand, JournalLine
from finance.accounting.errors import TransientError
from finance.accounting.mock import MockQuickBooksAdapter
from finance.reconciliation.ledger_resolution import (
    InMemoryLedgerRepository,
    LedgerKey,
)
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance
from finance.stripe.adapter import (
    StripePayment,
    apply_refund_event,
    payment_from_charge,
)

TENANT = "tenant-acme"
OTHER_TENANT = "tenant-globex"
PAYMENT_ID = "ch_exec_1"
OTHER_PAYMENT_ID = "ch_exec_other"
REFUND_ID = "re_exec_1"
ENTRY_KEY = "exec-seed-001"
HYPOTHESIS = "Refund posting lag probe for the deterministic executor."
EVIDENCE = ("ev-exec-1",)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block real sockets so every test stays deterministic and offline."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network is forbidden in executor tests")

    monkeypatch.setattr(socket, "socket", _explode)
    monkeypatch.setattr(urllib.request, "urlopen", _explode)


def _charge_event(
    *,
    event_id: str = "evt-exec-charge-1",
    charge_id: str = PAYMENT_ID,
    amount_minor: int = 10000,
    fee_minor: int | None = 250,
    created: int = 1750000000,
) -> dict[str, Any]:
    """Build a charge.succeeded envelope in minor-unit ints (no Decimal)."""
    obj: dict[str, Any] = {
        "id": charge_id,
        "amount": amount_minor,
        "currency": "usd",
        "created": created,
    }
    if fee_minor is not None:
        obj["application_fee_amount"] = fee_minor
    return {
        "id": event_id,
        "type": "charge.succeeded",
        "created": created,
        "data": {"object": obj},
    }


def _refund_event(
    *,
    event_id: str = "evt-exec-refund-1",
    refund_id: str = REFUND_ID,
    charge_id: str = PAYMENT_ID,
    amount_minor: int = 2500,
    charge_amount_minor: int = 10000,
    created: int = 1750000100,
) -> dict[str, Any]:
    """Build a refund.created envelope linked to a bare charge id."""
    return {
        "id": event_id,
        "type": "refund.created",
        "created": created,
        "data": {
            "object": {
                "id": refund_id,
                "amount": amount_minor,
                "currency": "usd",
                "charge": charge_id,
                "charge_amount_minor": charge_amount_minor,
                "created": created,
            }
        },
    }


def _fold(
    *,
    tenant_id: str = TENANT,
    charge_id: str = PAYMENT_ID,
    with_refund: bool = True,
) -> StripePayment:
    """Fold one charge plus an optional refund delta for ``tenant_id``."""
    payment = payment_from_charge(_charge_event(charge_id=charge_id), tenant_id=tenant_id)
    if with_refund:
        payment = apply_refund_event(payment, _refund_event(charge_id=charge_id))
    return payment


def _seeded_qb(*, tenant_id: str = TENANT) -> tuple[MockQuickBooksAdapter, str]:
    """Seed one balanced refund-lag entry; return adapter plus entry id."""
    adapter = MockQuickBooksAdapter()
    amount = Decimal("150.00")
    zero = Decimal("0")
    command = CorrectingEntryCommand(
        tenant_id=tenant_id,
        exception_id="exc-exec-001",
        exception_type="I-REFUND-LAG",
        currency="USD",
        lines=(
            JournalLine(account="4100-refunds", debit=amount, credit=zero),
            JournalLine(account="1000-cash", debit=zero, credit=amount),
        ),
        source_reference="stripe-ch-exec-1",
        memo="executor read-only probe",
    )
    entry = adapter.create_correcting_entry(command, ENTRY_KEY)
    return adapter, entry.entry_id


def _gmail_corpus(*, tenant_id: str = TENANT) -> dict[str, list[dict[str, Any]]]:
    """Build a single-hit fixture corpus scoped to ``tenant_id``."""
    return {
        tenant_id: [
            {
                "message_id": "msg-exec-1",
                "subject": "Refund receipt order 42",
                "body": "Your refund of 25.00 was processed",
            }
        ]
    }


def _full_bundle() -> tuple[AdapterBundle, MockQuickBooksAdapter, str, StripePayment]:
    """Seed stripe fold, QB entry, ledger leg, and gmail corpus together."""
    fold = _fold()
    adapter, entry_id = _seeded_qb()
    repo = InMemoryLedgerRepository.from_records([fold.to_record()])
    bundle = AdapterBundle(
        stripe_payments={(TENANT, PAYMENT_ID): fold},
        qb_adapter=adapter,
        ledger_repository=repo,
        gmail_corpus=_gmail_corpus(),
    )
    return bundle, adapter, entry_id, fold


def _plan(calls: Sequence[tuple[str, dict[str, str]]]) -> InvestigationPlan:
    """Build a valid dense plan from (capability, args) pairs."""
    ordered = tuple(
        CapabilityCall(capability=name, args=args, order_index=index)
        for index, (name, args) in enumerate(calls)
    )
    return InvestigationPlan(
        hypothesis_text=HYPOTHESIS,
        capability_calls=ordered,
        evidence_required=EVIDENCE,
    )


def _raw_plan(specs: Sequence[tuple[Any, Any, int]]) -> InvestigationPlan:
    """Bypass planner validation to test EXECUTOR enforcement directly."""
    calls = tuple(
        CapabilityCall.model_construct(capability=name, args=args, order_index=index)
        for name, args, index in specs
    )
    return InvestigationPlan.model_construct(
        hypothesis_text="bypass probe",
        capability_calls=calls,
        evidence_required=EVIDENCE,
    )


def _five_calls(entry_id: str) -> list[tuple[str, dict[str, str]]]:
    """Return the five-call happy-path pairs in allowlist order."""
    return [
        ("get_stripe_payment", {"payment_id": PAYMENT_ID}),
        ("get_stripe_refunds", {"payment_id": PAYMENT_ID}),
        ("get_qb_transaction", {"entry_id": entry_id}),
        ("get_expected_state", {"payment_id": PAYMENT_ID, "provider": "stripe"}),
        ("search_gmail", {"query": "refund"}),
    ]


def _assert_provenance(rows: Any) -> None:
    """Assert every evidence row carries the four provenance fields."""
    assert isinstance(rows, list) and rows, "expected evidence rows"
    for row in rows:
        assert isinstance(row, dict)
        for field in ("source", "source_record_id", "retrieved_at", "content_hash"):
            value = row.get(field)
            assert isinstance(value, str) and value.strip(), f"row misses {field}"


class _Always5xx:
    """Stub QB seam that always raises a scripted transient 5xx."""

    def get_entry(self, entry_id: str) -> NoReturn:
        """Raise a transient 5xx for any entry lookup."""
        raise TransientError(f"scripted 5xx for entry {entry_id!r}")

    def create_correcting_entry(self, command: Any, key: str) -> NoReturn:
        """Refuse writes: the executor seam is read-only."""
        raise AssertionError("write seam must never be touched")

    def void_entry(self, entry_id: str, key: str) -> NoReturn:
        """Refuse voids: the executor seam is read-only."""
        raise AssertionError("void seam must never be touched")


class TestValidFiveToolRun:
    """A valid five-tool plan executes once per call with provenance."""

    def test_five_tool_plan_executes_one_outcome_per_call(self) -> None:
        """Arrange a seeded bundle; Act execute; Assert five ordered hits."""
        # Arrange.
        bundle, _, entry_id, _ = _full_bundle()
        executor = CapabilityExecutor(bundle)
        plan = _plan(_five_calls(entry_id))
        # Act.
        outcomes = executor.execute(plan, TENANT)
        # Assert.
        assert len(outcomes) == 5
        assert [item.order_index for item in outcomes] == [0, 1, 2, 3, 4]
        assert [item.capability for item in outcomes] == [
            "get_stripe_payment",
            "get_stripe_refunds",
            "get_qb_transaction",
            "get_expected_state",
            "search_gmail",
        ]
        assert all(item.tenant_id == TENANT for item in outcomes)
        assert all(item.success for item in outcomes)
        assert all(item.error_code is None for item in outcomes)
        assert all(item.result.row_count > 0 for item in outcomes)

    def test_success_rows_carry_toolresult_provenance(self) -> None:
        """Arrange a valid run; Act execute; Assert provenance on rows."""
        # Arrange.
        bundle, _, entry_id, _ = _full_bundle()
        executor = CapabilityExecutor(bundle)
        plan = _plan(_five_calls(entry_id))
        # Act.
        outcomes = executor.execute(plan, TENANT)
        # Assert.
        for outcome in outcomes:
            _assert_provenance(outcome.result.data)


class TestWholeRunRejections:
    """Shape, allowlist, and gate failures reject with zero executions."""

    def test_unknown_capability_rejects_with_zero_executions(self) -> None:
        """Arrange an unknown name; Act execute; Assert reject, no calls."""
        # Arrange.
        bundle, adapter, _, _ = _full_bundle()
        baseline = len(adapter.calls)
        executor = CapabilityExecutor(bundle)
        plan = _raw_plan([("refund_everything_now", {"payment_id": PAYMENT_ID}, 0)])
        # Act.
        with pytest.raises(ExecutorRejectedError):
            executor.execute(plan, TENANT)
        # Assert.
        assert len(adapter.calls) == baseline

    @pytest.mark.parametrize("name", ["write_database", "call_api"])
    def test_write_like_capability_rejected(self, name: str) -> None:
        """Arrange a write-like name; Act execute; Assert whole-run reject."""
        # Arrange.
        bundle, adapter, _, _ = _full_bundle()
        baseline = len(adapter.calls)
        executor = CapabilityExecutor(bundle)
        plan = _raw_plan([(name, {"payment_id": PAYMENT_ID}, 0)])
        # Act.
        with pytest.raises(ExecutorRejectedError):
            executor.execute(plan, TENANT)
        # Assert.
        assert len(adapter.calls) == baseline

    def test_non_string_arg_rejected(self) -> None:
        """Arrange an int arg; Act execute; Assert string-only rejection."""
        # Arrange.
        bundle, adapter, _, _ = _full_bundle()
        baseline = len(adapter.calls)
        executor = CapabilityExecutor(bundle)
        plan = _raw_plan([("get_stripe_payment", {"payment_id": 12345}, 0)])
        # Act.
        with pytest.raises(ExecutorRejectedError):
            executor.execute(plan, TENANT)
        # Assert.
        assert len(adapter.calls) == baseline

    @pytest.mark.parametrize(
        "args",
        [
            {"payment_id": "v" * 513},
            {"k" * 65: "v"},
        ],
    )
    def test_oversize_arg_rejected(self, args: dict[str, str]) -> None:
        """Arrange an oversize key/value; Act execute; Assert rejection."""
        # Arrange.
        bundle, adapter, _, _ = _full_bundle()
        baseline = len(adapter.calls)
        executor = CapabilityExecutor(bundle)
        plan = _raw_plan([("get_stripe_payment", args, 0)])
        # Act.
        with pytest.raises(ExecutorRejectedError):
            executor.execute(plan, TENANT)
        # Assert.
        assert len(adapter.calls) == baseline

    @pytest.mark.parametrize(
        "args",
        [
            {"api_key": "value"},
            {"payment_id": PAYMENT_ID, "note": "sk-abc123secret"},
        ],
    )
    def test_credential_pattern_rejected(self, args: dict[str, str]) -> None:
        """Arrange credential text in key/value; Act; Assert rejection."""
        # Arrange.
        bundle, adapter, _, _ = _full_bundle()
        baseline = len(adapter.calls)
        executor = CapabilityExecutor(bundle)
        plan = _plan([("get_stripe_payment", args)])
        # Act.
        with pytest.raises(ExecutorRejectedError):
            executor.execute(plan, TENANT)
        # Assert.
        assert len(adapter.calls) == baseline

    @pytest.mark.parametrize(
        "args",
        [
            {"payment_id": PAYMENT_ID, "callback": "https://evil.example/exfil"},
            {"https://evil.example/x": "v"},
        ],
    )
    def test_url_arg_rejected(self, args: dict[str, str]) -> None:
        """Arrange URL text in key/value; Act execute; Assert rejection."""
        # Arrange.
        bundle, adapter, _, _ = _full_bundle()
        baseline = len(adapter.calls)
        executor = CapabilityExecutor(bundle)
        plan = _plan([("get_stripe_payment", args)])
        # Act.
        with pytest.raises(ExecutorRejectedError):
            executor.execute(plan, TENANT)
        # Assert.
        assert len(adapter.calls) == baseline

    @pytest.mark.parametrize(
        "args",
        [
            {"payment_id": "SELECT * FROM ledger"},
            {"payment_id": PAYMENT_ID, "note": "please call_api now"},
            {"write_database": "ledger"},
        ],
    )
    def test_sql_escape_rejected(self, args: dict[str, str]) -> None:
        """Arrange SQL/tool text in key/value; Act; Assert rejection."""
        # Arrange.
        bundle, adapter, _, _ = _full_bundle()
        baseline = len(adapter.calls)
        executor = CapabilityExecutor(bundle)
        plan = _plan([("get_stripe_payment", args)])
        # Act.
        with pytest.raises(ExecutorRejectedError):
            executor.execute(plan, TENANT)
        # Assert.
        assert len(adapter.calls) == baseline

    def test_excess_calls_rejected(self) -> None:
        """Arrange nine planned calls; Act execute; Assert bound rejection."""
        # Arrange.
        bundle, adapter, _, _ = _full_bundle()
        baseline = len(adapter.calls)
        executor = CapabilityExecutor(bundle)
        specs = [("get_stripe_payment", {"payment_id": PAYMENT_ID}, index) for index in range(9)]
        plan = _raw_plan(specs)
        # Act.
        with pytest.raises(ExecutorRejectedError):
            executor.execute(plan, TENANT)
        # Assert.
        assert len(adapter.calls) == baseline

    def test_cross_tenant_identifier_rejects_whole_run(self) -> None:
        """Arrange another tenant's payment; Act; Assert scope rejection."""
        # Arrange.
        fold = _fold()
        other_fold = _fold(tenant_id=OTHER_TENANT, charge_id=OTHER_PAYMENT_ID, with_refund=False)
        adapter, _ = _seeded_qb()
        baseline = len(adapter.calls)
        repo = InMemoryLedgerRepository.from_records([fold.to_record()])
        bundle = AdapterBundle(
            stripe_payments={
                (TENANT, PAYMENT_ID): fold,
                (OTHER_TENANT, OTHER_PAYMENT_ID): other_fold,
            },
            qb_adapter=adapter,
            ledger_repository=repo,
            gmail_corpus=_gmail_corpus(),
        )
        executor = CapabilityExecutor(bundle)
        plan = _plan(
            [
                (
                    "get_stripe_payment",
                    {"payment_id": OTHER_PAYMENT_ID, "tenant_id": OTHER_TENANT},
                )
            ]
        )
        # Act.
        with pytest.raises(ExecutorRejectedError):
            executor.execute(plan, TENANT)
        # Assert.
        assert len(adapter.calls) == baseline

    def test_provider_sdk_object_never_reaches_adapter(self) -> None:
        """Arrange a raw SDK object arg; Act; Assert validation rejection."""

        # Arrange.
        class _RawSdkObject:
            """Stand-in handle that must never cross the typed seam."""

        bundle, adapter, _, _ = _full_bundle()
        baseline = len(adapter.calls)
        executor = CapabilityExecutor(bundle)
        plan = _raw_plan([("get_stripe_payment", {"payment_id": _RawSdkObject()}, 0)])
        # Act.
        with pytest.raises(ExecutorRejectedError):
            executor.execute(plan, TENANT)
        # Assert.
        assert len(adapter.calls) == baseline


class TestBoundedFailures:
    """Adapter faults become bounded records, never raised escapes."""

    def test_adapter_timeout_is_bounded_not_raised(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Arrange a slow clock; Act execute; Assert TIMEOUT outcome."""
        # Arrange.
        bundle, _, _, _ = _full_bundle()
        executor = CapabilityExecutor(bundle)
        plan = _plan([("get_stripe_payment", {"payment_id": PAYMENT_ID})])
        state = {"calls": 0}

        def _fake_monotonic() -> float:
            state["calls"] += 1
            return 0.0 if state["calls"] == 1 else 3600.0

        monkeypatch.setattr(executor_module.time, "monotonic", _fake_monotonic)
        # Act.
        outcomes = executor.execute(plan, TENANT)
        # Assert.
        assert len(outcomes) == 1
        assert outcomes[0].success is False
        assert outcomes[0].error_code == "TIMEOUT"
        assert outcomes[0].result.row_count == 0
        assert "timeout" in outcomes[0].audit_note

    def test_adapter_5xx_is_bounded_failure_record(self) -> None:
        """Arrange a 5xx stub; Act execute; Assert bounded failure outcome."""
        # Arrange.
        fold = _fold()
        repo = InMemoryLedgerRepository.from_records([fold.to_record()])
        bundle = AdapterBundle(
            stripe_payments={(TENANT, PAYMENT_ID): fold},
            qb_adapter=_Always5xx(),  # type: ignore[arg-type]
            ledger_repository=repo,
            gmail_corpus=_gmail_corpus(),
        )
        executor = CapabilityExecutor(bundle)
        plan = _plan([("get_qb_transaction", {"entry_id": "MOCK-000001"})])
        # Act.
        outcomes = executor.execute(plan, TENANT)
        # Assert.
        assert len(outcomes) == 1
        assert outcomes[0].success is False
        assert outcomes[0].error_code == "TRANSIENT_5XX"
        assert outcomes[0].result.row_count == 0
        assert "5xx" in outcomes[0].audit_note


class TestDuplicateDedupe:
    """Identical planned calls share one underlying execution."""

    def test_duplicate_calls_execute_once_and_share_result(self) -> None:
        """Arrange duplicate calls; Act; Assert one call plus audit note."""
        # Arrange.
        bundle, adapter, entry_id, _ = _full_bundle()
        executor = CapabilityExecutor(bundle)
        plan = _plan(
            [
                ("get_qb_transaction", {"entry_id": entry_id}),
                ("get_qb_transaction", {"entry_id": entry_id}),
            ]
        )
        # Act.
        outcomes = executor.execute(plan, TENANT)
        # Assert.
        assert len(outcomes) == 2
        assert outcomes[0].deduped is False
        assert outcomes[1].deduped is True
        assert outcomes[1].result is outcomes[0].result
        assert "deduped" in outcomes[1].audit_note
        gets = [call for call in adapter.calls if call.op == "get_entry"]
        assert len(gets) == 1


class TestZeroMutation:
    """Runs mutate no financial facts and no P3 execution state."""

    def test_p1_reconcile_identical_before_and_after_run(self) -> None:
        """Arrange legs; Act execute; Assert P1 verdict plus stores kept."""
        # Arrange.
        bundle, adapter, entry_id, fold = _full_bundle()
        seed_calls = len(adapter.calls)
        entries_before = adapter.entry_count
        repo = bundle.ledger_repository
        assert repo is not None
        key = LedgerKey(tenant_id=TENANT, provider="stripe", payment_id=PAYMENT_ID)
        ledger_before = repo.get(key)
        assert ledger_before is not None
        processor = fold.to_record()
        tolerance = ReconciliationTolerance()
        before = reconcile(processor, ledger_before, tolerance)
        fold_key_before = fold.canonical_idempotency_key()
        executor = CapabilityExecutor(bundle)
        plan = _plan(_five_calls(entry_id))
        # Act.
        outcomes = executor.execute(plan, TENANT)
        # Assert.
        assert len(outcomes) == 5
        ledger_after = repo.get(key)
        assert ledger_after is not None
        assert reconcile(processor, ledger_after, tolerance) == before
        assert fold.canonical_idempotency_key() == fold_key_before
        assert adapter.entry_count == entries_before
        delta = adapter.calls[seed_calls:]
        assert delta, "expected read-only adapter traffic"
        assert all(call.op == "get_entry" for call in delta)

    def test_executor_imports_no_p3_execution_state(self) -> None:
        """Arrange executor source; Act AST scan; Assert no P3 imports."""
        # Arrange.
        path = Path(__file__).resolve().parents[3] / "agents" / "capabilities" / "executor.py"
        tree = ast.parse(path.read_text())
        # Act.
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.append(node.module)
        # Assert.
        assert modules, "expected executor imports to scan"
        assert not [
            name
            for name in modules
            if name == "finance.execution" or name.startswith("finance.execution.")
        ]
        assert not [name for name in modules if name == "apps" or name.startswith("apps.")]


class TestTypedCapabilitySeams:
    """Each closed capability passes through its typed read-only seam."""

    def test_stripe_payment_seam_reads_seeded_fold(self) -> None:
        """Arrange a seeded fold; Act execute; Assert the charge row."""
        # Arrange.
        bundle, _, _, _ = _full_bundle()
        executor = CapabilityExecutor(bundle)
        plan = _plan([("get_stripe_payment", {"payment_id": PAYMENT_ID})])
        # Act.
        outcomes = executor.execute(plan, TENANT)
        # Assert.
        assert len(outcomes) == 1
        assert outcomes[0].capability == "get_stripe_payment"
        assert outcomes[0].success is True
        rows = outcomes[0].result.data
        assert isinstance(rows, list) and len(rows) == 1
        assert rows[0]["source"] == "stripe"
        assert rows[0]["source_record_id"] == PAYMENT_ID
        _assert_provenance(rows)

    def test_stripe_refunds_seam_reads_refund_deltas(self) -> None:
        """Arrange a fold with a refund; Act; Assert one refund row."""
        # Arrange.
        bundle, _, _, _ = _full_bundle()
        executor = CapabilityExecutor(bundle)
        plan = _plan([("get_stripe_refunds", {"payment_id": PAYMENT_ID})])
        # Act.
        outcomes = executor.execute(plan, TENANT)
        # Assert.
        assert len(outcomes) == 1
        assert outcomes[0].capability == "get_stripe_refunds"
        assert outcomes[0].success is True
        rows = outcomes[0].result.data
        assert isinstance(rows, list) and len(rows) == 1
        assert rows[0]["source"] == "stripe"
        assert rows[0]["refund_id"] == REFUND_ID
        _assert_provenance(rows)

    def test_qb_transaction_seam_is_read_only(self) -> None:
        """Arrange a seeded entry; Act; Assert read hit with no writes."""
        # Arrange.
        bundle, adapter, entry_id, _ = _full_bundle()
        seed_calls = len(adapter.calls)
        entries_before = adapter.entry_count
        executor = CapabilityExecutor(bundle)
        plan = _plan([("get_qb_transaction", {"entry_id": entry_id})])
        # Act.
        outcomes = executor.execute(plan, TENANT)
        # Assert.
        assert len(outcomes) == 1
        assert outcomes[0].capability == "get_qb_transaction"
        assert outcomes[0].success is True
        rows = outcomes[0].result.data
        assert isinstance(rows, list) and len(rows) == 1
        assert rows[0]["source"] == "quickbooks"
        assert rows[0]["source_record_id"] == entry_id
        _assert_provenance(rows)
        assert adapter.entry_count == entries_before
        delta = adapter.calls[seed_calls:]
        assert [call.op for call in delta] == ["get_entry"]

    def test_expected_state_hit_reads_ledger_triple(self) -> None:
        """Arrange a seeded triple; Act; Assert the ledger row returns."""
        # Arrange.
        bundle, _, _, _ = _full_bundle()
        executor = CapabilityExecutor(bundle)
        plan = _plan([("get_expected_state", {"payment_id": PAYMENT_ID, "provider": "stripe"})])
        # Act.
        outcomes = executor.execute(plan, TENANT)
        # Assert.
        assert len(outcomes) == 1
        assert outcomes[0].capability == "get_expected_state"
        assert outcomes[0].success is True
        rows = outcomes[0].result.data
        assert isinstance(rows, list) and len(rows) == 1
        assert rows[0]["source"] == "ledger"
        assert rows[0]["source_record_id"] == PAYMENT_ID
        _assert_provenance(rows)

    def test_expected_state_missing_is_no_result_evidence(self) -> None:
        """Arrange an unknown triple; Act; Assert bounded no-result."""
        # Arrange.
        bundle, _, _, _ = _full_bundle()
        executor = CapabilityExecutor(bundle)
        plan = _plan([("get_expected_state", {"payment_id": "ch_unknown", "provider": "stripe"})])
        # Act.
        outcomes = executor.execute(plan, TENANT)
        # Assert.
        assert len(outcomes) == 1
        assert outcomes[0].success is False
        assert outcomes[0].error_code == "NO_RESULT"
        assert outcomes[0].result.row_count == 0
        assert outcomes[0].result.insufficient_data is True

    def test_gmail_empty_corpus_is_no_result(self) -> None:
        """Arrange an empty corpus; Act search; Assert no-result evidence."""
        # Arrange.
        fold = _fold()
        adapter, _ = _seeded_qb()
        repo = InMemoryLedgerRepository.from_records([fold.to_record()])
        bundle = AdapterBundle(
            stripe_payments={(TENANT, PAYMENT_ID): fold},
            qb_adapter=adapter,
            ledger_repository=repo,
            gmail_corpus={},
        )
        executor = CapabilityExecutor(bundle)
        plan = _plan([("search_gmail", {"query": "refund"})])
        # Act.
        outcomes = executor.execute(plan, TENANT)
        # Assert.
        assert len(outcomes) == 1
        assert outcomes[0].capability == "search_gmail"
        assert outcomes[0].success is False
        assert outcomes[0].result.row_count == 0

    def test_gmail_seeded_corpus_hits(self) -> None:
        """Arrange a seeded corpus; Act search; Assert the message row."""
        # Arrange.
        bundle, _, _, _ = _full_bundle()
        executor = CapabilityExecutor(bundle)
        plan = _plan([("search_gmail", {"query": "refund"})])
        # Act.
        outcomes = executor.execute(plan, TENANT)
        # Assert.
        assert len(outcomes) == 1
        assert outcomes[0].success is True
        rows = outcomes[0].result.data
        assert isinstance(rows, list) and len(rows) == 1
        assert rows[0]["source"] == "gmail"
        assert rows[0]["source_record_id"] == "msg-exec-1"
        _assert_provenance(rows)
