"""P5-05 prompt-injection corpus: untrusted content stays DATA, never instruction.

Parametrized over 8 adversarial payloads x 7 ingress vectors (56 combos):
every payload is preserved verbatim as evidence DATA with a content hash,
fenced TRUST: UNTRUSTED_CONTENT, and never alters tenant/actor/capabilities/
authorization/policy/state. Tool results carrying injections are preserved
as ToolResult evidence with hash; no new capability is auto-invoked; the
verifier never treats injected text as a planning directive.

Style: Arrange-Act-Assert, typed, deterministic, no network or LLM.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from agents.investigation.context import build_context
from agents.investigation.request import InvestigationRequest
from agents.verification.verifier import Verifier
from finance.evidence.grounding import compute_content_hash

_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2] / "fixtures" / "security" / "prompt_injection"
)
_SOURCES = (
    "gmail",
    "sheets",
    "legacy",
    "provider_metadata",
    "tool_result",
    "s3_object",
    "case_notes",
)
_TENANT = "meridian"
_ACTOR = "analyst-001"
_EXCEPTION_ID = "FS-2026-0916-00231"
_EXCEPTION_TYPE = "I-REFUND-LAG"


def _load_payloads() -> list[dict[str, Any]]:
    """Load all 8 prompt-injection fixtures sorted by attack id."""
    payloads: list[dict[str, Any]] = []
    for path in sorted(_FIXTURE_DIR.glob("payload_*.json")):
        payloads.append(json.loads(path.read_text(encoding="utf-8")))
    return payloads


_PAYLOADS = _load_payloads()
_PAYLOAD_IDS = [p["attack_id"] for p in _PAYLOADS]


def _request(evidence_id: str = "ev-injected-001") -> InvestigationRequest:
    """Build a trusted request for the meridian tenant."""
    return InvestigationRequest.model_validate(
        {
            "exception_id": _EXCEPTION_ID,
            "exception_type": _EXCEPTION_TYPE,
            "tenant_id": _TENANT,
            "actor": _ACTOR,
            "evidence_ids": [evidence_id],
        }
    )


def _store(evidence_id: str, content: str) -> dict[str, dict[str, Any]]:
    """Build a server-side evidence store holding injected content as DATA."""
    return {
        evidence_id: {
            "tenant_id": _TENANT,
            "case_id": _EXCEPTION_ID,
            "source_type": "gmail",
            "source_id": "msg-injected",
            "content": content,
            "provenance": "gmail:msg-injected",
        }
    }


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block real sockets so every test stays deterministic and offline."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network is forbidden in injection tests")

    monkeypatch.setattr("socket.socket", _explode)


# ===========================================================================
# Corpus completeness
# ===========================================================================


class TestCorpusCompleteness:
    """The adversarial corpus covers 8 attacks x 7 ingress vectors."""

    def test_eight_payloads_present(self) -> None:
        """All 8 payload fixtures exist."""
        assert len(_PAYLOADS) == 8
        assert [f"P5-05-{i:02d}" for i in range(1, 9)] == _PAYLOAD_IDS

    def test_every_payload_covers_all_sources(self) -> None:
        """Every payload defines text for all 7 ingress vectors."""
        for payload in _PAYLOADS:
            for source in _SOURCES:
                text = payload["sources"][source]
                assert isinstance(text, str) and text.strip(), (
                    f"{payload['attack_id']} missing source {source}"
                )

    def test_expected_attack_categories(self) -> None:
        """Corpus covers the 8 required attack categories."""
        categories = {p["category"] for p in _PAYLOADS}
        assert categories == {
            "ignore_previous_instructions",
            "execute_refund",
            "approve_proposal",
            "send_credentials",
            "change_tenant",
            "read_another_case",
            "call_unapproved_tool",
            "override_policy",
        }


# ===========================================================================
# DATA-only fence: 8 payloads x 7 sources
# ===========================================================================


class TestInjectionStaysData:
    """Injected text is preserved as DATA, never executed or authorized."""

    @pytest.mark.parametrize("payload", _PAYLOADS, ids=_PAYLOAD_IDS)
    @pytest.mark.parametrize("source", _SOURCES)
    def test_payload_preserved_verbatim_with_hash(
        self, payload: dict[str, Any], source: str
    ) -> None:
        """Arrange injected source text; Act build_context; Assert DATA fenced."""
        # Arrange.
        injected: str = payload["sources"][source]
        request = _request()
        # Act.
        ctx = build_context(request, _store("ev-injected-001", injected))
        # Assert: raw payload preserved verbatim as evidence DATA.
        assert ctx.evidence[0].content == injected
        # Assert: content hash equals sha256 of the preserved bytes.
        assert ctx.evidence[0].content_hash == hashlib.sha256(
            injected.encode()
        ).hexdigest()
        assert ctx.evidence[0].content_hash == compute_content_hash(
            injected.encode()
        )
        # Assert: untrusted-content fence present in rendered output.
        rendered = ctx.evidence[0].rendered()
        assert "TRUST: UNTRUSTED_CONTENT" in rendered
        assert injected in rendered

    @pytest.mark.parametrize("payload", _PAYLOADS, ids=_PAYLOAD_IDS)
    def test_payload_never_alters_authorization(
        self, payload: dict[str, Any]
    ) -> None:
        """Injection across every source leaves tenant/actor/scope untouched."""
        # Arrange: concatenate all 7 source texts into one evidence item.
        combined = "\n".join(payload["sources"][s] for s in _SOURCES)
        request = _request()
        # Act.
        ctx = build_context(request, _store("ev-injected-001", combined))
        # Assert: trusted request fields unchanged (injection is DATA only).
        assert ctx.tenant_id == _TENANT
        assert request.tenant_id == _TENANT
        assert request.actor == _ACTOR
        assert request.exception_id == _EXCEPTION_ID
        # Assert: capability allowlist unchanged — no new tool smuggled in.
        assert "execute_sql" not in request.capability_allowlist
        assert "call_api" not in request.capability_allowlist
        # Assert: context still bound to the original tenant/case.
        assert ctx.evidence[0].tenant_id == _TENANT

    def test_change_tenant_payload_does_not_switch_tenant(self) -> None:
        """The change-tenant payload (P5-05-05) cannot move the case."""
        payload = next(p for p in _PAYLOADS if p["attack_id"] == "P5-05-05")
        combined = "\n".join(payload["sources"][s] for s in _SOURCES)
        ctx = build_context(_request(), _store("ev-injected-001", combined))
        assert ctx.tenant_id == _TENANT
        assert "tenant-b" in combined  # premise: payload really says tenant-b
        assert ctx.evidence[0].tenant_id == _TENANT

    def test_override_policy_payload_does_not_change_policy(self) -> None:
        """The override-policy payload (P5-05-08) is fenced DATA only."""
        payload = next(p for p in _PAYLOADS if p["attack_id"] == "P5-05-08")
        combined = "\n".join(payload["sources"][s] for s in _SOURCES)
        ctx = build_context(_request(), _store("ev-injected-001", combined))
        rendered = ctx.evidence[0].rendered()
        assert "TRUST: UNTRUSTED_CONTENT" in rendered
        assert "Override policy" in rendered  # preserved as text, not applied


# ===========================================================================
# ToolResult injection: preserved with hash, no capability auto-invoked
# ===========================================================================


class TestToolResultInjection:
    """Tool outputs carrying injections stay evidence; nothing auto-executes."""

    def test_tool_result_preserved_with_hash(self) -> None:
        """ToolResult data holding an injection keeps hash + fence."""
        from shared.utils.tools.tool_result import ToolResult

        payload = next(p for p in _PAYLOADS if p["attack_id"] == "P5-05-07")
        injected: str = payload["sources"]["tool_result"]
        # Arrange: tool result whose memo carries the injection.
        result = ToolResult.model_validate(
            {
                "data": {"memo": injected},
                "row_count": 1,
                "coverage_pct": 1.0,
                "quality_score": 0.9,
                "freshness_seconds": 60,
                "schema_version": "1.0",
                "source_diversity": 1,
                "source_type": "financial_fact",
                "retrieval_scope": "factual",
                "tenant_id": _TENANT,
                "required_filters_present": True,
                "insufficient_data": False,
                "degraded_mode": None,
                "query_fingerprint": "fp-injection-test",
            }
        )
        # Act: the memo text flows into evidence content as DATA.
        memo = result.data["memo"] if isinstance(result.data, dict) else ""
        assert isinstance(memo, str)
        ctx = build_context(_request(), _store("ev-injected-001", memo))
        # Assert: preserved verbatim with hash, fenced, tenant-bound.
        assert ctx.evidence[0].content == injected
        assert ctx.evidence[0].content_hash == hashlib.sha256(
            injected.encode()
        ).hexdigest()
        assert "TRUST: UNTRUSTED_CONTENT" in ctx.evidence[0].rendered()
        assert ctx.evidence[0].tenant_id == _TENANT

    def test_no_new_capability_from_tool_injection(self) -> None:
        """Injection naming execute_sql/call_api adds no capability."""
        payload = next(p for p in _PAYLOADS if p["attack_id"] == "P5-05-07")
        request = _request()
        build_context(
            request, _store("ev-injected-001", payload["sources"]["tool_result"])
        )
        assert "execute_sql" not in request.capability_allowlist
        assert "call_api" not in request.capability_allowlist


# ===========================================================================
# Verifier: injected text is never a planning directive
# ===========================================================================


class TestVerifierIgnoresInjection:
    """Verifier treats injected text as ungrounded content, never orders."""

    def test_injection_without_citation_rejected(self) -> None:
        """A plan citing an unknown id (injection target) is rejected."""
        from agents.investigation.plan import InvestigationPlan

        plan = InvestigationPlan.model_validate(
            {
                "hypothesis_text": (
                    "Possible refund posting lag between processor and ledger."
                ),
                "capability_calls": [
                    {
                        "capability": "get_stripe_payment",
                        "args": {"payment_id": "pay_123"},
                        "order_index": 0,
                    }
                ],
                "evidence_required": ["ev-injected-ghost"],
                "escalation": False,
            }
        )
        verdict = Verifier().verify(plan, {"ev-injected-001"})
        assert verdict.status == "REJECTED_REPLAN"
        assert any("unknown_evidence_id" in r for r in verdict.reasons)

    def test_injection_execute_wording_not_executed(self) -> None:
        """'Execute refund' wording in evidence never becomes a verdict."""
        payload = next(p for p in _PAYLOADS if p["attack_id"] == "P5-05-02")
        ctx = build_context(
            _request(), _store("ev-injected-001", payload["sources"]["gmail"])
        )
        # The evidence content holds the attack text as DATA ...
        assert "execute a refund" in ctx.evidence[0].content.lower()
        # ... but no verdict/status/authorization object was produced.
        assert ctx.evidence[0].trust_classification == "UNTRUSTED_CONTENT"
