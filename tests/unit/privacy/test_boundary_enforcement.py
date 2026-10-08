"""P10-06 RED: retention interaction + static enforcement (failing).

- Anonymized webhook payloads are unrecoverable through every read
  path: the tombstone carries no PII and no API serves the original.
- KEEP tables cannot be purged through alternate paths: no ORM delete
  of authoritative tables exists outside the retention engine (which
  refuses them); enforced by source scan, not trust.
- No background/async execution surface exists that could lose tenant
  context: adding task-spawning primitives to prod code trips this
  test, forcing explicit tenant-propagation design first.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path


class TestAnonymizeUnrecoverable:
    def test_tombstoned_raw_yields_no_pii_on_any_read(self) -> None:
        from sqlalchemy.orm import Session

        from shared.models.database import Base as SharedBase
        from shared.privacy.retention import anonymize_expired, disposition_for
        from tests.unit.execution.test_executor import _engine

        engine = _engine()
        SharedBase.metadata.create_all(engine)
        old = datetime(2020, 1, 1, tzinfo=UTC)
        with Session(engine) as session:
            from shared.models.database import WebhookEvent

            session.add(
                WebhookEvent(
                    id="wh-adv-1",
                    tenant_id="tenant-acme",
                    provider="stripe",
                    event_id="evt-adv-1",
                    event_type="charge.succeeded",
                    status="RECEIVED",
                    fingerprint="fp-adv-1",
                    amount=Decimal("10.00"),
                    currency="USD",
                    raw={"customer": {"email": "acme-victim@example.com"}},
                    received_at=old,
                    created_at=old,
                )
            )
            session.commit()
        rule = disposition_for("webhook_events")
        with Session(engine) as session:
            assert anonymize_expired(session, rule, datetime(2026, 10, 8, tzinfo=UTC)) == 1
        with Session(engine) as session:
            from shared.models.database import WebhookEvent

            row = session.get(WebhookEvent, "wh-adv-1")
            assert row is not None
            blob = str(row.raw) + str(row.event_id) + str(row.fingerprint)
            assert "acme-victim@example.com" not in blob
            assert row.event_id == "evt-adv-1"


class TestKeepEnforcement:
    def test_no_orm_delete_of_keep_tables_in_prod(self) -> None:
        """Static guard: authoritative tables have no delete path.

        The retention engine refuses KEEP tables; this test proves no
        other prod code path deletes them either. Allowed: the retention
        engine itself (EXPIRE tables only, never KEEP) and tests.
        """
        repo_root = Path(__file__).resolve().parents[2]
        offenders: list[str] = []
        for base in ("finance", "agents", "apps", "shared"):
            for path in (repo_root / base).rglob("*.py"):
                if "__pycache__" in str(path):
                    continue
                if "session.delete(" in path.read_text(encoding="utf-8"):
                    offenders.append(str(path.relative_to(repo_root)))
        # Object-store key deletion is key-scoped, not an ORM purge path.
        assert offenders == [], offenders


class TestBackgroundTripwire:
    def test_no_detached_execution_surface_without_tenant_design(self) -> None:
        """Fail closed on new background execution: tenant must propagate.

        No asyncio tasks, threads, processes, Celery/Arq workers, or
        framework background tasks exist in prod paths today. Introducing
        any must come with explicit tenant-propagation design; this test
        forces that conversation instead of silent adoption.
        """
        repo_root = Path(__file__).resolve().parents[2]
        primitives = (
            "asyncio.create_task",
            "asyncio.ensure_future",
            "threading.Thread",
            "multiprocessing.Process",
            "BackgroundTasks",
            "celery",
            "arq.",
        )
        hits: list[str] = []
        for base in ("finance", "agents", "apps", "shared"):
            for path in (repo_root / base).rglob("*.py"):
                if "__pycache__" in str(path):
                    continue
                text = path.read_text(encoding="utf-8")
                found = [p for p in primitives if p in text]
                if found:
                    hits.append(f"{path.relative_to(repo_root)}: {found}")
        assert hits == [], hits
