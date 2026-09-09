"""Guarded execution boundary: approved proposal to verified books.

``Executor.run`` carries one ``APPROVED`` aggregate through the frozen
17-step order — integrity, guard, policy, idempotency, intent persist,
bounded adapter write, result persist, visibility poll, P1 post-verify,
terminal close-or-escalate — persisting before every side effect and
never closing on adapter success alone.

Only the Python standard library plus ``finance.*`` and ``shared.*``
are used. This package imports nothing from ``apps/`` or ``agents/``.
"""

from finance.execution.execution_result import (
    ExecutionResult,
    ExecutionResultStatus,
    PostVerifyVerdict,
)
from finance.execution.executor import Executor, execution_id_for

__all__ = [
    "ExecutionResult",
    "ExecutionResultStatus",
    "Executor",
    "PostVerifyVerdict",
    "execution_id_for",
]
