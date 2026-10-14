"""Durable-store guard (issue #113, review P1).

Production execution paths must bind idempotency, reservation, and
record stores to durable engines. In-memory backends exist ONLY for
explicit unit-test use. ``assert_durable`` fails closed: anything that
is not a recognizably engine-backed store raises outside tests.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def assert_durable(store: Any, *, store_name: str, allow_volatile: bool = False) -> None:
    """Raise unless ``store`` is engine-backed (or explicitly test-scoped).

    Args:
        store: The store instance (or None) to inspect.
        store_name: Human name for error messages.
        allow_volatile: Set True ONLY in unit tests that intentionally
            use in-memory backends. Production composition never sets it.
    """
    if allow_volatile:
        return
    volatile = getattr(store, "_volatile_backend", True) if store is not None else True
    if store is None or volatile:
        raise RuntimeError(
            f"{store_name} is volatile (in-memory): production execution "
            "requires a durable PostgreSQL-backed store. Pass an engine, "
            "or set allow_volatile=True only in unit tests."
        )
    engine = getattr(store, "_engine", None)
    logger.debug("%s bound to durable engine %s", store_name, type(engine).__name__)
