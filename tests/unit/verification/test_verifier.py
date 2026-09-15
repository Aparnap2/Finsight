"""P4.4 verifier adversarial tests: frozen gate, approve/CLOSED gap, no mutation.

Covers :class:`Verifier` without touching implementation or specs: valid
plans stay ``ACCEPTED`` (including benign ``disclose`` wording), approval
verbs reject as ``never_violation:declare_approval``, authoritative CLOSED
emissions reject as ``never_violation:emit_closed`` (both escalating at the
fixed budget), plus schema/unknown-field/allowlist/grounding/claim/
confidence/bounds stages, identical-bounds replans, provider-failure-shaped
malformed inputs that return verdicts (never raise), budget exhaustion to
HITL with attempts preserved, and a zero-P3-mutation regression (identical
P1 reconcile before/after plus an AST import scan).

Style: Arrange-Act-Assert per test, typed, deterministic, no network or
LLM. ``Decimal`` appears only to seed P1 reconcile fixture legs (no money
arithmetic); the verifier, verdict, and plan contracts stay Decimal-free.
"""

from __future__ import annotations

import ast
import socket
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agents.investigation.plan import (
    MAX_ARG_KEY_CHARS,
    MAX_ARG_VALUE_CHARS,
    MAX_EVIDENCE_REQUIRED,
    MAX_HYPOTHESIS_CHARS,
    CapabilityCall,
    InvestigationPlan,
)
from agents.verification.verdict import Verdict
from agents.verification.verifier import (
    DEFAULT_CONFIDENCE_CAP,
    DEFAULT_MAX_REPLANS,
    Verifier,
)
from finance.reconciliation.models import PaymentRecord, PaymentStatus
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance

_HYPOTHESIS = "Possible refund posting lag between processor and ledger records."
_EVIDENCE = ("ev-ledger-001",)
_AVAILABLE = frozenset({"ev-ledger-001", "ev-processor-002"})


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block real sockets so every test stays deterministic and offline."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network is forbidden in verifier tests")

    monkeypatch.setattr(socket, "socket", _explode)
    monkeypatch.setattr(urllib.request, "urlopen", _explode)


def _plan(
    hypothesis: str = _HYPOTHESIS,
    evidence: tuple[str, ...] = _EVIDENCE,
    escalation: bool = False,
) -> InvestigationPlan:
    """Build a schema-valid candidate plan through strict validation."""
    return InvestigationPlan.model_validate(
        {
            "hypothesis_text": hypothesis,
            "capability_calls": [
                {
                    "capability": "get_stripe_payment",
                    "args": {"payment_id": "pay_123"},
                    "order_index": 0,
                },
            ],
            "evidence_required": list(evidence),
            "escalation": escalation,
        }
    )


def _raw_plan(**overrides: Any) -> InvestigationPlan:
    """Build a plan via ``model_construct`` bypassing validation (adversarial)."""
    base: dict[str, Any] = {
        "hypothesis_text": _HYPOTHESIS,
        "capability_calls": (
            CapabilityCall.model_construct(
                capability="get_stripe_payment",
                args={"payment_id": "pay_123"},
                order_index=0,
            ),
        ),
        "evidence_required": _EVIDENCE,
        "escalation": False,
    }
    base.update(overrides)
    return InvestigationPlan.model_construct(**base)


def _with_extra(plan: InvestigationPlan, extra: dict[str, Any]) -> InvestigationPlan:
    """Smuggle unknown fields into ``__pydantic_extra__`` (provider-shaped)."""
    object.__setattr__(plan, "__pydantic_extra__", dict(extra))
    return plan


def _with_confidence(plan: InvestigationPlan, value: Any) -> InvestigationPlan:
    """Attach an explicit confidence attribute without touching extras."""
    object.__setattr__(plan, "confidence", value)
    return plan


def _leg(
    payment_id: str,
    gross: str,
    fee: str,
    refund: str,
    net: str,
) -> PaymentRecord:
    """Seed one P1 fixture leg from decimal strings (no arithmetic here)."""
    return PaymentRecord(
        payment_id=payment_id,
        provider="stripe",
        provider_event_id=f"evt-{payment_id}",
        idempotency_key="key-verifier-zero-mutation",
        gross=Decimal(gross),
        fee=Decimal(fee),
        refund=Decimal(refund),
        net=Decimal(net),
        currency="USD",
        status=PaymentStatus.SETTLED,
        occurred_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        tenant_id="tenant-acme",
    )


