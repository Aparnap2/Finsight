"""Safe formula compiler for the elevated formula registry.

Transforms a registry expression (e.g. ``(NetRevenue - COGS) / NetRevenue
* 100``) into a :class:`CompiledFormula` that can be evaluated with
``decimal.Decimal`` inputs — never ``float``, never ``eval``.

Expressions are parsed with the ``ast`` module and evaluated against a
strict allow-list of node types so arbitrary code execution is
impossible. Inputs are referenced by their canonical ``formula_id``
(snake_case); the compiler resolves the CamelCase names used inside the
expression (e.g. ``NetRevenue`` → ``net_revenue``) via a normalised name
index.

Descriptive expressions (e.g. ``"Sum of all invoices before
adjustments"``) are not arithmetic and are compiled as *unsupported*:
``evaluate`` raises :class:`FormulaEvaluationError` for those.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable, Mapping
from decimal import Decimal, DivisionByZero, InvalidOperation
from typing import Any

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FormulaCompilationError(ValueError):
    """Raised when an expression cannot be safely compiled."""


class FormulaEvaluationError(ValueError):
    """Raised when an expression cannot be evaluated from given inputs."""


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------


def _normalise(name: str) -> str:
    """Normalise an identifier for CamelCase/snake_case matching.

    ``NetRevenue`` and ``net_revenue`` both normalise to ``netrevenue``.

    Args:
        name: The raw identifier.

    Returns:
        Lower-cased alphanumeric key.
    """
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _function_map() -> dict[str, Any]:
    """Return the allow-listed functions available inside expressions."""
    return {
        "abs": abs,
        "max": max,
        "min": min,
        "round": round,
    }


# ---------------------------------------------------------------------------
# Compiled formula
# ---------------------------------------------------------------------------


class CompiledFormula:
    """A compiled, safely-evaluable formula.

    Attributes:
        formula_id: Canonical formula identifier.
        expression: The raw source expression.
        inputs: Sorted list of ``formula_id`` inputs the expression needs.
        supported: Whether the expression is arithmetic and evaluable.
        unsupported_reason: Why the formula is unsupported (empty when
            supported).
    """

    def __init__(
        self,
        formula_id: str,
        expression: str,
        inputs: list[str],
        supported: bool,
        unsupported_reason: str = "",
        source_inputs: list[str] | None = None,
    ) -> None:
        """Initialise a compiled formula.

        Args:
            formula_id: Canonical formula identifier.
            expression: The raw source expression.
            inputs: Sorted list of input ``formula_id`` values.
            supported: Whether the expression is arithmetic.
            unsupported_reason: Explanation when ``supported`` is False.
            source_inputs: Additional raw field names the expression
                references that are not registered formula ids (supplied
                by the caller at evaluation time).
        """
        self.formula_id = formula_id
        self.expression = expression
        self.inputs = sorted(inputs)
        self.source_inputs = sorted(source_inputs or [])
        self.supported = supported
        self.unsupported_reason = unsupported_reason
        self._tree: ast.Expression | None = None
        self._name_map: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, input_values: Mapping[str, Decimal]) -> Decimal:
        """Evaluate the formula against a mapping of input values.

        Args:
            input_values: Mapping of input name → Decimal value. Both the
                declared formula inputs (:attr:`inputs`) and any source
                fields (:attr:`source_inputs`) must be present.

        Returns:
            The computed ``Decimal`` result.

        Raises:
            FormulaEvaluationError: If the formula is unsupported, an
                input is missing, or arithmetic fails (division by zero).
        """
        if not self.supported or self._tree is None:
            msg = (
                f"Formula '{self.formula_id}' is not evaluable: "
                f"{self.unsupported_reason or 'unsupported expression'}"
            )
            raise FormulaEvaluationError(msg)

        required = set(self.inputs) | set(self.source_inputs)
        missing = [i for i in required if i not in input_values]
        if missing:
            msg = (
                f"Formula '{self.formula_id}' missing inputs: "
                f"{', '.join(sorted(missing))}"
            )
            raise FormulaEvaluationError(msg)

        functions = _function_map()
        scope: dict[str, Decimal | Any] = {
            name: input_values[formula_id]
            for name, formula_id in self._name_map.items()
        }
        for source_name in self.source_inputs:
            scope[source_name] = input_values[source_name]
        try:
            result = self._eval(self._tree.body, scope, functions)
        except (DivisionByZero, InvalidOperation, ZeroDivisionError) as exc:
            msg = f"Formula '{self.formula_id}' arithmetic failed: {exc}"
            raise FormulaEvaluationError(msg) from exc
        return result

    # ------------------------------------------------------------------
    # Internal AST evaluation
    # ------------------------------------------------------------------

    def _eval(
        self,
        node: ast.AST,
        scope: Mapping[str, Any],
        functions: Mapping[str, Any],
    ) -> Decimal:
        """Evaluate an AST node against the scope.

        Args:
            node: The AST node to evaluate.
            scope: Resolved name → value mapping.
            functions: Allow-listed callable mapping.

        Returns:
            The node's Decimal value.

        Raises:
            FormulaEvaluationError: If the node is disallowed or a name
                is unknown.
        """
        if isinstance(node, ast.Expression):
            return self._eval(node.body, scope, functions)

        if isinstance(node, ast.Constant):
            return self._coerce_constant(node.value)

        if isinstance(node, ast.Name):
            if node.id in scope:
                value = scope[node.id]
                if isinstance(value, Decimal):
                    return value
                return self._coerce_constant(value)
            msg = f"Unknown identifier '{node.id}' in '{self.formula_id}'"
            raise FormulaEvaluationError(msg)

        if isinstance(node, ast.BinOp):
            left = self._eval(node.left, scope, functions)
            right = self._eval(node.right, scope, functions)
            op = self._binary_op(node.op)
            return op(left, right)

        if isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand, scope, functions)
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return operand
            msg = f"Unsupported unary operator in '{self.formula_id}'"
            raise FormulaEvaluationError(msg)

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in functions:
                msg = f"Disallowed function call in '{self.formula_id}'"
                raise FormulaEvaluationError(msg)
            func = functions[node.func.id]
            args = [self._eval(arg, scope, functions) for arg in node.args]
            if node.keywords:
                msg = f"Keyword arguments disallowed in '{self.formula_id}'"
                raise FormulaEvaluationError(msg)
            raw = func(*args)
            return self._coerce_constant(raw)

        msg = f"Disallowed AST node {type(node).__name__} in '{self.formula_id}'"
        raise FormulaEvaluationError(msg)

    def _binary_op(self, op: ast.operator) -> Callable[[Decimal, Decimal], Decimal]:
        """Map an AST binary operator to a Decimal-safe callable.

        Args:
            op: The AST operator node.

        Returns:
            A two-argument callable.

        Raises:
            FormulaEvaluationError: If the operator is disallowed.
        """
        mapping: dict[type[ast.operator], Callable[[Decimal, Decimal], Decimal]] = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Mod: operator.mod,
            ast.Pow: operator.pow,
        }
        if type(op) in mapping:
            return mapping[type(op)]
        msg = f"Unsupported binary operator in '{self.formula_id}'"
        raise FormulaEvaluationError(msg)

    @staticmethod
    def _coerce_constant(value: Any) -> Decimal:
        """Coerce a constant into a Decimal.

        Args:
            value: Raw constant (int, float, str, Decimal).

        Returns:
            Decimal representation.

        Raises:
            FormulaEvaluationError: If the value is not numeric.
        """
        if isinstance(value, Decimal):
            return value
        if isinstance(value, bool):
            msg = "Boolean constants are disallowed in formula expressions"
            raise FormulaEvaluationError(msg)
        if isinstance(value, (int, float, str)):
            try:
                return Decimal(str(value))
            except (InvalidOperation, ValueError) as exc:
                msg = f"Cannot coerce '{value}' to Decimal"
                raise FormulaEvaluationError(msg) from exc
        msg = f"Unsupported constant type {type(value).__name__}"
        raise FormulaEvaluationError(msg)


# ---------------------------------------------------------------------------
# Compiler entry point
# ---------------------------------------------------------------------------


def compile_formula(
    record: dict[str, Any],
    name_index: Mapping[str, str] | None = None,
) -> CompiledFormula:
    """Compile a registry record into a :class:`CompiledFormula`.

    Args:
        record: A registry-v1 formula record.
        name_index: Optional mapping of normalised name → ``formula_id``
            for resolving names that are not among the record's declared
            inputs (e.g. aliases).

    Returns:
        The compiled formula. ``supported`` is False for descriptive
        (non-arithmetic) expressions.
    """
    formula_id = str(record["id"])
    expression = str(record["expression"])
    declared_inputs = [str(i) for i in record.get("inputs", [])]

    # Build a name → formula_id index from declared inputs plus the
    # caller-provided registry-wide index.
    name_map: dict[str, str] = {_normalise(i): i for i in declared_inputs}
    if name_index:
        for normalised, resolved_id in name_index.items():
            name_map.setdefault(normalised, resolved_id)

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        return CompiledFormula(
            formula_id=formula_id,
            expression=expression,
            inputs=declared_inputs,
            supported=False,
            unsupported_reason=f"expression is not arithmetic: {exc.msg}",
        )

    # Validate the tree statically: calls must be allow-listed and no
    # forbidden node types may appear. Unresolvable names become source
    # inputs (raw fields the caller provides at evaluation time).
    functions = _function_map()
    resolved: dict[str, str] = {}
    source_inputs: set[str] = set()
    try:
        _validate_tree(tree, formula_id, name_map, functions, resolved, source_inputs)
    except FormulaCompilationError as exc:
        return CompiledFormula(
            formula_id=formula_id,
            expression=expression,
            inputs=declared_inputs,
            supported=False,
            unsupported_reason=str(exc),
        )

    formula = CompiledFormula(
        formula_id=formula_id,
        expression=expression,
        inputs=declared_inputs,
        supported=True,
        source_inputs=sorted(source_inputs),
    )
    formula._tree = tree
    formula._name_map = resolved
    return formula


def _validate_tree(
    node: ast.AST,
    formula_id: str,
    name_map: Mapping[str, str],
    functions: Mapping[str, Any],
    resolved: dict[str, str],
    source_inputs: set[str],
) -> None:
    """Statically validate an expression AST.

    Args:
        node: The AST node to validate.
        formula_id: Formula identifier (for error messages).
        name_map: Normalised name → formula_id mapping.
        functions: Allow-listed functions.
        resolved: Output mapping of expression name → formula_id.
        source_inputs: Output set of unresolvable raw field names.

    Raises:
        FormulaCompilationError: If any node is disallowed.
    """
    if isinstance(node, ast.Expression):
        _validate_tree(node.body, formula_id, name_map, functions, resolved, source_inputs)
        return

    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            msg = f"Boolean constants disallowed in '{formula_id}'"
            raise FormulaCompilationError(msg)
        if not isinstance(node.value, (int, float)):
            msg = f"Unsupported constant in '{formula_id}'"
            raise FormulaCompilationError(msg)
        return

    if isinstance(node, ast.Name):
        key = _normalise(node.id)
        if key not in name_map:
            # Not a declared input nor a known registry formula: treat as
            # a raw source field the caller supplies at evaluation time.
            source_inputs.add(node.id)
            return
        resolved[node.id] = name_map[key]
        return

    if isinstance(node, ast.BinOp):
        _validate_tree(node.left, formula_id, name_map, functions, resolved, source_inputs)
        _validate_tree(node.right, formula_id, name_map, functions, resolved, source_inputs)
        if not isinstance(
            node.op,
            (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow),
        ):
            msg = f"Unsupported binary operator in '{formula_id}'"
            raise FormulaCompilationError(msg)
        return

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.USub, ast.UAdd)):
            msg = f"Unsupported unary operator in '{formula_id}'"
            raise FormulaCompilationError(msg)
        _validate_tree(node.operand, formula_id, name_map, functions, resolved, source_inputs)
        return

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in functions:
            msg = f"Disallowed function call in '{formula_id}'"
            raise FormulaCompilationError(msg)
        if node.keywords:
            msg = f"Keyword arguments disallowed in '{formula_id}'"
            raise FormulaCompilationError(msg)
        for arg in node.args:
            _validate_tree(arg, formula_id, name_map, functions, resolved, source_inputs)
        return

    msg = f"Disallowed AST node {type(node).__name__} in '{formula_id}'"
    raise FormulaCompilationError(msg)
