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

import logging
from datetime import UTC, datetime

from sqlalchemy import DateTime, Engine, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return a tz-aware UTC timestamp for ledger rows."""
    return datetime.now(UTC)


class _IdempotencyBase(DeclarativeBase):
    """Local declarative base so the ledger creates only its own table."""


class IdempotencyRow(_IdempotencyBase):
    """Persisted binding of one idempotency key to its first payload hash."""

    __tablename__ = "idempotency_keys"

    idempotency_key: Mapped[str] = mapped_column(String, primary_key=True)
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
        _IdempotencyBase.metadata.create_all(self._engine)

    def seen(self, key: str) -> bool:
        """Return True only when ``key`` already owns a ledger record.

        Args:
            key: Caller-supplied idempotency key to probe.

        Returns:
            A strict ``bool`` — never a truthy row object.
        """
        with Session(self._engine) as session:
            return session.get(IdempotencyRow, key) is not None

    def payload_hash_for(self, key: str) -> str | None:
        """Return the hash first recorded for ``key``, or None if unseen.

        Args:
            key: Caller-supplied idempotency key to inspect.

        Returns:
            The bound payload hash, or None when the key is new.
        """
        with Session(self._engine) as session:
            row = session.get(IdempotencyRow, key)
            return row.payload_hash if row is not None else None

    def record(self, key: str, payload_hash: str) -> None:
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
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Field 'key' must be a non-empty string.")
        if not isinstance(payload_hash, str) or not payload_hash.strip():
            raise ValueError("Field 'payload_hash' must be a non-empty string.")
        with Session(self._engine) as session:
            row = session.get(IdempotencyRow, key)
            if row is None:
                session.add(
                    IdempotencyRow(
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
        logger.info("idempotency recorded key=%s", key)
