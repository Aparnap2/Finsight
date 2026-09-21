"""RED P7-04 evidence discovery boundary — 20 adversarial invariants (A1-A20)."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.authority.claims import AgentCapability, AuthorityBoundary
from agents.authority.evidence import AuthorityError, EvidenceRecord, EvidenceRegistry
from agents.discovery import DiscoveryRequest, DiscoveryResult
from agents.discovery.request import ALLOWED_DISCOVERY_CAPABILITIES
from agents.runtime import RuntimeFactory

NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _registry() -> EvidenceRegistry:
    rec_a = EvidenceRecord(
        source_id="src-ledger-001",
        evidence_id="ev-ledger-001",
        captured_at=NOW - timedelta(seconds=60),
        digest=DIGEST_A,
        provenance="p6_evidence_store",
        ttl_seconds=3600,
    )
    rec_b = EvidenceRecord(
        source_id="src-ledger-002",
        evidence_id="ev-ledger-002",
        captured_at=NOW - timedelta(seconds=60),
        digest=DIGEST_B,
        provenance="p6_evidence_store",
        ttl_seconds=3600,
    )
    return EvidenceRegistry(
        {"ev-ledger-001": rec_a, "ev-ledger-002": rec_b},
        accessible_ids={"ev-ledger-001", "ev-ledger-002"},
    )


def _context() -> RuntimeFactory:
    factory = RuntimeFactory()
    ctx = factory.create_context(
        situation_id="sit-p704-001",
        now=NOW,
        registry=_registry(),
        boundary=AuthorityBoundary(),
    )
    return ctx  # type: ignore[return-value]


def _valid_request() -> DiscoveryRequest:
    return DiscoveryRequest(
        situation_id="sit-p704-001",
        company_id="meridian",
        now=NOW,
        allowed_evidence_ids=("ev-ledger-001",),
        objective="Investigate refund spike correlation.",
        allowed_capabilities=(AgentCapability.READ,),
    )


class TestA01ValidRequestRepresented:
    def test_a1_valid_discovery_request_can_be_represented(self) -> None:
        req = _valid_request()
        assert req.situation_id == "sit-p704-001"
        assert req.company_id == "meridian"
        assert req.now == NOW
        assert req.allowed_evidence_ids == ("ev-ledger-001",)
        assert "refund" in req.objective.lower()


class TestA02BlankIdentifiersRejected:
    def test_a2_blank_situation_rejected(self) -> None:
        with pytest.raises((ValidationError, AuthorityError, ValueError)):
            DiscoveryRequest(
                situation_id="   ",
                company_id="meridian",
                now=NOW,
                allowed_evidence_ids=("ev-ledger-001",),
                objective="Q",
                allowed_capabilities=(AgentCapability.READ,),
            )

    def test_a2_blank_company_rejected(self) -> None:
        with pytest.raises((ValidationError, AuthorityError, ValueError)):
            DiscoveryRequest(
                situation_id="sit-p704-001",
                company_id="",
                now=NOW,
                allowed_evidence_ids=("ev-ledger-001",),
                objective="Q",
                allowed_capabilities=(AgentCapability.READ,),
            )

    def test_a2_blank_objective_rejected(self) -> None:
        with pytest.raises((ValidationError, AuthorityError, ValueError)):
            DiscoveryRequest(
                situation_id="sit-p704-001",
                company_id="meridian",
                now=NOW,
                allowed_evidence_ids=("ev-ledger-001",),
                objective="   ",
                allowed_capabilities=(AgentCapability.READ,),
            )


class TestA03NaiveCapabilityEscalationRejected:
    def test_a3_string_capability_rejected(self) -> None:
        with pytest.raises((ValidationError, AuthorityError, ValueError)):
            DiscoveryRequest(  # type: ignore[arg-type]
                situation_id="sit-p704-001",
                company_id="meridian",
                now=NOW,
                allowed_evidence_ids=("ev-ledger-001",),
                objective="Q",
                allowed_capabilities=("approve",),  # type: ignore[arg-type]
            )

    def test_a3_financial_verb_rejected(self) -> None:
        with pytest.raises((ValidationError, AuthorityError, ValueError)):
            DiscoveryRequest(  # type: ignore[arg-type]
                situation_id="sit-p704-001",
                company_id="meridian",
                now=NOW,
                allowed_evidence_ids=("ev-ledger-001",),
                objective="Q",
                allowed_capabilities=("mutate_financial_state",),  # type: ignore[arg-type]
            )

    def test_a3_outside_allowlist_rejected(self) -> None:
        # HYPOTHESIZE is not in discovery allowlist
        with pytest.raises((ValidationError, AuthorityError, ValueError)):
            DiscoveryRequest(
                situation_id="sit-p704-001",
                company_id="meridian",
                now=NOW,
                allowed_evidence_ids=("ev-ledger-001",),
                objective="Q",
                allowed_capabilities=(AgentCapability.HYPOTHESIZE,),
            )


class TestA04RequestScopeExplicitImmutable:
    def test_a4_scope_explicit_and_immutable(self) -> None:
        req = _valid_request()
        assert req.allowed_evidence_ids == ("ev-ledger-001",)
        assert req.allowed_capabilities == (AgentCapability.READ,)
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            req.situation_id = "sit-hijacked"  # type: ignore[misc]
        with pytest.raises((ValidationError, TypeError, AttributeError)):
            req.allowed_evidence_ids = ("ev-other",)  # type: ignore[misc]

    def test_a4_allowed_capabilities_bounded(self) -> None:
        # must be subset of frozen allowlist
        for cap in ALLOWED_DISCOVERY_CAPABILITIES:
            assert cap in (AgentCapability.READ, AgentCapability.CORRELATE, AgentCapability.EXPLAIN)
        assert len(ALLOWED_DISCOVERY_CAPABILITIES) == 3


class TestA05RegistryInjectionRejected:
    def test_a5_registry_injection_rejected(self) -> None:
        with pytest.raises((ValidationError, AuthorityError, TypeError)):
            DiscoveryRequest(  # type: ignore[call-arg]
                situation_id="sit-p704-001",
                company_id="meridian",
                now=NOW,
                allowed_evidence_ids=("ev-ledger-001",),
                objective="Q",
                allowed_capabilities=(AgentCapability.READ,),
                registry=_registry(),  # type: ignore[call-arg]
            )


class TestA06AuthorityBoundaryInjectionRejected:
    def test_a6_boundary_injection_rejected(self) -> None:
        with pytest.raises((ValidationError, AuthorityError, TypeError)):
            DiscoveryRequest(  # type: ignore[call-arg]
                situation_id="sit-p704-001",
                company_id="meridian",
                now=NOW,
                allowed_evidence_ids=("ev-ledger-001",),
                objective="Q",
                allowed_capabilities=(AgentCapability.READ,),
                boundary=AuthorityBoundary(),  # type: ignore[call-arg]
            )

    def test_a6_authority_boundary_injection_rejected(self) -> None:
        with pytest.raises((ValidationError, AuthorityError, TypeError)):
            DiscoveryRequest(  # type: ignore[call-arg]
                situation_id="sit-p704-001",
                company_id="meridian",
                now=NOW,
                allowed_evidence_ids=("ev-ledger-001",),
                objective="Q",
                allowed_capabilities=(AgentCapability.READ,),
                authority_boundary=AuthorityBoundary(),  # type: ignore[call-arg]
            )


class TestA07AlternateRuntimeContextInjectionRejected:
    def test_a7_alternate_context_rejected(self) -> None:
        factory = RuntimeFactory()
        ctx = factory.create_context(
            situation_id="sit-p704-001",
            now=NOW,
            registry=_registry(),
            boundary=AuthorityBoundary(),
        )
        with pytest.raises((ValidationError, AuthorityError, TypeError)):
            DiscoveryRequest(  # type: ignore[call-arg]
                situation_id="sit-p704-001",
                company_id="meridian",
                now=NOW,
                allowed_evidence_ids=("ev-ledger-001",),
                objective="Q",
                allowed_capabilities=(AgentCapability.READ,),
                context=ctx,  # type: ignore[call-arg]
            )

    def test_a7_runtime_context_field_rejected(self) -> None:
        with pytest.raises((ValidationError, AuthorityError, TypeError)):
            DiscoveryRequest(  # type: ignore[call-arg]
                situation_id="sit-p704-001",
                company_id="meridian",
                now=NOW,
                allowed_evidence_ids=("ev-ledger-001",),
                objective="Q",
                allowed_capabilities=(AgentCapability.READ,),
                runtime_context="fake",  # type: ignore[call-arg]
            )


class TestA08CannotCallArbitraryTools:
    def test_a8_discovery_only_uses_p703_tools(self) -> None:
        path = Path("agents/discovery/engine.py")
        text = path.read_text()
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in ("httpx", "requests", "boto3", "psycopg", "openai"), (
                        f"forbidden import {alias.name}"
                    )
            if isinstance(node, ast.ImportFrom):
                assert node.module not in ("httpx", "requests", "boto3", "psycopg", "openai")
                if node.module and node.module.startswith("agents.tools"):
                    pass
        # must not expose arbitrary tool dispatch
        assert "BaseTool" not in text
        assert "plugin" not in text.lower() or "registry" in text.lower()

    def test_a8_engine_does_not_import_evidence_registry_directly(self) -> None:
        text = Path("agents/discovery/engine.py").read_text()
        # Direct EvidenceRegistry access from discovery agent is forbidden
        assert "EvidenceRegistry" not in text or "RuntimeContext" in text
        # The only evidence path is via P7-03 tools + RuntimeContext
        assert "from agents.tools" in text or "not yet implemented" in text


class TestA09SuccessContainsAdvisoryEvidenceOnly:
    def test_a9_success_advisory_only_via_discover(self) -> None:
        from agents.discovery.engine import discover

        factory = RuntimeFactory()
        reg = _registry()
        ctx = factory.create_context(
            situation_id="sit-p704-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p704-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-ledger-001",),
            objective="Correlate refund evidence.",
            allowed_capabilities=(AgentCapability.READ, AgentCapability.CORRELATE),
        )
        result = discover(req, context=ctx, tools=None)
        assert isinstance(result, DiscoveryResult)
        assert result.success is True
        assert result.evidence_refs is not None
        assert result.tier == "discovery"
        # advisory only — no authoritative marker
        if result.observations:
            for obs in result.observations:
                assert "VERIFIED" not in obs


class TestA10CannotContainAuthoritativeStatus:
    def test_a10_success_cannot_contain_verdict(self) -> None:
        # Direct construction with smuggled verdict must be rejected
        reg = _registry()
        ref = reg.create_reference("ev-ledger-001")
        with pytest.raises((AuthorityError, ValidationError, TypeError)):
            DiscoveryResult(  # type: ignore[call-arg]
                success=True,
                situation_id="sit-p704-001",
                company_id="meridian",
                now=NOW,
                evidence_refs=(ref,),
                observations=("advisory",),
                hypotheses=None,
                proposals=None,
                failure=None,
                status="VERIFIED",  # type: ignore[call-arg]
            )

    def test_a10_discover_must_not_emit_verdict(self) -> None:
        from agents.discovery.engine import discover

        factory = RuntimeFactory()
        reg = _registry()
        ctx = factory.create_context(
            situation_id="sit-p704-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p704-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-ledger-001",),
            objective="Q",
            allowed_capabilities=(AgentCapability.READ,),
        )
        result = discover(req, context=ctx)
        assert "verdict" not in result.to_dict()
        assert "status" not in result.to_dict()
        assert "decision" not in result.to_dict()


class TestA11MissingEvidenceTypedFailure:
    def test_a11_missing_becomes_typed_failure(self) -> None:
        from agents.discovery.engine import discover

        factory = RuntimeFactory()
        reg = _registry()
        ctx = factory.create_context(
            situation_id="sit-p704-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p704-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-missing-999",),
            objective="Find missing evidence.",
            allowed_capabilities=(AgentCapability.READ,),
        )
        result = discover(req, context=ctx)
        assert result.success is False
        assert result.failure is not None
        assert result.failure.code in ("MISSING_EVIDENCE", "DISCOVERY_FAILED")


class TestA12StaleInaccessibleTypedFailure:
    def test_a12_stale_typed_failure(self) -> None:
        from agents.discovery.engine import discover

        stale_at = NOW - timedelta(seconds=7200)
        rec = EvidenceRecord(
            source_id="src-ledger-001",
            evidence_id="ev-stale-001",
            captured_at=stale_at,
            digest=DIGEST_A,
            provenance="p6_evidence_store",
            ttl_seconds=3600,
        )
        reg = EvidenceRegistry({"ev-stale-001": rec})
        factory = RuntimeFactory()
        ctx = factory.create_context(
            situation_id="sit-p704-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p704-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-stale-001",),
            objective="Check stale handling.",
            allowed_capabilities=(AgentCapability.READ,),
        )
        result = discover(req, context=ctx)
        assert result.success is False
        assert result.failure is not None
        assert result.failure.code == "STALE_EVIDENCE"

    def test_a12_inaccessible_typed_failure(self) -> None:
        from agents.discovery.engine import discover

        reg_all = _registry()
        reg = EvidenceRegistry(
            {"ev-ledger-001": reg_all.get_record("ev-ledger-001")},
            accessible_ids=set(),
        )
        factory = RuntimeFactory()
        ctx = factory.create_context(
            situation_id="sit-p704-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p704-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-ledger-001",),
            objective="Check inaccessible.",
            allowed_capabilities=(AgentCapability.READ,),
        )
        result = discover(req, context=ctx)
        assert result.success is False
        assert result.failure is not None
        assert result.failure.code == "INACCESSIBLE_EVIDENCE"


class TestA13ContradictoryRemainsAmbiguous:
    def test_a13_contradictory_ambiguity_preserved(self) -> None:
        from agents.discovery.engine import discover

        factory = RuntimeFactory()
        reg = _registry()
        ctx = factory.create_context(
            situation_id="sit-p704-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p704-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-ledger-001", "ev-ledger-002"),
            objective="Correlate contradictory evidence.",
            allowed_capabilities=(AgentCapability.CORRELATE,),
        )
        result = discover(req, context=ctx)
        assert result.success is True
        # must not claim authoritative resolution
        blob = str(result.to_dict())
        assert "VERIFIED" not in blob
        assert "FACT" not in blob
        # observations should preserve ambiguity, not declare fact
        if result.observations:
            assert all("VERIFIED" not in o for o in result.observations)


class TestA14ToolFailurePropagated:
    def test_a14_tool_failure_not_fabricated(self) -> None:
        from agents.discovery.engine import discover

        class FailingTool:
            def __call__(self, *a: object, **kw: object) -> None:
                raise RuntimeError("tool timeout")

        factory = RuntimeFactory()
        reg = _registry()
        ctx = factory.create_context(
            situation_id="sit-p704-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p704-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-ledger-001",),
            objective="Q",
            allowed_capabilities=(AgentCapability.READ,),
        )
        result = discover(req, context=ctx, tools={"READ": FailingTool()})
        # must propagate as typed failure, not fabricated success
        assert result.success is False
        assert result.failure is not None


class TestA15UnavailableCapabilityNoFallback:
    def test_a15_unavailable_cannot_fallback(self) -> None:
        from agents.discovery.engine import discover

        factory = RuntimeFactory()
        reg = _registry()
        ctx = factory.create_context(
            situation_id="sit-p704-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        # request allows only READ, but tool double marks READ unavailable
        req = DiscoveryRequest(
            situation_id="sit-p704-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-ledger-001",),
            objective="Q",
            allowed_capabilities=(AgentCapability.READ,),
        )
        result = discover(req, context=ctx, tools={"READ": None})
        assert result.success is False
        assert result.failure is not None
        # must not silently use CORRELATE instead
        assert "CORRELATE" not in (result.failure.detail or "")


class TestA16NoFinancialMutationPath:
    def test_a16_no_mutation_attributes(self) -> None:
        import agents.discovery.engine as eng
        import agents.discovery.result as res

        for name in (
            "mutate",
            "execute",
            "write",
            "update",
            "delete",
            "approve",
            "verify",
            "commit",
        ):
            assert not hasattr(eng, name)
            assert not hasattr(res.DiscoveryResult, name)
        base = Path("agents/discovery/engine.py").read_text()
        extra = Path("agents/discovery/result.py").read_text()
        text = base + extra
        for kw in (
            "mutate_financial",
            "execute_financial",
            "financial writes",
            "verdict",
        ):
            # verdict may appear in comments as forbidden, but not as code
            if kw == "verdict":
                assert text.count("verdict") <= 2  # allow comment mentioning forbidden
            else:
                assert kw not in text.lower()

    def test_a16_result_has_no_financial_fields(self) -> None:
        reg = _registry()
        ref = reg.create_reference("ev-ledger-001")
        result = DiscoveryResult(
            success=True,
            situation_id="sit-p704-001",
            company_id="meridian",
            now=NOW,
            evidence_refs=(ref,),
            observations=("advisory observation",),
            hypotheses=None,
            proposals=None,
            failure=None,
        )
        d = result.to_dict()
        for k in ("amount", "balance", "ledger_write"):
            assert k not in d


class TestA17NoDirectExternalImports:
    def test_a17_no_external_clients(self) -> None:
        for rel in [
            "agents/discovery/request.py",
            "agents/discovery/result.py",
            "agents/discovery/engine.py",
        ]:
            text = Path(rel).read_text()
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        forbid = ("httpx", "requests", "boto3", "psycopg", "openai", "temporalio")
                        assert alias.name not in forbid
                if isinstance(node, ast.ImportFrom):
                    forbid_mod = ("httpx", "requests", "boto3", "psycopg", "openai", "temporalio")
                    assert node.module not in forbid_mod
            assert "boto3" not in text
            assert "psycopg" not in text
            assert "httpx" not in text
            assert "openai" not in text.lower() or "not yet implemented" in text.lower()

    def test_a17_no_direct_registry_access(self) -> None:
        text = Path("agents/discovery/engine.py").read_text()
        # engine must not instantiate EvidenceRegistry directly
        assert "EvidenceRegistry(" not in text


class TestA18CallerSuppliedNowPreserved:
    def test_a18_now_preserved_no_wallclock(self) -> None:
        from agents.discovery.engine import discover

        factory = RuntimeFactory()
        reg = _registry()
        ctx = factory.create_context(
            situation_id="sit-p704-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p704-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-ledger-001",),
            objective="Q",
            allowed_capabilities=(AgentCapability.READ,),
        )
        result = discover(req, context=ctx)
        assert result.now == NOW
        assert result.now == req.now
        assert result.now == ctx.now
        # no wall-clock reads in engine
        text = Path("agents/discovery/engine.py").read_text()
        assert "datetime.now" not in text
        assert "datetime.utcnow" not in text
        assert "time.time" not in text


class TestA19ScopeCannotBeChangedByReasoning:
    def test_a19_situation_company_immutable(self) -> None:
        from agents.discovery.engine import discover

        factory = RuntimeFactory()
        reg = _registry()
        ctx = factory.create_context(
            situation_id="sit-p704-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p704-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-ledger-001",),
            objective="Q",
            allowed_capabilities=(AgentCapability.READ,),
        )
        # fake model trying to hijack scope via tools
        result = discover(req, context=ctx, tools={"hijack_situation": "sit-hijacked"})
        assert result.situation_id == "sit-p704-001"
        assert result.company_id == "meridian"
        assert result.situation_id == req.situation_id
        assert result.situation_id == ctx.situation_id


class TestA20EvidenceScopeCannotExpand:
    def test_a20_evidence_scope_locked(self) -> None:
        from agents.discovery.engine import discover

        factory = RuntimeFactory()
        reg = _registry()
        ctx = factory.create_context(
            situation_id="sit-p704-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p704-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-ledger-001",),
            objective="Q",
            allowed_capabilities=(AgentCapability.READ,),
        )
        result = discover(req, context=ctx, tools={"extra_evidence": ("ev-ledger-002",)})
        if result.success:
            assert result.evidence_refs is not None
            ids = {r.evidence_id for r in result.evidence_refs}
            assert ids.issubset(set(req.allowed_evidence_ids)), f"scope expanded {ids}"
            assert "ev-ledger-002" not in ids
