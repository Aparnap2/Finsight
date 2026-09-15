"""Frozen code-owned capability registry (P4.3).

The registry is built once from an :class:`AdapterBundle` in deterministic
code. It exposes lookup only: unknown names are rejected at lookup with
:class:`ExecutorRejectedError`, and no runtime registration API is exposed
to LLM paths (there is deliberately no ``register`` method).

Only the standard library plus ``shared`` and ``finance`` read paths are
used. No LLM framework imports.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping

from agents.capabilities.capabilities import (
    AdapterBundle,
    BaseCapability,
    ExpectedStateCapability,
    GmailSearchCapability,
    QBTransactionCapability,
    StripePaymentCapability,
    StripeRefundsCapability,
)
from agents.capabilities.types import ExecutorRejectedError, is_allowlisted
from finance.accounting.errors import ValidationError
from finance.reconciliation.ledger_resolution import InMemoryLedgerRepository

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    """Code-owned frozen mapping of closed capability name to implementation."""

    def __init__(self, bundle: AdapterBundle) -> None:
        """Build the frozen five-entry mapping from read-only stores.

        Args:
            bundle: Injected read-only stores (persisted Stripe folds,
                sandbox QB adapter, ledger repository, Gmail fixture corpus).

        Raises:
            TypeError: If ``bundle`` is not an :class:`AdapterBundle`.
            ExecutorRejectedError: If a required store is missing.
        """
        if not isinstance(bundle, AdapterBundle):
            raise TypeError(f"bundle must be an AdapterBundle, got {type(bundle).__name__}.")
        if bundle.qb_adapter is None:
            raise ExecutorRejectedError("AdapterBundle carries no qb_adapter.")
        if bundle.ledger_repository is None:
            raise ExecutorRejectedError("AdapterBundle carries no ledger_repository.")
        if not isinstance(bundle.ledger_repository, InMemoryLedgerRepository):
            raise ExecutorRejectedError("ledger_repository must be an InMemoryLedgerRepository.")
        try:
            entries: dict[str, BaseCapability] = {
                "get_stripe_payment": StripePaymentCapability(bundle.stripe_payments),
                "get_stripe_refunds": StripeRefundsCapability(bundle.stripe_payments),
                "get_qb_transaction": QBTransactionCapability(bundle.qb_adapter),
                "get_expected_state": ExpectedStateCapability(bundle.ledger_repository),
                "search_gmail": GmailSearchCapability(bundle.gmail_corpus),
            }
        except (ValidationError, ValueError, TypeError) as exc:
            raise ExecutorRejectedError(f"Capability registry build failed: {exc}.") from exc
        self._entries: dict[str, BaseCapability] = entries

    @property
    def names(self) -> tuple[str, ...]:
        """Return the frozen capability names in allowlist order."""
        from agents.investigation.plan import FROZEN_CAPABILITY_ALLOWLIST

        return tuple(name for name in FROZEN_CAPABILITY_ALLOWLIST if name in self._entries)

    def get(self, name: str) -> BaseCapability:
        """Return the capability for ``name`` or reject unknown names.

        Args:
            name: Closed capability name.

        Raises:
            ExecutorRejectedError: If ``name`` is outside the frozen set or
                has no bound implementation (zero execution on this path).
        """
        if not is_allowlisted(name) or name not in self._entries:
            raise ExecutorRejectedError(f"Capability {name!r} is outside the frozen allowlist.")
        capability = self._entries[name]
        logger.debug("capability lookup name=%s", name)
        return capability

    def __contains__(self, name: object) -> bool:
        """Return True when ``name`` is a bound allowlisted capability."""
        return isinstance(name, str) and name in self._entries

    def __len__(self) -> int:
        """Return the number of bound capabilities (always five)."""
        return len(self._entries)

    def __iter__(self) -> Iterator[str]:
        """Iterate bound capability names in allowlist order."""
        return iter(self.names)

    def snapshot(self) -> Mapping[str, BaseCapability]:
        """Return a read-only view of the frozen name to capability mapping."""
        return dict(self._entries)


__all__ = ["CapabilityRegistry"]
