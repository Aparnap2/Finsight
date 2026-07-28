"""Department domain model.

Departments represent organisational units within a company that consume
and generate financial data.  Every budget line, actual, and forecast can
optionally be attributed to a department.
"""

from pydantic import BaseModel


class Department(BaseModel):
    """An organisational unit within a company.

    Departments are the primary dimension for cost and revenue allocation
    in budgeting and variance analysis.  They form a hierarchy via
    ``parent_id``.
    """

    id: str
    """Unique department identifier."""

    code: str
    """Department code (e.g. ``\"ENG\"`` for Engineering)."""

    name: str
    """Human-readable department name."""

    company_id: str
    """The company this department belongs to."""

    manager: str | None = None
    """Name or identifier of the department manager."""

    parent_id: str | None = None
    """Parent department (for organisational hierarchy)."""

    is_active: bool = True
    """Whether this department is currently active."""