def _import_roots(source: Path) -> set[str]:
    """Collect top-level import roots from a source file via AST."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _import_modules(source: Path) -> list[str]:
    """Collect full module paths from a source file via AST."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


class TestBaseline:
    """A clean plan passes every stage."""

    def test_valid_plan_accepted(self) -> None:
        """Arrange a valid plan; Act verify; Assert ACCEPTED with no reasons."""
        # Arrange.
        verifier = Verifier()
        plan = _plan()
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "ACCEPTED"
        assert verdict.reasons == ()
        assert verdict.attempt_index == 0

    def test_verifier_bounds_fixed_at_construction(self) -> None:
        """Arrange defaults; Act read props; Assert fixed budget and cap."""
        # Arrange.
        verifier = Verifier()
        # Act.
        max_replans = verifier.max_replans
        cap = verifier.confidence_cap
        # Assert.
        assert max_replans == DEFAULT_MAX_REPLANS == 2
        assert cap == DEFAULT_CONFIDENCE_CAP == 0.85

    def test_explicit_bounds_pinned(self) -> None:
        """Arrange custom bounds; Act verify; Assert the cap actually gates."""
        # Arrange.
        verifier = Verifier(max_replans=1, confidence_cap=0.5)
        plan = _plan(hypothesis="Probe with confidence 0.6 needs review.")
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verifier.max_replans == 1
        assert verifier.confidence_cap == 0.5
        assert verdict.status == "REJECTED_REPLAN"
        assert any(r.startswith("confidence_violation:") for r in verdict.reasons)


class TestApproveClosedGap:
    """The fixed approve/CLOSED gap probes are first-class rejections."""

    def test_benign_disclose_stays_accepted(self) -> None:
        """Arrange disclose wording; Act verify; Assert ACCEPTED (no CLOSED)."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(hypothesis="We disclose the refund lag probe for review.")
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "ACCEPTED"
        assert verdict.reasons == ()

    def test_closed_loop_benign_stays_accepted(self) -> None:
        """Arrange closed-loop wording; Act; Assert ACCEPTED, not emission."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(hypothesis="Closed loop review of the refund lag probe.")
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "ACCEPTED"

    @pytest.mark.parametrize(
        "wording",
        [
            "Please approve the refund probe.",
            "The probe was approved yesterday.",
            "Requesting approval for the probe.",
            "The probe authorizes the next lookup.",
            "Authorised follow-up on the probe.",
            "Please authorize the case review.",
        ],
        ids=["approve", "approved", "approval", "authorizes", "authorised", "authorize"],
    )
    def test_approve_wording_rejected_replan_with_declare_approval(self, wording: str) -> None:
        """Arrange approval verbs; Act; Assert REJECTED_REPLAN + approval code."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(hypothesis=f"Refund lag probe. {wording}")
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert "never_violation:declare_approval" in verdict.reasons
        assert verdict.attempt_index == 0

    @pytest.mark.parametrize(
        "wording",
        [
            "The case is closed.",
            "Please mark as closed today.",
            "Close the case after review.",
            "Closing the exception now.",
            "The exception closed yesterday.",
            "We close as closed per review.",
        ],
        ids=["is-closed", "mark-closed", "close-case", "closing", "exc-closed", "as-closed"],
    )
    def test_closed_emission_rejected_with_emit_closed(self, wording: str) -> None:
        """Arrange CLOSED emissions; Act; Assert REJECTED_REPLAN + emit code."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(hypothesis=f"Refund lag probe. {wording}")
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert "never_violation:emit_closed" in verdict.reasons
        assert verdict.attempt_index == 0

    def test_approve_at_budget_escalates_hitl(self) -> None:
        """Arrange approval plan; Act at max; Assert ESCALATE keeps the code."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(hypothesis="Refund lag probe. Please approve the review.")
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), DEFAULT_MAX_REPLANS)
        # Assert.
        assert verdict.status == "ESCALATE_HITL"
        assert "never_violation:declare_approval" in verdict.reasons
        assert any(r.startswith("budget_exhausted:") for r in verdict.reasons)
        assert verdict.attempt_index == DEFAULT_MAX_REPLANS

    def test_closed_at_budget_escalates_hitl(self) -> None:
        """Arrange CLOSED plan; Act at max; Assert ESCALATE keeps emit code."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(hypothesis="Refund lag probe. The case is closed.")
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), DEFAULT_MAX_REPLANS)
        # Assert.
        assert verdict.status == "ESCALATE_HITL"
        assert "never_violation:emit_closed" in verdict.reasons
        assert any(r.startswith("budget_exhausted:") for r in verdict.reasons)
        assert verdict.attempt_index == DEFAULT_MAX_REPLANS


