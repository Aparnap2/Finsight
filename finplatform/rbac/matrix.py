"""RBAC role → permission matrix for the FinSight platform (Layer 0).

Roles form a strict hierarchy — ``analyst < manager < director < cfo`` — and
each role inherits every permission of the roles below it. ``cfo`` receives
all permissions. Lookups fail closed: unknown roles or permissions yield
``False`` / an empty permission set.
"""

# Base permission set contributed by each role (before hierarchy folding).
# The fold is performed by :func:`_cumulative`, so every higher role
# automatically includes the permissions of all lower roles.
_PERMISSION_SETS: dict[str, frozenset[str]] = {
    "analyst": frozenset({"view_ledger", "view_budget", "view_variance", "view_artifacts"}),
    "manager": frozenset({"run_jobs", "approve_budget"}),
    "director": frozenset({"manage_users", "edit_config"}),
    "cfo": frozenset({"manage_tenants"}),
}

_ROLE_ORDER: tuple[str, ...] = ("analyst", "manager", "director", "cfo")


def _cumulative() -> dict[str, frozenset[str]]:
    """Fold base permission sets into the hierarchical role → permission map."""
    result: dict[str, frozenset[str]] = {}
    inherited: frozenset[str] = frozenset()
    for role in _ROLE_ORDER:
        inherited = inherited | _PERMISSION_SETS[role]
        result[role] = inherited
    return result


#: Effective permission set per role (hierarchical, cumulative). Keys are the
#: only valid roles; ``cfo`` holds all nine permissions.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = _cumulative()


def check_permission(role: str, permission: str) -> bool:
    """Return whether ``role`` holds ``permission`` (fail-closed).

    Unknown roles and unknown permissions both return ``False``.
    """
    permissions = ROLE_PERMISSIONS.get(role)
    if permissions is None:
        return False
    return permission in permissions


def permissions_for(role: str) -> frozenset[str]:
    """Return the full effective permission set for ``role``.

    Unknown roles yield an empty frozenset (fail-closed).
    """
    return ROLE_PERMISSIONS.get(role, frozenset())
