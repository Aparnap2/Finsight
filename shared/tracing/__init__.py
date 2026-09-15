"""Agent observability seam — Langfuse traces behind TracerProtocol.

Usage::

    from shared.tracing import create_tracer

    tracer = create_tracer()
    ctx = tracer.trace("exc-123", "tenant-456", "RevenueDecline")
    tracer.generation(ctx, "plan", "gpt-4", {...}, {...}, {...}, {})
    tracer.tool(ctx, "sql_query", {...}, {...}, {})
    tracer.flush()
"""

from shared.tracing.factory import create_tracer as create_tracer
from shared.tracing.noop import NoOpTracer as NoOpTracer
from shared.tracing.protocol import TraceContext as TraceContext
from shared.tracing.protocol import TracerProtocol as TracerProtocol

__all__ = ["TraceContext", "TracerProtocol", "NoOpTracer", "create_tracer"]
