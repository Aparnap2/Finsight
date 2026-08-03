"""Pre-built prompt templates for FinSight FP&A agents.

This module registers all built-in prompt templates with a
:class:`~finance.prompts.registry.PromptRegistry`.

Usage::

    from finance.prompts.registry import PromptRegistry
    from finance.prompts import templates

    registry = PromptRegistry()
    templates.register_all(registry)
"""

from __future__ import annotations

from finance.prompts.registry import PromptRegistry

from finance.prompts.templates import (
    board_report,
    driver,
    executive_summary,
    recommendation,
    risk,
    variance,
)

_MODULES = [
    variance,
    executive_summary,
    driver,
    recommendation,
    board_report,
    risk,
]


def register_all(registry: PromptRegistry) -> None:
    """Register all built-in prompt templates with *registry*.

    Args:
        registry: A :class:`PromptRegistry` instance to populate.
    """
    for mod in _MODULES:
        registry.register(
            name=mod.NAME,
            version=mod.VERSION,
            template=mod.TEMPLATE,
            description=mod.DESCRIPTION,
        )
