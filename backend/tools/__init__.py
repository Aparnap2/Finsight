from importlib import import_module

_THUNK_CACHE: dict[str, object] = {}


def __getattr__(name: str) -> object:
    """Lazy import of tool modules — avoids pulling in heavy deps (sqlalchemy etc.)
    when only ToolResult or a single tool is needed."""
    if name in _THUNK_CACHE:
        return _THUNK_CACHE[name]

    module_map: dict[str, str] = {
        "query_gl_detail": "backend.tools.gl_tools",
        "query_trial_balance": "backend.tools.gl_tools",
        "query_headcount": "backend.tools.headcount_tools",
        "query_vendor_spend": "backend.tools.vendor_tools",
        "query_sales_pipeline": "backend.tools.pipeline_tools",
        "query_prior_commentary": "backend.tools.rag_tools",
        "query_policy_document": "backend.tools.rag_tools",
        "ToolResult": "backend.tools.tool_result",
    }
    if name not in module_map:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    mod = import_module(module_map[name])
    attr = getattr(mod, name)
    _THUNK_CACHE[name] = attr
    return attr


__all__ = [
    "query_gl_detail",
    "query_trial_balance",
    "query_headcount",
    "query_vendor_spend",
    "query_sales_pipeline",
    "query_prior_commentary",
    "query_policy_document",
    "ToolResult",
]
