"""Planner error hierarchy for the P4.2 typed investigation planner.

The planner never falls back internally: every failure surfaces as a
:class:`PlannerError` so the caller (selection orchestration) can degrade
deterministically to the P3-template path. :class:`PlanRejectedError` marks
structural rejections (allowlist, grounding, wording) distinctly while
remaining catchable as :class:`PlannerError`.
"""

from __future__ import annotations


class PlannerError(Exception):
    """Base failure for investigation planning: provider or structural."""


class PlanRejectedError(PlannerError):
    """A candidate plan failed structural validation (flagged, never fixed)."""
