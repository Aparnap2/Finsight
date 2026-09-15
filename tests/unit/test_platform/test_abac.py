"""Tests for the ABAC policy engine (``finplatform.abac.engine``).

Verifies allow/deny evaluation with reason strings, Decimal-safe money
comparisons, ``combine="all"`` vs ``combine="any"`` semantics, fail-closed
handling of unknown fields/operators/malformed policies, and the
``eval_action`` convenience alias.
"""

from decimal import Decimal

import pytest

from finplatform.abac.engine import PolicyEngine

#: Allow a request whose amount exceeds the resolved approval limit.
ALLOW_OVER_LIMIT: dict[str, object] = {
    "effect": "allow",
    "rules": [{"field": "amount", "op": "gt", "value": "approval_limit"}],
}

#: Deny a request whose amount exceeds the resolved approval limit.
DENY_OVER_LIMIT: dict[str, object] = {
    "effect": "deny",
    "rules": [{"field": "amount", "op": "gt", "value": "approval_limit"}],
}

_TWO_RULE_POLICY: dict[str, object] = {
    "effect": "allow",
    "rules": [
        {"field": "amount", "op": "gt", "value": 1000},
        {"field": "department", "op": "eq", "value": "finance"},
    ],
}

_MIXED_CONTEXT = {"amount": Decimal("5000"), "department": "ops"}


class TestEvaluate:
    """evaluate returns (True|False, reason) tuples for allow/deny policies."""

    def test_allow_when_rule_passes(self) -> None:
        decision, reason = PolicyEngine().evaluate(
            ALLOW_OVER_LIMIT,
            {"amount": Decimal("120000"), "approval_limit": Decimal("50000"), "role": "manager"},
        )
        assert decision is True
        assert "allow:" in reason
        assert "120000" in reason
        assert "50000" in reason

    def test_allow_with_decimal_money_comparison(self) -> None:
        decision, reason = PolicyEngine().evaluate(
            ALLOW_OVER_LIMIT,
            {"amount": Decimal("120000"), "approval_limit": Decimal("50000")},
        )
        assert decision is True
        assert reason == "allow: amount 120000 > approval_limit 50000"

    def test_deny_effect_blocks_matching_request(self) -> None:
        decision, reason = PolicyEngine().evaluate(
            DENY_OVER_LIMIT,
            {"amount": Decimal("120000"), "approval_limit": Decimal("50000")},
        )
        assert decision is False
        assert reason.startswith("deny:")

    def test_deny_policy_non_match_allows(self) -> None:
        decision, reason = PolicyEngine().evaluate(
            DENY_OVER_LIMIT,
            {"amount": Decimal("40000"), "approval_limit": Decimal("50000")},
        )
        assert decision is True
        assert reason.startswith("allow:")

    def test_rule_value_resolved_from_context_reference(self) -> None:
        # A string rule value matching a context key resolves to that key's
        # value (approval limits sourced from tenant config).
        decision, reason = PolicyEngine().evaluate(
            ALLOW_OVER_LIMIT,
            {"amount": Decimal("60000"), "approval_limit": Decimal("50000")},
        )
        assert decision is True
        assert "approval_limit 50000" in reason


class TestCombine:
    """combine='all' requires every rule; combine='any' requires one."""

    def test_combine_all_denies_when_one_rule_fails(self) -> None:
        policy: dict[str, object] = {**_TWO_RULE_POLICY, "combine": "all"}
        decision, reason = PolicyEngine().evaluate(policy, _MIXED_CONTEXT)
        assert decision is False
        assert reason.startswith("deny:")

    def test_combine_any_allows_when_one_rule_passes(self) -> None:
        policy: dict[str, object] = {**_TWO_RULE_POLICY, "combine": "any"}
        decision, reason = PolicyEngine().evaluate(policy, _MIXED_CONTEXT)
        assert decision is True
        assert reason.startswith("allow:")

    def test_combine_all_allows_when_every_rule_passes(self) -> None:
        policy: dict[str, object] = {**_TWO_RULE_POLICY, "combine": "all"}
        context = {"amount": Decimal("5000"), "department": "finance"}
        decision, _reason = PolicyEngine().evaluate(policy, context)
        assert decision is True


class TestFailClosed:
    """Unknown fields/operators and malformed policies deny with a reason."""

    def test_unknown_field_denies(self) -> None:
        policy = {"effect": "allow", "rules": [{"field": "missing_field", "op": "eq", "value": 1}]}
        decision, reason = PolicyEngine().evaluate(policy, {"amount": Decimal("5")})
        assert decision is False
        assert "unknown field" in reason

    def test_unknown_operator_denies(self) -> None:
        policy = {"effect": "allow", "rules": [{"field": "amount", "op": "regex", "value": 1}]}
        decision, reason = PolicyEngine().evaluate(policy, {"amount": Decimal("5")})
        assert decision is False
        assert "unknown operator" in reason

    @pytest.mark.parametrize("effect", ["permit", None])
    def test_invalid_effect_denies(self, effect: str | None) -> None:
        policy: dict[str, object] = {
            "effect": effect,
            "rules": [{"field": "amount", "op": "gt", "value": 1}],
        }
        decision, reason = PolicyEngine().evaluate(policy, {"amount": Decimal("5")})
        assert decision is False
        assert "invalid policy effect" in reason

    def test_missing_rules_denies(self) -> None:
        decision, reason = PolicyEngine().evaluate({"effect": "allow"}, {"amount": Decimal("5")})
        assert decision is False
        assert "no rules" in reason

    def test_invalid_combine_mode_denies(self) -> None:
        policy: dict[str, object] = {
            "effect": "allow",
            "combine": "xor",
            "rules": [{"field": "amount", "op": "gt", "value": 1}],
        }
        decision, reason = PolicyEngine().evaluate(policy, {"amount": Decimal("5")})
        assert decision is False
        assert "invalid combine mode" in reason


class TestEvalAction:
    """eval_action is a convenience alias for evaluate."""

    def test_eval_action_matches_evaluate(self) -> None:
        engine = PolicyEngine()
        context = {
            "amount": Decimal("120000"),
            "approval_limit": Decimal("50000"),
            "role": "director",
        }
        assert engine.eval_action(ALLOW_OVER_LIMIT, context) == engine.evaluate(
            ALLOW_OVER_LIMIT, context
        )

    def test_eval_action_denies(self) -> None:
        decision, reason = PolicyEngine().eval_action(
            DENY_OVER_LIMIT,
            {"amount": Decimal("120000"), "approval_limit": Decimal("50000")},
        )
        assert decision is False
        assert reason.startswith("deny:")
