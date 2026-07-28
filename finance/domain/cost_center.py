"""Cost Center domain model.

Cost centres provide a finer granularity of cost tracking within a
department.  Budgets and actuals can be allocated to specific cost centres
for detailed spend analysis.
"""

from pydantic import BaseModel


class CostCenter(BaseModel):
    """A sub-unit within a department for detailed cost tracking.

    Cost centres allow finer-grained allocation of budgets and tracking of
    actuals beyond the department level.  Each cost centre has a single
    ``budget_owner`` responsible for its spending.
    """

    id: str
    """Unique cost centre identifier."""

    code: str
    """Cost centre code (e.g. ``\"ENG-CLOUD\"``)."""

    name: str
    """Human-readable cost centre name."""

    department_id: str
    """The department this cost centre belongs to."""

    company_id: str
    """The company this cost centre belongs to."""

    manager: str | None = None
    """Day-to-day manager of this cost centre."""

    budget_owner: str | None = None
    """Person responsible for the budget of this cost centre."""

    is_active: bool = True
    """Whether this cost centre is currently active."""
