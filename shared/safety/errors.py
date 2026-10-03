"""Typed persistence failures shared by every data-access boundary."""

from __future__ import annotations


class PersistenceError(Exception):
    """Raised when a database operation fails for infrastructure reasons.

    Distinct from a missing record: ``None``/``False`` from a repository is
    an authoritative "not found"; this exception means the answer itself
    is untrustworthy because the store was unavailable, unreachable, or
    rejected the query for non-domain reasons.
    """
