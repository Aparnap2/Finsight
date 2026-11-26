"""Error-hygiene guards for the API layer.

``ERROR_CATALOG.md`` §0 forbids two specific failure modes:

* leaking internal detail (exception text, SQL, paths) to the client, and
* swallowing a failure without recording its trace.

Both are easy to reintroduce in a review. These guards read the API source as
an AST, so they cannot be dodged by renaming a handler or moving a file.

Scope: ``apps/api/``. Agents, finance and shared layers are covered by their
own contracts; this guard is about the HTTP boundary where leakage is
externally observable.
"""

from __future__ import annotations

import ast
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[3] / "apps" / "api"

_LOG_METHODS = frozenset({"exception", "error", "critical"})


def _api_modules() -> list[Path]:
    return sorted(p for p in _API_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


def _http_exception_calls(node: ast.AST) -> list[ast.Call]:
    """Every ``HTTPException(...)`` construction below ``node``."""
    return [
        n
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "HTTPException"
    ]


def _is_server_error(call: ast.Call) -> bool:
    for keyword in call.keywords:
        if keyword.arg != "status_code":
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and isinstance(value.value, int):
            return value.value >= 500
    return False


def _detail_keyword(call: ast.Call) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == "detail":
            return keyword.value
    return None


def _mentions_exception_value(expr: ast.expr) -> bool:
    """True when ``expr`` interpolates or stringifies the caught exception."""
    for node in ast.walk(expr):
        # f"...{e}" — formatted value derived from the exception name.
        if isinstance(node, ast.FormattedValue):
            return True
        # str(e) / repr(e) / format(e)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"str", "repr", "format"}
        ):
            return True
    return False


def test_no_server_error_response_echoes_the_exception() -> None:
    """A 5xx ``detail`` must never contain the exception value."""
    offenders: list[str] = []
    for path in _api_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in _http_exception_calls(tree):
            if not _is_server_error(call):
                continue
            detail = _detail_keyword(call)
            if detail is None:
                continue
            if _mentions_exception_value(detail):
                offenders.append(f"{path.name}:{call.lineno}")
    assert offenders == [], (
        "5xx responses must return a generic message; log the exception instead: "
        + ", ".join(offenders)
    )


def test_every_server_error_is_logged_with_its_trace() -> None:
    """A 5xx raised from an ``except`` block must log before returning."""
    offenders: list[str] = []
    for path in _api_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for handler in ast.walk(tree):
            if not isinstance(handler, ast.ExceptHandler):
                continue
            raises_5xx = any(_is_server_error(c) for c in _http_exception_calls(handler))
            if not raises_5xx:
                continue
            logs = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr in _LOG_METHODS
                for statement in handler.body
                for n in ast.walk(statement)
            )
            if not logs:
                offenders.append(f"{path.name}:{handler.lineno}")
    assert offenders == [], (
        "a swallowed failure is a defect; log with logger.exception(...) before "
        "returning 5xx: " + ", ".join(offenders)
    )


def test_no_except_handler_is_a_silent_pass() -> None:
    """``except ...: pass`` hides the failure entirely."""
    offenders: list[str] = []
    for path in _api_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for handler in ast.walk(tree):
            if isinstance(handler, ast.ExceptHandler) and all(
                isinstance(statement, ast.Pass) for statement in handler.body
            ):
                offenders.append(f"{path.name}:{handler.lineno}")
    assert offenders == [], "except ...: pass swallows the failure: " + ", ".join(offenders)


def test_guard_scope_is_not_empty() -> None:
    """Negative control: the guard must actually be reading API modules."""
    modules = _api_modules()
    assert any(p.name == "reconciliation_routes.py" for p in modules)
    assert len(modules) >= 5
