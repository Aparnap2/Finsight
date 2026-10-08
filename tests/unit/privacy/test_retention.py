"""P10-05 RED: retention disposition + expiry engine (failing: no module).

Contract under review (see module docstring on GREEN):

- Every persisted surface has one rule: KEEP (authoritative, purge
  refused even when ancient), EXPIRE_AFTER (derived/transient, deleted
  past TTL), ANONYMIZE_AFTER (raw payloads tombstoned, envelope kept).
- TTLs are explicit policy inputs, not magic defaults.
- Purge is idempotent, dry-runnable (find_expired), tenant-scoped on
  request, and refuses KEEP tables loudly instead of skipping silent.
- File artifacts expire by mtime; missing sweep dirs raise (no silent
  misconfiguration).
- Telemetry file purge is tenant-blind (trace partitioning unestablished
  — inventory gap, not silently assumed).

Pure unit tests: in-memory/file SQLite, tmp dirs, fixed clocks.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

OLD = datetime(2020, 1, 1, tzinfo=UTC)
FRESH = datetime(2026, 10, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 8, tzinfo=UTC)


def _engine():
    from tests.unit.execution.test_executor import _engine as make

    return make()


class TestPolicyCompleteness:
    def test_persisted_surfaces_have_rules(self) -> None:
        from shared.privacy.retention import (
            PERSISTED_SURFACES,
            RetentionDisposition,
            disposition_for,
        )

        assert set(PERSISTED_SURFACES) == {
            "webhook_events",
            "exceptions",
            "exception_audits",
            "executions",
            "idempotency_keys",
            "telemetry_files",
            "eval_fixtures",
            "eval_reports",
        }
        for surface in PERSISTED_SURFACES:
            rule = disposition_for(surface)
            assert isinstance(rule.disposition, RetentionDisposition)

    def test_unknown_surface_refused(self) -> None:
        from shared.privacy.retention import RetentionRefusedError, disposition_for

        with pytest.raises(RetentionRefusedError):
            disposition_for("nope")

    def test_authoritative_surfaces_keep_forever(self) -> None:
        from shared.privacy.retention import (
            RetentionDisposition,
            disposition_for,
        )

        for surface in ("exceptions", "exception_audits", "executions"):
            assert disposition_for(surface).disposition is RetentionDisposition.KEEP


class TestKeepRefusal:
    def test_purge_refuses_authoritative_tables(self) -> None:
        from sqlalchemy.orm import Session

        from finance.exceptions.models import Base as ExceptionBase
        from shared.privacy.retention import RetentionRefusedError, disposition_for, purge_expired

        engine = _engine()
        ExceptionBase.metadata.create_all(engine)
        with Session(engine) as session:
            from finance.exceptions.models import ExceptionRow

            session.add(
                ExceptionRow(
                    exception_id="exc-old",
                    tenant_id="tenant-acme",
                    reconciliation_result_id="recon-old",
                    exception_type="FEE_MISMATCH",
                    severity="HIGH",
                    state="EXCEPTION",
                    state_version=1,
                    created_at=OLD,
                    updated_at=OLD,
                )
            )
            session.commit()
        with Session(engine) as session, pytest.raises(RetentionRefusedError):
            purge_expired(session, disposition_for("exceptions"), NOW)
        with Session(engine) as session:
            from finance.exceptions.models import ExceptionRow

            assert session.get(ExceptionRow, "exc-old") is not None


class TestExpiryBoundaries:
    def test_old_idempotency_binding_expires_fresh_survives(self) -> None:
        from sqlalchemy.orm import Session

        from shared.privacy.retention import disposition_for, purge_expired
        from shared.safety.idempotency import IdempotencyStore

        engine = _engine()
        store = IdempotencyStore(engine)
        store.record("tenant-acme", "old-key", "hash-old")
        store.record("tenant-acme", "fresh-key", "hash-fresh")
        with Session(engine) as session:
            from shared.safety.idempotency import IdempotencyRow

            session.query(IdempotencyRow).filter(
                IdempotencyRow.idempotency_key == "old-key"
            ).update({"created_at": OLD, "updated_at": OLD})
            session.commit()
        rule = disposition_for("idempotency_keys")
        with Session(engine) as session:
            deleted = purge_expired(session, rule, NOW)
        assert deleted == 1
        assert store.payload_hash_for("tenant-acme", "old-key") is None
        assert store.payload_hash_for("tenant-acme", "fresh-key") == "hash-fresh"

    def test_purge_is_idempotent(self) -> None:
        from sqlalchemy.orm import Session

        from shared.privacy.retention import disposition_for, purge_expired
        from shared.safety.idempotency import IdempotencyStore

        engine = _engine()
        store = IdempotencyStore(engine)
        store.record("tenant-acme", "old-key", "hash-old")
        with Session(engine) as session:
            from shared.safety.idempotency import IdempotencyRow

            session.query(IdempotencyRow).update({"created_at": OLD, "updated_at": OLD})
            session.commit()
        rule = disposition_for("idempotency_keys")
        with Session(engine) as session:
            assert purge_expired(session, rule, NOW) == 1
        with Session(engine) as session:
            assert purge_expired(session, rule, NOW) == 0

    def test_tenant_scoped_purge(self) -> None:
        from sqlalchemy.orm import Session

        from shared.privacy.retention import disposition_for, purge_expired
        from shared.safety.idempotency import IdempotencyStore

        engine = _engine()
        store = IdempotencyStore(engine)
        store.record("tenant-a", "k", "h")
        store.record("tenant-b", "k", "h")
        with Session(engine) as session:
            from shared.safety.idempotency import IdempotencyRow

            session.query(IdempotencyRow).update({"created_at": OLD, "updated_at": OLD})
            session.commit()
        rule = disposition_for("idempotency_keys")
        with Session(engine) as session:
            assert purge_expired(session, rule, NOW, tenant_id="tenant-a") == 1
        assert store.payload_hash_for("tenant-a", "k") is None
        assert store.payload_hash_for("tenant-b", "k") == "h"

    def test_find_expired_is_dry_run(self) -> None:
        from sqlalchemy.orm import Session

        from shared.privacy.retention import disposition_for, find_expired
        from shared.safety.idempotency import IdempotencyStore

        engine = _engine()
        store = IdempotencyStore(engine)
        store.record("tenant-acme", "old-key", "hash-old")
        with Session(engine) as session:
            from shared.safety.idempotency import IdempotencyRow

            session.query(IdempotencyRow).update({"created_at": OLD, "updated_at": OLD})
            session.commit()
        rule = disposition_for("idempotency_keys")
        with Session(engine) as session:
            found = find_expired(session, rule, NOW)
        assert len(found) == 1
        assert store.payload_hash_for("tenant-acme", "old-key") == "hash-old"


class TestAnonymize:
    def test_old_raw_tombstoned_envelope_kept(self) -> None:
        from sqlalchemy.orm import Session

        from shared.models.database import Base as SharedBase
        from shared.privacy.retention import anonymize_expired, disposition_for

        engine = _engine()
        SharedBase.metadata.create_all(engine)
        with Session(engine) as session:
            from shared.models.database import WebhookEvent

            session.add(
                WebhookEvent(
                    id="wh-old",
                    tenant_id="tenant-acme",
                    provider="stripe",
                    event_id="evt-old",
                    event_type="charge.succeeded",
                    status="RECEIVED",
                    fingerprint="fp-old",
                    amount=Decimal("100.00"),
                    currency="USD",
                    raw={"customer": {"email": "rahul@example.com"}},
                    received_at=OLD,
                    created_at=OLD,
                )
            )
            session.add(
                WebhookEvent(
                    id="wh-fresh",
                    tenant_id="tenant-acme",
                    provider="stripe",
                    event_id="evt-fresh",
                    event_type="charge.succeeded",
                    status="RECEIVED",
                    fingerprint="fp-fresh",
                    amount=Decimal("100.00"),
                    currency="USD",
                    raw={"ok": True},
                    received_at=FRESH,
                    created_at=FRESH,
                )
            )
            session.commit()
        rule = disposition_for("webhook_events")
        with Session(engine) as session:
            assert anonymize_expired(session, rule, NOW) == 1
        with Session(engine) as session:
            from shared.models.database import WebhookEvent

            old = session.get(WebhookEvent, "wh-old")
            fresh = session.get(WebhookEvent, "wh-fresh")
            assert old is not None and fresh is not None
            assert old.raw != {"customer": {"email": "rahul@example.com"}}
            assert "rahul@example.com" not in str(old.raw)
            assert old.event_id == "evt-old"
            assert fresh.raw == {"ok": True}
        with Session(engine) as session:
            assert anonymize_expired(session, rule, NOW) == 0

    def test_wrong_disposition_refused(self) -> None:
        from sqlalchemy.orm import Session

        from shared.privacy.retention import (
            RetentionRefusedError,
            anonymize_expired,
            disposition_for,
            purge_expired,
        )

        engine = _engine()
        with Session(engine) as session, pytest.raises(RetentionRefusedError):
            purge_expired(session, disposition_for("webhook_events"), NOW)
        with Session(engine) as session, pytest.raises(RetentionRefusedError):
            anonymize_expired(session, disposition_for("idempotency_keys"), NOW)


class TestFileExpiry:
    def test_old_trace_files_removed_fresh_kept(self, tmp_path: Path) -> None:
        from shared.privacy.retention import purge_files

        old_file = tmp_path / "run-old.json"
        fresh_file = tmp_path / "run-fresh.json"
        old_file.write_text("{}", encoding="utf-8")
        fresh_file.write_text("{}", encoding="utf-8")
        ancient = time.time() - 100 * 86400
        os.utime(old_file, (ancient, ancient))
        assert purge_files(tmp_path, older_than_days=30, now=NOW) == 1
        assert not old_file.exists()
        assert fresh_file.exists()
        assert purge_files(tmp_path, older_than_days=30, now=NOW) == 0

    def test_missing_directory_raises(self, tmp_path: Path) -> None:
        from shared.privacy.retention import purge_files

        with pytest.raises(FileNotFoundError):
            purge_files(tmp_path / "nope", older_than_days=30, now=NOW)
