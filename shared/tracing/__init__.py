"""Agent observability seam — Langfuse traces behind TracerProtocol.

Usage::

    from shared.tracing import create_tracer

    tracer = create_tracer()
    ctx = tracer.trace("exc-123", "tenant-456", "RevenueDecline")
    tracer.generation(ctx, "plan", "gpt-4", {...}, {...}, {...}, {})
    tracer.tool(ctx, "sql_query", {...}, {...}, {})
    tracer.flush()
"""

from shared.tracing.correlation import derive_correlation_id as derive_correlation_id
from shared.tracing.correlation import from_fingerprint as from_fingerprint
from shared.tracing.correlation import from_s3_key as from_s3_key
from shared.tracing.correlation import validate_correlation_id as validate_correlation_id
from shared.tracing.factory import create_tracer as create_tracer
from shared.tracing.noop import NoOpTracer as NoOpTracer
from shared.tracing.observability import ObservabilityTrace as ObservabilityTrace
from shared.tracing.protocol import TraceContext as TraceContext
from shared.tracing.protocol import TracerProtocol as TracerProtocol
from shared.tracing.redaction import sanitize_input as sanitize_input

try:
    from shared.tracing.phoenix_tracer import PhoenixTracer as PhoenixTracer  # noqa: F401
except ImportError:
    PhoenixTracer = None  # type: ignore[assignment,misc]

__all__ = [
    "ObservabilityTrace",
    "TraceContext",
    "TracerProtocol",
    "NoOpTracer",
    "PhoenixTracer",
    "create_tracer",
    "derive_correlation_id",
    "from_fingerprint",
    "from_s3_key",
    "validate_correlation_id",
    "sanitize_input",
]
