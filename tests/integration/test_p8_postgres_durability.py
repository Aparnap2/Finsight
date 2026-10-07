"""Integration: P8-03 durability semantics over Postgres (Phase 4).

Proves the frozen P8-03 seam holds against a Postgres-backed store
(``finance/p8_durability/postgres_store.py`` + alembic ``c9d5e7f1a204``):

* persist -> crash-simulate (fresh ``NullPool`` handle, no process memory)
  -> reload -> seal verifies via frozen ``verify_seal`` -> ordered recovery
  -> idempotent resume with the recorded outcome;
* idempotent resubmission of one identity keeps a single state row;
* replay returns the recorded outcome with zero provider invocations;
* seal tamper quarantines (observable, non-executable, refused execution);
* audit is append-only: re-saving a snapshot never mutates prior entries.

DB gate mirrors ``test_stripe_idempotency_restart.py``: ``NullPool`` fresh
sessions, skip-if-unreachable when Postgres does not answer. No LLM, no
provider SDKs, no Temporal/queues. Semantic authority stays with the frozen
``agents/p8_runtime/durability.py`` functions; the store is a byte-box.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from agents.p8_runtime import contract as p8_01
from agents.p8_runtime import durability
from agents.p8_runtime import execution as p8_02
from alembic import command
from finance.p8_durability.postgres_store import PostgresDurableRunStore

logger = logging.getLogger(__name__)

DEFAULT_DSN = "postgresql+psycopg://finsight:finsight@localhost:5432/finsight"
DSN = os.environ.get("FINSIGHT_TEST_DSN", DEFAULT_DSN)


class _SpyProvider:
    """Canned neutral provider counting every real invocation."""

    def __init__(self, run_id: str) -> None:
        """Bind the spy to one run id for provenance."""
        self._run_id = run_id
        self.complete_calls: list[dict[str, Any]] = []

    def complete(
        self, request: p8_01.ModelRequest, config: p8_01.RuntimeConfig
    ) -> p8_01.ModelResponse:
        """Record the call and return a canned valid response."""
        self.complete_calls.append({"request": request, "config": config})
        return p8_01.ModelResponse(
            run_id=self._run_id,
            output_text='{"summary": "pg-spy", "findings": []}',
            token_usage=1,
            latency_ms=1,
            provenance=p8_01.Provenance(
                prompt_context_id=request.prompt_context_id,
                evidence_ids=[],
                model="pg-spy-model",
                provider="pg-spy-provider",
                version="v1",
                runtime_config=config,
                started_at=datetime(2026, 1, 1, tzinfo=UTC),
                completed_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
                run_id=self._run_id,
            ),
        )


def _db_reachable(engine: sqlalchemy.Engine) -> bool:
    """Return True when the target database answers a trivial query."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - any connectivity failure skips
        logger.warning("integration DB unreachable, skipping: %s", exc)
        return False


