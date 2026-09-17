"""P6-03 creation rules: verdicts become FinancialSituations (or nothing).

Only case-creating classifications allocate a situation, always at
``DETECTED`` via the aggregate constructor — transitions stay
lifecycle-owned, so this module never calls ``transition_to``.
Reconciled-clean outcomes (``MATCHED``/``WITHIN_TOLERANCE``) and
``PENDING_EVIDENCE`` create nothing; situation ids embed a
caller-supplied date (no wall-clock reads here).
"""

from __future__ import annotations

import re
from decimal import Decimal

from finance.detection.classification import CASE_CREATING_CLASSIFICATIONS
from finance.detection.engine import DetectionVerdict
from finance.domain.financial_situation import FinancialSituation, SituationStatus
from finance.facts.books import BooksFact
from finance.facts.expected import ExpectedFact
from finance.facts.legacy import LegacyFact
from finance.facts.provider import ProviderNetFact

_DATE_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def allocate_situation_id(date_str: str, seq: int) -> str:
    """Allocate ``FS-YYYY-MMDD-NNNNN`` from a caller-supplied date.

    The shape is dictated by the frozen ``FinancialSituation`` id
    validator (``FS-\\d{4}-\\d{4}-\\d{5}``): a compact datestamp would
    produce ids the aggregate rejects, so the allocator emits the
    dashed shape creation can persist.

    Args:
        date_str: Settlement date as ``YYYY-MM-DD`` (caller clock, never
            read here so detection stays deterministic).
        seq: Positive per-day sequence number, zero-padded to five.

    Returns:
        The allocated situation id, e.g. ``FS-2026-0917-00231``.

    Raises:
        ValueError: If the date shape or sequence is invalid.
    """
    match = _DATE_PATTERN.fullmatch(date_str.strip())
    if match is None:
        raise ValueError(
            f"date_str must be YYYY-MM-DD, got {date_str!r}."
        )
    if seq < 1:
        raise ValueError(f"seq must be positive, got {seq!r}.")
    year, month, day = match.groups()
    return f"FS-{year}-{month}{day}-{seq:05d}"


def creation_rules(
    verdict: DetectionVerdict,
    *,
    expected: ExpectedFact | None,
    provider: ProviderNetFact | None,
    books: BooksFact | None,
    legacy: LegacyFact | None,
    date_str: str,
    seq: int,
) -> FinancialSituation | None:
    """Build the DETECTED situation for a case-creating verdict, else None.

    Carries the content hashes of every present fact as evidence refs
    (D3-compatible: the refs a later proposal needs) and the legs that
    size ``variance()`` exactly at the actionable number. Never calls
    ``transition_to``; never creates for clean/pending verdicts.

    Args:
        verdict: The frozen detection verdict to act on.
        expected: Sheets expected fact (None when absent).
        provider: Provider-net fact (None when absent).
        books: Books-total fact (None when absent).
        legacy: Legacy posting fact (None means nothing posted).
        date_str: Caller settlement date for id allocation.
        seq: Caller per-day sequence for id allocation.

    Returns:
        A ``DETECTED`` aggregate, or None when the verdict creates no
        case (clean, pending, unknown, or non-creating label).
    """
    if verdict.classification not in CASE_CREATING_CLASSIFICATIONS:
        return None
    if expected is None or provider is None or books is None:
        return None
    evidence = tuple(
        fact.provenance.content_hash
        for fact in (expected, provider, books, legacy)
        if fact is not None
    )
    return FinancialSituation(
        situation_id=allocate_situation_id(date_str, seq),
        company_id="meridian",
        expected=expected.expected_total,
        razorpay_net=provider.net,
        quickbooks=books.qb_total,
        legacy=legacy.accepted_total if legacy is not None else Decimal("0"),
        status=SituationStatus.DETECTED,
        evidence_ids=evidence,
    )
