"""Integration: flagship steps 1-2 via fixtures + P1 core, zero LLM (P2.4).

Flagship scope is steps 1-2 only (no QB-write, no HITL, no Gmail):

* Step 1 (setup): 50k charge vs 50k ledger closes ``MATCHED``.
* Step 2 (break): processor net 35k (50k gross - 15k refund) vs ledger net
  50k (refund not yet booked) yields ``EXCEPTION`` /
  ``PARTIAL_REFUND_ACCOUNTING_LAG`` (``I-REFUND-LAG``) / ``MATERIAL`` with
  a 15000 break in exact ``Decimal`` arithmetic.

Fixtures live in ``tests/fixtures/reconciliation/stripe/`` and carry money
as strings (parsed to ``Decimal`` here — never ``float``). Determinism plus
the forbidden-import scan below prove the zero-LLM path: the reconciler,
matcher, classifier, tolerances, fingerprints, models, and normalizer touch
no LLM, network, DB, clock, or randomness modules.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from finance.reconciliation.classifier import classify
from finance.reconciliation.ledger_resolution import (
    InMemoryLedgerRepository,
    LedgerKey,
    LedgerResolution,
    ResolutionStatus,
    project_canonical_processor,
    resolve_payment,
    stub_processor_from_stripe_records,
)
from finance.reconciliation.models import (
    ExceptionCode,
    MaterialityVerdict,
    PaymentRecord,
    ReconciliationOutcome,
)
from finance.reconciliation.normalizer import normalize
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "reconciliation" / "stripe"
ZERO = ReconciliationTolerance()


def _load(name: str) -> dict[str, object]:
    """Load one JSON fixture as a raw mapping."""
    return dict(json.loads((FIXTURES / name).read_text()))  # type: ignore[arg-type]


@pytest.mark.integration
class TestFlagshipStepsOneAndTwo:
    """Steps 1-2 of the flagship: setup MATCHED, then the refund-lag break."""

    def test_step1_charge_50k_vs_ledger_50k_is_matched(self) -> None:
        """Arrange 50k processor + 50k ledger; Assert MATCHED, zero diff."""
        charge = normalize(_load("charge_50000.json"))
        legs = _load("ledger_legs.json")
        ledger_before = normalize(legs["ledger_before"])  # type: ignore[arg-type]
        assert charge.net == Decimal("50000")
        assert ledger_before.net == Decimal("50000")
        result = reconcile(charge, ledger_before, ZERO)
        assert result.outcome is ReconciliationOutcome.MATCHED
        assert result.difference == Decimal("0.00")
        assert result.exception_code is None
        assert result.materiality is MaterialityVerdict.IMMATERIAL

    def test_step2_refund_15k_net_35k_vs_ledger_50k_is_refund_lag(self) -> None:
        """Arrange 35k expected vs 50k observed; Assert lag EXCEPTION MATERIAL."""
        refund = normalize(_load("refund_15000.json"))
        legs = _load("ledger_legs.json")
        ledger_before = normalize(legs["ledger_before"])  # type: ignore[arg-type]
        assert refund.net == Decimal("35000")
        assert ledger_before.net == Decimal("50000")
        result = reconcile(refund, ledger_before, ZERO)
        assert result.outcome is ReconciliationOutcome.EXCEPTION
        assert result.expected == Decimal("35000.00")
        assert result.observed == Decimal("50000.00")
        assert result.difference == Decimal("15000.00")
        assert result.variance == Decimal("15000.00")
        assert result.exception_code == ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG.value
        assert result.exception_code == "I-REFUND-LAG"
        assert result.materiality is MaterialityVerdict.MATERIAL
        assert classify(refund, ledger_before) is ExceptionCode.PARTIAL_REFUND_ACCOUNTING_LAG

    def test_step2_ledger_leg_fixture_agrees_with_processor_math(self) -> None:
        """Ledger-before (50k) minus the 15k refund equals the 35k expectation."""
        refund = normalize(_load("refund_15000.json"))
        legs = _load("ledger_legs.json")
        ledger_before = normalize(legs["ledger_before"])  # type: ignore[arg-type]
        processor_declared = normalize(legs["processor_net_35000"])  # type: ignore[arg-type]
        assert processor_declared.net == refund.net == Decimal("35000")
        assert ledger_before.net - refund.net == Decimal("15000")
        assert refund.gross == ledger_before.gross == Decimal("50000")


@pytest.mark.integration
class TestFlagshipUsesZeroLlmCalls:
    """Determinism + forbidden-import scan prove the zero-LLM path."""

    def test_reconcile_is_deterministic_across_runs(self) -> None:
        """Two runs over the same legs are byte-identical."""
        refund = normalize(_load("refund_15000.json"))
        legs = _load("ledger_legs.json")
        ledger_before = normalize(legs["ledger_before"])  # type: ignore[arg-type]
        first = reconcile(refund, ledger_before, ZERO)
        second = reconcile(refund, ledger_before, ZERO)
        assert first == second
        assert first.fingerprint == second.fingerprint
        assert first.difference == Decimal("15000.00")

    def test_pure_core_has_no_llm_network_db_clock_imports(self) -> None:
        """Scan P1 sources: no LLM, HTTP, DB, socket, clock, or random use."""
        package = Path(__file__).resolve().parents[2] / "finance" / "reconciliation"
        forbidden = (
            "import openai",
            "import anthropic",
            "import langchain",
            "import litellm",
            "import httpx",
            "import requests",
            "import urllib",
            "import socket",
            "import psycopg",
            "import sqlalchemy",
            "import random",
            "from openai",
            "from anthropic",
            "from langchain",
            "from litellm",
            "from httpx",
            "from requests",
            "from urllib",
            "from socket",
            "from random",
            "datetime.now(",
        )
        sources = "".join(
            (package / name).read_text()
            for name in (
                "reconciler.py",
                "matcher.py",
                "classifier.py",
                "tolerances.py",
                "fingerprints.py",
                "models.py",
                "normalizer.py",
            )
        ).lower()
        for token in forbidden:
            assert token not in sources, f"pure core must not reference {token}"
        for module in ("openai", "anthropic", "langchain_core", "litellm"):
            assert module not in sys.modules, f"LLM module {module} must not load"


LEDGER_KEY = LedgerKey(tenant_id="tenant-acme", provider="ledger", payment_id="ledger-flagship")


def _seeded_repo() -> InMemoryLedgerRepository:
    """Seed the deterministic ledger repo from the ``ledger_legs`` fixture."""
    legs = _load("ledger_legs.json")
    ledger_before = normalize(legs["ledger_before"])  # type: ignore[arg-type]
    return InMemoryLedgerRepository.from_records([ledger_before])


@pytest.mark.integration
class TestCommit3BLedgerLookupReconcileStop:
    """Commit 3B: fixture lookup -> frozen P1 reconcile -> verdict, STOP."""

    def test_checkpoint_charge_50k_refund_15k_lag_material_stop(self) -> None:
        """Full checkpoint trace: 50k/15k -> canonical 35k -> 15k lag MATERIAL."""
        charge = normalize(_load("charge_50000.json"))
        refund = normalize(_load("refund_15000.json"))
        canonical = stub_processor_from_stripe_records(charge, [refund])
        assert canonical.gross == Decimal("50000")
        assert canonical.refund == Decimal("15000")
        assert canonical.net == Decimal("35000")
        resolution = resolve_payment(canonical, LEDGER_KEY, _seeded_repo(), ZERO)
        assert isinstance(resolution, LedgerResolution)
        assert resolution.status is ResolutionStatus.EXCEPTION
        assert resolution.ledger is not None and resolution.ledger.net == Decimal("50000")
        assert resolution.result is not None
        assert resolution.result.difference == Decimal("15000.00")
        assert resolution.result.exception_code == "I-REFUND-LAG"
        assert resolution.result.materiality is MaterialityVerdict.MATERIAL

    def test_step1_matched_is_closed_path_data(self) -> None:
        """Unrefunded 50k charge vs 50k ledger resolves MATCHED via 3B wiring."""
        charge = normalize(_load("charge_50000.json"))
        canonical = project_canonical_processor(charge, [])
        assert canonical.net == Decimal("50000")
        resolution = resolve_payment(canonical, LEDGER_KEY, _seeded_repo(), ZERO)
        assert resolution.status is ResolutionStatus.MATCHED
        assert resolution.result is not None
        assert resolution.result.outcome is ReconciliationOutcome.MATCHED
        assert resolution.result.difference == Decimal("0.00")
        assert resolution.result.exception_code is None

    def test_missing_reference_is_deterministic_missing_state(self) -> None:
        """Unknown (tenant, provider, payment) triple -> LEDGER_RECORD_MISSING."""
        canonical = stub_processor_from_stripe_records(
            normalize(_load("charge_50000.json")), [normalize(_load("refund_15000.json"))]
        )
        missing = LedgerKey(tenant_id="tenant-acme", provider="ledger", payment_id="ledger-unknown")
        first = resolve_payment(canonical, missing, _seeded_repo(), ZERO)
        second = resolve_payment(canonical, missing, _seeded_repo(), ZERO)
        assert first.status is ResolutionStatus.LEDGER_RECORD_MISSING
        assert first == second
        assert first.ledger is None
        assert first.result is None

    def test_refunds_accumulate_from_persisted_records_not_latest_payload(self) -> None:
        """Two persisted refunds (15k + 5k) project 30k net, never payload net."""
        charge = normalize(_load("charge_50000.json"))
        first_refund = normalize(_load("refund_15000.json"))
        second_raw = dict(_load("refund_15000.json"))
        second_raw["provider_event_id"] = "evt-flagship-refund-2"
        second_raw["idempotency_key"] = "stripe-flagship-001-refund-2"
        second_raw["refund_minor"] = 500000
        second_raw["occurred_at"] = "2026-05-02T13:00:00Z"
        second_refund = normalize(second_raw)
        assert isinstance(second_refund, PaymentRecord)
        canonical = project_canonical_processor(charge, [first_refund, second_refund])
        assert canonical.refund == Decimal("20000")
        assert canonical.net == Decimal("30000")
        assert canonical.net == charge.gross - charge.fee - (
            first_refund.refund + second_refund.refund
        )
        resolution = resolve_payment(canonical, LEDGER_KEY, _seeded_repo(), ZERO)
        assert resolution.status is ResolutionStatus.EXCEPTION
        assert resolution.result is not None
        assert resolution.result.difference == Decimal("20000.00")

    def test_3b_module_has_no_investigation_llm_hitl_or_write_imports(self) -> None:
        """AST scan of 3B source: no LLM/HITL/QB/Sheets/network dependencies."""
        import ast

        module = (
            Path(__file__).resolve().parents[2]
            / "finance"
            / "reconciliation"
            / "ledger_resolution.py"
        )
        text = module.read_text()
        tree = ast.parse(text)
        forbidden_top_levels = {
            "groq",
            "openai",
            "anthropic",
            "langchain",
            "langchain_core",
            "litellm",
            "httpx",
            "requests",
            "sqlalchemy",
            "random",
        }
        forbidden_names = {"hitl", "quickbooks", "sheets", "gmail"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0].lower()
                    assert root not in forbidden_top_levels, (
                        f"3B module must not import {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0].lower()
                assert root not in forbidden_top_levels | forbidden_names, (
                    f"3B module must not import from {node.module}"
                )
            elif isinstance(node, ast.Name):
                assert node.id.lower() not in forbidden_names, f"3B module must not bind {node.id}"
            elif isinstance(node, ast.Attribute):
                assert node.attr.lower() not in forbidden_names, (
                    f"3B module must not touch .{node.attr}"
                )
        # The STOP boundary is documented in the module docstring.
        assert "STOP" in text