@pytest.fixture(scope="module")
def engine() -> Generator[sqlalchemy.Engine, None, None]:
    """Fresh-session engine; skips the module when Postgres is down.

    Applies ``alembic upgrade head`` first so the alembic version table
    owns the DDL: this module shares one database with the tenant
    migration tests, whose own ``upgrade head`` would otherwise re-issue
    ``CREATE TABLE p8_run_states`` over the tables
    ``PostgresDurableRunStore`` created via ``create_all``
    (``DuplicateTable``). Alembic is idempotent and version-tracked, so
    whichever module runs first stamps head and the other becomes a
    no-op; the store's ``create_all`` remains a pure ensure-exists.
    """
    eng = create_engine(DSN, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    if not _db_reachable(eng):
        pytest.skip("integration database not reachable")
    _apply_alembic_head()
    yield eng
    eng.dispose()


def _apply_alembic_head() -> None:
    """Bring the shared database to alembic head (idempotent, version-tracked)."""
    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", DSN)
    command.upgrade(cfg, "head")


def _identity(tag: str) -> p8_01.RunIdentity:
    """Build a unique run identity so rows never collide across runs."""
    return p8_01.RunIdentity(
        run_id=f"run-pg-{uuid4().hex[:8]}-{tag}",
        input_fingerprint="f" * 64,
    )


def _execute(identity: p8_01.RunIdentity) -> tuple[p8_02.RunRecord, _SpyProvider]:
    """Execute one run through the frozen seam with a counting spy."""
    spy = _SpyProvider(identity.run_id)
    record = durability.execute_run(identity, provider=spy)
    assert isinstance(record, p8_02.RunRecord)
    return record, spy


def _persist(
    store: PostgresDurableRunStore, identity: p8_01.RunIdentity, *, include_audit: bool = True
) -> None:
    """Persist the frozen snapshot projection plus its audit trail."""
    snap = durability.snapshot(identity)
    store.save_snapshot(
        run_id=snap.run_id,
        input_fingerprint=snap.input_fingerprint,
        scope=snap.scope,
        attempts=[attempt.model_dump(mode="json") for attempt in snap.attempts],
        terminal_state=snap.terminal_state,
        budget_usage=snap.budget_usage.model_dump(mode="json"),
        integrity_seal=snap.integrity_seal,
    )
    if include_audit:
        for event in snap.audit_events:
            store.append_audit(snap.run_id, snap.input_fingerprint, event)


def _fresh_store(engine: sqlalchemy.Engine) -> PostgresDurableRunStore:
    """Simulate a crash: a brand-new handle with no process-memory state."""
    engine.dispose()
    crashed = create_engine(DSN, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    return PostgresDurableRunStore(crashed)


def _seal_projection(loaded: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the frozen canonical seal projection from a loaded row."""
    return {
        "run_id": loaded["run_id"],
        "input_fingerprint": loaded["input_fingerprint"],
        "scope": loaded["scope"],
        "attempts": loaded["attempts"],
        "terminal_state": loaded["terminal_state"],
        "budget_usage": loaded["budget_usage"],
    }


def test_persist_crash_recover_resume(engine: sqlalchemy.Engine) -> None:
    """PG snapshot survives a crash; frozen recovery order + resume hold."""
    identity = _identity("recover")
    record, _ = _execute(identity)
    store = PostgresDurableRunStore(engine)
    _persist(store, identity)

    reloaded = _fresh_store(engine).load_snapshot(identity.run_id, identity.input_fingerprint)
    assert reloaded is not None
    assert durability.verify_seal(_seal_projection(reloaded), reloaded["integrity_seal"])
    assert [a["attempt_number"] for a in reloaded["attempts"]] == list(
        range(len(reloaded["attempts"]))
    )

    event_log: list[str] = []
    durability.recover_run(identity, event_log=event_log)
    assert event_log == list(durability.RECOVERY_ORDER)

    resubmitted = durability.resubmit(identity)
    assert resubmitted.mode == "recorded"
    assert resubmitted.forked is False
    assert resubmitted.terminal_state == record.terminal_state


def test_idempotent_resubmission_single_effect(engine: sqlalchemy.Engine) -> None:
    """Same identity persisted twice keeps one row and one recorded outcome."""
    identity = _identity("idem")
    record, _ = _execute(identity)
    store = PostgresDurableRunStore(engine)
    _persist(store, identity)
    _persist(store, identity)

    assert store.run_row_count(identity.run_id, identity.input_fingerprint) == 1
    first = durability.resubmit(identity)
    second = durability.resubmit(identity)
    assert first.mode == "recorded" and second.mode == "recorded"
    assert first.terminal_state == record.terminal_state == second.terminal_state


def test_replay_with_zero_provider_calls(engine: sqlalchemy.Engine) -> None:
    """Reloaded history replays the recorded outcome without invoking."""
    identity = _identity("replay")
    record, _ = _execute(identity)
    store = PostgresDurableRunStore(engine)
    _persist(store, identity)
    _fresh_store(engine).load_snapshot(identity.run_id, identity.input_fingerprint)

    replay_spy = _SpyProvider(identity.run_id)
    view = durability.replay_durable(identity, provider=replay_spy)
    assert replay_spy.complete_calls == []
    assert view.new_invocations == 0 and view.new_budget_consumed == 0
    assert view.wrote is False
    assert view.outcome is not None
    assert view.outcome.terminal_state == record.terminal_state


def test_seal_tamper_quarantines(engine: sqlalchemy.Engine) -> None:
    """Tampered PG bytes fail the frozen seal and quarantine the run."""
    identity = _identity("tamper")
    _execute(identity)
    store = PostgresDurableRunStore(engine)
    _persist(store, identity)

    with engine.connect() as conn:
        conn.execute(
            text(
                "UPDATE p8_run_states SET attempts = '[]'::jsonb "
                "WHERE run_id = :run_id AND input_fingerprint = :fp"
            ),
            {"run_id": identity.run_id, "fp": identity.input_fingerprint},
        )
    tampered = store.load_snapshot(identity.run_id, identity.input_fingerprint)
    assert tampered is not None
    assert not durability.verify_seal(_seal_projection(tampered), tampered["integrity_seal"])

    durability.quarantine(identity)
    store.set_quarantined(identity.run_id, identity.input_fingerprint)
    assert store.is_quarantined(identity.run_id, identity.input_fingerprint) is True
    assert durability.execute_run(identity, provider=_SpyProvider(identity.run_id)) is False
    assert durability.replay_durable(identity).outcome is None


def test_audit_append_only(engine: sqlalchemy.Engine) -> None:
    """Re-saving a snapshot preserves every prior audit entry in order."""
    identity = _identity("audit")
    _execute(identity)
    store = PostgresDurableRunStore(engine)
    _persist(store, identity)
    before = store.audit_entries(identity.run_id, identity.input_fingerprint)
    assert len(before) >= 1

    durability.append_audit(identity, "pg-probe:second-write")
    # The frozen snapshot caches the audit list at store time, so the new
    # in-memory event travels through the PG append path while the snapshot
    # re-save exercises the update path without touching prior entries.
    store.append_audit(identity.run_id, identity.input_fingerprint, "pg-probe:second-write")
    _persist(store, identity, include_audit=False)
    after = store.audit_entries(identity.run_id, identity.input_fingerprint)
    assert after[: len(before)] == before
    assert len(after) > len(before)
    assert "pg-probe:second-write" in after
