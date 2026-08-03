"""Simple deterministic ABAC policy engine for the FinSight platform (Layer 0).

No general-purpose policy language and no OPA/Cedar dependency: policies are
plain dicts of the shape ``{"effect": "allow"|"deny", "rules": [...],
"combine": "all"|"any"}`` evaluated against an actor/request context dict.
Evaluation is fail-closed: unknown fields, unknown operators and
non-comparable values deny with a reason.

Each rule is ``{"field": str, "op": "gt"|"ge"|"lt"|"le"|"eq"|"in"|"contains",
"value": ...}``. The ``field`` key reads its value from ``context`` (e.g.
``amount``, ``department``, ``role``, ``tenant``, ``status``). A string
``value`` that matches a context key is resolved as a context reference (e.g.
an approval limit sourced from tenant config) so reason strings read like
``"deny: amount 120000 > approval_limit 50000 (manager)"``. Money comparisons
are performed in ``decimal.Decimal``.
"""

from decimal import Decimal, InvalidOperation
from typing import Any

_ALLOWED_OPS: frozenset[str] = frozenset({"gt", "ge", "lt", "le", "eq", "in", "contains"})
_NUMERIC_OPS: frozenset[str] = frozenset({"gt", "ge", "lt", "le"})

#: Operator display when a rule passes.
_OP_DISPLAY: dict[str, str] = {
    "gt": ">",
    "ge": ">=",
    "lt": "<",
    "le": "<=",
    "eq": "==",
    "in": "in",
    "contains": "contains",
}

#: Operator display when a rule fails (the negated comparison).
_INVERSE_DISPLAY: dict[str, str] = {
    "gt": "<=",
    "ge": "<",
    "lt": ">=",
    "le": ">",
    "eq": "!=",
    "in": "not in",
    "contains": "not contains",
}


def _as_decimal(value: Any) -> Decimal | None:
    """Best-effort conversion of a value to Decimal; None when not numeric."""
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _compare_numeric(op: str, left: Decimal, right: Decimal) -> bool:
    """Apply a numeric comparison operator to two Decimals."""
    if op == "gt":
        return left > right
    if op == "ge":
        return left >= right
    if op == "lt":
        return left < right
    return left <= right


def _values_equal(left: Any, right: Any) -> bool:
    """Equality that prefers Decimal comparison when both sides are numeric."""
    left_dec = _as_decimal(left)
    right_dec = _as_decimal(right)
    if left_dec is not None and right_dec is not None:
        return left_dec == right_dec
    return left == right


class PolicyEngine:
    """Deterministic ABAC evaluator. Stateless; share or instantiate freely."""

    def evaluate(self, policy: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
        """Evaluate ``policy`` against ``context``.

        Returns ``(decision, reason)`` where ``decision`` is True when the
        request is allowed. Fail-closed: malformed policies, unknown
        fields/operators and non-comparable values deny with a reason.
        """
        effect = policy.get("effect")
        if effect not in ("allow", "deny"):
            return False, f"deny: invalid policy effect {effect!r} (must be 'allow' or 'deny')"

        rules = policy.get("rules")
        if not isinstance(rules, list) or not rules:
            return False, "deny: policy has no rules"

        combine = policy.get("combine", "all")
        if combine not in ("all", "any"):
            return False, f"deny: invalid combine mode {combine!r} (must be 'all' or 'any')"

        first_pass_reason: str | None = None
        first_fail_reason: str | None = None
        for rule in rules:
            if not isinstance(rule, dict):
                return False, "deny: rule must be a dict with field/op/value"
            passed, error, reason = self._eval_rule(rule, context)
            if error:
                return False, f"deny: {reason}"  # fail-closed on any rule error
            if passed and first_pass_reason is None:
                first_pass_reason = reason
            if not passed and first_fail_reason is None:
                first_fail_reason = reason

        # combine == "all": matched iff every rule passed (none failed).
        # combine == "any": matched iff at least one rule passed.
        matched = (first_fail_reason is None) if combine == "all" else (first_pass_reason is not None)

        if effect == "allow":
            if matched:
                return True, f"allow: {first_pass_reason}"
            if combine == "all" and first_fail_reason is not None:
                return False, f"deny: {first_fail_reason}"
            return False, "deny: no rule matched (combine=any)"

        # effect == "deny": matched rules deny; unmatched rules do not apply.
        if matched:
            return False, f"deny: {first_pass_reason if first_pass_reason else first_fail_reason}"
        if first_fail_reason is not None:
            return True, f"allow: deny policy did not match ({first_fail_reason})"
        return True, "allow: deny policy did not match (no rule matched)"

    def eval_action(self, policy: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
        """Convenience alias for :meth:`evaluate`."""
        return self.evaluate(policy, context)

    def _eval_rule(self, rule: dict[str, Any], context: dict[str, Any]) -> tuple[bool, bool, str]:
        """Evaluate a single rule against the context.

        Returns ``(passed, error, reason)``. When ``error`` is True the rule
        could not be evaluated (unknown field/op, non-comparable value) and the
        caller must fail closed. ``reason`` is a human-readable comparison
        string such as ``"amount 12000 <= approval_limit 50000 (director)"``.
        """
        field = rule.get("field")
        op = rule.get("op")
        if not isinstance(field, str) or not isinstance(op, str):
            return False, True, "rule must define string 'field' and 'op'"
        if op not in _ALLOWED_OPS:
            return False, True, f"unknown operator {op!r} (allowed: {sorted(_ALLOWED_OPS)})"
        if field not in context:
            return False, True, f"unknown field {field!r} (not present in context)"

        ctx_value = context[field]
        rule_value, value_label = self._resolve_value(rule.get("value"), context)

        passed: bool
        if op in _NUMERIC_OPS:
            left = _as_decimal(ctx_value)
            right = _as_decimal(rule_value)
            if left is None or right is None:
                return False, True, f"cannot compare non-numeric values for field {field!r}"
            passed = _compare_numeric(op, left, right)
        elif op == "eq":
            passed = _values_equal(ctx_value, rule_value)
        elif op == "in":
            if isinstance(rule_value, str):
                if not isinstance(ctx_value, str):
                    return False, True, f"'in' needs a string or collection value for field {field!r}"
                passed = ctx_value in rule_value
            elif isinstance(rule_value, (list, tuple, set, frozenset)):
                try:
                    passed = ctx_value in rule_value
                except TypeError:
                    return False, True, f"cannot test membership for field {field!r}"
            else:
                return False, True, f"'in' requires a collection or string value for field {field!r}"
        else:  # contains
            if isinstance(ctx_value, str):
                if not isinstance(rule_value, str):
                    return False, True, f"'contains' needs a string value for field {field!r}"
                passed = rule_value.lower() in ctx_value.lower()
            elif isinstance(ctx_value, (list, tuple, set, frozenset)):
                passed = rule_value in ctx_value
            else:
                return False, True, f"'contains' needs a string or collection value for field {field!r}"

        display = _OP_DISPLAY[op] if passed else _INVERSE_DISPLAY[op]
        rendered_value = f"{value_label} {rule_value}" if value_label else str(rule_value)
        role = context.get("role")
        role_suffix = f" ({role})" if isinstance(role, str) else ""
        reason = f"{field} {ctx_value} {display} {rendered_value}{role_suffix}"
        return passed, False, reason

    def _resolve_value(self, value: Any, context: dict[str, Any]) -> tuple[Any, str | None]:
        """Resolve a rule value, treating string context keys as references."""
        if isinstance(value, str) and value in context:
            return context[value], value
        return value, None
