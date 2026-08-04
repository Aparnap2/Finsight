"""Tests for the commentary domain models.

Covers ``shared/models/state.py``: ``CommentarySection``, ``ActionItem``,
and ``CommentaryDraft`` — the structures the commentary engine produces and
the review workflow consumes. Key invariants: drafts always carry at least
the section list, actions are optional with a default priority, and the
approval state is explicitly tracked.
"""

import pytest
from pydantic import ValidationError

from shared.models.state import ActionItem, CommentaryDraft, CommentarySection


def _section(**overrides: object) -> CommentarySection:
    """Build a default commentary section."""
    defaults: dict[str, object] = {
        "section_type": "variance_analysis",
        "content": "Travel spend increased 12% driven by airfare.",
        "cited_data_points": ["VAR-2026-042"],
    }
    defaults.update(overrides)
    return CommentarySection(**defaults)


def _action(**overrides: object) -> ActionItem:
    """Build a default action item."""
    defaults: dict[str, object] = {
        "description": "Renegotiate airfare contract.",
        "assigned_to": "procurement.lead",
        "due_by": "2026-09-30",
        "priority": "high",
    }
    defaults.update(overrides)
    return ActionItem(**defaults)


def _draft(**overrides: object) -> CommentaryDraft:
    """Build a default commentary draft."""
    defaults: dict[str, object] = {
        "sections": [_section()],
        "generated_at": "2026-07-15T12:00:00Z",
    }
    defaults.update(overrides)
    return CommentaryDraft(**defaults)


# =============================================================================
# CommentarySection
# =============================================================================


class TestCommentarySection:
    """Commentary section construction."""

    def test_constructs_with_required_fields(self) -> None:
        """A section builds with required fields."""
        section = _section()
        assert section.section_type == "variance_analysis"
        assert section.content == "Travel spend increased 12% driven by airfare."

    def test_cited_data_points_default_to_empty(self) -> None:
        """cited_data_points defaults to an empty list."""
        section = CommentarySection(
            section_type="variance_analysis", content="Travel spend increased."
        )
        assert section.cited_data_points == []

    def test_section_type_required(self) -> None:
        """A section requires a section type."""
        with pytest.raises(ValidationError):
            _section(section_type=None)

    def test_content_required(self) -> None:
        """A section requires content."""
        with pytest.raises(ValidationError):
            _section(content=None)

    def test_cited_data_points_stored(self) -> None:
        """Cited data points are preserved."""
        section = _section(cited_data_points=["VAR-1", "KPI-2"])
        assert section.cited_data_points == ["VAR-1", "KPI-2"]

    def test_all_section_types_representable(self) -> None:
        """The documented section types are all representable."""
        for section_type in (
            "variance_analysis",
            "root_cause",
            "recommendation",
            "summary",
            "narrative",
        ):
            assert _section(section_type=section_type).section_type == section_type


# =============================================================================
# ActionItem
# =============================================================================


class TestActionItem:
    """Action item construction."""

    def test_constructs_with_required_fields(self) -> None:
        """An action item builds with required fields."""
        action = _action()
        assert action.description == "Renegotiate airfare contract."
        assert action.assigned_to == "procurement.lead"
        assert action.due_by == "2026-09-30"
        assert action.priority == "high"

    def test_assigned_to_defaults_to_none(self) -> None:
        """assigned_to defaults to None."""
        assert _action(assigned_to=None).assigned_to is None

    def test_due_by_defaults_to_none(self) -> None:
        """due_by defaults to None."""
        assert _action(due_by=None).due_by is None

    def test_priority_defaults_to_medium(self) -> None:
        """priority defaults to medium."""
        action = ActionItem(description="Renegotiate airfare contract.")
        assert action.priority == "medium"

    def test_description_required(self) -> None:
        """An action item requires a description."""
        with pytest.raises(ValidationError):
            _action(description=None)

    def test_priority_values_representable(self) -> None:
        """Low, medium, and high priorities are representable."""
        for priority in ("low", "medium", "high"):
            assert _action(priority=priority).priority == priority


# =============================================================================
# CommentaryDraft
# =============================================================================


class TestCommentaryDraft:
    """Commentary draft construction and defaults."""

    def test_constructs_with_required_fields(self) -> None:
        """A draft builds with required fields."""
        draft = _draft()
        assert len(draft.sections) == 1
        assert draft.generated_at == "2026-07-15T12:00:00Z"

    def test_actions_default_to_empty(self) -> None:
        """actions defaults to an empty list."""
        assert _draft().actions == []

    def test_assertions_used_default_to_empty(self) -> None:
        """assertions_used defaults to an empty list."""
        assert _draft().assertions_used == []

    def test_version_defaults_to_one(self) -> None:
        """version defaults to 1."""
        assert _draft().version == 1

    def test_status_defaults_to_draft(self) -> None:
        """status defaults to draft."""
        assert _draft().status == "draft"

    def test_approval_state_defaults_to_none(self) -> None:
        """approval_state defaults to None."""
        assert _draft().approval_state is None

    def test_sections_required(self) -> None:
        """A draft requires at least a sections list."""
        with pytest.raises(ValidationError):
            _draft(sections=None)

    def test_empty_sections_representable(self) -> None:
        """An empty sections list is representable."""
        assert _draft(sections=[]).sections == []

    def test_multiple_sections_stored(self) -> None:
        """A draft carries multiple sections in order."""
        draft = _draft(
            sections=[
                _section(section_type="summary"),
                _section(section_type="variance_analysis"),
            ]
        )
        assert [s.section_type for s in draft.sections] == [
            "summary",
            "variance_analysis",
        ]

    def test_actions_stored(self) -> None:
        """Actions are preserved on the draft."""
        draft = _draft(actions=[_action(), _action(priority="medium")])
        assert len(draft.actions) == 2
        assert draft.actions[1].priority == "medium"

    def test_assertions_used_stored(self) -> None:
        """Assertion ids consumed are preserved."""
        draft = _draft(assertions_used=["ASRT-001", "ASRT-002"])
        assert draft.assertions_used == ["ASRT-001", "ASRT-002"]

    def test_approval_state_settable(self) -> None:
        """The approval state is explicitly settable."""
        draft = _draft(approval_state="approved")
        assert draft.approval_state == "approved"

    def test_status_settable(self) -> None:
        """The workflow status is settable."""
        draft = _draft(status="submitted")
        assert draft.status == "submitted"

    def test_version_settable(self) -> None:
        """The version increments via the field."""
        draft = _draft(version=3)
        assert draft.version == 3

    def test_round_trip_serialization(self) -> None:
        """A draft round-trips through model_dump."""
        draft = _draft(
            actions=[_action()],
            assertions_used=["ASRT-001"],
            approval_state="pending_review",
        )
        dumped = draft.model_dump()
        rebuilt = CommentaryDraft(**dumped)
        assert rebuilt == draft