class TestSchema:
    """Stage 1 rejects malformed shapes before any other judgment."""

    def test_blank_hypothesis_rejected(self) -> None:
        """Arrange blank text; Act; Assert schema blank-hypothesis code."""
        # Arrange.
        verifier = Verifier()
        plan = _raw_plan(hypothesis_text="   ")
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == ("schema_violation:hypothesis_text_blank",)

    def test_empty_capability_calls_rejected(self) -> None:
        """Arrange zero calls; Act; Assert schema empty-calls code."""
        # Arrange.
        verifier = Verifier()
        plan = _raw_plan(capability_calls=())
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == ("schema_violation:capability_calls_empty",)

    def test_empty_evidence_required_rejected(self) -> None:
        """Arrange zero evidence; Act; Assert schema empty-evidence code."""
        # Arrange.
        verifier = Verifier()
        plan = _raw_plan(evidence_required=())
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == ("schema_violation:evidence_required_empty",)

    def test_order_index_mismatch_rejected(self) -> None:
        """Arrange wrong order; Act; Assert schema ordering code."""
        # Arrange.
        verifier = Verifier()
        bad = CapabilityCall.model_construct(
            capability="get_stripe_payment", args={"payment_id": "pay_1"}, order_index=7
        )
        plan = _raw_plan(capability_calls=(bad,))
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == ("schema_violation:calls[0].order_index_mismatch",)

    def test_duplicate_evidence_rejected(self) -> None:
        """Arrange dup ids; Act; Assert schema duplicate code."""
        # Arrange.
        verifier = Verifier()
        plan = _raw_plan(evidence_required=("ev-ledger-001", "ev-ledger-001"))
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == ("schema_violation:evidence_required_duplicate:ev-ledger-001",)

    def test_escalation_not_bool_rejected(self) -> None:
        """Arrange int flag; Act; Assert strict-bool schema code."""
        # Arrange.
        verifier = Verifier()
        plan = _raw_plan(escalation=1)
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == ("schema_violation:escalation_not_bool",)

    def test_pydantic_boundary_rejects_unknown_fields(self) -> None:
        """Arrange extra key; Act validate; Assert strict boundary ValidationError."""
        # Arrange.
        payload: dict[str, Any] = {
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
            "rogue_field": True,
        }
        # Act.
        with pytest.raises(ValidationError):
            InvestigationPlan.model_validate(payload)
        # Assert (no assert needed beyond raises; explicit marker below).
        assert set(InvestigationPlan.model_fields) == {
            "hypothesis_text",
            "capability_calls",
            "evidence_required",
            "escalation",
        }

    def test_smuggled_unknown_field_rejected_by_verifier(self) -> None:
        """Arrange smuggled extra; Act; Assert schema unknown-fields code."""
        # Arrange.
        verifier = Verifier()
        plan = _with_extra(_plan(), {"rogue_field": True})
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == ("schema_violation:unknown_fields:rogue_field",)


