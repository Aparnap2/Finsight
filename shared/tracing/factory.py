"""Tracer factory: create a TracerProtocol from environment variables.

Usage::

    from shared.tracing.factory import create_tracer

    tracer = create_tracer()        # reads LANGFUSE_PUBLIC_KEY from env
    tracer = create_tracer(_env={})  # explicit env dict for testing

Priority:
    1. ``PHOENIX_COLLECTOR_ENDPOINT`` (or ``PHOENIX_ENDPOINT``) → PhoenixTracer
       (local OTel, ``http://localhost:6006/v1/traces``, no SaaS).
    2. ``LANGFUSE_PUBLIC_KEY`` → LangfuseTracer.
    3. Otherwise → NoOpTracer.

All SDKs are lazy-imported — only loaded when the factory decides to
create that tracer. Phoenix wraps ``phoenix.otel.register`` with
``project_name``, ``endpoint``, ``auto_instrument``, and ``batch``.
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
        PhoenixTracer when ``PHOENIX_COLLECTOR_ENDPOINT`` is set,
        LangfuseTracer when ``LANGFUSE_PUBLIC_KEY`` is set, otherwise
        NoOpTracer.
    """
    env: dict[str, str] | None = _env if _env is not None else None

    def _get(key: str) -> str:
        if env is not None:
            return env.get(key, "")
        return os.environ.get(key, "")

    # 1. Phoenix — local OTel collector (no SaaS account, reproducible).
    phoenix_endpoint = (
        _get("PHOENIX_COLLECTOR_ENDPOINT").strip()
        or _get("PHOENIX_ENDPOINT").strip()
        or _get("PHOENIX_HOST").strip()
    )
    if phoenix_endpoint:
        project = _get("PHOENIX_PROJECT_NAME").strip() or "finsight"
        auto_instr_raw = _get("PHOENIX_AUTO_INSTRUMENT").strip().lower()
        auto_instrument = auto_instr_raw not in ("0", "false", "no") if auto_instr_raw else True
        batch_raw = _get("PHOENIX_BATCH").strip().lower()
        batch = batch_raw not in ("0", "false", "no") if batch_raw else True

        from shared.tracing.phoenix_tracer import PhoenixTracer  # noqa: PLC0415

        return PhoenixTracer(
            endpoint=phoenix_endpoint,
            project_name=project,
            auto_instrument=auto_instrument,
            batch=batch,
        )

    # 2. Langfuse — hosted SaaS (optional).
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
