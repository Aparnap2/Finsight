"""Tests for the RBAC role → permission matrix (``finplatform.rbac.matrix``).

Verifies that the analyst → manager → director → cfo hierarchy is cumulative,
that ``cfo`` holds every permission, and that lookups fail closed for unknown
roles and unknown permissions.
"""

from finplatform.rbac.matrix import ROLE_PERMISSIONS, check_permission, permissions_for

_ALL_ROLES = ("analyst", "manager", "director", "cfo")


class TestCheckPermission:
    """check_permission returns True/False according to the role matrix."""

    def test_analyst_can_view_ledger(self) -> None:
        assert check_permission("analyst", "view_ledger") is True

    def test_analyst_cannot_approve_budget(self) -> None:
        assert check_permission("analyst", "approve_budget") is False

    def test_director_can_approve_budget(self) -> None:
        assert check_permission("director", "approve_budget") is True

    def test_director_cannot_manage_tenants(self) -> None:
        assert check_permission("director", "manage_tenants") is False

    def test_manager_cannot_manage_users(self) -> None:
        assert check_permission("manager", "manage_users") is False

    def test_cfo_can_manage_tenants(self) -> None:
        assert check_permission("cfo", "manage_tenants") is True

    def test_cfo_has_every_known_permission(self) -> None:
        for permission in permissions_for("cfo"):
            assert check_permission("cfo", permission) is True

    def test_unknown_role_fails_closed(self) -> None:
        assert check_permission("ceo", "view_ledger") is False
        assert check_permission("intern", "view_ledger") is False

    def test_unknown_permission_fails_closed(self) -> None:
        assert check_permission("cfo", "delete_everything") is False
        assert check_permission("analyst", "no_such_permission") is False


class TestPermissionsFor:
    """permissions_for returns cumulative sets; unknown roles yield empty."""

    def test_cfo_permissions_are_superset_of_every_role(self) -> None:
        cfo = permissions_for("cfo")
        for role in _ALL_ROLES:
            assert cfo.issuperset(permissions_for(role))

    def test_hierarchy_is_cumulative(self) -> None:
        assert permissions_for("manager").issuperset(permissions_for("analyst"))
        assert permissions_for("director").issuperset(permissions_for("manager"))
        assert permissions_for("cfo").issuperset(permissions_for("director"))

    def test_analyst_permission_set(self) -> None:
        assert permissions_for("analyst") == frozenset(
            {"view_ledger", "view_budget", "view_variance", "view_artifacts"}
        )

    def test_unknown_role_returns_empty_set(self) -> None:
        assert permissions_for("ceo") == frozenset()

    def test_all_known_roles_present(self) -> None:
        assert set(ROLE_PERMISSIONS) == set(_ALL_ROLES)
