"""Crash-safe idempotency ledger for execution keys.

``IdempotencyStore`` binds each caller-supplied idempotency key to the
payload hash it was first seen with. A repeat presenting the same key
with the same hash is a safe replay; the same key with a differing hash
is an ``IDEMPOTENCY_CONFLICT`` that must perform no write.

The store owns its engine (an injected shared engine in production and
tests, otherwise a private in-memory SQLite database) and creates only
its own ``idempotency_keys`` table, so sharing an engine with the
exception aggregate never disturbs other tables.

Only the Python standard library plus SQLAlchemy are used. This module
imports nothing from ``apps/``, ``agents/``, or ``finance/``.
"""

from __future__ import annotations

import enum
import logging
from datetime import UTC, datetime

from sqlalchemy import DateTime, Engine, PrimaryKeyConstraint, String, create_engine
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from shared.safety.errors import PersistenceError
from shared.safety.secrets import ScrubLogFilter, scrub_text

logger = logging.getLogger(__name__)
logger.addFilter(ScrubLogFilter())


def _utcnow() -> datetime:
    """Return a tz-aware UTC timestamp for ledger rows."""
    return datetime.now(UTC)


class ClaimOutcome(enum.Enum):
    """Result of an atomic idempotency claim."""

    FRESH = "fresh"
    REPLAY = "replay"
    CONFLICT = "conflict"


class _IdempotencyBase(DeclarativeBase):
    """Local declarative base so the ledger creates only its own table."""


class IdempotencyRow(_IdempotencyBase):
    """Persisted binding of one idempotency key to its first payload hash."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (PrimaryKeyConstraint("tenant_id", "idempotency_key"),)

    tenant_id: Mapped[str] = mapped_column(String, nullable=False, default="")
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class IdempotencyStore:
    """Key → payload-hash ledger with strict-boolean reads.

    The store is crash-safe across handles: two stores over one engine
    observe each other's committed records, which is what lets a
    restarted executor recover instead of re-executing blindly.
    """

    def __init__(self, engine: Engine | None = None) -> None:
        """Bind the ledger to an engine, creating only its own table.

        Args:
            engine: Shared engine (tests and the executor pass the same
                engine they use for the exception aggregate). When
                omitted, a private in-memory SQLite database is used.
        """
        self._engine = engine or create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        try:
            _IdempotencyBase.metadata.create_all(self._engine)
        except OperationalError:
            # Concurrent executor ctor: losing race on create_all is benign.
            _IdempotencyBase.metadata.create_all(self._engine)

    def seen(self, tenant_id: str, key: str) -> bool:
        """Return True only when ``key`` already owns a ledger record.

        Args:
            key: Caller-supplied idempotency key to probe.

        Returns:
            A strict ``bool`` — never a truthy row object.
        """
        try:
            with Session(self._engine) as session:
                return session.get(IdempotencyRow, (tenant_id, key)) is not None
        except (OperationalError, InterfaceError) as exc:
            raise PersistenceError(f"idempotency seen({scrub_text(key)!r}) failed: {exc}") from exc

    def payload_hash_for(self, tenant_id: str, key: str) -> str | None:
        """Return the hash first recorded for ``key``, or None if unseen.

        Args:
            key: Caller-supplied idempotency key to inspect.

        Returns:
            The bound payload hash, or None when the key is new.
        """
        try:
            with Session(self._engine) as session:
                row = session.get(IdempotencyRow, (tenant_id, key))
                return row.payload_hash if row is not None else None
        except (OperationalError, InterfaceError) as exc:
            raise PersistenceError(
                f"idempotency payload_hash_for({scrub_text(key)!r}) failed: {exc}"
            ) from exc

    def record(self, tenant_id: str, key: str, payload_hash: str) -> None:
        """Bind ``key`` to ``payload_hash``, refreshing an identical binding.

        Recording the same ``(key, hash)`` pair twice is a no-op replay;
        binding one key to two hashes never happens here — differing
        payloads are rejected by the caller as conflicts before record.

        Args:
            key: Caller-supplied idempotency key (non-empty).
            payload_hash: Opaque payload fingerprint (non-empty).

        Raises:
            ValueError: If either argument is blank or not a string.
        """
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Field 'tenant_id' must be a non-empty string.")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Field 'key' must be a non-empty string.")
        if not isinstance(payload_hash, str) or not payload_hash.strip():
            raise ValueError("Field 'payload_hash' must be a non-empty string.")
        try:
            with Session(self._engine) as session:
                row = session.get(IdempotencyRow, (tenant_id, key))
                if row is None:
                    session.add(
                        IdempotencyRow(
                            tenant_id=tenant_id,
                            idempotency_key=key,
                            payload_hash=payload_hash,
                            created_at=_utcnow(),
                            updated_at=_utcnow(),
                        )
                    )
                else:
                    row.payload_hash = payload_hash
                    row.updated_at = _utcnow()
                session.commit()
        except IntegrityError:
            # Concurrent first-write for the same (tenant, key): re-read
            # and accept as a no-op replay when the hash matches.
            with Session(self._engine) as session:
                winner = session.get(IdempotencyRow, (tenant_id, key))
                if winner is not None and winner.payload_hash == payload_hash:
                    pass
                else:
                    raise
        except (OperationalError, InterfaceError) as exc:
            raise PersistenceError(
                f"idempotency record({scrub_text(key)!r}) failed: {exc}"
            ) from exc
        logger.info("idempotency recorded key=%s", key)

    def claim(self, tenant_id: str, key: str, payload_hash: str) -> ClaimOutcome:
        """Atomically bind ``key`` to its first ``payload_hash``.

        Returns :attr:`ClaimOutcome.FRESH` for the first claim, ``REPLAY``
        when the same key re-presents the same hash, and ``CONFLICT`` when
        the same key re-presents a different hash (no overwrite). Exactly
        one concurrent caller wins the fresh bind; losers observe REPLAY or
        CONFLICT instead of an error, and the row's hash is never mutated
        by a losing claim.

        Args:
            key: Caller-supplied idempotency key (non-empty).
            payload_hash: Opaque payload fingerprint (non-empty).

        Returns:
            The :class:`ClaimOutcome` for this claim.

        Raises:
            ValueError: If either argument is blank or not a string.
        """
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Field 'tenant_id' must be a non-empty string.")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Field 'key' must be a non-empty string.")
        if not isinstance(payload_hash, str) or not payload_hash.strip():
            raise ValueError("Field 'payload_hash' must be a non-empty string.")
        try:
            with Session(self._engine) as session:
                row = session.get(IdempotencyRow, (tenant_id, key))
                if row is None:
                    try:
                        session.add(
                            IdempotencyRow(
                                tenant_id=tenant_id,
                                idempotency_key=key,
                                payload_hash=payload_hash,
                                created_at=_utcnow(),
                                updated_at=_utcnow(),
                            )
                        )
                        session.commit()
                        logger.info("idempotency claimed key=%s outcome=fresh", key)
                        return ClaimOutcome.FRESH
                    except IntegrityError:
                        session.rollback()
                        row = session.get(IdempotencyRow, (tenant_id, key))
                if row is not None and row.payload_hash == payload_hash:
                    return ClaimOutcome.REPLAY
                return ClaimOutcome.CONFLICT
        except (OperationalError, InterfaceError) as exc:
            raise PersistenceError(f"idempotency claim({scrub_text(key)!r}) failed: {exc}") from exc
