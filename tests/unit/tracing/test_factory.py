"""Unit tests for shared.tracing.factory.

Verifies that create_tracer returns the correct backend based on
environment configuration.  All Langfuse SDK interactions are mocked;
zero network, zero real SDK calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from shared.tracing.factory import create_tracer
from shared.tracing.noop import NoOpTracer

# ---------------------------------------------------------------------------
# No env → NoOpTracer
# ---------------------------------------------------------------------------


class TestNoEnvReturnsNoOp:
    """When LANGFUSE_PUBLIC_KEY is absent, factory returns NoOpTracer."""

    def test_empty_env_dict(self) -> None:
        tracer = create_tracer(_env={})
        assert isinstance(tracer, NoOpTracer)

    def test_none_env_returns_noop(self) -> None:
        """_env=None means 'use os.environ' — in CI there's no key."""
        tracer = create_tracer(_env=None)
        # In CI/local dev without LANGFUSE_PUBLIC_KEY set, should be NoOp.
        assert isinstance(tracer, NoOpTracer)

    def test_empty_string_key(self) -> None:
        tracer = create_tracer(_env={"LANGFUSE_PUBLIC_KEY": ""})
        assert isinstance(tracer, NoOpTracer)

    def test_whitespace_only_key(self) -> None:
        tracer = create_tracer(_env={"LANGFUSE_PUBLIC_KEY": "   "})
        assert isinstance(tracer, NoOpTracer)

    def test_only_secret_key_set(self) -> None:
        """Secret alone is insufficient — public key is the gate."""
        tracer = create_tracer(
            _env={"LANGFUSE_SECRET_KEY": "sk-lf-abc", "LANGFUSE_HOST": "http://x"}
        )
        assert isinstance(tracer, NoOpTracer)


# ---------------------------------------------------------------------------
# Key present → LangfuseTracer (mocked)
# ---------------------------------------------------------------------------


class TestKeyPresentReturnsLangfuseTracer:
    """When LANGFUSE_PUBLIC_KEY is set, factory returns LangfuseTracer."""

    def test_returns_langfuse_tracer_when_key_set(self) -> None:
        mock_tracer_cls = MagicMock()
        mock_tracer_cls.return_value = MagicMock()

        with patch(
            "shared.tracing.langfuse_tracer.LangfuseTracer",
            mock_tracer_cls,
        ):
            create_tracer(
                _env={
                    "LANGFUSE_PUBLIC_KEY": "pk-lf-test-key",
                    "LANGFUSE_SECRET_KEY": "sk-lf-test-secret",
                    "LANGFUSE_HOST": "http://localhost:3000",
                }
            )
            # The factory imports LangfuseTracer lazily, so we patch it
            # and verify it was called with the right args.
            mock_tracer_cls.assert_called_once_with(
                public_key="pk-lf-test-key",
                secret_key="sk-lf-test-secret",
                host="http://localhost:3000",
            )

    def test_host_defaults_to_cloud(self) -> None:
        mock_tracer_cls = MagicMock()

        with patch(
            "shared.tracing.langfuse_tracer.LangfuseTracer",
            mock_tracer_cls,
        ):
            create_tracer(_env={"LANGFUSE_PUBLIC_KEY": "pk-lf-x"})
            _, kwargs = mock_tracer_cls.call_args
            assert kwargs["host"] == "https://cloud.langfuse.com"

    def test_host_override(self) -> None:
        mock_tracer_cls = MagicMock()

        with patch(
            "shared.tracing.langfuse_tracer.LangfuseTracer",
            mock_tracer_cls,
        ):
            create_tracer(
                _env={
                    "LANGFUSE_PUBLIC_KEY": "pk-lf-x",
                    "LANGFUSE_HOST": "http://custom:3000",
                }
            )
            _, kwargs = mock_tracer_cls.call_args
            assert kwargs["host"] == "http://custom:3000"

    def test_secret_key_defaults_to_empty(self) -> None:
        mock_tracer_cls = MagicMock()

        with patch(
            "shared.tracing.langfuse_tracer.LangfuseTracer",
            mock_tracer_cls,
        ):
            create_tracer(_env={"LANGFUSE_PUBLIC_KEY": "pk-lf-x"})
            _, kwargs = mock_tracer_cls.call_args
            assert kwargs["secret_key"] == ""


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """NoOpTracer satisfies TracerProtocol at runtime."""

    def test_noop_is_tracer_protocol(self) -> None:
        from shared.tracing.protocol import TracerProtocol

        assert isinstance(NoOpTracer(), TracerProtocol)
