"""Tests for ActionItem model, taxonomy, and blocked-action enforcement."""
import pytest
from decimal import Decimal
from backend.models.action import (
    ActionItem, ActionStatus, ActionDomain, ActionImpact,
    ActionResult, create_action, create_action_from_assertion,
    APPROVED_ACTIONS,
)
from backend.models.assertions import Assertion, AssertionType


class TestCreateAction:
    def test_create_valid_action(self):
        result = create_action(
            action="reduce", domain=ActionDomain.COST,
            target="cloud spend", description="Reduce cloud spend",
            cited_assertion_ids=["a1"], owner="FinOps",
            impact=ActionImpact(expected_savings=Decimal("50000")),
            policy_permitted=True,
        )
        assert result.created
        assert result.action_item.status == ActionStatus.APPROVED
        assert result.action_item.can_execute

    def test_action_not_in_taxonomy_blocked(self):
        result = create_action(
            action="delete", domain=ActionDomain.COST,
            target="servers", description="Delete servers",
            cited_assertion_ids=["a1"],
        )
        assert not result.created
        assert result.action_item.status == ActionStatus.BLOCKED

    def test_action_no_cited_assertions_blocked(self):
        result = create_action(
            action="reduce", domain=ActionDomain.COST,
            target="spend", description="Reduce spend",
            cited_assertion_ids=[],
        )
        assert not result.created
        assert result.action_item.status == ActionStatus.BLOCKED

    def test_action_without_policy_warns(self):
        result = create_action(
            action="reduce", domain=ActionDomain.COST,
            target="spend", description="Reduce spend",
            cited_assertion_ids=["a1"], policy_permitted=False,
        )
        assert result.created
        assert result.action_item.status == ActionStatus.PROPOSED
        assert any("policy" in w.lower() for w in result.warnings)

    def test_action_without_impact_warns(self):
        result = create_action(
            action="reduce", domain=ActionDomain.COST,
            target="spend", description="Reduce spend",
            cited_assertion_ids=["a1"], policy_permitted=True,
        )
        assert result.created
        assert not result.action_item.impact_quantified
        assert any("impact" in w.lower() for w in result.warnings)

    def test_action_without_owner_warns(self):
        result = create_action(
            action="reduce", domain=ActionDomain.COST,
            target="spend", description="Reduce spend",
            cited_assertion_ids=["a1"], policy_permitted=True,
            impact=ActionImpact(expected_savings=Decimal("10000")),
        )
        assert result.created
        assert not result.action_item.owner_identified
        assert any("owner" in w.lower() for w in result.warnings)


class TestActionItemProperties:
    def test_can_execute_only_when_approved(self):
        approved = ActionItem(id="a1", action="reduce", domain=ActionDomain.COST, target="spend", description="", cited_assertion_ids=[], status=ActionStatus.APPROVED)
        assert approved.can_execute
        blocked = ActionItem(id="a2", action="reduce", domain=ActionDomain.COST, target="spend", description="", cited_assertion_ids=[], status=ActionStatus.BLOCKED)
        assert not blocked.can_execute
        proposed = ActionItem(id="a3", action="reduce", domain=ActionDomain.COST, target="spend", description="", cited_assertion_ids=[], status=ActionStatus.PROPOSED)
        assert not proposed.can_execute

    def test_is_blocked_property(self):
        item = ActionItem(id="a1", action="reduce", domain=ActionDomain.COST, target="spend", description="", cited_assertion_ids=[], status=ActionStatus.BLOCKED)
        assert item.is_blocked


class TestCreateFromAssertion:
    def test_create_from_assertion(self):
        a = Assertion(
            id="a1", type=AssertionType.ACTION,
            text="Should reduce cloud spend", value=Decimal("0"),
            metadata={"action": "reduce", "target": "cloud spend"},
        )
        result = create_action_from_assertion(a, owner="FinOps")
        assert result.created
        assert result.action_item.domain == ActionDomain.COST

    def test_create_from_assertion_infers_revenue(self):
        a = Assertion(
            id="a2", type=AssertionType.ACTION,
            text="Should increase revenue", value=Decimal("0"),
            metadata={"action": "increase", "target": "revenue"},
        )
        result = create_action_from_assertion(a)
        assert result.created
        assert result.action_item.domain == ActionDomain.REVENUE

    def test_create_from_assertion_infers_headcount(self):
        a = Assertion(
            id="a3", type=AssertionType.ACTION,
            text="Should hire engineers", value=Decimal("0"),
            metadata={"action": "hire", "target": "engineering headcount"},
        )
        result = create_action_from_assertion(a)
        assert result.created
        assert result.action_item.domain == ActionDomain.HEADCOUNT


class TestTaxonomy:
    def test_approved_taxonomy_has_entries(self):
        assert len(APPROVED_ACTIONS) > 0

    def test_all_entries_have_valid_domain(self):
        for verb, domain in APPROVED_ACTIONS:
            assert isinstance(domain, ActionDomain)

    def test_action_to_dict(self):
        result = create_action(
            action="reduce", domain=ActionDomain.COST,
            target="spend", description="Reduce spend",
            cited_assertion_ids=["a1"], owner="FinOps",
            policy_permitted=True,
            impact=ActionImpact(expected_savings=Decimal("50000")),
        )
        d = result.action_item.to_dict()
        assert d["action"] == "reduce"
        assert d["domain"] == "cost"
        assert d["status"] == "approved"
