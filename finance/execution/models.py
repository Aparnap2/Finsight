"""Persisted execution intent/outcome records for the execution boundary.

``ExecutionRow`` binds one caller-supplied idempotency key to the stable
execution it drove: the deterministic ``execution_id`` minted from the
key, the owning exception/proposal pins, the payload hash the key was
first seen with, and the outcome triple (``result``,
``external_reference``, ``post_verify``). The row is written as an
intent (outcome columns null) before any adapter side effect and
updated to the terminal outcome after post-verification, so a
restarted executor replays the same record instead of re-executing.

A local ``DeclarativeBase`` keeps execution storage decoupled: only
the ``execution_records`` table is created, never touching the
exception aggregate or idempotency ledger tables sharing the engine.

Only SQLAlchemy plus the Python standard library are used. This module
imports nothing from ``apps/``, ``agents/``, ``shared/``, or any other
``finance.*`` package.
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Local declarative base so execution creates only its own table."""


class ExecutionRow(Base):
    """Persisted intent/outcome of one ``Executor.run`` keyed execution."""

    __tablename__ = "execution_records"

    idempotency_key: Mapped[str] = mapped_column(String, primary_key=True)
    execution_id: Mapped[str] = mapped_column(String, nullable=False)
    exception_id: Mapped[str] = mapped_column(String, nullable=False)
    proposal_id: Mapped[str] = mapped_column(String, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String, nullable=False)
    result: Mapped[str | None] = mapped_column(String, nullable=True)
    external_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    post_verify: Mapped[str | None] = mapped_column(String, nullable=True)