class TestAllowlist:
    """Stage 2 admits only the frozen five capabilities."""

    def test_unsupported_capability_rejected(self) -> None:
        """Arrange read_database; Act; Assert allowlist code, no execution."""
        # Arrange.
        verifier = Verifier()
        bad = CapabilityCall.model_construct(
            capability="read_database", args={"table": "ledger"}, order_index=0
        )
        plan = _raw_plan(capability_calls=(bad,))
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == ("allowlist_violation:read_database",)

    @pytest.mark.parametrize(
        "capability", ["write_database", "call_api"], ids=["write-db", "call-api"]
    )
    def test_write_like_capabilities_rejected(self, capability: str) -> None:
        """Arrange write-like calls; Act; Assert allowlist violation."""
        # Arrange.
        verifier = Verifier()
        bad = CapabilityCall.model_construct(
            capability=capability, args={"target": "ledger"}, order_index=0
        )
        plan = _raw_plan(capability_calls=(bad,))
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == (f"allowlist_violation:{capability}",)


class TestGrounding:
    """Stage 3 grounds every evidence id in the available set."""

    def test_evidence_not_in_available_set_rejected(self) -> None:
        """Arrange unknown id; Act; Assert grounding violation."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(evidence=("ev-unknown-999",))
        # Act.
        verdict = verifier.verify(plan, {"ev-ledger-001"}, 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == ("grounding_violation:unknown_evidence_id:ev-unknown-999",)

    @pytest.mark.parametrize(
        "available",
        ["ev-ledger-001", [123], ["  "], ["ev-ledger-001", 7]],
        ids=["string-not-set", "non-string-entry", "blank-entry", "mixed-entry"],
    )
    def test_malformed_available_set_fails_closed(self, available: Any) -> None:
        """Arrange bad available set; Act; Assert fail-closed, no escalation."""
        # Arrange.
        verifier = Verifier()
        plan = _plan()
        # Act.
        verdict = verifier.verify(plan, available, 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == ("bounds_violation:available_evidence_ids_malformed",)


class TestClaimClassification:
    """Stage 4 keeps factual/verified framing off the plan."""

    @pytest.mark.parametrize(
        ("hypothesis", "code"),
        [
            ("The lag is verified in the ledger.", "never_violation:declare_verified"),
            ("Evidence verified for the lag.", "never_violation:declare_evidence_verified"),
            ("Execution verified for the lag.", "never_violation:declare_execution_verified"),
            ("The lag is VERIFIED in records.", "never_violation:declare_verified"),
            ("Lag execution_verified in review.", "never_violation:declare_execution_verified"),
        ],
        ids=["bare", "evidence", "execution", "upper", "joined"],
    )
    def test_ungrounded_factual_claim_rejected(self, hypothesis: str, code: str) -> None:
        """Arrange VERIFIED markers; Act; Assert the matching never code."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(hypothesis=hypothesis)
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert code in verdict.reasons

    @pytest.mark.parametrize(
        "hypothesis",
        [
            "The lag was caused by the ledger, proven by records.",
            "Root cause is confirmed by the ledger review.",
            "The break proves the factual refund lag.",
        ],
        ids=["caused-proven", "root-confirmed", "proves-factual"],
    )
    def test_causal_claim_marked_verified_rejected(self, hypothesis: str) -> None:
        """Arrange causal+authoritative sentence; Act; Assert causal code."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(hypothesis=hypothesis)
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert "never_violation:causal_claim_as_verified" in verdict.reasons

    def test_bare_causal_hypothesis_stays_hypothesis_side(self) -> None:
        """Arrange causal verb alone; Act; Assert ACCEPTED without framing."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(hypothesis="Possible root cause is refund lag; needs review.")
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "ACCEPTED"
        assert verdict.reasons == ()


