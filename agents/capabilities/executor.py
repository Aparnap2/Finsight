"""Deterministic capability executor (P4.3).

:class:`CapabilityExecutor` executes a pre-validated :class:`InvestigationPlan`
in deterministic code after verifier approval. It re-checks the plan shape
(allowlist membership, string-only bounded args, call count bound, dense
ordering), rejects cross-tenant identifiers and forbidden arg content for the
whole run with zero partial execution, then executes in ``order_index`` order
with per-call timeout accounting. Adapter 5xx and per-call errors become
bounded :class:`CapabilityFailure` records carried as zero-row ``ToolResult``
evidence; only fatal configuration (bad bundle, unknown capability, whole-run
rejection) raises :class:`ExecutorRejectedError`.

Identical ``(capability, args)`` pairs planned twice are executed once: the
second outcome shares the first ``ToolResult`` with ``deduped=True`` plus an
audit note. Executing the same deterministic read twice is forbidden.

The executor returns evidence only: no financial mutation, no state
transitions, no proposals. Provider-independent (no Groq/OpenAI imports);
``agents`` imports ``shared`` plus ``finance`` read paths only.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Mapping

from agents.capabilities.capabilities import AdapterBundle
from agents.capabilities.registry import CapabilityRegistry
from agents.capabilities.types import (
    MAX_EXECUTOR_CALLS,
    CapabilityOutcome,
    CapabilityRequest,
    ExecutorRejectedError,
    args_fingerprint,
)
from agents.investigation.plan import (
    FROZEN_CAPABILITY_ALLOWLIST,
    MAX_ARG_KEY_CHARS,
    MAX_ARG_VALUE_CHARS,
    MAX_ARGS_PER_CALL,
    MAX_CAPABILITY_CALLS,
    InvestigationPlan,
)
from finance.accounting.errors import EntryNotFoundError, TransientError
from shared.models.degraded_mode import DegradedMode
from shared.utils.tools.tool_result import (
    ToolResult,
    compute_query_fingerprint,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 5.0
"""Default per-call timeout budget (seconds)."""

_TENANT_ARG_KEYS = frozenset({"tenant_id", "tenant"})
"""Arg keys treated as tenant scope declarations."""

_URL_RE = re.compile(r"(https?://|wss?://|ftp://|://|www\.)", re.IGNORECASE)
"""Rejects credentials-by-URL and exfiltration targets in args."""

_SQL_RE = re.compile(
    r"\b(select|insert|update|delete|drop|union|alter|create|exec(ute)?|"
    r"execute_sql|read_database|write_database|call_api)\b|--|/\*|\*/",
    re.IGNORECASE,
)
"""Rejects SQL / generic-tool escape hatches in args."""

_CREDENTIAL_RE = re.compile(
    r"(api[_-]?key|secret|password|passwd|pwd|bearer|private[_-]?key|"
    r"credential|connection[_-]?string|postgres(ql)?://|mysql://|sk-[a-z0-9])",
    re.IGNORECASE,
)
"""Rejects secrets and connection handles in args."""


def _check_forbidden_args(args: Mapping[str, str], *, order_index: int) -> None:
    """Reject URLs, SQL/tool escapes, and credential patterns in args.

    Raises:
        ExecutorRejectedError: On the first forbidden key or value.
    """
    for key, value in args.items():
        for label, text in (("key", key), (f"args[{key!r}]", value)):
            if _URL_RE.search(text):
                raise ExecutorRejectedError(
                    f"call[{order_index}] {label} carries a URL; rejected whole run."
                )
            if _SQL_RE.search(text):
                raise ExecutorRejectedError(
                    f"call[{order_index}] {label} carries SQL/tool-escape text; rejected whole run."
                )
            if _CREDENTIAL_RE.search(text):
                raise ExecutorRejectedError(
                    f"call[{order_index}] {label} carries credential text; rejected whole run."
                )


def _failure_result(
    capability: str,
    tenant_id: str,
    args: Mapping[str, str],
    *,
    error_code: str,
) -> ToolResult:
    """Build a bounded per-call failure ``ToolResult`` (zero rows, data only)."""
    return ToolResult(
        data=[],
        row_count=0,
        coverage_pct=0.0,
        quality_score=0.0,
        freshness_seconds=None,
        schema_version="1.0",
        source_diversity=1,
        source_type="financial_fact",
        retrieval_scope="factual",
        tenant_id=tenant_id,
        required_filters_present=True,
        insufficient_data=True,
        degraded_mode=DegradedMode.LOW_COVERAGE.value,
        query_fingerprint=compute_query_fingerprint(capability, **dict(args)),
    )


class CapabilityExecutor:
    """Deterministic evidence-only executor over a frozen registry."""

    def __init__(
        self,
        bundle: AdapterBundle,
        *,
        max_calls: int = MAX_EXECUTOR_CALLS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Bind the read-only bundle and enforce executor budgets.

        Args:
            bundle: Read-only stores backing the five closed capabilities.
            max_calls: Per-run call ceiling (must be 1..8, never above the
                frozen ``MAX_CAPABILITY_CALLS``).
            timeout_seconds: Per-call timeout budget (positive, finite).

        Raises:
            ExecutorRejectedError: On fatal misconfiguration (bad budgets).
            TypeError: If ``bundle`` is not an :class:`AdapterBundle`.
        """
        if not isinstance(max_calls, int) or isinstance(max_calls, bool):
            raise ExecutorRejectedError("max_calls must be an int.")
        if max_calls < 1 or max_calls > MAX_CAPABILITY_CALLS or max_calls > MAX_EXECUTOR_CALLS:
            raise ExecutorRejectedError(
                f"max_calls must be 1..{MAX_CAPABILITY_CALLS}, got {max_calls}."
            )
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not (timeout_seconds > 0)
            or timeout_seconds != timeout_seconds
            or timeout_seconds in (float("inf"), float("-inf"))
        ):
            raise ExecutorRejectedError("timeout_seconds must be a positive finite number.")
        self._registry = CapabilityRegistry(bundle)
        self._max_calls = max_calls
        self._timeout_seconds = float(timeout_seconds)

    @property
    def registry(self) -> CapabilityRegistry:
        """Return the frozen capability registry."""
        return self._registry

    @property
    def max_calls(self) -> int:
        """Return the per-run call ceiling."""
        return self._max_calls

    @property
    def timeout_seconds(self) -> float:
        """Return the per-call timeout budget in seconds."""
        return self._timeout_seconds

    def execute(self, plan: InvestigationPlan, tenant_id: str) -> tuple[CapabilityOutcome, ...]:
        """Execute a pre-validated plan deterministically; evidence only.

        Args:
            plan: Candidate plan whose shape is re-checked here (allowlist,
                string-only bounded args, call count, dense ordering).
            tenant_id: Tenant scope every lookup executes under.

        Returns:
            One :class:`CapabilityOutcome` per planned call, in
            ``order_index`` order; duplicate identical calls share the first
            ``ToolResult`` with ``deduped=True`` plus an audit note.

        Raises:
            ExecutorRejectedError: Whole-run rejection (bad shape, unknown
                capability, tenant mismatch, forbidden args). Zero
                capabilities execute on this path.
            TypeError: If ``plan`` is not an :class:`InvestigationPlan`.
        """
        if not isinstance(plan, InvestigationPlan):
            raise TypeError(f"plan must be an InvestigationPlan, got {type(plan).__name__}.")
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ExecutorRejectedError("tenant_id must be a non-blank string.")
        self._recheck_shape(plan)
        ordered = sorted(plan.capability_calls, key=lambda call: call.order_index)
        self._recheck_run_gates(ordered, tenant_id)
        cache: dict[str, ToolResult] = {}
        first_index: dict[str, int] = {}
        outcomes: list[CapabilityOutcome] = []
        for call in ordered:
            fingerprint = args_fingerprint(call.capability, call.args)
            if fingerprint in cache:
                shared = cache[fingerprint]
                outcomes.append(
                    CapabilityOutcome(
                        capability=call.capability,
                        order_index=call.order_index,
                        tenant_id=tenant_id,
                        result=shared,
                        success=shared.row_count > 0,
                        error_code=None if shared.row_count > 0 else "DEDUPED_EMPTY",
                        deduped=True,
                        audit_note=(
                            f"deduped: shared execution of order_index={first_index[fingerprint]}"
                        ),
                    )
                )
                continue
            outcome = self._execute_once(
                call.capability, dict(call.args), tenant_id, call.order_index
            )
            cache[fingerprint] = outcome.result
            first_index[fingerprint] = call.order_index
            outcomes.append(outcome)
        outcomes.sort(key=lambda item: item.order_index)
        logger.info("executor run tenant=%s calls=%d", tenant_id, len(outcomes))
        return tuple(outcomes)

    def _recheck_shape(self, plan: InvestigationPlan) -> None:
        """Re-check the pre-validated plan shape (defense in depth).

        Raises:
            ExecutorRejectedError: On call-count, allowlist, args-shape, or
                ordering violations.
        """
        calls = plan.capability_calls
        if len(calls) < 1 or len(calls) > self._max_calls:
            raise ExecutorRejectedError(
                f"plan carries {len(calls)} calls; executor bound is {self._max_calls}."
            )
        if len(calls) > MAX_CAPABILITY_CALLS:
            raise ExecutorRejectedError(
                f"plan carries {len(calls)} calls; frozen max is {MAX_CAPABILITY_CALLS}."
            )
        allowed = frozenset(FROZEN_CAPABILITY_ALLOWLIST)
        for position, call in enumerate(calls):
            if call.capability not in allowed:
                raise ExecutorRejectedError(
                    f"call[{position}] names {call.capability!r} outside the frozen allowlist."
                )
            if call.order_index != position:
                raise ExecutorRejectedError(
                    f"call[{position}].order_index is {call.order_index}; "
                    f"must equal its position ({position})."
                )
            if len(call.args) > MAX_ARGS_PER_CALL:
                raise ExecutorRejectedError(
                    f"call[{position}] holds {len(call.args)} args; max is {MAX_ARGS_PER_CALL}."
                )
            for key, value in call.args.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    raise ExecutorRejectedError(f"call[{position}] args must be string-only.")
                if not key.strip():
                    raise ExecutorRejectedError(f"call[{position}] has a blank args key.")
                if len(key) > MAX_ARG_KEY_CHARS:
                    raise ExecutorRejectedError(f"call[{position}] args key exceeds bound.")
                if len(value) > MAX_ARG_VALUE_CHARS:
                    raise ExecutorRejectedError(f"call[{position}] args value exceeds bound.")

    def _recheck_run_gates(
        self,
        ordered: list[object],
        tenant_id: str,
    ) -> None:
        """Enforce tenant scope and forbidden-content gates before execution.

        Raises:
            ExecutorRejectedError: On cross-tenant identifiers or forbidden
                URL/SQL/credential content. Zero capabilities execute after.
        """
        from agents.investigation.plan import CapabilityCall

        for call in ordered:
            assert isinstance(call, CapabilityCall)
            for key, value in call.args.items():
                if key.strip().lower() in _TENANT_ARG_KEYS and value.strip() != tenant_id:
                    raise ExecutorRejectedError(
                        f"call[{call.order_index}] declares tenant {value!r}; "
                        f"run scope is {tenant_id!r}: rejected whole run."
                    )
            _check_forbidden_args(call.args, order_index=call.order_index)

    def _execute_once(
        self, capability: str, args: dict[str, str], tenant_id: str, order_index: int
    ) -> CapabilityOutcome:
        """Run one capability with timeout accounting; failures stay bounded."""
        request = CapabilityRequest(
            capability=capability,  # type: ignore[arg-type]
            args=args,
            tenant_id=tenant_id,
            round_index=0,
        )
        target = self._registry.get(capability)
        started = time.monotonic()
        try:
            result = target.run(request)
        except TransientError as exc:
            logger.info("capability 5xx capability=%s order=%d", capability, order_index)
            result = _failure_result(capability, tenant_id, args, error_code="TRANSIENT_5XX")
            return CapabilityOutcome(
                capability=capability,  # type: ignore[arg-type]
                order_index=order_index,
                tenant_id=tenant_id,
                result=result,
                success=False,
                error_code="TRANSIENT_5XX",
                audit_note=f"adapter 5xx bounded: {exc}",
            )
        except (EntryNotFoundError, LookupError) as exc:
            logger.info("capability miss capability=%s order=%d", capability, order_index)
            result = _failure_result(capability, tenant_id, args, error_code="NOT_FOUND")
            return CapabilityOutcome(
                capability=capability,  # type: ignore[arg-type]
                order_index=order_index,
                tenant_id=tenant_id,
                result=result,
                success=False,
                error_code="NOT_FOUND",
                audit_note=f"lookup miss bounded: {exc}",
            )
        except ExecutorRejectedError:
            raise
        except Exception as exc:
            logger.info("capability failure capability=%s order=%d", capability, order_index)
            result = _failure_result(capability, tenant_id, args, error_code="CAPABILITY_FAILURE")
            return CapabilityOutcome(
                capability=capability,  # type: ignore[arg-type]
                order_index=order_index,
                tenant_id=tenant_id,
                result=result,
                success=False,
                error_code="CAPABILITY_FAILURE",
                audit_note=f"capability failure bounded: {type(exc).__name__}",
            )
        elapsed = time.monotonic() - started
        if elapsed > self._timeout_seconds:
            logger.info("capability timeout capability=%s order=%d", capability, order_index)
            result = _failure_result(capability, tenant_id, args, error_code="TIMEOUT")
            return CapabilityOutcome(
                capability=capability,  # type: ignore[arg-type]
                order_index=order_index,
                tenant_id=tenant_id,
                result=result,
                success=False,
                error_code="TIMEOUT",
                audit_note=f"per-call timeout exceeded ({elapsed:.3f}s) bounded",
            )
        if not isinstance(result, ToolResult):
            result = _failure_result(capability, tenant_id, args, error_code="BAD_SHAPE")
            return CapabilityOutcome(
                capability=capability,  # type: ignore[arg-type]
                order_index=order_index,
                tenant_id=tenant_id,
                result=result,
                success=False,
                error_code="BAD_SHAPE",
                audit_note="capability returned non-ToolResult; quarantined",
            )
        if result.tenant_id != tenant_id:
            result = _failure_result(capability, tenant_id, args, error_code="TENANT_MISMATCH")
            return CapabilityOutcome(
                capability=capability,  # type: ignore[arg-type]
                order_index=order_index,
                tenant_id=tenant_id,
                result=result,
                success=False,
                error_code="TENANT_MISMATCH",
                audit_note="capability tenant mismatch; quarantined",
            )
        return CapabilityOutcome(
            capability=capability,  # type: ignore[arg-type]
            order_index=order_index,
            tenant_id=tenant_id,
            result=result,
            success=result.row_count > 0,
            error_code=None if result.row_count > 0 else "NO_RESULT",
            audit_note="" if result.row_count > 0 else "no-result evidence",
        )


__all__ = ["DEFAULT_TIMEOUT_SECONDS", "CapabilityExecutor"]
