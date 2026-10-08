"""Retention dispositions and expiry engine (P10-05).

Policy (explicit inputs, not magic defaults):

- AUTHORITATIVE stores (exceptions, exception_audits, executions)
  are KEEP: purge attempts raise instead of deleting.
- ``webhook_events`` rows are ANONYMIZE_AFTER: the envelope stays,
  the raw payload becomes a tombstone (no schema change required).
- ``idempotency_keys`` bindings EXPIRE_AFTER: late retries stay safe
  because the execution state machine backstops them (terminal rows
  replay, intents recover-or-conflict, never-executed work runs fresh
  exactly once) — expiry can only remove replay history, never resurrect
  a settled financial action.
- Trace files and eval run reports expire by file mtime; fixtures and
  projections are KEEP/versioned or storageless.

TTL day counts are policy inputs (``*_DAYS`` constants); adjust per
counsel, not per incident. All operations are idempotent, dry-runnable
via :func:`find_expired`, and tenant-scoped on request. No model
imports: tables resolve by name via reflection, so this module keeps
the ``shared`` layering rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, delete, select, update

WEBHOOK_ANONYMIZE_DAYS: int = 90
IDEMPOTENCY_EXPIRE_DAYS: int = 90
TRACE_EXPIRE_DAYS: int = 30
EVAL_REPORT_EXPIRE_DAYS: int = 90

ANONYMIZED_RAW: dict[str, bool] = {"anonymized": True}


class RetentionRefusedError(Exception):
    """Raised when an expiry operation targets a non-expiring disposition."""


class RetentionDisposition(StrEnum):
    """Closed disposition vocabulary for persisted surfaces."""

    KEEP = "keep"
    EXPIRE_AFTER = "expire_after"
    ANONYMIZE_AFTER = "anonymize_after"


@dataclass(frozen=True)
class RetentionRule:
    """One surface's retention contract (explicit policy input)."""

    table: str
    source_id: str
    disposition: RetentionDisposition
    ttl_days: int | None
    timestamp_column: str = "created_at"
    tenant_column: str | None = "tenant_id"
    rationale: str = ""


RETENTION_POLICIES: tuple[RetentionRule, ...] = (
    RetentionRule(
        table="webhook_events",
        source_id="razorpay",
        disposition=RetentionDisposition.ANONYMIZE_AFTER,
        ttl_days=WEBHOOK_ANONYMIZE_DAYS,
        rationale="Raw provider payloads carry PII; envelope metadata stays for audit joins.",
    ),
    RetentionRule(
        table="exceptions",
        source_id="finsight_derived",
        disposition=RetentionDisposition.KEEP,
        ttl_days=None,
        rationale="Authoritative financial lifecycle truth; never auto-delete.",
    ),
    RetentionRule(
        table="exception_audits",
        source_id="finsight_derived",
        disposition=RetentionDisposition.KEEP,
        ttl_days=None,
        rationale="Append-only accountability trail; never auto-delete.",
    ),
    RetentionRule(
        table="executions",
        source_id="finsight_derived",
        disposition=RetentionDisposition.KEEP,
        ttl_days=None,
        rationale="Authoritative execution ledger; replay depends on it.",
    ),
    RetentionRule(
        table="idempotency_keys",
        source_id="finsight_derived",
        disposition=RetentionDisposition.EXPIRE_AFTER,
        ttl_days=IDEMPOTENCY_EXPIRE_DAYS,
        rationale="Bindings bound table growth; state machine backstops late retries.",
    ),
    RetentionRule(
        table="telemetry_files",
        source_id="finsight_derived",
        disposition=RetentionDisposition.EXPIRE_AFTER,
        ttl_days=TRACE_EXPIRE_DAYS,
        rationale="Debug-only artifacts; file mtime ordered, tenant-blind (known gap).",
    ),
    RetentionRule(
        table="eval_fixtures",
        source_id="finsight_derived",
        disposition=RetentionDisposition.KEEP,
        ttl_days=None,
        rationale="Versioned benchmark source in git, not data at rest.",
    ),
    RetentionRule(
        table="eval_reports",
        source_id="finsight_derived",
        disposition=RetentionDisposition.EXPIRE_AFTER,
        ttl_days=EVAL_REPORT_EXPIRE_DAYS,
        rationale="Derived, reproducible from fixtures + code version.",
    ),
)

PERSISTED_SURFACES: tuple[str, ...] = tuple(rule.table for rule in RETENTION_POLICIES)


