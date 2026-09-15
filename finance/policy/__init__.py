"""Finance execution policy: deterministic pre-execution gate.

``check`` admits only an ``APPROVED`` record whose pinned triple exactly
matches the live proposal, whose stored hash still verifies, whose
action is sandbox-bookable, and whose recomputed amount fits the
threshold with balanced journal legs. Anything else is denied before
any adapter call.

Only the Python standard library plus ``finance.*`` are used. This
package imports nothing from ``apps/``, ``agents/``, or ``shared/``.
"""

from finance.policy.execution_policy import PolicyDecision, check

__all__ = ["PolicyDecision", "check"]
