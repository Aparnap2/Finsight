"""Quarantined: legacy ``finance.llm`` provider stack (REMOVED).

The provider modules (client, model_router, structured_generation,
response_validator, telemetry) were unreachable from all executable paths —
imported only by each other and dead-code tests — and have been deleted.

Live LLM access goes through ``shared.utils.llm_client`` (used by
``agents/`` and ``apps/``). Do NOT resurrect provider logic in this package;
extend the shared client instead.
"""
