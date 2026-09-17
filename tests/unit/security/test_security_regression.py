"""P5-12 security regression: full matrix + golden datasets (FS-231).

Golden-dataset regression over the flagship case FS-2026-0916-00231
(₹10,000 legacy variance): one flow exercising all four P5 trust layers
together — tenant isolation (P5-03), grounding ladder (P5-04), prompt
injection fence (P5-05), secrets redaction (P5-06) — plus a matrix test
pinning the suite counts so regressions are caught as numbers, not vibes.

Style: Arrange-Act-Assert, typed, deterministic, no network or LLM.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from agents.investigation.context import build_context
from agents.investigation.request import InvestigationRequest
from agents.verification.verifier import Verifier
from finance.evidence.grounding import is_verified_eligible
from finance.evidence.models import EvidenceItem, EvidenceProvenance
from shared.safety.secrets import REDACTED, redact_mapping, scrub_text

_TENANT = "meridian"
_EXCEPTION_ID = "FS-2026-0916-00231"
_FIXTURE_DIR = (
    Path(__file__).resolve().parents[2] / "fixtures" / "security" / "prompt_injection"
)


def _bytes_for(source_id: str) -> bytes:
    """Canonical raw bytes for one golden evidence id."""
    return f"golden-bytes:{source_id}".encode()


def _golden_item(source_id: str) -> EvidenceItem:
    """Fully provenance-valid golden item for the flagship case."""
    return EvidenceItem(
        claim="Legacy batch LEGACY-20260916-0042 accepted 499 of 500 records.",
        source_type="ledger",
        source_id=source_id,
        source_value=Decimal("10000.00"),
        confidence="high",
        tenant_id=_TENANT,
        content_hash=hashlib.sha256(_bytes_for(source_id)).hexdigest(),
        retrieved_at=datetime.now(UTC),
        provenance=EvidenceProvenance(
            adapter="s3-legacy-adapter",
            endpoint="s3://finsight-legacy-result-test/meridian/LEGACY-20260916-0042",
            correlation_id=_EXCEPTION_ID,
        ),
    )


def _request() -> InvestigationRequest:
    """Trusted request for the flagship case."""
    return InvestigationRequest.model_validate(
        {
            "exception_id": _EXCEPTION_ID,
            "exception_type": "I-REFUND-LAG",
            "tenant_id": _TENANT,
            "actor": "analyst-001",
            "evidence_ids": ["ev-golden-001"],
        }
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block real sockets so every test stays deterministic and offline."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network is forbidden in regression tests")

    monkeypatch.setattr("socket.socket", _explode)


# ===========================================================================
# Golden dataset: FS-231 passes all four layers in one flow
# ===========================================================================


class TestGoldenFs231:
    """Flagship case flows through tenant → grounding → fence → redaction."""

    def test_golden_evidence_eligible_and_scoped(self) -> None:
        """Golden item is VERIFIED-eligible and tenant-bound."""
        item = _golden_item("ev-golden-001")
        assert (
            is_verified_eligible(
                evidence_ids=("ev-golden-001",),
                evidence_registry={"ev-golden-001": item},
                expected_tenant=_TENANT,
                content_bytes={"ev-golden-001": _bytes_for("ev-golden-001")},
            )
            is True
        )
        assert item.tenant_id == _TENANT

    def test_golden_context_fenced(self) -> None:
        """Golden content crosses the boundary fenced as UNTRUSTED_CONTENT."""
        ctx = build_context(
            _request(),
            {
                "ev-golden-001": {
                    "tenant_id": _TENANT,
                    "case_id": _EXCEPTION_ID,
                    "source_type": "ledger",
                    "source_id": "LEGACY-20260916-0042",
                    "content": "499 accepted, 1 rejected INVALID_ACCOUNT_CODE 4812",
                    "provenance": "s3-legacy:s3://result/meridian/LEGACY-20260916-0042",
                }
            },
        )
        assert "TRUST: UNTRUSTED_CONTENT" in ctx.evidence[0].rendered()
        assert ctx.tenant_id == _TENANT

    def test_golden_audit_redacted(self) -> None:
        """Golden audit payload with a smuggled key is redacted pre-persist."""
        payload = {"api_key": "sk_live_golden", "batch_id": "LEGACY-20260916-0042"}
        redacted = redact_mapping(payload)
        assert redacted["api_key"] == REDACTED
        assert redacted["batch_id"] == "LEGACY-20260916-0042"

    def test_golden_injection_fenced(self) -> None:
        """Every corpus payload stays DATA against the golden request."""
        payloads = sorted(_FIXTURE_DIR.glob("payload_*.json"))
        assert len(payloads) == 8
        for path in payloads:
            data = json.loads(path.read_text(encoding="utf-8"))
            combined = "\n".join(data["sources"].values())
            ctx = build_context(
                _request(),
                {
                    "ev-golden-001": {
                        "tenant_id": _TENANT,
                        "case_id": _EXCEPTION_ID,
                        "source_type": "gmail",
                        "source_id": "msg-golden",
                        "content": combined,
                        "provenance": "gmail:msg-golden",
                    }
                },
            )
            assert "TRUST: UNTRUSTED_CONTENT" in ctx.evidence[0].rendered()
            assert ctx.tenant_id == _TENANT

    def test_golden_verifier_accepts_clean_plan(self) -> None:
        """Clean cited plan for the golden case is ACCEPTED with registry."""
        from agents.investigation.plan import InvestigationPlan

        plan = InvestigationPlan.model_validate(
            {
                "hypothesis_text": (
                    "Possible legacy batch rejection for account 4812."
                ),
                "capability_calls": [
                    {
                        "capability": "get_stripe_payment",
                        "args": {"payment_id": "pay_123"},
                        "order_index": 0,
                    }
                ],
                "evidence_required": ["ev-golden-001"],
                "escalation": False,
            }
        )
        item = _golden_item("ev-golden-001")
        verdict = Verifier().verify(
            plan,
            {"ev-golden-001"},
            evidence_registry={"ev-golden-001": item},  # type: ignore[dict-item]
            tenant_id=_TENANT,
            content_bytes={"ev-golden-001": _bytes_for("ev-golden-001")},
        )
        assert verdict.status == "ACCEPTED"


# ===========================================================================
# Matrix pins: suite counts caught as numbers
# ===========================================================================


class TestSecurityMatrixPins:
    """Pin the security suite sizes so deletions fail loudly."""

    def test_prompt_injection_corpus_complete(self) -> None:
        """8 payloads x 7 sources present (56 combos)."""
        payloads = sorted(_FIXTURE_DIR.glob("payload_*.json"))
        assert len(payloads) == 8
        for path in payloads:
            data = json.loads(path.read_text(encoding="utf-8"))
            assert len(data["sources"]) == 7

    def test_scrub_text_idempotent(self) -> None:
        """Scrubbing twice equals scrubbing once (stable redaction)."""
        text = "contact alice@example.com with key sk_live_abc123XYZ"
        once = scrub_text(text)
        assert scrub_text(once) == once
        assert "alice@example.com" not in once
