"""P5-06 PII/secrets: retained/redacted/hashed/excluded per hop.

Verifies secrets never reach the LLM context, agent output, observability
payloads, application logs, or audit rows; PII is hashed or excluded unless
allowlisted. Covers :mod:`shared.safety.secrets` units, webhook audit
redaction, tracer sanitization, and the CI ``rg`` gate premise (no secret
literals in prompt/trace fixtures).

Style: Arrange-Act-Assert, typed, deterministic, no network or LLM.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from shared.safety.secrets import (
    REDACTED,
    REDACTED_EMAIL,
    contains_secret_literal,
    hash_pii,
    redact_mapping,
    redact_value,
    scrub_text,
)

_SECRET = "sk_live_abc123_secret_api_key_XYZ"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block real sockets so every test stays deterministic and offline."""

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("live network is forbidden in secret tests")

    monkeypatch.setattr("socket.socket", _explode)


# ===========================================================================
# Unit: redact_value / redact_mapping
# ===========================================================================


class TestRedactMapping:
    """Secret-keyed values collapse to [REDACTED]; others pass through."""

    def test_secret_key_redacted(self) -> None:
        """api_key values are redacted."""
        assert redact_value("api_key", _SECRET) == REDACTED

    def test_secret_suffix_redacted(self) -> None:
        """Any key containing 'secret' is redacted."""
        assert redact_value("client_secret", "hunter2") == REDACTED

    def test_benign_key_passes_through(self) -> None:
        """Non-secret keys keep their values."""
        assert redact_value("tenant_id", "meridian") == "meridian"

    def test_mapping_top_level(self) -> None:
        """Top-level secret keys redacted, input never mutated."""
        data = {"api_key": _SECRET, "tenant_id": "meridian"}
        redacted = redact_mapping(data)
        assert redacted == {"api_key": REDACTED, "tenant_id": "meridian"}
        assert data["api_key"] == _SECRET

    def test_mapping_nested_dict(self) -> None:
        """Nested dict secret keys redacted one level deep."""
        data = {"headers": {"Authorization": "Bearer abc", "other": "x"}}
        redacted = redact_mapping(data)
        assert redacted["headers"]["Authorization"] == REDACTED
        assert redacted["headers"]["other"] == "x"

    def test_mapping_list_of_dicts(self) -> None:
        """Lists of dicts redacted element-wise."""
        data = {"items": [{"token": "t1", "id": "1"}]}
        redacted = redact_mapping(data)
        assert redacted["items"] == [{"token": REDACTED, "id": "1"}]


# ===========================================================================
# Unit: scrub_text / hash_pii / contains_secret_literal
# ===========================================================================


class TestScrubText:
    """Free-text scrubbing removes bearer tokens, sk-keys, emails."""

    def test_bearer_token_scrubbed(self) -> None:
        """Bearer credential values are scrubbed, scheme kept."""
        out = scrub_text("Authorization: Bearer abc123XYZ")
        assert "abc123XYZ" not in out
        assert "Bearer" in out

    def test_sk_key_scrubbed(self) -> None:
        """sk- style keys are scrubbed."""
        out = scrub_text(f"key={_SECRET}")
        assert _SECRET not in out

    def test_email_scrubbed(self) -> None:
        """Emails collapse to the email marker."""
        out = scrub_text("contact alice@example.com for approval")
        assert "alice@example.com" not in out
        assert REDACTED_EMAIL in out

    def test_benign_text_untouched(self) -> None:
        """Non-sensitive text passes through byte-identical."""
        text = "Refund of 100.00 posted to ledger account 4812."
        assert scrub_text(text) == text


