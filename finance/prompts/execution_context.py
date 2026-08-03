"""Execution context for prompt invocations.

Captures metadata about a single prompt execution including timing,
token usage, and success status.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ExecutionContext(BaseModel):
    """Metadata for a single prompt execution.

    Tracks which prompt was called, with which model and provider,
    how long it took, how many tokens were consumed, and whether
    it succeeded.
    """

    prompt_name: str
    prompt_version: str
    model: str
    provider: str
    variables: dict[str, Any]
    started_at: datetime
    completed_at: datetime | None = None
    token_count: int | None = None
    latency_ms: int | None = None
    success: bool | None = None
