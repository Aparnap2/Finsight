"""P7-04 evidence discovery agent — RED stub (not yet implemented).

The only evidence path is:

  agent reasoning
      ↓
  P7-03 typed investigation tools (evidence_lookup / correlate / explain)
      ↓
  frozen EvidenceRegistry authority
      ↓
  typed advisory result

No direct DB/S3/API/ERP, no direct EvidenceRegistry access, no second registry,
no alternate RuntimeContext, no vector DB, no graph memory, no Temporal,
no LangGraph, no real LLM, no financial writes, no verdicts, no hidden side
effects. This stub exists only to define the importable boundary; the real
implementation will be added after RED tests demonstrate the missing behavior.
"""

from __future__ import annotations

from typing import Any

from agents.discovery.request import DiscoveryRequest
from agents.discovery.result import DiscoveryResult
from agents.runtime.context import RuntimeContext


def discover(
    request: DiscoveryRequest,
    *,
    context: RuntimeContext,
    tools: Any | None = None,
) -> DiscoveryResult:
    """Advisory discovery over P7-03 tools, bound to factory-issued context.

    Args:
        request: Validated DiscoveryRequest (situation/company/now/scope/objective).
        context: Factory-issued RuntimeContext (registry/boundary/now bound).
        tools: Optional fake/deterministic tool doubles for testing.

    Returns:
        DiscoveryResult advisory result (success) or typed failure.

    Raises:
        NotImplementedError: Until RED is replaced with GREEN implementation.
    """
    raise NotImplementedError("P7-04 discovery not yet implemented — RED phase.")
