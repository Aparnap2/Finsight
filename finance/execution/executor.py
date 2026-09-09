"""Guarded executor: approved proposal to verified books (v2 resolution).

``Executor.run`` carries one ``APPROVED`` aggregate through the frozen
order — execution-record replay, idempotency conflict check, fresh
``APPROVED`` state gate, triple-plus-hash integrity, guard, policy,
ledger record, ``EXECUTING`` intent persist (committed before any
adapter write), bounded same-key adapter writes, result persist,
``POST_VERIFYING`` commit, visibility poll, P1 post-verify, terminal
close-or-escalate — persisting before every side effect and never
closing on adapter success alone.

Replay and crash recovery: the stable ``exec_<sha16(key)>`` identity
addresses one ``ExecutionRow`` per idempotency key, so a restart with
the same key returns the prior outcome (complete row) or recovers the
booked entry by scanning adapter calls by key (intent row without a
result) instead of blindly re-executing. Same-key adapter conflicts
perform no write.

Only the Python standard library plus ``finance.*`` and ``shared.*``
are used. This module imports nothing from ``apps/`` or ``agents/``.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from finance.accounting.commands import CorrectingEntryCommand, JournalLine
from finance.accounting.errors import AccountingError, EntryNotFoundError, TransientError
from finance.exceptions.errors import ConcurrencyConflictError
from finance.exceptions.models import ExceptionAuditRow, ExceptionRow
from finance.exceptions.repository import ExceptionRepository
from finance.exceptions.states import ExceptionState
from finance.execution.execution_result import (
    ExecutionResult,
    ExecutionResultStatus,
    PostVerifyVerdict,
)
from finance.execution.models import Base as ExecutionBase
from finance.execution.models import ExecutionRow
from finance.policy.execution_policy import DEFAULT_AMOUNT_THRESHOLD
from finance.policy.execution_policy import check as policy_check
from finance.proposals.builder import verify_hash
from finance.proposals.proposal import ProposalAction
from finance.reconciliation.models import (
    ExceptionCode,
    PaymentRecord,
    ReconciliationOutcome,
)
from finance.reconciliation.reconciler import reconcile
from finance.reconciliation.tolerances import ReconciliationTolerance
from shared.safety.execution_guard import ExecutionCommand, ExecutionGuard
from shared.safety.idempotency import IdempotencyStore

logger = logging.getLogger(__name__)

#: Zero in exact Decimal arithmetic for the post-verify tolerance default.
_ZERO = Decimal("0")

#: Upper bound on same-key adapter write attempts (transient 5xx retries).
_MAX_ADAPTER_WRITES = 3

#: Zero-tolerance oracle for injected-leg post-verification (any drift breaks).
_ZERO_TOLERANCE = ReconciliationTolerance(absolute=Decimal("0"), percent=Decimal("0"))


def execution_id_for(idempotency_key: str) -> str:
    """Derive a stable execution id from the caller-supplied key.

    Args:
        idempotency_key: Caller-supplied idempotency key (non-empty).

    Returns:
        ``exec_<16 hex>`` stable for identical keys, so replays address
        the same record instead of minting duplicates.
    """
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError("Field 'idempotency_key' must be a non-empty string.")
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"exec_{digest[:16]}"


def _utcnow() -> datetime:
    """Return a tz-aware UTC timestamp for CAS audit rows."""
    return datetime.now(UTC)


class Executor:
    """Fourteen-step guarded executor over the sandbox accounting boundary.

    The executor owns no state of its own beyond configuration: every
    intent, write outcome, and terminal verdict is persisted to the
    shared engine before the next side effect, so fresh handles resume
    from the database alone.
    """

    def __init__(
        self,
        adapter: Any,
        engine: Engine,
        *,
        clock: Any | None = None,
        ledger_leg: PaymentRecord | None = None,
        processor_leg: PaymentRecord | None = None,
        expected_post_verify: str | None = None,
        max_polls: int = 10,
        amount_threshold: Decimal = DEFAULT_AMOUNT_THRESHOLD,
    ) -> None:
        """Bind the executor to an adapter, engine, and verification config.

        Args:
            adapter: Sandbox accounting boundary (deterministic, injected).
            engine: SQLAlchemy engine shared with ``ExceptionRepository``
                and the idempotency ledger.
            clock: Injectable ticker advanced once per visibility miss
                (fake clocks in tests; never slept on, only ticked).
            ledger_leg: Injected observed post-write books for P1 verify.
            processor_leg: Injected expected books for P1 verify.
            expected_post_verify: Accepted for fixture vocabulary only;
                it never forces the verdict, which always comes from an
                independent check.
            max_polls: Upper bound on ``get_entry`` visibility reads.
            amount_threshold: Exclusive policy ceiling (Decimal-only).
        """
        if adapter is None:
            raise ValueError("Field 'adapter' must be provided.")
        if isinstance(max_polls, bool) or not isinstance(max_polls, int):
            raise TypeError("Field 'max_polls' must be an int.")
        if max_polls < 1:
            raise ValueError("Field 'max_polls' must be >= 1.")
        if isinstance(amount_threshold, (bool, float)):
            raise TypeError("amount_threshold must be Decimal.")
        if not isinstance(amount_threshold, Decimal) or not amount_threshold.is_finite():
            raise ValueError("amount_threshold must be a finite Decimal.")
        if amount_threshold <= _ZERO:
            raise ValueError("amount_threshold must be positive.")
        self._adapter = adapter
        self._engine = engine
        self._clock = clock
        self._ledger_leg = ledger_leg
        self._processor_leg = processor_leg
        self._expected_post_verify = expected_post_verify
        self._max_polls = max_polls
        self._amount_threshold = amount_threshold
        self.unsafe_action_count: int = 0
        self._repo = ExceptionRepository(engine)
        self._store = IdempotencyStore(engine)
        ExecutionBase.metadata.create_all(engine)

    def run(
        self,
        approved_snapshot: Any,
        proposal: Any,
        approval: Any,
        idempotency_key: str,
    ) -> ExecutionResult:
        """Execute one approved proposal to a verified terminal outcome.

        Args:
            approved_snapshot: Caller-held ``APPROVED`` aggregate view
                (the fresh row is re-read; a stale view never gates).
            proposal: Live proposal draft carrying the recomputed amount.
            approval: Terminal HITL record pinning the proposal triple.
            idempotency_key: Caller-supplied key owning this execution.

        Returns:
            The frozen ``ExecutionResult`` — ``SUCCEEDED`` + ``MATCHED``
            only when the independent post-verify passed (exception
            ``CLOSED``), ``FAILED`` + ``MISMATCH`` on any write or
            verification break (exception ``ESCALATED``), ``REJECTED`` +
            ``MISMATCH`` on any pre-write refusal (no state change).
        """
        execution_id = execution_id_for(idempotency_key)
        exception_id = str(getattr(approved_snapshot, "exception_id", ""))

        # (1) Execution-record replay fast-path: a prior row owns the key.
        # Runs BEFORE the APPROVED state gate so crash restarts passing a
        # stale APPROVED snapshot against CLOSED rows return the prior.
        prior = self._load_row(idempotency_key)
        if prior is not None and prior.result is not None and prior.post_verify is not None:
            logger.info("execution replay key=%s id=%s", idempotency_key, prior.execution_id)
            return self._result_from_row(prior)

        payload_hash = str(getattr(proposal, "content_hash", ""))

        # (2) Store conflict check: same key, differing hash performs no write.
        seen_hash = self._store.payload_hash_for(idempotency_key)
        if seen_hash is not None and seen_hash != payload_hash:
            logger.warning("idempotency conflict key=%s: no write performed", idempotency_key)
            return self._rejected(execution_id, idempotency_key, exception_id)

        # (3) Fresh APPROVED state gate off a re-read row, never the snapshot.
        fresh = self._repo.get(exception_id) if exception_id else None
        if fresh is None or fresh.state is not ExceptionState.APPROVED:
            logger.warning("execution refused key=%s: exception not APPROVED", idempotency_key)
            return self._rejected(execution_id, idempotency_key, exception_id)

        # (4) Triple-plus-hash integrity: pinned triple matches, hash verifies.
        if not self._integrity_ok(proposal, approval):
            self.unsafe_action_count += 1
            logger.warning("execution refused key=%s: triple/hash skew", idempotency_key)
            return self._rejected(execution_id, idempotency_key, fresh.exception_id)

        # (5) Sandbox guard tripwire over the pinned command.
        guard = ExecutionGuard().check(
            ExecutionCommand(
                exception_id=fresh.exception_id,
                proposal_id=str(getattr(proposal, "proposal_id", "")),
                approval_id=str(getattr(approval, "approval_id", "")),
                idempotency_key=idempotency_key,
                amount=getattr(proposal, "amount", Decimal("0")),
            )
        )
        if not guard.allowed:
            self.unsafe_action_count += guard.unsafe
            logger.warning("execution refused key=%s: guard denied", idempotency_key)
            return self._rejected(execution_id, idempotency_key, fresh.exception_id)

        # (6) Deterministic finance policy gate over (proposal, approval).
        decision = policy_check(proposal, approval, amount_threshold=self._amount_threshold)
        if not decision.allowed:
            self.unsafe_action_count += 1
            logger.warning("execution refused key=%s: policy denied", idempotency_key)
            return self._rejected(execution_id, idempotency_key, fresh.exception_id)

        # (7) Bind the key to this payload hash (identical re-record is a no-op).
        self._store.record(idempotency_key, payload_hash)

        command = self._build_command(fresh, proposal, execution_id)

        if prior is not None:
            # Crash recovery: an intent row exists with no terminal outcome.
            # Recover the booked entry by scanning adapter calls by key and
            # never blindly re-execute; same-key rewrites replay, not duplicate.
            live = self._repo.get(fresh.exception_id)
            if live is None:
                return self._rejected(execution_id, idempotency_key, fresh.exception_id)
            entry_id = self._scan_adapter_calls(idempotency_key)
            entry = None
            if entry_id is None and command is not None:
                entry = self._bounded_write(command, idempotency_key)
                if entry is None:
                    return self._mark_failed(live, execution_id, idempotency_key, None)
                entry_id = str(entry.entry_id)
            self._update_row(idempotency_key, external_reference=entry_id)
            if live.state is ExceptionState.EXECUTING:
                live = self._cas(live, ExceptionState.POST_VERIFYING, actor="executor")
            return self._verify_and_close(live, execution_id, idempotency_key, proposal)

        if command is None:
            # Policy-admitted but adapter-unbookable action: persist intent,
            # then fail closed (no adapter write exists for this action).
            live = self._persist_intent(
                fresh, execution_id, idempotency_key, payload_hash, proposal
            )
            return self._mark_failed(live, execution_id, idempotency_key, None)

        # (8) Persist EXECUTING intent row + COMMIT before any adapter write.
        live = self._persist_intent(fresh, execution_id, idempotency_key, payload_hash, proposal)

        # (9) Bounded same-key adapter writes (transient 5xx retries only).
        entry = self._bounded_write(command, idempotency_key)
        if entry is None:
            return self._mark_failed(live, execution_id, idempotency_key, None)

        # (10) Persist the booked write outcome before verification.
        self._update_row(idempotency_key, external_reference=str(entry.entry_id))

        # (11) POST_VERIFYING + COMMIT: verification runs inside this state.
        live = self._cas(live, ExceptionState.POST_VERIFYING, actor="executor")
        return self._verify_and_close(live, execution_id, idempotency_key, proposal)

    def _verify_and_close(
        self,
        live: Any,
        execution_id: str,
        idempotency_key: str,
        proposal: Any,
    ) -> ExecutionResult:
        """Poll visibility, post-verify, and drive the terminal CAS chain.

        Args:
            live: Aggregate at ``POST_VERIFYING`` (or ``EXECUTING`` on the
                recovery path, which is advanced first).
            execution_id: Stable execution identity for this key.
            idempotency_key: Caller-supplied key owning this execution.
            proposal: Live proposal draft carrying the expected amount.

        Returns:
            ``SUCCEEDED`` + ``MATCHED`` (exception ``CLOSED``) on an
            independent match, else ``FAILED`` + ``MISMATCH`` (escalated).
        """
        if live.state is ExceptionState.EXECUTING:
            live = self._cas(live, ExceptionState.POST_VERIFYING, actor="executor")
        row = self._load_row(idempotency_key)
        entry_id = row.external_reference if row is not None else None
        observed = self._poll(entry_id) if entry_id else None
        matched = self._post_verify(proposal, observed)
        if matched:
            # (14a) MATCHED -> EXECUTION_VERIFIED -> CLOSED.
            self._update_row(
                idempotency_key,
                result=ExecutionResultStatus.SUCCEEDED.value,
                post_verify=PostVerifyVerdict.MATCHED.value,
            )
            live = self._cas(live, ExceptionState.EXECUTION_VERIFIED, actor="executor")
            live = self._cas(live, ExceptionState.CLOSED, actor="executor")
            logger.info("execution verified key=%s id=%s", idempotency_key, execution_id)
            return ExecutionResult(
                execution_id=execution_id,
                result=ExecutionResultStatus.SUCCEEDED,
                external_reference=entry_id,
                post_verify=PostVerifyVerdict.MATCHED,
                idempotency_key=idempotency_key,
                exception_id=live.exception_id,
            )
        # (14b) Any mismatch fails and escalates; adapter success never closes.
        return self._mark_failed(live, execution_id, idempotency_key, entry_id)

    def _mark_failed(
        self,
        live: Any,
        execution_id: str,
        idempotency_key: str,
        entry_id: str | None,
    ) -> ExecutionResult:
        """Persist ``FAILED``/``MISMATCH`` and CAS through ``ESCALATED``.

        Args:
            live: Current aggregate (``EXECUTING`` or ``POST_VERIFYING``).
            execution_id: Stable execution identity for this key.
            idempotency_key: Caller-supplied key owning this execution.
            entry_id: Booked adapter entry id, if a write succeeded.

        Returns:
            The frozen ``FAILED`` + ``MISMATCH`` result.
        """
        self._update_row(
            idempotency_key,
            result=ExecutionResultStatus.FAILED.value,
            external_reference=entry_id,
            post_verify=PostVerifyVerdict.MISMATCH.value,
        )
        if live.state in (ExceptionState.EXECUTING, ExceptionState.POST_VERIFYING):
            live = self._cas(live, ExceptionState.FAILED, actor="executor")
        if live.state is ExceptionState.FAILED:
            live = self._cas(live, ExceptionState.ESCALATED, actor="executor")
        logger.warning("execution failed key=%s id=%s", idempotency_key, execution_id)
        return ExecutionResult(
            execution_id=execution_id,
            result=ExecutionResultStatus.FAILED,
            external_reference=entry_id,
            post_verify=PostVerifyVerdict.MISMATCH,
            idempotency_key=idempotency_key,
            exception_id=live.exception_id,
        )

    def _rejected(
        self, execution_id: str, idempotency_key: str, exception_id: str
    ) -> ExecutionResult:
        """Build a pre-write ``REJECTED`` result (no state change, no write).

        Args:
            execution_id: Stable execution identity for this key.
            idempotency_key: Caller-supplied key owning this execution.
            exception_id: Owning exception, possibly empty on early refusal.

        Returns:
            The frozen ``REJECTED`` + ``MISMATCH`` result.
        """
        return ExecutionResult(
            execution_id=execution_id,
            result=ExecutionResultStatus.REJECTED,
            external_reference=None,
            post_verify=PostVerifyVerdict.MISMATCH,
            idempotency_key=idempotency_key,
            exception_id=exception_id,
        )

    def _integrity_ok(self, proposal: Any, approval: Any) -> bool:
        """Check the pinned triple matches and the stored hash verifies.

        Args:
            proposal: Live proposal draft.
            approval: Terminal HITL record pinning the proposal triple.

        Returns:
            True only when the approval triple equals the live proposal
            triple and ``verify_hash`` passes (no drift tolerated).
        """
        try:
            if not verify_hash(proposal):
                return False
            pin_triple = approval.pin_triple() if hasattr(approval, "pin_triple") else None
            live_triple = proposal.pin_triple() if hasattr(proposal, "pin_triple") else None
            if pin_triple is None or live_triple is None:
                return False
            return tuple(pin_triple) == tuple(live_triple)
        except (TypeError, ValueError, AttributeError):
            return False

    def _build_command(
        self, fresh: Any, proposal: Any, execution_id: str
    ) -> CorrectingEntryCommand | None:
        """Build the sandbox correcting-entry command from the proposal.

        Args:
            fresh: Re-read ``APPROVED`` aggregate (tenant + type scope).
            proposal: Live proposal draft (legs + amount).
            execution_id: Stable execution identity (memo lineage).

        Returns:
            The balanced ``CorrectingEntryCommand``, or None when the
            policy-admitted action has no adapter write (e.g. voids,
            which need an entry id the executor never mints).
        """
        if proposal.action is not ProposalAction.CREATE_CORRECTING_ENTRY:
            logger.warning(
                "execution %s: action %r has no adapter write",
                execution_id,
                getattr(proposal, "action", None),
            )
            return None
        exception_type = getattr(fresh, "exception_type", "")
        code = (
            exception_type.value
            if isinstance(exception_type, ExceptionCode)
            else str(exception_type)
        )
        currency = "USD"
        if self._processor_leg is not None:
            currency = self._processor_leg.currency
        elif self._ledger_leg is not None:
            currency = self._ledger_leg.currency
        amount = proposal.amount
        lines = (
            JournalLine(account=proposal.debit_account, debit=amount, credit=Decimal("0")),
            JournalLine(account=proposal.credit_account, debit=Decimal("0"), credit=amount),
        )
        return CorrectingEntryCommand(
            tenant_id=fresh.tenant_id,
            exception_id=fresh.exception_id,
            exception_type=code,
            currency=currency,
            lines=lines,
            source_reference=str(proposal.proposal_id),
            memo=f"execution {execution_id} proposal {proposal.proposal_id}",
        )

    def _bounded_write(self, command: CorrectingEntryCommand, key: str) -> Any | None:
        """Attempt the adapter write at most three times on the same key.

        Args:
            command: Balanced correcting-entry command for the proposal.
            key: Idempotency key reused byte-identically across retries.

        Returns:
            The booked entry, or None when every attempt raised (write
            failures book nothing, so retries never duplicate).
        """
        attempt = 0
        while attempt < _MAX_ADAPTER_WRITES:
            attempt += 1
            try:
                return self._adapter.create_correcting_entry(command, key)
            except TransientError as exc:
                logger.warning("transient 5xx key=%s attempt=%s: %s", key, attempt, exc)
                continue
            except AccountingError as exc:
                logger.warning("adapter refused key=%s: %s", key, exc)
                return None
        logger.warning("adapter attempts exhausted key=%s", key)
        return None

    def _poll(self, entry_id: str) -> Any | None:
        """Poll ``get_entry`` until visible or the poll bound exhausts.

        Args:
            entry_id: Booked adapter entry id under lookup.

        Returns:
            The visible entry, or None when the bound exhausted first
            (a miss never proves a failed write — only an unverified one).
        """
        for _ in range(self._max_polls):
            try:
                return self._adapter.get_entry(entry_id)
            except EntryNotFoundError:
                self._tick_clock()
                continue
        logger.warning("visibility bound exhausted entry=%s", entry_id)
        return None

    def _tick_clock(self) -> None:
        """Advance the injected clock once (never sleeps, never blocks)."""
        advance = getattr(self._clock, "advance", None)
        if callable(advance):
            advance(1)

    def _post_verify(self, proposal: Any, observed: Any | None) -> bool:
        """Independently verify the booked write against expected books.

        With injected legs the unmodified P1 ``reconcile`` oracle decides
        under a zero tolerance (the accepted ``expected_post_verify``
        fixture value never forces this verdict); otherwise the polled
        entry must total exactly the proposal amount with balanced legs.

        Args:
            proposal: Live proposal draft carrying the expected amount.
            observed: Polled adapter entry, or None when invisible.

        Returns:
            True only on an independent ``MATCHED`` (or exact total plus
            balanced legs); every unverified case is a mismatch.
        """
        if self._ledger_leg is not None or self._processor_leg is not None:
            if observed is None:
                return False
            expected = self._processor_leg or _record_from_entry(observed)
            seen = self._ledger_leg or _record_from_entry(observed)
            verdict = reconcile(expected, seen, _ZERO_TOLERANCE)
            return verdict.outcome is ReconciliationOutcome.MATCHED
        if observed is None:
            return False
        if observed.total != proposal.amount:
            return False
        debits = sum((line.debit for line in observed.lines), _ZERO)
        credit_total = sum((line.credit for line in observed.lines), _ZERO)
        return debits == credit_total

    def _scan_adapter_calls(self, key: str) -> str | None:
        """Recover a booked entry id by scanning adapter calls for the key.

        Args:
            key: Idempotency key whose outcome is being recovered.

        Returns:
            The entry id of the latest same-key ``SUCCESS`` call, or None
            when no write for the key is observable.
        """
        calls = getattr(self._adapter, "calls", None)
        if not calls:
            return None
        for call in reversed(list(calls)):
            if getattr(call, "key", None) != key:
                continue
            if str(getattr(call, "outcome", "")) != "SUCCESS":
                continue
            entry_id = getattr(call, "entry_id", None)
            if isinstance(entry_id, str) and entry_id:
                return entry_id
        return None

    def _persist_intent(
        self, fresh: Any, execution_id: str, key: str, payload_hash: str, proposal: Any
    ) -> Any:
        """Atomically CAS to ``EXECUTING`` and persist the intent row.

        The single commit lands the ``execution_id`` on the exception row
        before any adapter call, so spies and crash restarts observe the
        intent.

        Args:
            fresh: Re-read ``APPROVED`` aggregate (CAS predicate source).
            execution_id: Stable execution identity for this key.
            key: Idempotency key (execution record primary key).
            payload_hash: Proposal content hash bound to the key.
            proposal: Live proposal draft (proposal-id pin source).

        Returns:
            The re-read ``EXECUTING`` aggregate.

        Raises:
            ConcurrencyConflictError: If the predicated CAS hits zero rows.
        """
        now = _utcnow()
        with Session(self._engine) as session:
            stmt = (
                update(ExceptionRow)
                .where(
                    ExceptionRow.exception_id == fresh.exception_id,
                    ExceptionRow.state_version == fresh.state_version,
                    ExceptionRow.state == fresh.state.value,
                )
                .values(
                    state=ExceptionState.EXECUTING.value,
                    state_version=ExceptionRow.state_version + 1,
                    execution_id=execution_id,
                    updated_at=now,
                )
            )
            result = session.execute(stmt)
            if result.rowcount != 1:
                session.rollback()
                current = self._repo.get(fresh.exception_id)
                actual = current.state_version if current is not None else -1
                self._audit_outcome(
                    fresh,
                    ExceptionState.EXECUTING.value,
                    "executor",
                    "REJECTED",
                    f"CONCURRENCY_CONFLICT expected={fresh.state_version} actual={actual}",
                    actual_version=actual,
                )
                raise ConcurrencyConflictError(
                    fresh.exception_id,
                    fresh.state_version,
                    actual,
                    detail="atomic CAS UPDATE affected 0 rows",
                )
            session.add(
                ExceptionAuditRow(
                    exception_id=fresh.exception_id,
                    tenant_id=fresh.tenant_id,
                    actor="executor",
                    from_state=fresh.state.value,
                    attempted_state=ExceptionState.EXECUTING.value,
                    expected_version=fresh.state_version,
                    actual_version=fresh.state_version + 1,
                    outcome="APPLIED",
                    reason=f"{fresh.state.value} -> EXECUTING {execution_id}",
                    created_at=now,
                )
            )
            session.add(
                ExecutionRow(
                    idempotency_key=key,
                    execution_id=execution_id,
                    exception_id=fresh.exception_id,
                    proposal_id=str(getattr(proposal, "proposal_id", fresh.exception_id)),
                    payload_hash=payload_hash,
                    result=None,
                    external_reference=None,
                    post_verify=None,
                )
            )
            session.commit()
        logger.info("execution intent key=%s id=%s", key, execution_id)
        refreshed = self._repo.get(fresh.exception_id)
        if refreshed is None:  # pragma: no cover - defensive, row just won CAS
            raise ConcurrencyConflictError(
                fresh.exception_id,
                fresh.state_version,
                -1,
                detail="row vanished after winning CAS",
            )
        return refreshed

    def _cas(self, snapshot: Any, target: ExceptionState, *, actor: str) -> Any:
        """CAS-advance one exception transition predicated on version+state.

        Mirrors the approval service shape: ``repository.apply`` rejects
        non-P3.2 targets, so execution CAS issues the predicated
        ``UPDATE`` directly against ``ExceptionRow``.

        Args:
            snapshot: Caller-held pre-transition view (expected version).
            target: Requested next state (an SM-1 execution edge).
            actor: Caller identity for the audit row.

        Returns:
            The post-transition aggregate re-read from the winning row.

        Raises:
            ConcurrencyConflictError: If the predicated ``UPDATE`` affects
                zero rows (stale version or state). Audited, unmutated.
        """
        now = _utcnow()
        with Session(self._engine) as session:
            stmt = (
                update(ExceptionRow)
                .where(
                    ExceptionRow.exception_id == snapshot.exception_id,
                    ExceptionRow.state_version == snapshot.state_version,
                    ExceptionRow.state == snapshot.state.value,
                )
                .values(
                    state=target.value,
                    state_version=ExceptionRow.state_version + 1,
                    updated_at=now,
                )
            )
            result = session.execute(stmt)
            if result.rowcount == 1:
                session.add(
                    ExceptionAuditRow(
                        exception_id=snapshot.exception_id,
                        tenant_id=snapshot.tenant_id,
                        actor=actor,
                        from_state=snapshot.state.value,
                        attempted_state=target.value,
                        expected_version=snapshot.state_version,
                        actual_version=snapshot.state_version + 1,
                        outcome="APPLIED",
                        reason=f"{snapshot.state.value} -> {target.value}",
                        created_at=now,
                    )
                )
                session.commit()
                logger.info(
                    "execution CAS id=%s %s -> %s",
                    snapshot.exception_id,
                    snapshot.state.value,
                    target.value,
                )
            else:
                session.rollback()
                current = self._repo.get(snapshot.exception_id)
                actual = current.state_version if current is not None else -1
                self._audit_outcome(
                    snapshot,
                    target.value,
                    actor,
                    "REJECTED",
                    f"CONCURRENCY_CONFLICT expected={snapshot.state_version} actual={actual}",
                    actual_version=actual,
                )
                raise ConcurrencyConflictError(
                    snapshot.exception_id,
                    snapshot.state_version,
                    actual,
                    detail="atomic CAS UPDATE affected 0 rows",
                )
        refreshed = self._repo.get(snapshot.exception_id)
        if refreshed is None:  # pragma: no cover - defensive, row just won CAS
            raise ConcurrencyConflictError(
                snapshot.exception_id,
                snapshot.state_version,
                -1,
                detail="row vanished after winning CAS",
            )
        return refreshed

    def _audit_outcome(
        self,
        snapshot: Any,
        attempted_state: str,
        actor: str,
        outcome: str,
        reason: str,
        *,
        actual_version: int | None = None,
    ) -> None:
        """Append one audit fact without mutating the aggregate row."""
        with Session(self._engine) as session:
            session.add(
                ExceptionAuditRow(
                    exception_id=snapshot.exception_id,
                    tenant_id=snapshot.tenant_id,
                    actor=actor,
                    from_state=snapshot.state.value,
                    attempted_state=attempted_state,
                    expected_version=snapshot.state_version,
                    actual_version=(
                        actual_version if actual_version is not None else snapshot.state_version
                    ),
                    outcome=outcome,
                    reason=reason,
                    created_at=_utcnow(),
                )
            )
            session.commit()

    def _load_row(self, key: str) -> ExecutionRow | None:
        """Read one execution record by key (replay/resume path)."""
        with Session(self._engine) as session:
            row = session.get(ExecutionRow, key)
            if row is None:
                return None
            session.expunge(row)
            return row

    def _update_row(
        self,
        key: str,
        *,
        result: str | None = None,
        external_reference: str | None = None,
        post_verify: str | None = None,
    ) -> None:
        """Update outcome columns on one execution record (no-op if absent)."""
        with Session(self._engine) as session:
            row = session.get(ExecutionRow, key)
            if row is None:
                logger.warning("execution row missing key=%s: skip update", key)
                return
            if result is not None:
                row.result = result
            if external_reference is not None:
                row.external_reference = external_reference
            if post_verify is not None:
                row.post_verify = post_verify
            session.commit()

    def _result_from_row(self, row: ExecutionRow) -> ExecutionResult:
        """Rehydrate the frozen result from a completed execution record."""
        return ExecutionResult(
            execution_id=row.execution_id,
            result=str(row.result),
            external_reference=row.external_reference,
            post_verify=str(row.post_verify),
            idempotency_key=row.idempotency_key,
            exception_id=row.exception_id,
        )


def _record_from_entry(entry: Any) -> PaymentRecord:
    """Derive the expected-side payment leg from a booked adapter entry.

    Args:
        entry: Booked sandbox entry (total + currency + tenant echo).

    Returns:
        A single-leg ``PaymentRecord`` netting exactly the entry total,
        so the P1 oracle compares books against what was written.
    """
    total = entry.total if isinstance(entry.total, Decimal) else Decimal(str(entry.total))
    return PaymentRecord(
        payment_id=str(entry.entry_id),
        provider="sandbox-adapter",
        provider_event_id=str(entry.entry_id),
        idempotency_key=str(entry.idempotency_key),
        gross=total,
        fee=Decimal("0"),
        refund=Decimal("0"),
        net=total,
        currency=str(entry.currency),
        status="SETTLED",
        occurred_at=_utcnow(),
        tenant_id=str(entry.tenant_id),
    )
