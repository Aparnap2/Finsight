"""Frozen boundary types for the FinSight LLM provider seam.

All types are frozen dataclasses. None of them holds credentials, API keys,
or secrets — call journals carry model/cost metadata only.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class InvestigationPrompt:
    """Bounded, deterministic LLM input assembled before any provider call.

    Attributes:
        user_prompt: The investigation question or task text.
        system_prompt: Optional system instruction scoping the allowed acts.
        evidence_ids: Verified evidence references only (may be empty).
        allowlist_snapshot: Capability allowlist snapshot for this round.
    """

    user_prompt: str
    system_prompt: str = ""
    evidence_ids: tuple[str, ...] = ()
    allowlist_snapshot: tuple[str, ...] = field(default_factory=tuple)

    def to_messages(self) -> list[dict[str, str]]:
        """Render as OpenAI-compatible chat messages (no secrets included)."""
        messages: list[dict[str, str]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": self.user_prompt})
        return messages


@dataclass(frozen=True)
class ProviderHealth:
    """Liveness signal gating invocation (unhealthy triggers P3 fallback).

    Attributes:
        ok: True when the provider may be invoked.
        latency_ms: Health-probe latency, when measured.
        reason: Short, credential-free reason when unhealthy.
    """

    ok: bool
    latency_ms: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ModelMetadata:
    """Model/cost identity for audit logging (no secrets).

    Attributes:
        provider: Provider name (e.g. "groq", "fake").
        model: Model identifier.
        version: Optional model/pipeline version for cost auditing.
    """

    provider: str
    model: str
    version: str | None = None


@dataclass(frozen=True)
class ProviderCallLog:
    """Per-call audit record: model + cost metadata only, never secrets.

    Attributes:
        provider: Provider name.
        model: Model identifier used for the call.
        success: Whether the call produced schema-valid output.
        latency_ms: Measured call latency, when known.
        input_chars: Rendered prompt length (cost proxy).
        output_chars: Raw output length (cost proxy).
        error_kind: Exception class name on failure, else None.
    """

    provider: str
    model: str
    success: bool
    latency_ms: float | None = None
    input_chars: int | None = None
    output_chars: int | None = None
    error_kind: str | None = None
