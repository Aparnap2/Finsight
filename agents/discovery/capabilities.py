"""P7-04 discovery capability allowlist — subset of P7-03 tools only."""

from __future__ import annotations

from agents.authority.claims import AgentCapability

DISCOVERY_ALLOWED_CAPABILITIES: frozenset[AgentCapability] = frozenset(
    {
        AgentCapability.READ,
        AgentCapability.CORRELATE,
        AgentCapability.EXPLAIN,
    }
)
"""Capabilities the discovery agent may dispatch — exactly P7-03 tools."""

__all__ = ["DISCOVERY_ALLOWED_CAPABILITIES"]