def disposition_for(table: str) -> RetentionRule:
    """Return the retention rule for a persisted surface name."""
    for rule in RETENTION_POLICIES:
        if rule.table == table:
            return rule
    raise RetentionRefusedError(f"no retention rule for surface {table!r}")


def _resolve_table(session: Any, rule: RetentionRule) -> Table:
    """Reflect the rule's table off the session's bind."""
    bind = session.get_bind()
    return Table(rule.table, MetaData(), autoload_with=bind)


def _cutoff(rule: RetentionRule, now: datetime) -> datetime:
    """Compute the expiry threshold for a TTL-bearing rule."""
    assert rule.ttl_days is not None
    return now - timedelta(days=rule.ttl_days)


def _expired_clause(table: Table, rule: RetentionRule, cutoff: datetime) -> Any:
    """Build the age predicate for the rule's timestamp column."""
    return table.c[rule.timestamp_column] < cutoff


def find_expired(
    session: Any, rule: RetentionRule, now: datetime, tenant_id: str | None = None
) -> list[tuple[Any, ...]]:
    """List primary keys of expired rows without mutating (dry run)."""
    if rule.disposition is RetentionDisposition.KEEP:
        raise RetentionRefusedError(f"surface {rule.table!r} is KEEP: refusing scan")
    if rule.ttl_days is None:
        raise RetentionRefusedError(f"surface {rule.table!r} has no TTL")
    table = _resolve_table(session, rule)
    stmt = select(table).where(_expired_clause(table, rule, _cutoff(rule, now)))
    if tenant_id is not None and rule.tenant_column is not None:
        stmt = stmt.where(table.c[rule.tenant_column] == tenant_id)
    pk_columns = list(table.primary_key.columns)
    return [tuple(row[c.name] for c in pk_columns) for row in session.execute(stmt).mappings()]


def purge_expired(
    session: Any, rule: RetentionRule, now: datetime, tenant_id: str | None = None
) -> int:
    """Delete expired rows for EXPIRE_AFTER rules; return the deleted count.

    Idempotent: re-running finds nothing new. Refuses KEEP and
    ANONYMIZE_AFTER tables (use :func:`anonymize_expired` for those).
    """
    if rule.disposition is not RetentionDisposition.EXPIRE_AFTER:
        raise RetentionRefusedError(
            f"surface {rule.table!r} is {rule.disposition.value}: refusing purge"
        )
    if rule.ttl_days is None:
        raise RetentionRefusedError(f"surface {rule.table!r} has no TTL")
    table = _resolve_table(session, rule)
    stmt = delete(table).where(_expired_clause(table, rule, _cutoff(rule, now)))
    if tenant_id is not None and rule.tenant_column is not None:
        stmt = stmt.where(table.c[rule.tenant_column] == tenant_id)
    result = session.execute(stmt)
    session.commit()
    return int(result.rowcount or 0)


def anonymize_expired(
    session: Any, rule: RetentionRule, now: datetime, tenant_id: str | None = None
) -> int:
    """Tombstone expired raw payloads, preserving envelope rows.

    Idempotent: already-tombstoned rows are skipped and uncounted.
    Only valid for ANONYMIZE_AFTER rules.
    """
    if rule.disposition is not RetentionDisposition.ANONYMIZE_AFTER:
        raise RetentionRefusedError(
            f"surface {rule.table!r} is {rule.disposition.value}: refusing anonymize"
        )
    if rule.ttl_days is None:
        raise RetentionRefusedError(f"surface {rule.table!r} has no TTL")
    table = _resolve_table(session, rule)
    stmt = (
        update(table)
        .where(_expired_clause(table, rule, _cutoff(rule, now)))
        .where(table.c["raw"].is_not(None))
        .where(table.c["raw"] != ANONYMIZED_RAW)
        .values(raw=ANONYMIZED_RAW)
    )
    if tenant_id is not None and rule.tenant_column is not None:
        stmt = stmt.where(table.c[rule.tenant_column] == tenant_id)
    result = session.execute(stmt)
    session.commit()
    return int(result.rowcount or 0)


def purge_files(
    directory: Path | str, *, older_than_days: int, now: datetime, pattern: str = "*.json"
) -> int:
    """Delete files older than the TTL; return the removed count.

    Idempotent; missing directories raise (never silently misconfigured).
    File purge is tenant-blind: trace partitioning is unestablished.
    """
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"sweep directory missing: {root}")
    threshold = now.timestamp() - older_than_days * 86400
    removed = 0
    for path in sorted(root.glob(pattern)):
        if not path.is_file():
            continue
        if path.stat().st_mtime < threshold:
            path.unlink()
            removed += 1
    return removed
