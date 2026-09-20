"""P6-08 track A read ports — R3 seams (F66) plus the R1/R2 store alias.

Defines the two minimal read ports the R3 re-readers consume, plus a
verbatim alias for the existing S3 read seam that serves R1/R2. Ports
are interfaces: tests bind fakes, production adapters bind later, and
no new infrastructure is introduced.

Timeouts ride caller parameters on the re-reader functions, never the
ports themselves.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from finance.object_store.port import ObjectStorePort


class ExpectedSettlementReader(Protocol):
    """Authoritative expected-settlement source (P6-01 matrix, Sheets side)."""

    def read_expected(self, case_key: str) -> tuple[Decimal, datetime | None]:
        """Return the expected settlement total plus its source as-of time."""
        ...


class ProviderPendingReader(Protocol):
    """Authoritative provider-pending source (P6-01 matrix, Razorpay side)."""

    def read_pending(self, batch_key: str) -> tuple[Decimal, datetime | None]:
        """Return the recognised pending timing total plus its source as-of time."""
        ...


ReReadStore = ObjectStorePort
"""R1/R2 read seam: the existing S3 port reused verbatim (F25, F65)."""
