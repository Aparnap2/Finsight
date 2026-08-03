"""Reasoning orchestration.

Bridges the deterministic reasoning pipeline (``finance.reasoning``) into
the commentary layer's output shape (:class:`CommentaryDraft`) so existing
commentary consumers can use the reasoning pipeline unchanged.

Layer rules: agents → finance → shared. This package imports only
``finance`` and ``shared`` — never ``apps``.
"""

from agents.reasoning.orchestrator import run_reasoning_commentary

__all__ = ["run_reasoning_commentary"]
