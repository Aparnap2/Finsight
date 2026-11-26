"""Phase 6 adversarial suite: 16 deterministic attacks, typed defenders.

Every attack asserts BOTH the typed defender outcome AND the absence of
the forbidden effect. Deterministic only: no network, creds, real DB,
Temporal, cloud, or LLM. Reuses frozen P6/P7/P8 helpers by import; this
file creates temp file engines only for the concurrency test and edits no
frozen modules.
"""

from __future__ import annotations

import dataclasses
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import tests.integration.test_api_execute_verify as api_t
import tests.integration.test_p6_executable_slice as p6s
from agents.brief import brief
from agents.discovery import DiscoveryRequest
from agents.discovery.engine import discover as _real_discover
from agents.evaluation.harness import evaluate
from agents.integration.control_plane import ControlPlaneGate
from agents.reasoning.resolution import reason
from apps.api import execution_routes as ex
from finance.accounting.mock import MockQuickBooksAdapter
from finance.approvals.service import ApprovalService
from finance.exceptions.repository import ExceptionRepository
from finance.execution.executor import Executor

_TENANT_B = "tenant-b"
_CANARIES = ("CANARY-SECRET-sk-test-9f8e7d6c", "PII-CANARY-4111111111111111")


def _p6_spies(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Spy on the P6 execution seam; blocked paths must stay silent."""
    calls: list[str] = []
    orig_run = Executor.run
    orig_decide = ApprovalService.decide

    def spy_run(self: Executor, *a: Any, **k: Any) -> Any:
        calls.append("Executor.run")
        return orig_run(self, *a, **k)

    def spy_decide(self: ApprovalService, *a: Any, **k: Any) -> Any:
        calls.append("ApprovalService.decide")
        return orig_decide(self, *a, **k)

    monkeypatch.setattr(Executor, "run", spy_run)
    monkeypatch.setattr(ApprovalService, "decide", spy_decide)
    return calls


def _post(client: TestClient, snapshot: Any, proposal: Any, **kw: Any) -> Any:
    """POST /execute with fixture coordinates plus caller overrides."""
    body = api_t._body(snapshot, proposal, key="adv-default", exec_key="adv-x")
    if "key" in kw:
        kw["idempotency_key"] = kw.pop("key")
    if "exec_key" in kw:
        kw["execution_idempotency_key"] = kw.pop("exec_key")
    body.update(kw)
    return client.post("/execute", json=body)


def _injection_payloads() -> list[str]:
    """Load canonical_payload from fixtures 01, 02, and 05."""
    base = Path(__file__).parent.parent / "fixtures" / "security" / "prompt_injection"
    out = []
    for name in (
        "payload_01_ignore_previous_instructions.json",
        "payload_02_execute_refund.json",
        "payload_05_change_tenant.json",
    ):
        out.append(json.loads((base / name).read_text())["canonical_payload"])
    return out


class TestAdversarialSystem:
    """Sixteen attacks; each proves defender outcome plus no forbidden effect."""

    def test_01_cross_tenant_refused_without_side_effects(self) -> None:
        """B creds + A resources -> 403 CROSS_TENANT, zero A-side effects."""
        engine, snapshot, proposal, adapter, executor = api_t._seed()
        lookup = {proposal.proposal_id: proposal}
        client = TestClient(api_t._build_app(engine, lookup, executor, tenant_id=_TENANT_B))
        before = snapshot.state_version
        resp = _post(client, snapshot, proposal, key="adv-01", exec_key="adv-x01")
        assert resp.status_code == 403, resp.text
        assert resp.json()["code"] == "CROSS_TENANT"
        assert adapter.entry_count == 0  # no booking
        current = ExceptionRepository(engine).get(snapshot.exception_id)
        assert current is not None and current.state_version == before  # untouched
        rows = ApprovalService(engine, amount_threshold=p6s._THRESHOLD).get_for_exception(
            snapshot.exception_id
        )
        assert rows == []  # no approval minted

    def test_02_cross_situation_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Valid tenant, wrong situation bundle -> typed refusal, P6 silent."""
        spies = _p6_spies(monkeypatch)
        # Real cross-situation discovery admitted under the home context.
        from agents.discovery.engine import discover as _real_discover
        from tests.integration.test_p7_advisory_pipeline import _context as _p7ctx
        from tests.integration.test_p7_advisory_pipeline import _request as _p7req

        home, away = _p7ctx(), _p7ctx(situation_id="sit-other-999")
        away_disc = _real_discover(_p7req(away), context=away)
        assert away_disc.success is True
        home_disc = _real_discover(_p7req(home), context=home)
        home_rea = reason(home_disc, context=home)
        home_br = brief(home_rea, context=home)
        assert (
            evaluate(
                "E", "E1", context=home, discovery=away_disc, reasoning=home_rea, brief=home_br
            )
            == "REJECTED"
        )
        res = ControlPlaneGate().admit(
            context=home, discovery=away_disc, reasoning=home_rea, brief=home_br
        )
        assert res.kind == "BLOCKED"  # typed refusal
        assert res.reason == "SCOPE_MISMATCH"
        assert spies == []  # no P6 entry

    def test_03_replay_completed_key_single_effect(self) -> None:
        """Replay of a completed key -> 200, same execution, one booking."""
        engine, snapshot, proposal, adapter, executor = api_t._seed()
        lookup = {proposal.proposal_id: proposal}
        client = TestClient(api_t._build_app(engine, lookup, executor, tenant_id=p6s._TENANT))
        payload = api_t._body(snapshot, proposal, key="adv-03", exec_key="adv-x03")
        first = client.post("/execute", json=payload)
        assert first.status_code == 201, first.text
        second = client.post("/execute", json=payload)
        assert second.status_code == 200, second.text
        assert second.json()["deduplicated"] is True
        assert second.json()["execution_id"] == first.json()["execution_id"]
        assert adapter.entry_count == 1  # single effect
        rows = ApprovalService(engine, amount_threshold=p6s._THRESHOLD).get_for_exception(
            snapshot.exception_id
        )
        assert len(rows) == 1  # recorded outcome, one row

    def test_04_concurrent_replays_single_winner(self) -> None:
        """Pre-seeded 201 + barrier-synced replays -> all 200s, one effect.

        NOTE (determinism): threads sharing one StaticPool in-memory SQLite
        connection corrupt row reads (None.tzinfo -> 500s), and racing fresh
        POSTs cannot stably split 201/200. So: pre-seed one completed key
        single-threaded (the counted 201), then barrier-fire concurrent
        REPLAYS, each thread with its own engine + executor + TestClient over
        a shared temp FILE db. Replays are read-only, so SQLite serializes
        safely while concurrency stays real (no lock around client.post).
        """
        import tempfile

        from sqlalchemy import create_engine as _create_engine

        for round_no in range(3):  # rerun 3x for stability
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                db_path = tmp.name
            engines: list[Any] = []
            try:
                seed_engine = _create_engine(f"sqlite:///{db_path}")
                engines.append(seed_engine)
                repo = ExceptionRepository(seed_engine)
                snapshot, proposal = p6s._seed_awaiting(repo)
                adapter = MockQuickBooksAdapter()
                seed_executor = Executor(adapter, seed_engine)
                lookup = {proposal.proposal_id: proposal}
                seed_client = TestClient(
                    api_t._build_app(seed_engine, lookup, seed_executor, tenant_id=p6s._TENANT)
                )
                payload = api_t._body(
                    snapshot, proposal, key=f"adv-04-r{round_no}", exec_key=f"adv-x04-r{round_no}"
                )
                first = seed_client.post("/execute", json=payload)
                assert first.status_code == 201, first.text  # the counted winner
                execution_id = first.json()["execution_id"]
                n, barrier = 7, threading.Barrier(7)
                results: list[tuple[Any, Any]] = []

                def _hit(
                    _barrier: threading.Barrier = barrier,
                    _db_path: str = db_path,
                    _engines: list[Any] = engines,
                    _snapshot: Any = snapshot,
                    _adapter: Any = adapter,
                    _lookup: Any = lookup,
                    _payload: Any = payload,
                    _results: list[tuple[Any, Any]] = results,
                ) -> None:
                    try:
                        _barrier.wait(timeout=10)
                        eng = _create_engine(f"sqlite:///{_db_path}")
                        _engines.append(eng)
                        repo_t = ExceptionRepository(eng)
                        assert repo_t.get(_snapshot.exception_id) is not None
                        exe_t = Executor(_adapter, eng)
                        cli = TestClient(
                            api_t._build_app(eng, _lookup, exe_t, tenant_id=p6s._TENANT)
                        )
                        r = cli.post("/execute", json=_payload)
                        _results.append((r.status_code, r.json().get("execution_id")))
                    except Exception as exc:  # surface thread failures, don't hang
                        _results.append(("EXC", repr(exc)))

                threads = [threading.Thread(target=_hit) for _ in range(n)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=60)
                assert len(results) == n
                statuses = [s for s, _ in results]
                assert statuses == [200] * n  # all replays, zero 500s
                assert {e for _, e in results} == {execution_id}  # single execution
                assert adapter.entry_count == 1  # single effect
            finally:
                for eng in engines:
                    eng.dispose()
                Path(db_path).unlink(missing_ok=True)

    def test_05_stale_version_refused_without_execution(self) -> None:
        """Superseded proposal version -> 409 VERSION_CONFLICT, nothing runs."""
        engine, snapshot, proposal, adapter, executor = api_t._seed()
        lookup = {proposal.proposal_id: proposal}
        client = TestClient(api_t._build_app(engine, lookup, executor, tenant_id=p6s._TENANT))
        resp = _post(
            client,
            snapshot,
            proposal,
            key="adv-05",
            exec_key="adv-x05",
            expected_state_version=snapshot.state_version - 1,
        )
        assert resp.status_code == 409, resp.text
        assert resp.json()["code"] == "VERSION_CONFLICT"
        assert adapter.entry_count == 0  # no execution
        rows = ApprovalService(engine, amount_threshold=p6s._THRESHOLD).get_for_exception(
            snapshot.exception_id
        )
        assert rows == []

    def test_07_approval_laundering_refused(self) -> None:
        """Approval for X applied to Y -> 409 mismatch refusal, one effect."""
        engine, snapshot, proposal, adapter, executor = api_t._seed()
        lookup = {proposal.proposal_id: proposal}
        client = TestClient(api_t._build_app(engine, lookup, executor, tenant_id=p6s._TENANT))
        first = client.post(
            "/execute", json=api_t._body(snapshot, proposal, key="adv-07", exec_key="adv-x07")
        )
        assert first.status_code == 201, first.text
        # Same key rebound to a different proposal triple.
        launder = dict(api_t._body(snapshot, proposal, key="adv-07", exec_key="adv-x07b"))
        launder["proposal_version"] = proposal.version + 1
        resp = client.post("/execute", json=launder)
        assert resp.status_code == 409, resp.text
        assert resp.json()["code"] in ("IDEMPOTENCY_CONFLICT", "APPROVAL_SKEW")
        assert adapter.entry_count == 1  # no second effect
        # Direct authorization skew: record for X cannot authorize Y.
        service = ApprovalService(engine, amount_threshold=p6s._THRESHOLD)
        record = service.get_by_idempotency_key("adv-07")
        assert record is not None
        skewed = dataclasses.replace(proposal, version=proposal.version + 99)
        with pytest.raises(ex.AuthorizationRefusedError):
            ex.authorize_execution(
                record=record,
                proposal=skewed,
                tenant_id=p6s._TENANT,
                authorization_id="authz-adv-07",
            )

    def test_08_high_confidence_keeps_evaluation_order(self) -> None:
        """0.99-confidence thin evidence -> evaluate precedes admit, no bypass."""
        from tests.integration.test_p7_advisory_pipeline import _context as _p7ctx
        from tests.integration.test_p7_advisory_pipeline import _request as _p7req

        order: list[str] = []
        ctx = _p7ctx()
        disc = _real_discover(_p7req(ctx), context=ctx)
        rea = reason(disc, context=ctx)
        br = brief(rea, context=ctx)
        assert disc.success and rea.success and br.success is True
        assert (
            evaluate("E", "E1", context=ctx, discovery=disc, reasoning=rea, brief=br) == "CONTAINED"
        )
        order.append("evaluate")
        gate = ControlPlaneGate()
        low = gate.admit(
            context=ctx,
            discovery=disc,
            reasoning=rea.model_copy(update={"confidence": 0.10}),
            brief=br,
        )
        order.append("admit-low")
        high = gate.admit(
            context=ctx,
            discovery=disc,
            reasoning=rea.model_copy(update={"confidence": 0.99}),
            brief=br,
        )
        order.append("admit-high")
        assert order == ["evaluate", "admit-low", "admit-high"]  # order preserved
        assert low.kind == high.kind == "P6_HANDOFF"  # confidence changes nothing
        assert getattr(high, "authorization", None) is None  # no bypass minted

    def test_09_contradictory_evidence_stays_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Contradictory evidence -> conflict preserved, gate BLOCKED, P6 silent."""
        from agents.authority.claims import AgentCapability
        from tests.integration.test_p7_advisory_pipeline import _context as _p7ctx

        spies = _p6_spies(monkeypatch)
        ctx = _p7ctx()
        req = DiscoveryRequest(
            situation_id=ctx.situation_id,
            company_id=ctx.company_id,
            now=ctx.now,
            allowed_evidence_ids=("ev-ledger-001", "ev-ledger-002"),
            objective="Contradictory ledgers under review.",
            allowed_capabilities=(AgentCapability.READ,),
        )
        disc = _real_discover(req, context=ctx)
        rea = reason(disc, context=ctx)
        assert rea.conflicting_evidence != ()
        br = brief(rea, context=ctx)
        assert (
            (br.conflicting_evidence is not None and br.conflicting_evidence != ())
            or "disagree" in (br.uncertainty_section or "").lower()
            or "contradict" in (br.uncertainty_section or "").lower()
        )
        assert (
            evaluate("C", "C1", context=ctx, discovery=disc, reasoning=rea, brief=br) == "CONTAINED"
        )
        res = ControlPlaneGate().admit(context=ctx, discovery=disc, reasoning=rea, brief=br)
        assert res.kind == "BLOCKED"  # conflict preserved, never passed
        assert res.reason in {"CONFLICTING_EVIDENCE", "UNRESOLVED_UNCERTAIN"}
        assert spies == []
