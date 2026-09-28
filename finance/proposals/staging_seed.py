"""Staging seed-data: deterministic proposal rebuild (no authority).

The live ``/execute`` lookup is a process-local in-memory dict that no
external script can populate cross-process, so the route rebuilds the
seeded exception's v1 proposal on demand via this helper. It drafts
through the frozen ``build_proposal`` only — it authorizes nothing — and
returns ``None`` unless the rebuilt id equals the aggregate's pinned
``proposal_id`` (unknown ids still refuse upstream as PROPOSAL_UNKNOWN).

Only ``finance.*`` plus the standard library are used. This module
imports nothing from ``apps/``, ``agents/``, or ``shared/``.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from finance.exceptions.states import ExceptionState
from finance.proposals.builder import build_proposal
from finance.proposals.proposal import Proposal
from finance.reconciliation.models import PaymentRecord, PaymentStatus

logger = logging.getLogger(__name__)

_EVIDENCE_CANDIDATE = "ev-1"


def staging_canonical_records(
    tenant_id: str, occurred_at: datetime
) -> tuple[PaymentRecord, PaymentRecord]:
    """Return the frozen-fixture refund-lag legs (35k vs 50k -> 15k diff)."""
    first = PaymentRecord(
        payment_id="pay-proc-301",
        provider="stripe",
        provider_event_id="evt-proc-301",
        idempotency_key="idem-proc-301",
        gross=Decimal("50000.00"),
        fee=Decimal("0.00"),
        refund=Decimal("15000.00"),
        net=Decimal("35000.00"),
        currency="USD",
        status=PaymentStatus.PARTIALLY_REFUNDED,
        occurred_at=occurred_at,
        tenant_id=tenant_id,
    )
    second = PaymentRecord(
        payment_id="pay-ledger-301",
        provider="stripe",
        provider_event_id="evt-ledger-301",
        idempotency_key="idem-ledger-301",
        gross=Decimal("50000.00"),
        fee=Decimal("0.00"),
        refund=Decimal("0.00"),
        net=Decimal("50000.00"),
        currency="USD",
        status=PaymentStatus.SETTLED,
        occurred_at=occurred_at,
        tenant_id=tenant_id,
    )
    return (first, second)


def rebuild_proposal_for(snapshot: Any) -> Proposal | None:
    """Rebuild the aggregate's pinned v1 proposal via the frozen builder.

    Args:
        snapshot: Stored aggregate at/after AWAITING_APPROVAL carrying a
            pinned ``proposal_id``.

    Returns:
        The rebuilt v1 ``Proposal`` when its id equals the pinned
        ``proposal_id``; otherwise None (caller keeps the refusal).
    """
    pinned = getattr(snapshot, "proposal_id", None)
    if not pinned:
        return None
    try:
        view = dataclasses.replace(snapshot, state=ExceptionState.EVIDENCE_VERIFIED)
    except (TypeError, ValueError):
        return None
    sealed = tuple(getattr(snapshot, "evidence_ids", ()) or ())
    cited = (_EVIDENCE_CANDIDATE,) if _EVIDENCE_CANDIDATE in sealed else sealed[:1]
    if not cited:
        return None
    try:
        proposal = build_proposal(
            view,
            staging_canonical_records(str(snapshot.tenant_id), snapshot.created_at),
            cited,
        )
    except (TypeError, ValueError):
        logger.warning("staging rebuild failed for %s", getattr(snapshot, "exception_id", "?"))
        return None
    if proposal.proposal_id != pinned:
        return None
    return proposal
