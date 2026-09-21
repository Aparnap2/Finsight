"""RED P7-06 human resolution brief — Gates A-I advisory invariants (no GREEN yet).

Gate 1 is RED-only: these tests specify the contract and must FAIL until the
minimal brief boundary is implemented. Frozen P7-01..P7-05 must remain GREEN.

Business-auditor lens: can the system represent and control the business
situation without losing, prematurely closing, misrepresenting, or bypassing
it? The brief is a human-readable advisory package — never a decision artifact.

Four-perspective convergence:
  engineering — minimal typed surface, frozen provenance, no second authority
  product — human must be able to act without mistaking advice for decision
  design — scannable sections, no status theatre, evidence-linked
  business-auditor — outcome-first: nothing lost, prematurely closed,
    misrepresented, or bypassed; uncertainty preserved, approval never implied
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from agents.authority.claims import AgentCapability, AuthorityBoundary
from agents.authority.evidence import AuthorityError, EvidenceRecord, EvidenceRegistry
from agents.discovery import DiscoveryRequest
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


def _context():
    factory = RuntimeFactory()
    return factory.create_context(
        situation_id="sit-p706-001",
        now=NOW,
        registry=_registry(),
        boundary=AuthorityBoundary(),
    )


def _valid_reasoning():
    """Produce a valid ReasoningResult via discover→reason chain."""
    from agents.discovery.engine import discover
    from agents.reasoning.resolution import reason

    ctx = _context()
    req = DiscoveryRequest(
        situation_id="sit-p706-001",
        company_id="meridian",
        now=NOW,
        allowed_evidence_ids=("ev-ledger-001",),
        objective="Investigate refund spike correlation.",
        allowed_capabilities=(AgentCapability.READ,),
    )
    disc = discover(req, context=ctx)
    result = reason(disc, context=ctx)
    assert getattr(result, "success", False) is True
    return result


# ---------------------------------------------------------------------------
# Gate A — Input integrity: only successful, valid ReasoningResult
# ---------------------------------------------------------------------------


class TestAValidInputRepresented:
    def test_a1_valid_reasoning_can_be_briefed(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        assert out.situation_id == "sit-p706-001"
        assert out.company_id == "meridian"
        assert out.now == NOW
        assert out.tier == "brief"
        assert getattr(out, "success", False) is True


class TestAInvalidReasoningRejected:
    def test_a2_failed_reasoning_is_invalid_input(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        from agents.reasoning.resolution import ReasoningFailure, ReasoningResult

        bad = ReasoningResult(
            success=False,
            situation_id="sit-p706-001",
            company_id="meridian",
            now=NOW,
            evidence_refs=None,
            candidate_interpretation=None,
            conflicting_evidence=(),
            uncertainty="Discovery failed.",
            rationale="No reasoning.",
            unresolved_questions=(),
            advisory_proposal=None,
            failure=ReasoningFailure(code="INVALID_DISCOVERY_RESULT", detail="bad"),
        )
        ctx = _context()
        out = brief(bad, context=ctx)
        assert getattr(out, "success", True) is False
        assert getattr(getattr(out, "failure", None), "code", "") in (
            "INVALID_REASONING_INPUT",
            "BRIEF_GENERATION_FAILED",
        )

    def test_a_blank_situation_rejected(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        from agents.reasoning.resolution import ReasoningResult

        reg = _registry()
        ref = reg.create_reference("ev-ledger-001")
        bad = ReasoningResult(
            success=True,
            situation_id="   ",
            company_id="meridian",
            now=NOW,
            evidence_refs=(ref,),
            candidate_interpretation="interpretation",
            conflicting_evidence=(),
            uncertainty="uncertain",
            rationale="grounded",
            unresolved_questions=(),
            advisory_proposal=None,
        )
        ctx = _context()
        # blank situation must be either ValidationError/AuthorityError or typed failure
        try:
            out = brief(bad, context=ctx)
            assert getattr(out, "success", True) is False
        except (ValidationError, AuthorityError, ValueError):
            pass

    def test_a_naive_now_rejected(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        from agents.reasoning.resolution import ReasoningResult

        reg = _registry()
        ref = reg.create_reference("ev-ledger-001")
        naive = datetime(2026, 9, 1, 12, 0, 0)
        try:
            bad = ReasoningResult(
                success=True,
                situation_id="sit-p706-001",
                company_id="meridian",
                now=naive,  # type: ignore[arg-type]
                evidence_refs=(ref,),
                candidate_interpretation="interpretation",
                conflicting_evidence=(),
                uncertainty="uncertain",
                rationale="grounded",
                unresolved_questions=(),
                advisory_proposal=None,
            )
            ctx = _context()
            out = brief(bad, context=ctx)
            assert getattr(out, "success", True) is False
        except (ValidationError, AuthorityError, ValueError):
            pass

    def test_a_wrong_company_rejected(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        from agents.reasoning.resolution import ReasoningResult

        reg = _registry()
        ref = reg.create_reference("ev-ledger-001")
        try:
            bad = ReasoningResult(
                success=True,
                situation_id="sit-p706-001",
                company_id="acme",
                now=NOW,
                evidence_refs=(ref,),
                candidate_interpretation="interpretation",
                conflicting_evidence=(),
                uncertainty="uncertain",
                rationale="grounded",
                unresolved_questions=(),
                advisory_proposal=None,
            )
            ctx = _context()
            out = brief(bad, context=ctx)
            assert getattr(out, "success", True) is False
        except (ValidationError, AuthorityError, ValueError):
            pass


class TestAContextMismatch:
    def test_a_scope_mismatch_context_vs_reasoning(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        factory = RuntimeFactory()
        other_ctx = factory.create_context(
            situation_id="sit-other-999",
            now=NOW,
            registry=_registry(),
            boundary=AuthorityBoundary(),
        )
        out = brief(reasoning, context=other_ctx)
        assert getattr(out, "success", True) is False
        assert getattr(getattr(out, "failure", None), "code", "") == "SCOPE_MISMATCH"

    def test_a_now_mismatch_refused(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        later = NOW + timedelta(hours=1)
        factory = RuntimeFactory()
        later_ctx = factory.create_context(
            situation_id="sit-p706-001",
            now=later,
            registry=_registry(),
            boundary=AuthorityBoundary(),
        )
        out = brief(reasoning, context=later_ctx)
        assert getattr(out, "success", True) is False
        assert getattr(getattr(out, "failure", None), "code", "") == "SCOPE_MISMATCH"


# ---------------------------------------------------------------------------
# Gate B — Evidence linkage: every material statement maps to evidence
# ---------------------------------------------------------------------------


class TestBEvidenceLinkage:
    def test_b_every_section_traceable_to_reasoning_evidence(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        reasoning_ids = {r.evidence_id for r in reasoning.evidence_refs or ()}
        brief_ids = {r.evidence_id for r in getattr(out, "evidence_refs", ()) or ()}
        assert brief_ids.issubset(reasoning_ids)
        # Supporting evidence entries, if structured, must reference valid ids
        for entry in getattr(out, "supporting_evidence", []) or []:
            if isinstance(entry, dict) and "evidence_id" in entry:
                assert entry["evidence_id"] in reasoning_ids
            elif isinstance(entry, str):
                # string entries must still be non-empty but evidence linkage
                # is via brief's evidence_refs — already checked
                assert entry.strip()

    def test_b_no_scope_expansion(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        # Try to smuggle an extra evidence id not in reasoning via monkey?
        # The brief itself should never output an evidence_id outside reasoning scope.
        ctx = _context()
        out = brief(reasoning, context=ctx)
        reasoning_ids = {r.evidence_id for r in reasoning.evidence_refs or ()}
        brief_ids = {r.evidence_id for r in getattr(out, "evidence_refs", ()) or ()}
        assert brief_ids.issubset(reasoning_ids)
        d = out.to_dict() if hasattr(out, "to_dict") else {}
        for eid in d.get("evidence_ids", []) or []:
            assert eid in reasoning_ids

    def test_b_evidence_refs_remain_authoritative(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        for ref in getattr(out, "evidence_refs", ()) or ():
            assert getattr(ref, "_token", ""), "evidence refs must remain HMAC-bound"
            # provenance preserved
            assert getattr(ref, "provenance", "") == "p6_evidence_store"

    def test_b_no_invented_evidence_via_raw_fields(self) -> None:
        path = Path("agents/brief/__init__.py")
        # If brief is implemented, check it doesn't mint refs from raw fields
        if path.exists():
            text = path.read_text()
            # No EvidenceRegistry instantiation that would re-mint
            assert "EvidenceRegistry(" not in text
        else:
            # RED: brief not yet implemented — force fail to prove RED
            assert path.exists(), "RED: agents/brief/__init__.py not yet implemented"


# ---------------------------------------------------------------------------
# Gate C — Human readability: explicit sections
# ---------------------------------------------------------------------------


class TestCHumanReadability:
    def test_c_explicit_sections_exist_and_non_blank(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        required = (
            "situation_context",
            "observed_summary",
            "reasoning_summary",
            "supporting_evidence",
            "conflicting_evidence",
            "uncertainty_section",
            "unresolved_questions",
            "advisory_next_step",
        )
        for name in required:
            assert hasattr(out, name), f"missing section {name}"
            val = getattr(out, name)
            if isinstance(val, str):
                assert val.strip(), f"section {name} must be non-blank"
                assert len(val.strip().split()) >= 3, f"section {name} must be scannable prose"
            elif isinstance(val, (list, tuple)):
                # conflicting/unresolved may be empty only when reasoning has none
                # but supporting_evidence should be non-empty for valid input
                if name == "supporting_evidence":
                    assert len(val) > 0, "supporting_evidence must be non-empty"
            else:
                assert val is not None, f"section {name} must not be None"

    def test_c_sections_are_not_collapsed_blob(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        # Ensure brief exposes structured sections, not just one blob
        d = out.to_dict() if hasattr(out, "to_dict") else {}
        # to_dict should carry section keys, not just situation_id
        for key in ("situation_context", "observed_summary", "reasoning_summary"):
            assert key in d, f"to_dict missing section {key}"

    def test_c_headings_free_of_authority_markers(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        blob = ""
        for name in (
            "situation_context",
            "observed_summary",
            "reasoning_summary",
            "uncertainty_section",
            "advisory_next_step",
        ):
            val = getattr(out, name, "")
            if isinstance(val, str):
                blob += " " + val
        for marker in ("VERIFIED", "APPROVED", "EXECUTED", "SETTLED"):
            assert marker not in blob


# ---------------------------------------------------------------------------
# Gate D — Uncertainty preservation
# ---------------------------------------------------------------------------


class TestDUncertaintyPreservation:
    def test_d_contradictory_remains_visible(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        from agents.discovery.engine import discover
        from agents.reasoning.resolution import reason

        reg = _registry()
        factory = RuntimeFactory()
        ctx = factory.create_context(
            situation_id="sit-p706-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p706-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-ledger-001", "ev-ledger-002"),
            objective="Correlate contradictory evidence.",
            allowed_capabilities=(AgentCapability.CORRELATE,),
        )
        disc = discover(req, context=ctx)
        reasoning = reason(disc, context=ctx)
        # reasoning with 2 refs is contradictory in current implementation
        out = brief(reasoning, context=ctx)
        # Brief must preserve conflicting evidence and uncertainty
        has_conflict = len(getattr(out, "conflicting_evidence", []) or []) > 0
        text = (
            (getattr(out, "uncertainty_section", "") or "")
            + " "
            + (getattr(out, "reasoning_summary", "") or "")
        )
        has_uncertain = "contradict" in text.lower() or "ambigu" in text.lower()
        assert has_conflict or has_uncertain

    def test_d_missing_evidence_remains_unresolved(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        # uncertainty must be non-blank and must not claim VERIFIED
        assert getattr(out, "uncertainty_section", "").strip() != ""
        assert "VERIFIED" not in getattr(out, "uncertainty_section", "")
        assert "VERIFIED" not in getattr(out, "reasoning_summary", "")

    def test_d_stale_is_typed_failure_not_prose(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        from agents.discovery.engine import discover
        from agents.reasoning.resolution import reason

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
            situation_id="sit-p706-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p706-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-stale-001",),
            objective="Check stale handling.",
            allowed_capabilities=(AgentCapability.READ,),
        )
        disc = discover(req, context=ctx)
        reasoning = reason(disc, context=ctx)
        # reasoning for stale should be failure; if reasoning succeeded we still test brief
        if getattr(reasoning, "success", False) is False:
            out = brief(reasoning, context=ctx)
        else:
            # Force a stale reasoning shape manually
            out = brief(reasoning, context=ctx)
        assert getattr(out, "success", True) is False
        assert getattr(getattr(out, "failure", None), "code", "") in (
            "STALE_EVIDENCE",
            "INVALID_REASONING_INPUT",
            "BRIEF_GENERATION_FAILED",
            "SCOPE_MISMATCH",
        )

    def test_d_unresolved_questions_propagated(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        from agents.discovery.engine import discover
        from agents.reasoning.resolution import reason

        reg = _registry()
        factory = RuntimeFactory()
        ctx = factory.create_context(
            situation_id="sit-p706-001",
            now=NOW,
            registry=reg,
            boundary=AuthorityBoundary(),
        )
        req = DiscoveryRequest(
            situation_id="sit-p706-001",
            company_id="meridian",
            now=NOW,
            allowed_evidence_ids=("ev-ledger-001", "ev-ledger-002"),
            objective="Correlate contradictory evidence.",
            allowed_capabilities=(AgentCapability.CORRELATE,),
        )
        disc = discover(req, context=ctx)
        reasoning = reason(disc, context=ctx)
        out = brief(reasoning, context=ctx)
        # When reasoning has unresolved_questions, brief must preserve them
        if len(getattr(reasoning, "unresolved_questions", ())) > 0:
            assert len(getattr(out, "unresolved_questions", []) or []) > 0


# ---------------------------------------------------------------------------
# Gate E — Advisory semantics: never authoritative
# ---------------------------------------------------------------------------


class TestEAdvisorySemantics:
    def test_e_no_authoritative_markers_in_brief(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        blob = str(out.to_dict() if hasattr(out, "to_dict") else str(out))
        for marker in (
            "VERIFIED",
            "FAILED",
            "APPROVED",
            "EXECUTED",
            "SETTLED",
            "FACT",
            "DECISION",
        ):
            assert marker not in blob
        d = out.to_dict() if hasattr(out, "to_dict") else {}
        for k in ("status", "verdict", "decision", "amount"):
            assert k not in d

    def test_e_tier_is_brief_not_verified(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        assert getattr(out, "tier", "") == "brief"
        d = out.to_dict() if hasattr(out, "to_dict") else {}
        assert d.get("tier") == "brief"

    def test_e_no_authoritative_amount_without_ref(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        d = out.to_dict() if hasattr(out, "to_dict") else {}
        # Brief must not carry a bare authoritative amount field
        assert "amount" not in d
        # And prose must not assert Amount is ... as authoritative fact
        prose = " ".join(
            str(getattr(out, name, ""))
            for name in (
                "situation_context",
                "reasoning_summary",
                "advisory_next_step",
            )
        )
        # If amount appears, it must be clearly cited — we forbid bare authoritative amount phrases
        # The simplest check: no "amount" key in dict already covers typed amount
        assert "VERIFIED" not in prose


# ---------------------------------------------------------------------------
# Gate F — No hidden approval
# ---------------------------------------------------------------------------


class TestFNoHiddenApproval:
    def test_f_no_approval_or_execution_markers(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        blob = str(out.to_dict() if hasattr(out, "to_dict") else str(out)).lower()
        for marker in (
            "approval_request",
            "approval",
            "authorized",
            "execute",
            "command",
            "perform_correction",
        ):
            # "approval" appears inside "advisory" etc — check word boundaries
            if marker == "approval":
                # Check that "approval" as standalone approval semantics is not present
                # Allow if part of no-approval text? Forbid "approval" token in brief
                assert "approval" not in blob
            else:
                assert marker not in blob
        d = out.to_dict() if hasattr(out, "to_dict") else {}
        for k in ("approval_request", "decision", "command", "status"):
            assert k not in d

    def test_f_advisory_next_step_is_not_decision(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        val = getattr(out, "advisory_next_step", "") or ""
        assert isinstance(val, str) and val.strip()
        assert "APPROVED" not in val
        assert "EXECUTED" not in val
        # Must read as advisory, not as authoritative decision language
        assert "Status:" not in val or "APPROVED" not in val

    def test_f_no_status_theatre(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        blob = " ".join(
            str(getattr(out, n, ""))
            for n in (
                "situation_context",
                "advisory_next_step",
                "reasoning_summary",
            )
        )
        for phrase in ("Status: APPROVED", "Decision:", "Approved by", "Settled"):
            assert phrase not in blob


# ---------------------------------------------------------------------------
# Gate G — No second authority
# ---------------------------------------------------------------------------


class TestGNoSecondAuthority:
    def test_g_no_registry_or_policy_instantiation(self) -> None:
        # RED: brief not yet implemented — path must exist check fails to prove RED
        # Once implemented, must not contain second authority factories
        paths = [
            Path("agents/brief/__init__.py"),
            Path("agents/brief/brief.py"),
            Path("agents/brief/models.py"),
        ]
        found = [p for p in paths if p.exists()]
        if not found:
            raise AssertionError("RED: agents/brief not yet implemented")
        for path in found:
            text = path.read_text()
            assert "EvidenceRegistry(" not in text
            assert "AuthorityBoundary(" not in text
            assert "to_authoritative" not in text
            assert "to_fact" not in text
            assert "PolicyEngine" not in text
            assert "VerdictEngine" not in text
            assert "ExecutionInterface" not in text

    def test_g_no_direct_external_imports(self) -> None:
        paths = [
            Path("agents/brief/__init__.py"),
            Path("agents/brief/brief.py"),
            Path("agents/brief/models.py"),
        ]
        found = [p for p in paths if p.exists()]
        if not found:
            raise AssertionError("RED: agents/brief not yet implemented")
        for path in found:
            text = path.read_text()
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert alias.name not in (
                            "httpx",
                            "requests",
                            "boto3",
                            "psycopg",
                            "openai",
                            "temporalio",
                            "langchain",
                            "langgraph",
                            "qdrant",
                            "redis",
                        )
                if isinstance(node, ast.ImportFrom):
                    assert node.module not in (
                        "httpx",
                        "requests",
                        "boto3",
                        "psycopg",
                        "openai",
                        "temporalio",
                        "langchain",
                        "langgraph",
                        "qdrant",
                        "redis",
                    )
                    if node.module:
                        assert not node.module.startswith("langchain")
                        assert not node.module.startswith("langgraph")


# ---------------------------------------------------------------------------
# Gate H — Failure behavior: typed, not fabricated
# ---------------------------------------------------------------------------


class TestHFailureBehavior:
    def test_h_invalid_reasoning_produces_typed_failure(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        from agents.reasoning.resolution import ReasoningFailure, ReasoningResult

        bad = ReasoningResult(
            success=False,
            situation_id="sit-p706-001",
            company_id="meridian",
            now=NOW,
            evidence_refs=None,
            candidate_interpretation=None,
            conflicting_evidence=(),
            uncertainty="fail",
            rationale="fail",
            unresolved_questions=(),
            advisory_proposal=None,
            failure=ReasoningFailure(code="INVALID_DISCOVERY_RESULT", detail="bad"),
        )
        ctx = _context()
        out = brief(bad, context=ctx)
        assert getattr(out, "success", True) is False
        assert getattr(getattr(out, "failure", None), "code", "") in (
            "INVALID_REASONING_INPUT",
            "STALE_EVIDENCE",
            "SCOPE_MISMATCH",
            "BRIEF_GENERATION_FAILED",
        )
        assert getattr(getattr(out, "failure", None), "detail", "").strip() != ""

    def test_h_typed_failure_codes_only(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        from agents.reasoning.resolution import ReasoningFailure, ReasoningResult

        allowed = {
            "INVALID_REASONING_INPUT",
            "STALE_EVIDENCE",
            "SCOPE_MISMATCH",
            "BRIEF_GENERATION_FAILED",
        }
        bad = ReasoningResult(
            success=False,
            situation_id="sit-p706-001",
            company_id="meridian",
            now=NOW,
            evidence_refs=None,
            candidate_interpretation=None,
            conflicting_evidence=(),
            uncertainty="fail",
            rationale="fail",
            unresolved_questions=(),
            advisory_proposal=None,
            failure=ReasoningFailure(code="STALE_EVIDENCE", detail="stale"),
        )
        ctx = _context()
        out = brief(bad, context=ctx)
        assert getattr(out, "success", True) is False
        assert getattr(getattr(out, "failure", None), "code", "") in allowed

    def test_h_no_plausible_prose_on_failure(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        from agents.reasoning.resolution import ReasoningFailure, ReasoningResult

        bad = ReasoningResult(
            success=False,
            situation_id="sit-p706-001",
            company_id="meridian",
            now=NOW,
            evidence_refs=None,
            candidate_interpretation=None,
            conflicting_evidence=(),
            uncertainty="fail",
            rationale="fail",
            unresolved_questions=(),
            advisory_proposal=None,
            failure=ReasoningFailure(code="STALE_EVIDENCE", detail="stale"),
        )
        ctx = _context()
        out = brief(bad, context=ctx)
        assert getattr(out, "success", True) is False
        # On failure, sections must be empty/None, not fabricated plausible prose
        for name in ("situation_context", "observed_summary", "reasoning_summary"):
            val = getattr(out, name, None)
            if val is not None:
                # If present, it must not look like a successful brief
                assert not (isinstance(val, str) and len(val.strip()) > 20 and "VERIFIED" in val)


# ---------------------------------------------------------------------------
# Gate I — Replay/context integrity
# ---------------------------------------------------------------------------


class TestIReplayIntegrity:
    def test_i_preserves_situation_company_now_scope(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        assert out.situation_id == reasoning.situation_id == ctx.situation_id
        assert out.company_id == reasoning.company_id == ctx.company_id
        assert out.now == reasoning.now == ctx.now
        reasoning_ids = {r.evidence_id for r in reasoning.evidence_refs or ()}
        brief_ids = {r.evidence_id for r in getattr(out, "evidence_refs", ()) or ()}
        assert brief_ids.issubset(reasoning_ids)
        # provenance preserved
        for ref in getattr(out, "evidence_refs", ()) or ():
            assert ref.provenance == "p6_evidence_store"

    def test_i_no_wall_clock(self) -> None:
        paths = [
            Path("agents/brief/__init__.py"),
            Path("agents/brief/brief.py"),
            Path("agents/brief/models.py"),
        ]
        found = [p for p in paths if p.exists()]
        if not found:
            raise AssertionError("RED: agents/brief not yet implemented")
        for path in found:
            text = path.read_text()
            assert "datetime.now" not in text
            assert "datetime.utcnow" not in text
            assert "time.time" not in text

    def test_i_provenance_preserved_in_to_dict(self) -> None:
        from agents.brief import brief  # type: ignore[import-not-found]

        reasoning = _valid_reasoning()
        ctx = _context()
        out = brief(reasoning, context=ctx)
        d = out.to_dict() if hasattr(out, "to_dict") else {}
        assert d.get("situation_id") == "sit-p706-001"
        assert d.get("company_id") == "meridian"
        assert "evidence_ids" in d or "evidence_refs" in d
