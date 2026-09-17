"""P6-04 deterministic evidence collection + chain + package (RED).

Strict TDD: this suite is written FIRST against the frozen contract
``docs/architecture/P6-04_EVIDENCE_CONTRACT.md`` (E1-E33, FS-231
golden walk section 3, adversarial A1-A13 deterministic core) and
must FAIL until the implementation lands under ``finance/correlation/``.

Scope: meridian only, INR, Decimal-only money, no LLM, no network,
no wall-clock reads (caller-supplied times only).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256

import pytest

from finance.evidence.grounding import (
    compute_content_hash,
    evaluate_ladder,
    is_verified_eligible,
    verify_provenance,
)

AT = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
"""Caller-supplied frozen timestamp (never wall-clock)."""

BACKDATED = datetime(2026, 9, 10, 8, 0, 0, tzinfo=UTC)
"""Backdated retrieval timestamp (must be preserved verbatim)."""


def _hash(tag: str) -> str:
    """Return deterministic 64-hex digest for a tag."""
    return sha256(tag.encode("utf-8")).hexdigest()


def _prov(tag: str, **over: object) -> object:
    """Build a valid FactProvenance for a tag (imported lazily)."""
    from finance.facts.provenance import FactProvenance

    base: dict[str, object] = {
        "adapter": "test-adapter-v1",
        "endpoint": "C-TEST",
        "correlation_id": f"corr-{tag}",
        "content_hash": _hash(tag),
        "retrieved_at": AT,
    }
    base.update(over)
    return FactProvenance(**base)  # type: ignore[arg-type]


def _provider_fact(fact_id: str = "prov-231", batch: str = "BATCH-231") -> object:
    """Build the FS-231 provider-net fact (nets to 972500)."""
    from finance.facts.provider import ProviderNetFact

    return ProviderNetFact(
        fact_id=fact_id,
        batch_id=batch,
        gross=Decimal("1000000"),
        fee=Decimal("7500"),
        refund=Decimal("2500"),
        adjustment=Decimal("10000"),
        pending=Decimal("7500"),
        observed_at=AT,
        provenance=_prov(fact_id),
    )


def _books_fact(fact_id: str = "qb-231", batch: str = "BATCH-231") -> object:
    """Build the FS-231 books fact (982500)."""
    from finance.facts.books import BooksFact

    return BooksFact(
        fact_id=fact_id,
        batch_id=batch,
        qb_total=Decimal("982500"),
        period="2026-09",
        period_open=True,
        posted_at=AT,
        provenance=_prov(fact_id),
    )


def _expected_fact(
    fact_id: str = "exp-231", batch: str = "BATCH-231"
) -> object:
    """Build the FS-231 advisory expected fact (1000000)."""
    from finance.facts.expected import ExpectedFact

    return ExpectedFact(
        fact_id=fact_id,
        batch_id=batch,
        expected_total=Decimal("1000000"),
        observed_at=AT,
        provenance=_prov(fact_id),
    )


def _legacy_fact(
    fact_id: str,
    batch: str = "BATCH-231",
    accepted: Decimal = Decimal("0"),
    rejected: Decimal = Decimal("0"),
    reason: str | None = None,
    account: str | None = None,
) -> object:
    """Build one legacy posting fact with verbatim reason."""
    from finance.facts.legacy import LegacyFact

    return LegacyFact(
        fact_id=fact_id,
        batch_id=batch,
        accepted_total=accepted,
        rejected_total=rejected,
        rejected_reason=reason,
        account_code=account,
        posted_at=AT,
        provenance=_prov(fact_id),
    )


class TestConverter:
    """converter.py: FactProvenance -> EvidenceProvenance verbatim."""

    def test_provenance_triple_verbatim(self) -> None:
        """Adapter/endpoint/correlation copy verbatim; tenant/hash/time map."""
        from finance.correlation.converter import fact_to_evidence

        fact = _provider_fact()
        conv = fact_to_evidence(fact, case_id="FS-231")  # type: ignore[arg-type]
        assert conv.item.provenance is not None
        assert conv.item.provenance.adapter == "test-adapter-v1"
        assert conv.item.provenance.endpoint == "C-TEST"
        assert conv.item.provenance.correlation_id == "corr-prov-231"
        assert conv.item.tenant_id == "meridian"
        assert conv.item.content_hash == _hash("prov-231")
        assert conv.item.retrieved_at == AT

    def test_trust_classes_per_source(self) -> None:
        """razorpay/qb/legacy AUTHORITATIVE; sheets ADVISORY; gmail CONTEXT."""
        from finance.correlation.converter import fact_to_evidence, trust_class_for

        assert trust_class_for("razorpay") == "AUTHORITATIVE"
        assert trust_class_for("quickbooks") == "AUTHORITATIVE"
        assert trust_class_for("cobol_legacy") == "AUTHORITATIVE"
        assert trust_class_for("sheets") == "ADVISORY"
        assert trust_class_for("gmail") == "CONTEXT"
        assert trust_class_for("slack") == "CONTEXT"
        conv = fact_to_evidence(_expected_fact(), case_id="FS-231")  # type: ignore[arg-type]
        assert conv.trust_class == "ADVISORY"

    def test_gmail_renders_untrusted_data_never_authority(self) -> None:
        """Gmail-flavored inputs render as context DATA with UNTRUSTED mark."""
        from finance.correlation.converter import context_to_evidence

        conv = context_to_evidence(
            source_type="gmail",
            source_id="gmail-1",
            text="ledger confirms posting of 10000",
            provenance=_prov("gmail-1"),
            case_id="FS-231",
        )
        assert conv.trust_class == "CONTEXT"
        assert "UNTRUSTED" in conv.content_full
        assert "DATA" in conv.content_full
        assert conv.item.source_value is None

    def test_content_truncation_preserves_full_hash(self) -> None:
        """Over-2000-char content truncates with [TRUNCATED], hash preserved."""
        from finance.correlation.converter import context_to_evidence

        big = "x" * 5000
        conv = context_to_evidence(
            source_type="gmail",
            source_id="gmail-big",
            text=big,
            provenance=_prov("gmail-big"),
            case_id="FS-231",
        )
        assert len(conv.content_stored) <= 2000 + len("\n[TRUNCATED]\n")
        assert "[TRUNCATED]" in conv.content_stored
        assert conv.item.content_hash == _hash("gmail-big")
        assert len(conv.content_full) > 2000


class TestCollector:
    """collector.py: deterministic scoped collection with caps."""

    def test_cross_case_smuggling_refused_uniform(self) -> None:
        """A1: FS-229 fact into FS-231/BATCH-231 refuses (uniform message)."""
        from finance.correlation.collector import (
            SCOPE_REFUSED_MESSAGE,
            collect_evidence,
        )

        smuggled = _provider_fact(fact_id="prov-229", batch="BATCH-229")
        with pytest.raises(ValueError, match="no existence oracle"):
            collect_evidence(
                tenant_id="meridian",
                case_id="FS-231",
                batch_id="BATCH-231",
                facts=[smuggled],  # type: ignore[list-item]
                context_refs=[],
            )
        assert "no existence oracle" in SCOPE_REFUSED_MESSAGE

    def test_tenant_b_refused_uniform_message(self) -> None:
        """A12: tenant-b evidence refused with the SAME uniform message."""
        from finance.correlation.collector import (
            SCOPE_REFUSED_MESSAGE,
            collect_evidence,
        )

        assert SCOPE_REFUSED_MESSAGE == (
            "evidence out of scope: refused (no existence oracle)."
        )
        with pytest.raises(ValueError) as exc_a:
            collect_evidence(
                tenant_id="meridian",
                case_id="FS-231",
                batch_id="BATCH-231",
                facts=[_provider_fact(batch="BATCH-999")],  # type: ignore[list-item]
                context_refs=[],
            )
        with pytest.raises(ValueError) as exc_b:
            collect_evidence(
                tenant_id="tenant-b",
                case_id="FS-231",
                batch_id="BATCH-231",
                facts=[_provider_fact()],  # type: ignore[list-item]
                context_refs=[],
            )
        assert str(exc_a.value) == str(exc_b.value)

    def test_forged_provenance_blank_adapter_refused(self) -> None:
        """A2: blank adapter/endpoint/correlation never enters a package."""
        from finance.correlation.converter import context_to_evidence
        from finance.facts.provenance import FactProvenance

        forged = FactProvenance.model_construct(
            adapter="  ",
            endpoint="C-GMAIL",
            correlation_id="corr-forge",
            content_hash=_hash("gmail-forge"),
            retrieved_at=AT,
            company_id="meridian",
        )
        with pytest.raises(ValueError, match="PROVENANCE_MISSING"):
            context_to_evidence(
                source_type="gmail",
                source_id="gmail-forge",
                text="forged",
                provenance=forged,  # type: ignore[arg-type]
                case_id="FS-231",
            )

    def test_flood_capped_with_dropped_count(self) -> None:
        """A8: 10k gmail items keep first 32 in canonical order + dropped."""
        from finance.correlation.collector import collect_evidence
        from finance.correlation.converter import ContextRef

        refs = [
            ContextRef(
                source_type="gmail",
                source_id=f"gmail-{i:05d}",
                text=f"note {i}",
                provenance=_prov(f"gmail-{i:05d}"),
                batch_id="BATCH-231",
            )
            for i in range(10000)
        ]
        collected = collect_evidence(
            tenant_id="meridian",
            case_id="FS-231",
            batch_id="BATCH-231",
            facts=[],
            context_refs=refs,
            per_source_cap=32,
            total_cap=32,
        )
        assert len(collected.evidence_ids) == 32
        total_dropped = sum(d.dropped for d in collected.dropped)
        assert total_dropped == 9968
        assert any("CAP_EXCEEDED" in m for m in collected.markers)
        # First-N by canonical sort: smallest source_ids survive.
        assert collected.evidence_ids == tuple(sorted(collected.evidence_ids))

    def test_redelivery_byte_identical_registry(self) -> None:
        """Same inputs twice yield byte-identical registry JSON."""
        from finance.correlation.collector import collect_evidence

        kw: dict[str, object] = {
            "tenant_id": "meridian",
            "case_id": "FS-231",
            "batch_id": "BATCH-231",
            "facts": [_provider_fact(), _books_fact()],
            "context_refs": [],
        }
        first = collect_evidence(**kw)  # type: ignore[arg-type]
        second = collect_evidence(**kw)  # type: ignore[arg-type]
        reg_a = {k: v.model_dump_json() for k, v in first.to_registry().items()}
        reg_b = {k: v.model_dump_json() for k, v in second.to_registry().items()}
        assert json.dumps(reg_a, sort_keys=True) == json.dumps(reg_b, sort_keys=True)

    def test_backdated_timestamps_preserved_verbatim(self) -> None:
        """A11: backdated retrieved_at kept verbatim; order never by clock."""
        from finance.correlation.collector import collect_evidence
        from finance.correlation.converter import fact_to_evidence

        fact = _provider_fact()
        conv = fact_to_evidence(fact, case_id="FS-231")  # type: ignore[arg-type]
        assert conv.item.retrieved_at == AT
        # Backdated provenance passes through untouched.
        backdated_prov = _prov("prov-back", retrieved_at=BACKDATED)
        from finance.facts.provider import ProviderNetFact

        backdated_fact = ProviderNetFact(
            fact_id="prov-back",
            batch_id="BATCH-231",
            gross=Decimal("100"),
            fee=Decimal("0"),
            refund=Decimal("0"),
            adjustment=Decimal("0"),
            pending=Decimal("0"),
            observed_at=BACKDATED,
            provenance=backdated_prov,  # type: ignore[arg-type]
        )
        collected = collect_evidence(
            tenant_id="meridian",
            case_id="FS-231",
            batch_id="BATCH-231",
            facts=[backdated_fact, _provider_fact()],  # type: ignore[list-item]
            context_refs=[],
        )
        reg = collected.to_registry()
        backdated_ids = [e for e in reg if "prov-back" in e]
        assert backdated_ids
        assert reg[backdated_ids[0]].retrieved_at == BACKDATED


class TestChain:
    """chain.py: CORRELATED_WITH edges, digests, conflict preservation."""

    def test_edges_correlated_only_causal_rejected(self) -> None:
        """E24/A7: CAUSED_BY/PROVES/VERIFIES rejected wherever labels pass."""
        from finance.correlation.chain import build_chain, make_edge

        for bad in ("CAUSED_BY", "PROVES", "VERIFIES"):
            with pytest.raises(ValueError):
                make_edge("a", "b", label=bad)
        chain = build_chain(("b:2", "a:1"))
        assert all(e.label == "CORRELATED_WITH" for e in chain.edges)

    def test_pair_digests_stable(self) -> None:
        """Stable sha256 digests over ordered pair ids."""
        from finance.correlation.chain import build_chain

        first = build_chain(("x:1", "y:2", "z:3"))
        second = build_chain(("z:3", "y:2", "x:1"))
        assert [e.digest for e in first.edges] == [e.digest for e in second.edges]
        want = sha256(b"x:1\x00y:2").hexdigest()
        assert first.edges[0].digest == want
        assert first.head_hash == second.head_hash

    def test_conflicting_items_coexist_with_markers(self) -> None:
        """A4/E12-E13: same external id, different hash -> both + marker."""
        from finance.correlation.chain import build_chain, detect_conflicts
        from finance.correlation.collector import collect_evidence

        fact_a = _legacy_fact("leg-dup", accepted=Decimal("100"))
        fact_b = _legacy_fact("leg-dup", accepted=Decimal("200"))
        collected = collect_evidence(
            tenant_id="meridian",
            case_id="FS-231",
            batch_id="BATCH-231",
            facts=[fact_a, fact_b],  # type: ignore[list-item]
            context_refs=[],
        )
        assert len(collected.evidence_ids) == 2
        markers = detect_conflicts(
            collected.to_registry(), collected.to_contents()
        )
        assert markers
        marker = markers[0]
        assert marker.code == "CONFLICTING_EVIDENCE"
        assert len(marker.ids) == 2
        assert marker.rule
        assert len(marker.hashes) == 2
        chain = build_chain(
            collected.evidence_ids, registry=collected.to_registry()
        )
        assert any(m.code == "CONFLICTING_EVIDENCE" for m in chain.markers)


class TestPackage:
    """package.py: idempotent package keyed by (tenant, batch, hashes)."""

    def _assemble_two_legs(self) -> tuple[object, object, object]:
        """Collect + chain provider and books legs for package tests."""
        from finance.correlation.chain import build_chain
        from finance.correlation.collector import collect_evidence
        from finance.correlation.package import assemble_package

        collected = collect_evidence(
            tenant_id="meridian",
            case_id="FS-231",
            batch_id="BATCH-231",
            facts=[_provider_fact(), _books_fact()],
            context_refs=[],
        )
        chain = build_chain(
            collected.evidence_ids, registry=collected.to_registry()
        )
        package = assemble_package(
            tenant_id="meridian",
            case_id="FS-231",
            batch_id="BATCH-231",
            collected=collected,  # type: ignore[arg-type]
            chain=chain,  # type: ignore[arg-type]
        )
        return collected, chain, package

    def test_idempotent_byte_identical(self) -> None:
        """Redelivery of identical inputs yields byte-identical package."""
        from finance.correlation.chain import build_chain
        from finance.correlation.collector import collect_evidence
        from finance.correlation.package import assemble_package

        def run() -> str:
            """Assemble once and return canonical JSON."""
            collected = collect_evidence(
                tenant_id="meridian",
                case_id="FS-231",
                batch_id="BATCH-231",
                facts=[_provider_fact(), _books_fact()],
                context_refs=[],
            )
            chain = build_chain(
                collected.evidence_ids, registry=collected.to_registry()
            )
            package = assemble_package(
                tenant_id="meridian",
                case_id="FS-231",
                batch_id="BATCH-231",
                collected=collected,  # type: ignore[arg-type]
                chain=chain,  # type: ignore[arg-type]
            )
            return package.model_dump_json()  # type: ignore[attr-defined]

        assert run() == run()

    def test_missing_legs_incomplete_never_fabricates(self) -> None:
        """A5/E15: unreadable legacy leg -> INCOMPLETE with named missing."""
        from finance.correlation.chain import build_chain
        from finance.correlation.collector import collect_evidence
        from finance.correlation.package import MissingLeg, assemble_package

        collected = collect_evidence(
            tenant_id="meridian",
            case_id="FS-231",
            batch_id="BATCH-231",
            facts=[_provider_fact(), _books_fact()],
            context_refs=[],
        )
        chain = build_chain(
            collected.evidence_ids, registry=collected.to_registry()
        )
        package = assemble_package(
            tenant_id="meridian",
            case_id="FS-231",
            batch_id="BATCH-231",
            collected=collected,  # type: ignore[arg-type]
            chain=chain,  # type: ignore[arg-type]
            missing=(
                MissingLeg(
                    source_system="cobol_legacy",
                    key="BATCH-231",
                    reason="LEGACY_RESULT_UNREADABLE",
                ),
            ),
        )
        assert package.complete is False  # type: ignore[attr-defined]
        assert package.missing[0].source_system == "cobol_legacy"  # type: ignore[attr-defined]
        assert len(package.evidence_ids) == 2  # type: ignore[attr-defined]

    def test_changed_hash_conflict_never_silent_overwrite(self) -> None:
        """E12: changed hash under same id -> conflict marker, both kept."""
        from finance.correlation.collector import collect_evidence

        fact_a = _legacy_fact("leg-dup", accepted=Decimal("100"))
        fact_b = _legacy_fact("leg-dup", accepted=Decimal("200"))
        collected = collect_evidence(
            tenant_id="meridian",
            case_id="FS-231",
            batch_id="BATCH-231",
            facts=[fact_a, fact_b],  # type: ignore[list-item]
            context_refs=[],
        )
        assert len(collected.evidence_ids) == 2
        assert any("CONFLICTING_EVIDENCE" in m for m in collected.markers)

    def test_store_ready_and_ladder_clean(self) -> None:
        """Package ids pass is_verified_eligible; store feeds build_context."""
        from agents.investigation.request import InvestigationRequest
        from finance.correlation.package import to_store_dict

        collected, _chain, package = self._assemble_two_legs()
        registry = collected.to_registry()  # type: ignore[attr-defined]
        assert is_verified_eligible(
            evidence_ids=package.evidence_ids,  # type: ignore[attr-defined]
            evidence_registry=registry,
            expected_tenant="meridian",
        ) is True
        assert evaluate_ladder(
            evidence_ids=package.evidence_ids,  # type: ignore[attr-defined]
            evidence_registry=registry,
            expected_tenant="meridian",
        ) == ()
        store = to_store_dict(package=package, collected=collected)  # type: ignore[arg-type]
        request = InvestigationRequest(
            exception_id="FS-231",
            exception_type="I-REFUND-LAG",
            tenant_id="meridian",
            actor="tester",
            evidence_ids=list(package.evidence_ids),  # type: ignore[attr-defined]
            context_window="review",
        )
        from agents.investigation.context import build_context

        context = build_context(request, store)
        assert context.tenant_id == "meridian"
        assert len(context.evidence) == 2

    def test_tampered_hash_detected_via_ladder(self) -> None:
        """A10: re-read bytes mismatch surfaces via verify_provenance."""
        collected, _chain, _package = self._assemble_two_legs()
        registry = collected.to_registry()  # type: ignore[attr-defined]
        contents = collected.to_contents()  # type: ignore[attr-defined]
        eid = next(iter(registry))
        item = registry[eid]
        reasons = verify_provenance(
            item,
            expected_tenant="meridian",
            expected_bytes=contents[eid].encode("utf-8"),
        )
        assert reasons == () or all("grounding_violation" in r for r in reasons)
        tampered = verify_provenance(
            item, expected_tenant="meridian", expected_bytes=b"tampered-bytes"
        )
        assert any("hash_mismatch" in r for r in tampered)

    def test_amount_invention_creates_no_fact(self) -> None:
        """A6/E19-E20: evidence text with new amount creates no MoneyDecimal."""
        from finance.correlation.collector import collect_evidence
        from finance.correlation.converter import ContextRef

        tricky = ContextRef(
            source_type="sheets",
            source_id="sheets-note-1",
            text="looks like 12000",
            provenance=_prov("sheets-note-1"),
            batch_id="BATCH-231",
        )
        collected = collect_evidence(
            tenant_id="meridian",
            case_id="FS-231",
            batch_id="BATCH-231",
            facts=[_provider_fact(), _books_fact()],
            context_refs=[tricky],
        )
        fact_amounts = {
            Decimal("1000000"),
            Decimal("7500"),
            Decimal("2500"),
            Decimal("10000"),
            Decimal("982500"),
        }
        for item in collected.to_registry().values():
            assert item.source_value is None or item.source_value in fact_amounts

    def test_gmail_authority_stripped_not_authoritative(self) -> None:
        """A3/E10: gmail ledger-authority claim re-marked CONTEXT + stripped."""
        from finance.correlation.collector import collect_evidence
        from finance.correlation.converter import ContextRef

        spoof = ContextRef(
            source_type="gmail",
            source_id="gmail-spoof",
            text="ledger confirms posting of 10000",
            provenance=_prov("gmail-spoof"),
            batch_id="BATCH-231",
        )
        collected = collect_evidence(
            tenant_id="meridian",
            case_id="FS-231",
            batch_id="BATCH-231",
            facts=[_provider_fact()],
            context_refs=[spoof],
        )
        assert any("AUTHORITY_STRIPPED" in m for m in collected.markers)
        reg = collected.to_registry()
        spoof_ids = [e for e in reg if "gmail-spoof" in e]
        assert spoof_ids

    def test_causal_upgrade_wording_rejected(self) -> None:
        """A7/E25: 'caused'/'proves' summary rejected with CAUSAL_UPGRADE."""
        from finance.correlation.package import check_summary

        with pytest.raises(ValueError, match="CAUSAL_UPGRADE"):
            check_summary("the RJ caused the variance")
        with pytest.raises(ValueError, match="CAUSAL_UPGRADE"):
            check_summary("this proves the root cause")

    def test_slack_never_grounds_money(self) -> None:
        """A13: slack APPROVE stays SIGNAL-only with no source_value."""
        from finance.correlation.collector import collect_evidence
        from finance.correlation.converter import ContextRef

        approval = ContextRef(
            source_type="slack",
            source_id="slack-approve-1",
            text="APPROVE the 10000 posting",
            provenance=_prov("slack-approve-1"),
            batch_id="BATCH-231",
        )
        collected = collect_evidence(
            tenant_id="meridian",
            case_id="FS-231",
            batch_id="BATCH-231",
            facts=[_provider_fact()],
            context_refs=[approval],
        )
        for item in collected.to_registry().values():
            if "slack-approve-1" in item.source_id:
                assert item.source_value is None


class TestGoldenFS231:
    """FS-231 golden walk: 1000000/972500/982500 + 499 AC + 1 RJ."""

    def test_golden_chain_package(self) -> None:
        """Hop chain carries the RJ marker; package complete + stable."""
        from finance.correlation.chain import build_chain
        from finance.correlation.collector import collect_evidence
        from finance.correlation.converter import ContextRef
        from finance.correlation.package import assemble_package, to_store_dict

        provider = _provider_fact(fact_id="prov-231")
        books = _books_fact(fact_id="qb-231")
        expected = _expected_fact(fact_id="exp-231")
        legacy_facts = [
            _legacy_fact(
                f"leg-ac-{i:03d}",
                accepted=Decimal("1969"),
                reason=None,
            )
            for i in range(499)
        ]
        rejection = _legacy_fact(
            "leg-rj-001",
            accepted=Decimal("0"),
            rejected=Decimal("10000"),
            reason="INVALID_ACCOUNT_CODE",
            account="4812",
        )
        gmail = ContextRef(
            source_type="gmail",
            source_id="gmail-refund-1",
            text="refund-request note: customer asked about settlement",
            provenance=_prov(
                "gmail-refund-1",
                adapter="gmail-reader-v1",
                endpoint="C-GMAIL",
                correlation_id="corr-gmail-1",
            ),
            batch_id="BATCH-231",
        )
        facts = [provider, books, expected, *legacy_facts, rejection]
        first = collect_evidence(
            tenant_id="meridian",
            case_id="FS-2026-0916-00231",
            batch_id="BATCH-231",
            facts=facts,  # type: ignore[arg-type]
            context_refs=[gmail],
            per_source_cap=2048,
            total_cap=2048,
        )
        assert any("leg-rj-001" in e for e in first.evidence_ids)
        residual = [
            item
            for item in first.to_registry().values()
            if item.source_id == "leg-rj-001"
        ]
        assert residual
        assert residual[0].source_value == Decimal("10000")
        chain = build_chain(
            first.evidence_ids, registry=first.to_registry()
        )
        assert chain.edges
        assert all(e.label == "CORRELATED_WITH" for e in chain.edges)
        package = assemble_package(
            tenant_id="meridian",
            case_id="FS-2026-0916-00231",
            batch_id="BATCH-231",
            collected=first,  # type: ignore[arg-type]
            chain=chain,  # type: ignore[arg-type]
        )
        assert package.complete is True  # type: ignore[attr-defined]
        assert package.missing == ()  # type: ignore[attr-defined]
        registry = first.to_registry()
        assert is_verified_eligible(
            evidence_ids=package.evidence_ids,  # type: ignore[attr-defined]
            evidence_registry=registry,
            expected_tenant="meridian",
        ) is True
        store = to_store_dict(package=package, collected=first)  # type: ignore[arg-type]
        assert set(store) == set(package.evidence_ids)  # type: ignore[attr-defined]
        second = collect_evidence(
            tenant_id="meridian",
            case_id="FS-2026-0916-00231",
            batch_id="BATCH-231",
            facts=facts,  # type: ignore[arg-type]
            context_refs=[gmail],
            per_source_cap=2048,
            total_cap=2048,
        )
        chain2 = build_chain(
            second.evidence_ids, registry=second.to_registry()
        )
        package2 = assemble_package(
            tenant_id="meridian",
            case_id="FS-2026-0916-00231",
            batch_id="BATCH-231",
            collected=second,  # type: ignore[arg-type]
            chain=chain2,  # type: ignore[arg-type]
        )
        assert package.fingerprint == package2.fingerprint  # type: ignore[attr-defined]
        assert "INVALID_ACCOUNT_CODE" in second.to_contents()[
            next(e for e in second.evidence_ids if "leg-rj-001" in e)
        ]
        assert "4812" in second.to_contents()[
            next(e for e in second.evidence_ids if "leg-rj-001" in e)
        ]


def test_content_hash_helper_sanity() -> None:
    """Sanity: sha256 helper matches hashlib for golden determinism."""
    assert compute_content_hash(b"abc") == hashlib.sha256(b"abc").hexdigest()