class TestConfidence:
    """Stage 5 rejects over-cap confidence; it never clamps-and-passes."""

    @pytest.mark.parametrize(
        "hypothesis",
        [
            "Refund probe with confidence 0.95 needs review.",
            "Refund probe with confidence: 95% for review.",
            "Refund probe with 95% confidence needs review.",
            "Refund probe, confident at 0.99, needs review.",
        ],
        ids=["decimal", "percent-sign", "leading-percent", "confident"],
    )
    def test_declared_confidence_above_cap_rejected(self, hypothesis: str) -> None:
        """Arrange over-cap text; Act; Assert confidence violation."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(hypothesis=hypothesis)
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert any(r.startswith("confidence_violation:") for r in verdict.reasons)

    def test_explicit_confidence_field_above_cap_rejected(self) -> None:
        """Arrange 0.99 attribute; Act; Assert field-confidence violation."""
        # Arrange.
        verifier = Verifier()
        plan = _with_confidence(_plan(), 0.99)
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert any("field_confidence" in r for r in verdict.reasons)

    def test_confidence_at_cap_accepted(self) -> None:
        """Arrange exactly 0.85; Act; Assert ACCEPTED (cap is inclusive)."""
        # Arrange.
        verifier = Verifier()
        plan = _with_confidence(
            _plan(hypothesis="Refund probe with confidence 0.85 needs review."), 0.85
        )
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "ACCEPTED"
        assert verdict.reasons == ()


class TestBoundsAndBudget:
    """Stage 6 plus the budget gate bound excessive plans and replans."""

    def test_hypothesis_over_ceiling_rejected(self) -> None:
        """Arrange 2001-char text; Act; Assert bounds length code."""
        # Arrange.
        verifier = Verifier()
        plan = _raw_plan(hypothesis_text="h" * (MAX_HYPOTHESIS_CHARS + 1))
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == (
            f"bounds_violation:hypothesis_text_len_{MAX_HYPOTHESIS_CHARS + 1}"
            f"_gt_max_{MAX_HYPOTHESIS_CHARS}",
        )

    def test_too_many_evidence_ids_rejected(self) -> None:
        """Arrange 33 ids; Act; Assert bounds count code."""
        # Arrange.
        verifier = Verifier()
        ids = tuple(f"ev-{i:03d}" for i in range(MAX_EVIDENCE_REQUIRED + 1))
        plan = _raw_plan(evidence_required=ids)
        available = set(ids) | set(_AVAILABLE)
        # Act.
        verdict = verifier.verify(plan, available, 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == (
            f"bounds_violation:evidence_required_{MAX_EVIDENCE_REQUIRED + 1}"
            f"_gt_max_{MAX_EVIDENCE_REQUIRED}",
        )

    def test_oversize_arg_key_rejected(self) -> None:
        """Arrange long key; Act; Assert bounds key-length code."""
        # Arrange.
        verifier = Verifier()
        bad = CapabilityCall.model_construct(
            capability="get_stripe_payment",
            args={"k" * (MAX_ARG_KEY_CHARS + 1): "v"},
            order_index=0,
        )
        plan = _raw_plan(capability_calls=(bad,))
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons[0].startswith("bounds_violation:calls[0].arg_key_len_")

    def test_oversize_arg_value_rejected(self) -> None:
        """Arrange long value; Act; Assert bounds value-length code."""
        # Arrange.
        verifier = Verifier()
        bad = CapabilityCall.model_construct(
            capability="get_stripe_payment",
            args={"payment_id": "x" * (MAX_ARG_VALUE_CHARS + 1)},
            order_index=0,
        )
        plan = _raw_plan(capability_calls=(bad,))
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons[0].startswith("bounds_violation:calls[0].arg_value_len_")

    def test_excessive_calls_rejected(self) -> None:
        """Arrange nine calls; Act; Assert schema ceiling, never executed."""
        # Arrange.
        verifier = Verifier()
        calls = tuple(
            CapabilityCall.model_construct(
                capability="get_stripe_payment",
                args={"payment_id": f"pay_{i:03d}"},
                order_index=i,
            )
            for i in range(9)
        )
        plan = _raw_plan(capability_calls=calls)
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == ("schema_violation:capability_calls_9_gt_max_8",)

    @pytest.mark.parametrize("attempt", [-1, "0", 1.5, None])
    def test_malformed_attempt_fails_closed_without_escalation(self, attempt: Any) -> None:
        """Arrange bad attempt; Act; Assert fail-closed REJECTED_REPLAN."""
        # Arrange.
        verifier = Verifier()
        plan = _plan()
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), attempt)
        # Assert.
        assert verdict.status == "REJECTED_REPLAN"
        assert verdict.reasons == ("bounds_violation:attempt_must_be_non_negative_int",)

    def test_excessive_replans_escalate_hitl(self) -> None:
        """Arrange failing plan; Act at/past max; Assert ESCALATE_HITL."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(evidence=("ev-unknown-999",))
        # Act.
        at_max = verifier.verify(plan, {"ev-ledger-001"}, DEFAULT_MAX_REPLANS)
        past_max = verifier.verify(plan, {"ev-ledger-001"}, DEFAULT_MAX_REPLANS + 1)
        # Assert.
        for verdict in (at_max, past_max):
            assert verdict.status == "ESCALATE_HITL"
            assert "grounding_violation:unknown_evidence_id:ev-unknown-999" in verdict.reasons
            assert any(r.startswith("budget_exhausted:") for r in verdict.reasons)


