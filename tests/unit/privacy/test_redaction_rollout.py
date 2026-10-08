"""P10-04 RED: rollout surfaces must not leak raw sensitive data (failing).

Each test drives a real operational surface with hostile input and
asserts the persisted/emitted artifact contains no raw secrets, PII,
or (for logs) financial values:

- telemetry trace files (query/steps/results/summaries);
- audit rows (free-text reason; actor ids stay for accountability);
- executor log records (caplog over a real run);
- provider call telemetry (lock-in: metadata only by design).

Pure unit tests (tmp_path, in-memory/file SQLite, caplog). No network.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SECRET = "sk-test-synthetic-secret-value"
EMAIL = "rahul@example.com"


def _seed_repo(engine: Any) -> Any:
    """Create one aggregate at EXCEPTION for audit-write tests."""
    from finance.exceptions.aggregate import ExceptionAggregate
    from finance.exceptions.repository import ExceptionRepository
    from finance.reconciliation.models import ExceptionCode

    repo = ExceptionRepository(engine)
    aggregate = ExceptionAggregate.create(
        exception_id="exc-roll-1",
        tenant_id="tenant-acme",
        reconciliation_result_id="recon-roll-1",
        exception_type=ExceptionCode.FEE_MISMATCH,
        severity="HIGH",
        created_at=datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC),
    )
    repo.create(aggregate, actor="seeder")
    return repo


class TestTelemetryFiles:
    def test_capture_scrubs_query_and_step_results(self, tmp_path: Path) -> None:
        from finance.cognition.state.models import ReasoningState
        from finance.cognition.telemetry import ReasoningTelemetry

        telemetry = ReasoningTelemetry(output_dir=str(tmp_path))
        state = ReasoningState(query=f"why did {EMAIL} get charged")
        state.record_step(
            "planner",
            {"api_key": SECRET, "note": f"mail {EMAIL}"},
            confidence=0.9,
            message=f"contact {EMAIL}",
        )
        path = telemetry.capture(run_id="run-roll-1", state=state)
        text = Path(path).read_text(encoding="utf-8")
        assert SECRET not in text
        assert EMAIL not in text
        assert "run-roll-1" in text

    def test_capture_keeps_structure_usable(self, tmp_path: Path) -> None:
        from finance.cognition.state.models import ReasoningState
        from finance.cognition.telemetry import ReasoningTelemetry

        telemetry = ReasoningTelemetry(output_dir=str(tmp_path))
        state = ReasoningState(query="clean query")
        path = telemetry.capture(run_id="run-roll-2", state=state)
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        assert payload["run_id"] == "run-roll-2"
        assert payload["query"] == "clean query"


class TestAuditWrite:
    def test_rejection_reason_scrubbed_actor_preserved(self) -> None:
        from tests.unit.execution.test_executor import _engine

        engine = _engine()
        repo = _seed_repo(engine)
        snapshot = repo.get("exc-roll-1")
        assert snapshot is not None
        repo._audit_rejection(
            snapshot,
            "CLOSED",
            f"reviewer-{EMAIL}",
            f"duplicate of {EMAIL}, key {SECRET}",
        )
        trail = repo.audit_trail("exc-roll-1")
        assert trail, "rejection must be audited"
        reasons = " ".join(a.reason for a in trail)
        assert SECRET not in reasons
        assert EMAIL not in reasons
        actors = " ".join(a.actor for a in trail)
        assert f"reviewer-{EMAIL}" in actors

    def test_stripe_amounts_never_logged(self, caplog: Any) -> None:
        from finance.stripe.adapter import stripe_to_normalized

        event = {
            "id": "evt_roll_1",
            "type": "charge.succeeded",
            "created": 1767225600,
            "data": {
                "object": {
                    "id": "ch_roll_1",
                    "amount": 1500000,
                    "currency": "usd",
                    "created": 1767225600,
                    "application_fee_amount": 25000,
                }
            },
        }
        with caplog.at_level(logging.INFO):
            stripe_to_normalized(event, tenant_id="tenant-acme")
        assert "gross=15000" not in caplog.text


class TestExecutorLogs:
    def test_secret_idempotency_key_never_logged(self, caplog: Any, tmp_path: Path) -> None:
        from finance.accounting.mock import MockQuickBooksAdapter
        from tests.unit.execution.test_execution_boundary import _Seed
        from tests.unit.execution.test_executor import _engine, _make_executor

        engine = _engine()
        seed = _Seed(engine)
        with caplog.at_level(logging.INFO):
            _make_executor(MockQuickBooksAdapter(), engine).run(
                seed.approved, seed.proposal, seed.approval, SECRET
            )
        assert SECRET not in caplog.text

    def test_email_shaped_ids_never_logged(self, caplog: Any) -> None:
        from finance.accounting.mock import MockQuickBooksAdapter
        from tests.unit.execution.test_execution_boundary import _Seed
        from tests.unit.execution.test_executor import _engine, _make_executor

        engine = _engine()
        seed = _Seed(engine)
        with caplog.at_level(logging.INFO):
            _make_executor(MockQuickBooksAdapter(), engine).run(
                seed.approved, seed.proposal, seed.approval, f"key-{EMAIL}"
            )
        assert EMAIL not in caplog.text


class TestProviderTelemetry:
    def test_call_journal_carries_no_prompt_or_pii(self) -> None:
        from pydantic import BaseModel

        from shared.llm.fake import FakeLLM
        from shared.llm.types import InvestigationPrompt

        class _Out(BaseModel):
            ok: bool

        fake = FakeLLM(scripted={"_Out": {"ok": True}})
        prompt = InvestigationPrompt(user_prompt=f"contact {EMAIL}, key {SECRET}")
        fake.generate_structured(prompt, _Out)
        blob = str(fake.journal)
        assert EMAIL not in blob
        assert SECRET not in blob
        assert "contact" not in blob
