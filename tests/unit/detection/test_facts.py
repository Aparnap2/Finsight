"""Validation rules for P6-03 canonical facts (boundary rejection).

Covers the RED contract for ``finance/facts``: provenance shape,
INR-only currency, tz-aware timestamps, Decimal-only money (float
rejected), the five-term provider-net equation, and frozen models.
"""

from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256

import pytest
from pydantic import ValidationError

from finance.facts.books import BooksFact
from finance.facts.expected import ExpectedFact
from finance.facts.legacy import LegacyFact
from finance.facts.provenance import FactProvenance
from finance.facts.provider import ProviderNetFact, decompose_provider_net

_AT = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)


def _hash(tag: str) -> str:
    """Return a deterministic 64-hex digest for a tag."""
    return sha256(tag.encode("utf-8")).hexdigest()


def _prov(tag: str) -> FactProvenance:
    """Build a valid provenance for a tag."""
    return FactProvenance(
        adapter="test-adapter-v1",
        endpoint="C-TEST",
        correlation_id=f"corr-{tag}",
        content_hash=_hash(tag),
        retrieved_at=_AT,
    )


class TestProvenance:
    """FactProvenance carries adapter identity plus a 64-hex hash."""

    def test_valid_provenance(self) -> None:
        """A complete provenance validates with meridian default."""
        prov = _prov("ok")
        assert prov.company_id == "meridian"
        assert len(prov.content_hash) == 64

    def test_bad_hash_rejected(self) -> None:
        """Non-64-hex content hashes are rejected at the boundary."""
        with pytest.raises(ValidationError):
            FactProvenance(
                adapter="a",
                endpoint="e",
                correlation_id="c",
                content_hash="not-a-hash",
                retrieved_at=_AT,
            )

    def test_naive_timestamp_rejected(self) -> None:
        """Naive retrieved_at timestamps are rejected at the boundary."""
        with pytest.raises(ValidationError):
            FactProvenance(
                adapter="a",
                endpoint="e",
                correlation_id="c",
                content_hash=_hash("naive"),
                retrieved_at=datetime(2026, 9, 17, 12, 0, 0),
            )

    def test_company_boundary(self) -> None:
        """Only company_id meridian is accepted."""
        with pytest.raises(ValidationError):
            FactProvenance(
                adapter="a",
                endpoint="e",
                correlation_id="c",
                content_hash=_hash("co"),
                retrieved_at=_AT,
                company_id="acme",
            )

    def test_frozen(self) -> None:
        """Provenance is immutable after construction."""
        prov = _prov("frozen")
        with pytest.raises(ValidationError):
            prov.adapter = "other"  # type: ignore[misc]


class TestExpectedFact:
    """ExpectedFact is the advisory sheets view (never authoritative)."""

    def test_valid(self) -> None:
        """A sheets expected fact validates with INR currency."""
        fact = ExpectedFact(
            fact_id="exp-1",
            batch_id="BATCH-1",
            expected_total=Decimal("496250"),
            observed_at=_AT,
            provenance=_prov("exp-1"),
        )
        assert fact.source == "sheets"
        assert fact.currency == "INR"

    def test_float_rejected(self) -> None:
        """Float totals are rejected at the boundary."""
        with pytest.raises(ValidationError):
            ExpectedFact(
                fact_id="exp-f",
                batch_id="BATCH-1",
                expected_total=500000.0,  # type: ignore[arg-type]
                observed_at=_AT,
                provenance=_prov("exp-f"),
            )

    def test_currency_rejected(self) -> None:
        """Non-INR currency is rejected (never converted or coerced)."""
        with pytest.raises(ValidationError):
            ExpectedFact(
                fact_id="exp-c",
                batch_id="BATCH-1",
                expected_total=Decimal("1"),
                currency="USD",
                observed_at=_AT,
                provenance=_prov("exp-c"),
            )


class TestProviderNetFact:
    """ProviderNetFact carries the five-term provider decomposition."""

    def test_net_equation_fs231(self) -> None:
        """FS-231: 1000000/7500/2500/10000/7500 nets to 972500."""
        fact = ProviderNetFact(
            fact_id="prov-231",
            batch_id="BATCH-231",
            gross=Decimal("1000000"),
            fee=Decimal("7500"),
            refund=Decimal("2500"),
            adjustment=Decimal("10000"),
            pending=Decimal("7500"),
            observed_at=_AT,
            provenance=_prov("prov-231"),
        )
        assert fact.net == Decimal("972500")

    def test_decompose_helper(self) -> None:
        """decompose_provider_net builds the fact with the same net."""
        fact = decompose_provider_net(
            Decimal("1000000"),
            Decimal("7500"),
            Decimal("2500"),
            Decimal("10000"),
            Decimal("7500"),
            provenance=_prov("decomp"),
            fact_id="prov-d",
            batch_id="BATCH-231",
        )
        assert fact.net == Decimal("972500")

    def test_decompose_float_rejected(self) -> None:
        """Float legs are rejected before any fact exists."""
        with pytest.raises(TypeError):
            decompose_provider_net(
                1000000.0,  # type: ignore[arg-type]
                Decimal("7500"),
                Decimal("2500"),
                Decimal("10000"),
                Decimal("7500"),
                provenance=_prov("decomp-f"),
            )

    def test_float_field_rejected(self) -> None:
        """Float fee legs are rejected at the model boundary."""
        with pytest.raises(ValidationError):
            ProviderNetFact(
                fact_id="prov-f",
                batch_id="BATCH-1",
                gross=Decimal("500000"),
                fee=7500.0,  # type: ignore[arg-type]
                refund=Decimal("0"),
                adjustment=Decimal("0"),
                pending=Decimal("0"),
                observed_at=_AT,
                provenance=_prov("prov-f"),
            )


class TestBooksFact:
    """BooksFact carries the QuickBooks accounting truth."""

    def test_valid(self) -> None:
        """A books fact validates with period openness carried."""
        fact = BooksFact(
            fact_id="qb-1",
            batch_id="BATCH-1",
            qb_total=Decimal("496250"),
            period="2026-09",
            period_open=True,
            posted_at=_AT,
            provenance=_prov("qb-1"),
        )
        assert fact.period_open is True

    def test_float_rejected(self) -> None:
        """Float books totals are rejected at the boundary."""
        with pytest.raises(ValidationError):
            BooksFact(
                fact_id="qb-f",
                batch_id="BATCH-1",
                qb_total=496250.0,  # type: ignore[arg-type]
                period="2026-09",
                period_open=True,
                posted_at=_AT,
                provenance=_prov("qb-f"),
            )


class TestLegacyFact:
    """LegacyFact carries accepted/rejected totals plus verbatim reason."""

    def test_reason_verbatim(self) -> None:
        """The COBOL reject reason rides verbatim (or None when clean)."""
        rejected = LegacyFact(
            fact_id="leg-rj",
            batch_id="BATCH-231",
            accepted_total=Decimal("982500"),
            rejected_total=Decimal("10000"),
            rejected_reason="INVALID_ACCOUNT_CODE",
            posted_at=_AT,
            provenance=_prov("leg-rj"),
        )
        assert rejected.rejected_reason == "INVALID_ACCOUNT_CODE"
        clean = LegacyFact(
            fact_id="leg-ok",
            batch_id="BATCH-1",
            accepted_total=Decimal("496250"),
            posted_at=_AT,
            provenance=_prov("leg-ok"),
        )
        assert clean.rejected_reason is None
        assert clean.rejected_total == Decimal("0")
