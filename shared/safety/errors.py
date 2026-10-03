"""Typed persistence failures shared by every data-access boundary."""

from __future__ import annotations

import functools
from collections.abc import Callable

from sqlalchemy.exc import InterfaceError, OperationalError


class PersistenceError(Exception):
    """Raised when a database operation fails for infrastructure reasons.

    Distinct from a missing record: ``None``/``False`` from a repository is
    an authoritative "not found"; this exception means the answer itself
    is untrustworthy because the store was unavailable, unreachable, or
    rejected the query for non-domain reasons.
    """


def persist_guarded[**P, T](func: Callable[P, T]) -> Callable[P, T]:
    """Wrap DB-backed calls so SQL errors surface as :class:`PersistenceError`.

    Domain errors (domain exceptions, IntegrityError conflicts) are not
    SQL transport failures and propagate unchanged.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return func(*args, **kwargs)
        except (OperationalError, InterfaceError) as exc:
            raise PersistenceError(f"persistence failure in {func.__name__}: {exc}") from exc

    return wrapper