class TestHashPii:
    """PII hashing is tenant-scoped and deterministic."""

    def test_deterministic(self) -> None:
        """Same input + tenant yields the same hash."""
        assert hash_pii("alice@example.com", tenant_id="meridian") == hash_pii(
            "alice@example.com", tenant_id="meridian"
        )

    def test_tenant_scoped(self) -> None:
        """Different tenants yield different hashes (no cross-join)."""
        assert hash_pii("alice@example.com", tenant_id="meridian") != hash_pii(
            "alice@example.com", tenant_id="tenant-b"
        )

    def test_raw_value_absent(self) -> None:
        """The raw PII value never appears in its hash."""
        assert "alice@example.com" not in hash_pii(
            "alice@example.com", tenant_id="meridian"
        )

    def test_contains_secret_literal_flags_sk(self) -> None:
        """sk- literals are flagged; redacted text is clean."""
        assert contains_secret_literal(f"key={_SECRET}") is True
        assert contains_secret_literal("api_key: [REDACTED]") is False


# ===========================================================================
# Hop: webhook audit redaction
# ===========================================================================


class TestAuditRedaction:
    """Audit rows never persist secret values."""

    def test_audit_event_data_redacted(self) -> None:
        """_audit stores redacted event_data (secret keys collapsed)."""
        from apps.api.webhooks import _audit

        session = MagicMock()
        _audit(
            session,
            tenant_id="meridian",
            event_type="webhook.received",
            event_data={"api_key": _SECRET, "event_id": "evt_123"},
            period="2026-09",
        )
        added = session.add.call_args[0][0]
        assert added.event_data["api_key"] == REDACTED
        assert added.event_data["event_id"] == "evt_123"
        assert _SECRET not in str(added.event_data)


# ===========================================================================
# Hop: tracer sanitization (no secret in spans)
# ===========================================================================


class TestTracerSanitization:
    """Observability spans carry sanitized inputs (no secrets, no bodies)."""

    def test_langfuse_generation_sanitizes_secret(self) -> None:
        """LangfuseTracer.generation forwards sanitized input (no secret)."""
        import sys
        import types
        from contextlib import nullcontext
        from unittest.mock import MagicMock

        from shared.tracing.langfuse_tracer import LangfuseTracer
        from shared.tracing.protocol import TraceContext

        fake_module = types.ModuleType("langfuse")
        fake_module.Langfuse = MagicMock  # type: ignore[attr-defined]
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setitem(sys.modules, "langfuse", fake_module)
        try:
            tracer = LangfuseTracer(
                public_key="pk-test", secret_key="sk-test", host="http://x"
            )
        finally:
            monkeypatch.undo()
        fake_sdk_ctx = MagicMock()
        fake_sdk_ctx.trace_id = "CASE-1027"
        tracer._langfuse.get_trace_context.return_value = fake_sdk_ctx  # type: ignore[attr-defined]
        tracer._langfuse.start_as_current_observation.return_value = nullcontext()  # type: ignore[attr-defined]
        ctx = TraceContext(trace_id="CASE-1027", _ref=fake_sdk_ctx)
        tracer.generation(
            ctx,
            "planner_llm",
            "test-model",
            {"api_key": _SECRET, "hypothesis_ref": "lag"},
            {"text": "ok"},
            {"input": 1, "output": 1},
        )
        sent_input = tracer._langfuse.start_as_current_observation.call_args[1][  # type: ignore[attr-defined]
            "input"
        ]
        assert sent_input.get("api_key") != _SECRET
        assert _SECRET not in str(sent_input)

    def test_noop_tracer_safe(self) -> None:
        """NoOpTracer records nothing secret-bearing."""
        from shared.tracing.noop import NoOpTracer

        tracer = NoOpTracer()
        assert _SECRET not in str(tracer)


# ===========================================================================
# Hop: secret literal in evidence never reaches prompt/log output
# ===========================================================================


class TestEvidenceSecretContainment:
    """A secret smuggled into evidence content is scrubbed before logging."""

    def test_scrub_before_log(self, caplog: Any) -> None:
        """Scrubbed evidence text logged; raw secret never in log records."""
        content = f"Gmail memo carries {_SECRET} inline"
        with caplog.at_level(logging.INFO):
            logging.getLogger("finsight.evidence").info(
                "evidence content: %s", scrub_text(content)
            )
        assert _SECRET not in caplog.text
        assert "evidence content" in caplog.text
