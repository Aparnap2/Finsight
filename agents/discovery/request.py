"""Discovery request — RED permissive stub (no enforcement)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from agents.discovery.capabilities import DISCOVERY_ALLOWED_CAPABILITIES

ALLOWED_DISCOVERY_CAPABILITIES = DISCOVERY_ALLOWED_CAPABILITIES


@dataclass
class DiscoveryRequest:
    """Permissive stub: accepts anything, no validation (RED)."""

    situation_id: str
    company_id: str
    now: datetime
    allowed_evidence_ids: tuple[Any, ...]
    objective: str
    allowed_capabilities: tuple[Any, ...] = ()
    # Permissive injection seams (RED: should be rejected)
    registry: Any | None = None
    boundary: Any | None = None
    evidence_registry: Any | None = None
    authority_boundary: Any | None = None
    context: Any | None = None
    runtime_context: Any | None = None
