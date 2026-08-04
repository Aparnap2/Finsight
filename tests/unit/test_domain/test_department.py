"""Tests for the Department domain model.

Covers ``finance/domain/department.py``: the organisational unit used for
cost and revenue allocation. Key invariants: departments belong to a
company, form a hierarchy via ``parent_id``, and default to active.
"""

import pytest
from pydantic import ValidationError

from finance.domain.department import Department


def _department(**overrides: object) -> Department:
    """Build a default department."""
    defaults: dict[str, object] = {
        "id": "DEPT-ENG",
        "code": "ENG",
        "name": "Engineering",
        "company_id": "CF001",
    }
    defaults.update(overrides)
    return Department(**defaults)


class TestDepartment:
    """Department construction."""

    def test_constructs_with_required_fields(self) -> None:
        """A department builds with required fields."""
        department = _department()
        assert department.id == "DEPT-ENG"
        assert department.code == "ENG"
        assert department.name == "Engineering"
        assert department.company_id == "CF001"

    def test_manager_defaults_to_none(self) -> None:
        """manager defaults to None."""
        assert _department().manager is None

    def test_parent_id_defaults_to_none(self) -> None:
        """parent_id defaults to None."""
        assert _department().parent_id is None

    def test_is_active_defaults_to_true(self) -> None:
        """Departments default to active."""
        assert _department().is_active is True

    def test_manager_settable(self) -> None:
        """The manager is settable."""
        assert _department(manager="Ada Lovelace").manager == "Ada Lovelace"

    def test_parent_id_settable(self) -> None:
        """The parent department is settable."""
        assert _department(parent_id="DEPT-CORP").parent_id == "DEPT-CORP"

    def test_inactive_department_representable(self) -> None:
        """An inactive department is representable."""
        assert _department(is_active=False).is_active is False

    def test_id_required(self) -> None:
        """A department requires an id."""
        with pytest.raises(ValidationError):
            _department(id=None)

    def test_code_required(self) -> None:
        """A department requires a code."""
        with pytest.raises(ValidationError):
            _department(code=None)

    def test_name_required(self) -> None:
        """A department requires a name."""
        with pytest.raises(ValidationError):
            _department(name=None)

    def test_company_id_required(self) -> None:
        """A department requires a company id."""
        with pytest.raises(ValidationError):
            _department(company_id=None)

    def test_round_trip_serialization(self) -> None:
        """A department round-trips through model_dump."""
        department = _department(manager="Ada Lovelace", parent_id="DEPT-GORP")
        dumped = department.model_dump()
        rebuilt = Department(**dumped)
        assert rebuilt == department