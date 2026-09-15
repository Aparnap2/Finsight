"""Tracer factory: create a TracerProtocol from environment variables.

Usage::

    from shared.tracing.factory import create_tracer

    tracer = create_tracer()        # reads LANGFUSE_PUBLIC_KEY from env
    tracer = create_tracer(_env={})  # explicit env dict for testing

Returns ``NoOpTracer`` when ``LANGFUSE_PUBLIC_KEY`` is unset, and
``LangfuseTracer`` when it is.  The langfuse SDK is lazy-imported —
it is only loaded when the factory decides to create a real tracer.
"""

from __future__ import annotations

import os

from shared.tracing.noop import NoOpTracer
from shared.tracing.protocol import TracerProtocol


def create_tracer(
    _env: dict[str, str] | None = None,
) -> TracerProtocol:
    """Create a tracer based on environment configuration.

    Args:
        _env: Optional env dict for testing.  When ``None`` the real
            ``os.environ`` is used.

    Returns:
        ``NoOpTracer`` when ``LANGFUSE_PUBLIC_KEY`` is not set (or empty),
        otherwise a ``LangfuseTracer`` wired to the configured host.
    """
    env: dict[str, str] | None = _env if _env is not None else None

    def _get(key: str) -> str:
        if env is not None:
            return env.get(key, "")
        return os.environ.get(key, "")

    public_key = _get("LANGFUSE_PUBLIC_KEY").strip()
    if not public_key:
        return NoOpTracer()

    secret_key = _get("LANGFUSE_SECRET_KEY").strip()
    host = _get("LANGFUSE_HOST").strip() or "https://cloud.langfuse.com"

    # Lazy import — only when we actually need the real tracer.
    from shared.tracing.langfuse_tracer import LangfuseTracer  # noqa: PLC0415

    return LangfuseTracer(
        public_key=public_key,
        secret_key=secret_key,
        host=host,
    )