class TestReplanBounds:
    """Re-plan never relaxes: identical bounds and authority every attempt."""

    def test_allowlist_identical_every_attempt(self) -> None:
        """Arrange bad capability; Act attempts 0/1/max; Assert same reasons."""
        # Arrange.
        verifier = Verifier()
        bad = CapabilityCall.model_construct(
            capability="read_database", args={"table": "ledger"}, order_index=0
        )
        plan = _raw_plan(capability_calls=(bad,))
        # Act.
        first = verifier.verify(plan, set(_AVAILABLE), 0)
        second = verifier.verify(plan, set(_AVAILABLE), 1)
        exhausted = verifier.verify(plan, set(_AVAILABLE), DEFAULT_MAX_REPLANS)
        # Assert.
        assert first.status == "REJECTED_REPLAN"
        assert second.status == "REJECTED_REPLAN"
        assert first.reasons == second.reasons == ("allowlist_violation:read_database",)
        assert exhausted.status == "ESCALATE_HITL"
        assert exhausted.reasons[:1] == first.reasons
        assert verifier.max_replans == DEFAULT_MAX_REPLANS
        assert verifier.confidence_cap == DEFAULT_CONFIDENCE_CAP

    def test_authority_never_expands_on_replan(self) -> None:
        """Arrange approval plan; Act 0/1; Assert identical rejection."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(hypothesis="Refund probe. Please approve the review.")
        # Act.
        first = verifier.verify(plan, set(_AVAILABLE), 0)
        second = verifier.verify(plan, set(_AVAILABLE), 1)
        # Assert.
        assert first.status == "REJECTED_REPLAN"
        assert second.status == "REJECTED_REPLAN"
        assert first.reasons == second.reasons
        assert "never_violation:declare_approval" in second.reasons

    def test_escalation_flag_grants_no_authority(self) -> None:
        """Arrange escalation=True; Act; Assert still ACCEPTED shape, no grant."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(escalation=True)
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        # Assert.
        assert verdict.status == "ACCEPTED"
        assert verdict.reasons == ()
        assert plan.escalation is True

    def test_budget_exhaustion_preserves_attempts_and_reasons(self) -> None:
        """Arrange failure; Act at max; Assert attempt kept plus exhausted code."""
        # Arrange.
        verifier = Verifier()
        plan = _plan(hypothesis="The lag is verified in the ledger.")
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), DEFAULT_MAX_REPLANS)
        # Assert.
        assert verdict.status == "ESCALATE_HITL"
        assert verdict.attempt_index == DEFAULT_MAX_REPLANS
        assert "never_violation:declare_verified" in verdict.reasons
        assert verdict.reasons[-1] == (
            f"budget_exhausted:attempt_{DEFAULT_MAX_REPLANS}_gte_max_{DEFAULT_MAX_REPLANS}"
        )


