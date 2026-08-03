"""LLM boundary for the reasoning pipeline.

The commentary provider is the ONLY place the reasoning pipeline may
touch an LLM. Providers receive validated assertions — never raw data —
and return narrative text.

- :class:`CommentaryProvider` — the protocol every provider implements.
- :class:`StructuredCommentaryProvider` — builds the prompt from the
  prompt registry, enforces structured output via a Pydantic schema, and
  degrades to a deterministic summary when the LLM is unavailable or
  returns malformed output.
- :class:`NullCommentaryProvider` — deterministic template-based summary
  with no LLM (degraded mode).
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel

from finance.prompts.registry import PromptRegistry
from finance.prompts.renderer import PromptRenderer
from finance.prompts.templates import reasoning_commentary
from shared.models.assertions import Assertion, SupportLevel

PROMPT_NAME = reasoning_commentary.NAME


class CommentarySection(BaseModel):
    """A single structured section of rendered commentary."""

    heading: str
    content: str


class CommentaryOutput(BaseModel):
    """Structured output contract enforced on the LLM response."""

    summary: str
    sections: list[CommentarySection]


class CommentaryProvider(Protocol):
    """Generates narrative commentary from validated assertions only."""

    def generate(self, assertions: list[Assertion]) -> str: ...


def _render_assertions(assertions: list[Assertion]) -> str:
    """Render assertions as prompt-safe lines (text + confidence only)."""
    if not assertions:
        return "(no assertions)"
    lines = []
    for assertion in assertions:
        lines.append(
            f"- [{assertion.type.value}] {assertion.text} "
            f"(confidence={assertion.confidence:.2f}, "
            f"support={assertion.support_level.value})"
        )
    return "\n".join(lines)


def _serialize_structured(output: CommentaryOutput) -> str:
    """Deterministically serialize a validated CommentaryOutput to text."""
    parts = [output.summary]
    for section in output.sections:
        parts.append(f"## {section.heading}")
        parts.append(section.content)
    return "\n\n".join(parts)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract a JSON object from an LLM response (fences tolerated)."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        start = 1 if lines[0].startswith("```") else 0
        end = -1 if lines[-1].strip().startswith("```") else len(lines)
        cleaned = "\n".join(lines[start:end]).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class StructuredCommentaryProvider:
    """Commentary provider backed by an injected LLM client.

    The client must expose ``generate(prompt: str) -> str`` (duck-typed —
    nothing from the LLM layer is imported here). The prompt is built
    from the ``reasoning_commentary`` template in the prompt registry and
    contains assertions only. The raw response is parsed as JSON and
    validated against :class:`CommentaryOutput`; any failure falls back
    to the deterministic summary (degraded mode).
    """

    def __init__(
        self,
        llm_client: Any,
        registry: PromptRegistry | None = None,
        context: dict[str, str] | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._registry = registry
        self._context = context or {}
        self._degraded = False

    def _ensure_registry(self) -> PromptRegistry:
        """Ensure the reasoning commentary template is registered and
        return the (now non-None) prompt registry."""
        if self._registry is None:
            self._registry = PromptRegistry()
        if not self._registry.has(PROMPT_NAME):
            self._registry.register(
                name=reasoning_commentary.NAME,
                version=reasoning_commentary.VERSION,
                template=reasoning_commentary.TEMPLATE,
                description=reasoning_commentary.DESCRIPTION,
            )
        return self._registry

    def _prompt(self, assertions: list[Assertion]) -> str:
        """Build the prompt from the registry template — assertions only."""
        template = self._ensure_registry().get(PROMPT_NAME).template
        return PromptRenderer().render(
            template,
            variables={
                "entity_name": self._context.get("entity_name", "the company"),
                "period": self._context.get("period", ""),
                "audience": self._context.get("audience", "analyst"),
                "assertions": _render_assertions(assertions),
            },
        )

    def generate(self, assertions: list[Assertion]) -> str:
        """Generate commentary for the given assertions (never raw data)."""
        prompt = self._prompt(assertions)
        raw = self._llm_client.generate(prompt)
        parsed = _extract_json(raw)
        if parsed is None:
            return self._fallback(assertions)
        try:
            output = CommentaryOutput.model_validate(parsed)
        except Exception:
            return self._fallback(assertions)
        self._degraded = False
        return _serialize_structured(output)

    def _fallback(self, assertions: list[Assertion]) -> str:
        """Degrade to the deterministic summary (no LLM)."""
        self._degraded = True
        return NullCommentaryProvider().generate(assertions)

    @property
    def degraded(self) -> bool:
        """True when the provider last degraded to the deterministic summary."""
        return self._degraded


class NullCommentaryProvider:
    """Deterministic, template-based commentary — no LLM (degraded mode)."""

    degraded = True

    def generate(self, assertions: list[Assertion]) -> str:
        """Produce a deterministic summary from assertions only."""
        lines: list[str] = ["# Deterministic Commentary", ""]
        if not assertions:
            lines.append("No assertions were produced from the available evidence.")
            return "\n".join(lines)

        verified = sum(
            1 for a in assertions if a.support_level == SupportLevel.VERIFIED
        )
        probable = sum(
            1 for a in assertions if a.support_level == SupportLevel.PROBABLE
        )
        weak = sum(
            1
            for a in assertions
            if a.support_level in (SupportLevel.WEAK, SupportLevel.INSUFFICIENT)
        )
        lines.append("## Summary")
        lines.append(
            f"{verified} verified fact(s), {probable} probable cause(s), "
            f"{weak} hypothesis/hypotheses assessed from "
            f"{len(assertions)} assertion(s)."
        )
        lines.append("")
        lines.append("## Assertions")
        for assertion in assertions:
            lines.append(f"- [{assertion.type.value}] {assertion.text}")
        return "\n".join(lines)
