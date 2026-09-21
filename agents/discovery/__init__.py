"""P7-04 evidence discovery boundary — advisory, registry-bound, scope-locked."""

from __future__ import annotations

from agents.discovery.engine import discover
from agents.discovery.request import ALLOWED_DISCOVERY_CAPABILITIES, DiscoveryRequest
from agents.discovery.result import DiscoveryFailure, DiscoveryResult

__all__ = [
    "ALLOWED_DISCOVERY_CAPABILITIES",
    "DiscoveryFailure",
    "DiscoveryRequest",
    "DiscoveryResult",
    "discover",
]