class TestProviderFailureAndTotality:
    """Malformed inputs fail closed as verdicts; the verifier never raises."""

    @pytest.mark.parametrize(
        "garbage",
        [None, 123, "plan", [], {}, {"error": "timeout"}, object()],
        ids=["none", "int", "string", "list", "dict", "error-dict", "object"],
    )
    def test_provider_failure_shaped_plan_returns_rejected(self, garbage: Any) -> None:
        """Arrange provider-shaped garbage; Act; Assert REJECTED, never raises."""
        # Arrange.
        verifier = Verifier()
        # Act.
        verdict = verifier.verify(garbage, set(_AVAILABLE), 0)
        # Assert.
        assert isinstance(verdict, Verdict)
        assert verdict.status == "REJECTED_REPLAN"
        assert len(verdict.reasons) == 1
        assert verdict.reasons[0].startswith("schema_violation:not_investigation_plan:")

    @pytest.mark.parametrize(
        "garbage",
        [None, 0, 3.14, {"hypothesis_text": "x"}, ["ev-ledger-001"], object()],
        ids=["none", "zero", "float", "dict", "list", "object"],
    )
    def test_verifier_never_raises_on_garbage_input(self, garbage: Any) -> None:
        """Arrange garbage plans; Act; Assert a frozen verdict is returned."""
        # Arrange.
        verifier = Verifier()
        # Act.
        verdict = verifier.verify(garbage, set(_AVAILABLE), 0)
        # Assert.
        assert isinstance(verdict, Verdict)
        assert verdict.status in ("ACCEPTED", "REJECTED_REPLAN", "ESCALATE_HITL")
        assert verdict.attempt_index == 0

    def test_constructor_rejects_bad_bounds(self) -> None:
        """Arrange bad bounds; Act construct; Assert TypeError/ValueError."""
        # Arrange.
        valid_cap = DEFAULT_CONFIDENCE_CAP
        valid_max = DEFAULT_MAX_REPLANS
        # Act + Assert.
        with pytest.raises(TypeError):
            Verifier(max_replans=True, confidence_cap=valid_cap)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            Verifier(max_replans=-1, confidence_cap=valid_cap)
        with pytest.raises(TypeError):
            Verifier(max_replans=valid_max, confidence_cap="high")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            Verifier(max_replans=valid_max, confidence_cap=1.5)


class TestZeroP3Mutation:
    """Verify runs mutate no financial facts and no execution state."""

    def test_p1_reconcile_identical_before_and_after_verify(self) -> None:
        """Arrange legs; Act verify; Assert P1 verdict identical."""
        # Arrange.
        processor = _leg("proc-verifier", "50000.00", "0.00", "15000.00", "35000.00")
        ledger = _leg("ledger-verifier", "50000.00", "0.00", "0.00", "50000.00")
        tolerance = ReconciliationTolerance()
        before = reconcile(processor, ledger, tolerance)
        verifier = Verifier()
        plan = _plan()
        # Act.
        verdict = verifier.verify(plan, set(_AVAILABLE), 0)
        after = reconcile(processor, ledger, tolerance)
        # Assert.
        assert verdict.status == "ACCEPTED"
        assert after == before
        assert after.difference == before.difference

    def test_verify_leaves_plan_unchanged(self) -> None:
        """Arrange plan dump; Act verify twice; Assert byte-identical plan."""
        # Arrange.
        verifier = Verifier()
        plan = _plan()
        dumped_before = plan.model_dump_json()
        # Act.
        first = verifier.verify(plan, set(_AVAILABLE), 0)
        second = verifier.verify(plan, set(_AVAILABLE), 1)
        # Assert.
        assert plan.model_dump_json() == dumped_before
        assert first.status == "ACCEPTED"
        assert second.status == "ACCEPTED"

    def test_verification_imports_no_forbidden_modules(self) -> None:
        """Arrange verifier sources; Act AST scan; Assert no finance/apps/LLM."""
        # Arrange.
        package = Path(__file__).resolve().parents[3] / "agents" / "verification"
        modules: dict[str, list[str]] = {
            name: _import_modules(package / name) for name in ("verifier.py", "verdict.py")
        }
        roots = {name: _import_roots(package / name) for name in ("verifier.py", "verdict.py")}
        # Act + Assert.
        assert modules["verifier.py"], "expected verifier imports to scan"
        for name, imports in modules.items():
            assert not [
                module for module in imports if module == "finance" or module.startswith("finance.")
            ], f"{name} must not import finance execution"
            assert not [
                module for module in imports if module == "apps" or module.startswith("apps.")
            ], f"{name} must not import apps"
        for name, root_set in roots.items():
            banned_frameworks = (
                "langchain",
                "langgraph",
                "litellm",
                "groq",
                "openai",
                "httpx",
                "requests",
            )
            for banned in banned_frameworks:
                assert banned not in root_set, f"{name} must not import {banned}"
