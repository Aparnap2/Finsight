"""RED P8-03 runtime state persistence & replay — Gates A-J durability invariants.

Gate 1 is design-only: the P8-03 durability surface
(``agents.p8_runtime.durability``) is intentionally absent on this branch, so
these tests must fail structurally (ModuleNotFoundError) until durability
semantics are implemented. Frozen P8-01 (``agents.p8_runtime.contract``) and
P8-02 (``agents.p8_runtime.execution``) must remain GREEN. No src/ changes.

Expected public surface of ``agents.p8_runtime.durability`` (GREEN target):

- Durable projection of frozen P8-02 ``RunRecord`` (closed I4 allowlist;
  I5 forbidden fields never persisted; observer metadata only, I6).
- UNKNOWN-then-reconcile for crashes in RUNNING (I7); terminal immutability
  (I8); resumable non-terminals via ``execute_run`` ordering (I9).
- At-least-once provider reconciliation vs exactly-once effects; recorded
  attempts never re-invoke ``ProviderAdapter.complete`` (I10, I11).
- Idempotent resubmission on ``RunIdentity``; duplicate-run fork forbidden;
  fingerprint key rule extends to durable state (I12, I13).
- Ordered gap-free attempt history; read-only replay (I14, I15).
- Ordered recovery load->verify->reconcile->resume/seal as provenance, not
  attempts; blind auto-retry forbidden (I16, I17, I18).
- Per-identity serialization; scope fixed in durable key; quarantine
  non-executable (I19, I20).
- Integrity seal (canonical JSON, sorted keys, SHA-256, ``p8-03-seal``
  domain); mismatch quarantines without auto-heal (I21, I22, I23).
- Append-only audit with minimization (I24, I25).
- P7 shape-identical output; ownership seam table; doc-only Gate 1
  (I26, I27, I28, I29, I30, plus I1, I2, I3).

Every test cites its contract invariant (I1-I30). Adversarial cases (>=8)
carry an ``adversarial_`` marker. Pure pytest, Phase 1 UNIT: no network,
no filesystem writes, deterministic, no wall-clock dependence.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.p8_runtime import contract as p8_01
from agents.p8_runtime import execution as p8_02

TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "EXHAUSTED"})
FORBIDDEN_PERSISTED = frozenset(
    {
        "api_key",
        "credentials",
        "provider_secret",
        "raw_pii",
        "raw_prompt_body",
        "live_adapter",
        "live_socket",
        "live_cursor",
        "authorization",
        "approval",
        "execution",
        "settlement",
        "verdict",
        "gate_result",
    }
)
BACKEND_TOKENS = frozenset(
    {
        "temporal",
        "redis",
        "langgraph",
        "qdrant",
        "postgres",
        "kafka",
        "boto3",
        "openai",
    }
)
P7_TYPE_NAMES = frozenset(
    {"DiscoveryResult", "ReasoningResult", "HumanResolutionBrief", "GateResult"}
)
BANNED_DURABILITY_NAMES = frozenset(
    {
        "AuthorizationToken",
        "ApprovalDecision",
        "ExecutionRecord",
        "VerificationVerdict",
        "SettlementRecord",
        "AuthoritativeFact",
        "EvidenceRegistry",
        "AuthorityBoundary",
        "PolicyDecision",
        "GateResult",
    }
)


def _durability():
    """Import the intentionally absent P8-03 durability surface (RED)."""
    from agents.p8_runtime import durability

    return durability


def _identity():
    """Frozen P8-01 RunIdentity fixture pinning the durability key seam."""
    payload = {"situation_id": "sit-p803-001", "company_id": "meridian"}
    return p8_01.RunIdentity(
        run_id="run-p803-001",
        input_fingerprint=p8_01.compute_input_fingerprint(payload),
    )


def _budget():
    """Frozen P8-01 Budget fixture pinning the resume-accounting seam."""
    return p8_01.Budget(
        max_model_calls=2,
        max_tokens=1000,
        max_tool_calls=1,
        deadline_seconds=60.0,
        max_retries=1,
    )


def _recorded_terminal_record() -> p8_02.RunRecord:
    """Frozen P8-01/P8-02 SUCCEEDED record used as fixture input for identity proofs."""
    provenance = p8_01.Provenance(
        prompt_context_id="ctx-p803-001",
        evidence_ids=["ev-1"],
        model="frozen-model",
        provider="frozen-provider",
        version="v1",
        runtime_config=p8_01.RuntimeConfig(max_tokens=100, timeout_ms=1000),
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        completed_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
        run_id="run-p803-001",
    )
    attempt = p8_02.AttemptRecord(
        run_id="run-p803-001",
        attempt_number=0,
        input_fingerprint=_identity().input_fingerprint,
        provenance=provenance,
        latency_ms=10,
        token_usage=5,
        validated_output=p8_01.StructuredModelOutput(
            summary="recorded summary", findings=["recorded finding"]
        ),
    )
    return p8_02.RunRecord(
        run_identity=_identity(),
        attempts=[attempt],
        provenance=[provenance],
        timing=[10],
        budget_usage=p8_01.BudgetUsage(
            model_calls=1, tokens=5, tool_calls=0, elapsed_seconds=0.1, retries=0
        ),
        terminal_state="SUCCEEDED",
        budget_checks=1,
        attempt_count=1,
        invocations_after_exhaustion=0,
        terminal_outcome=p8_02.TerminalOutcome(
            summary="recorded summary", terminal_state="SUCCEEDED"
        ),
        scope="meridian:sit-p803-001",
        intake_scope="meridian:sit-p803-001",
    )


class _RecordingProviderSpy:
    """Behavioral stand-in for ProviderAdapter.complete: records every invocation."""

    def __init__(self) -> None:
        self.complete_calls: list[dict[str, Any]] = []

    def complete(
        self, request: p8_01.ModelRequest, config: p8_01.RuntimeConfig
    ) -> p8_01.ModelResponse:
        """Record the call and return a canned neutral response for counting."""
        self.complete_calls.append({"request": request, "config": config})
        return p8_01.ModelResponse(
            run_id="run-p803-001",
            output_text='{"summary": "spy", "findings": []}',
            token_usage=1,
            latency_ms=1,
            provenance=p8_01.Provenance(
                prompt_context_id=request.prompt_context_id,
                evidence_ids=[],
                model="spy-model",
                provider="spy-provider",
                version="v1",
                runtime_config=config,
                started_at=datetime(2026, 1, 1, tzinfo=UTC),
                completed_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
                run_id="run-p803-001",
            ),
        )


# ---------------------------------------------------------------------------
# A — Persisted-field allowlist vs forbidden fields (I4, I5, I6)
# ---------------------------------------------------------------------------


class TestAPersistedFields:
    def test_a1_closed_allowlist_only(self) -> None:
        """I4: durable state holds ONLY identity/scope/attempts/terminal/budget/seal/audit."""
        durability = _durability()
        expected = frozenset(
            {
                "run_id",
                "input_fingerprint",
                "scope",
                "attempts",
                "terminal_state",
                "budget_usage",
                "integrity_seal",
                "audit_events",
            }
        )
        assert expected == durability.PERSISTED_FIELDS

    def test_a2_forbidden_fields_never_persisted(self) -> None:
        """I5: credentials/secrets/raw-PII/live-handles/authority never durable; logs scrubbed."""
        durability = _durability()
        assert FORBIDDEN_PERSISTED.isdisjoint(set(durability.PERSISTED_FIELDS))
        assert durability.scrubs_secrets_and_pii(durability.snapshot(_identity())) is True

    def test_a3_durable_record_is_run_record_projection(self) -> None:
        """I6/I1: durable record projects frozen P8-02 RunRecord; no P7/authority coercion."""
        durability = _durability()
        assert durability.DurableRunState.wraps is not None
        assert durability.DurableRunState.wrapped_type == "RunRecord"
        for token in ("AuthoritativeFact", "to_journal", "to_settlement", *P7_TYPE_NAMES):
            assert token not in str(durability.DurableRunState.model_fields)


# ---------------------------------------------------------------------------
# B — Crash during RUNNING reconciles, terminals immutable (I7, I8, I9)
# ---------------------------------------------------------------------------


class TestBCrashRecovery:
    def test_b1_running_crash_loads_unknown_then_reconciles(self) -> None:
        """I7: interrupted RUNNING marks each in-flight attempt UNKNOWN, then reconciles."""
        durability = _durability()
        recovered = durability.recover_run(_identity())
        assert recovered.in_flight_mark == "UNKNOWN"
        assert recovered.reconciled is True

    def test_adversarial_assume_success_on_recovery_forbidden(self) -> None:
        """I7: recovery never assumes SUCCEEDED, synthesizes output, or silently completes."""
        durability = _durability()
        recovered = durability.recover_run(_identity())
        assert recovered.terminal_state != "SUCCEEDED"
        assert recovered.synthesized_output is None
        assert recovered.silent_completion is False

    def test_b2_nonterminal_resumable_never_silently_completable(self) -> None:
        """I9: interrupted non-terminal resumes via reconcile+resume, never direct terminal."""
        durability = _durability()
        recovered = durability.recover_run(_identity())
        assert recovered.terminal_state not in TERMINAL_STATES
        resumed = durability.resume_run(_identity())
        assert resumed.via == ("reconcile", "resume")
        assert resumed.skipped_reconcile is False
        assert durability.seal_terminal_without_resume(_identity()) is False

    def test_adversarial_terminal_mutation_forbidden(self) -> None:
        """I8: SUCCEEDED/FAILED/EXHAUSTED have no outgoing transitions once recorded."""
        durability = _durability()
        for state in TERMINAL_STATES:
            assert durability.transitions_from_recorded(state) == ()
        assert durability.rewrite_terminal(_identity(), "SUCCEEDED") is False


# ---------------------------------------------------------------------------
# C — At-least-once provider vs exactly-once effects (I10, I11)
# ---------------------------------------------------------------------------


class TestCInvocationGuarantees:
    def test_c1_interrupted_call_reconciles_without_assumption(self) -> None:
        """I10: recovery assumes the call may/may-not have run; reconciles via history+budget."""
        durability = _durability()
        assert durability.reconcile_unknown(_identity()).assumed is False
        assert durability.reconcile_unknown(_identity()).via == ("history", "budget")

    def test_c2_recorded_attempts_never_reinvoke(self) -> None:
        """I11: replay after recovery returns recorded outcomes; zero invocations/budget."""
        durability = _durability()
        assert durability.replay_durable(_identity()).new_invocations == 0
        assert durability.replay_durable(_identity()).new_budget_consumed == 0

    def test_adversarial_recorded_attempt_reinvocation_forbidden(self) -> None:
        """I11: provider complete() is never called again for a recorded attempt."""
        durability = _durability()
        assert durability.reinvoke_recorded(_identity(), attempt_number=0) is False

    def test_adversarial_spy_silence_on_replay_and_recovery(self) -> None:
        """I11/I15: replay/recovery paths make ZERO complete() calls on the provider spy."""
        durability = _durability()
        spy = _RecordingProviderSpy()
        durability.replay_durable(_identity(), provider=spy)
        durability.recover_run(_identity(), provider=spy)
        assert spy.complete_calls == []

    def test_adversarial_exhaustion_freezes_provider_spy(self) -> None:
        """I8/I11: after terminal state is recorded the spy freezes; no post-terminal calls."""
        durability = _durability()
        spy = _RecordingProviderSpy()
        durability.execute_run(_identity(), provider=spy)
        frozen = list(spy.complete_calls)
        durability.execute_run(_identity(), provider=spy)
        durability.resume_run(_identity(), provider=spy)
        assert spy.complete_calls == frozen

    def test_c5_each_executed_attempt_asserts_exactly_one_spy_call(self) -> None:
        """I10/I11: each durable attempt maps to exactly one provider complete() call."""
        durability = _durability()
        spy = _RecordingProviderSpy()
        durability.execute_run(_identity(), provider=spy)
        history = durability.history(_identity())
        assert len(history) >= 1
        assert len(spy.complete_calls) == len(history)


# ---------------------------------------------------------------------------
# D — Idempotent resubmission on RunIdentity (I12, I13)
# ---------------------------------------------------------------------------


class TestDIdempotency:
    def test_d1_recorded_returns_outcome_incomplete_resumes(self) -> None:
        """I12: same identity returns recorded terminal outcome, or resumes when incomplete."""
        durability = _durability()
        assert durability.resubmit(_identity()).mode in {"recorded", "resumed"}

    def test_adversarial_duplicate_fork_forbidden(self) -> None:
        """I12/I13: resubmission never forks a duplicate run; one identity, one live run."""
        durability = _durability()
        assert durability.resubmit(_identity()).forked is False
        assert durability.live_count(_identity()) <= 1

    def test_d3_fingerprint_key_rule_extends_to_durable_state(self) -> None:
        """I13: same run_id + different fingerprint never replays another outcome; no aliasing."""
        durability = _durability()
        other = p8_01.RunIdentity(run_id="run-p803-001", input_fingerprint="0" * 64)
        assert durability.resubmit(other).aliased is False

    def test_d1b_recorded_terminal_resubmission_returns_identical_outcome(self) -> None:
        """I12: resubmission of a recorded terminal identity returns the identical outcome."""
        durability = _durability()
        recorded = _recorded_terminal_record()
        result = durability.resubmit(recorded.run_identity, recorded_record=recorded)
        assert result.mode == "recorded"
        assert result.forked is False
        assert result.terminal_state == recorded.terminal_state
        assert result.outcome.model_dump() == recorded.terminal_outcome.model_dump()


# ---------------------------------------------------------------------------
# E — Attempt history & read-only replay (I14, I15)
# ---------------------------------------------------------------------------


class TestEHistoryReplay:
    def test_e1_full_ordered_gap_free_history_durable(self) -> None:
        """I14: durable state retains ordered attempts with provenance/timing/usage/kind."""
        durability = _durability()
        attempts = durability.history(_identity())
        assert [a.attempt_number for a in attempts] == list(range(len(attempts)))
        assert all(isinstance(a.provenance, p8_01.Provenance) for a in attempts)

    def test_e2_replay_reads_only_unrecorded_returns_none(self) -> None:
        """I15: replay writes/invokes/consumes/mints nothing; unrecorded identity -> None."""
        durability = _durability()
        assert durability.replay_durable(_identity()).wrote is False
        ghost = p8_01.RunIdentity(run_id="run-p803-ghost", input_fingerprint="0" * 64)
        assert durability.replay_durable(ghost).outcome is None

    def test_adversarial_replay_with_invocation_forbidden(self) -> None:
        """I15/I11: replay triggers zero provider calls, zero attempts, zero budget."""
        durability = _durability()
        before = durability.provider_call_count(_identity())
        durability.replay_durable(_identity())
        assert durability.provider_call_count(_identity()) == before


# ---------------------------------------------------------------------------
# F — Recovery protocol order, provenance-not-attempt, no blind retry (I16-I18)
# ---------------------------------------------------------------------------


class TestFRecoveryProtocol:
    def test_f1_fixed_order_load_verify_reconcile_resume_or_seal(self) -> None:
        """I16: recovery runs load->seal-verify->UNKNOWN-reconcile->resume/seal in order."""
        durability = _durability()
        assert durability.RECOVERY_ORDER == ("load", "verify", "reconcile", "resume_or_seal")

    def test_f1b_recovery_observes_precedence_on_recording_probe(self) -> None:
        """I16: recovery appends load->verify->reconcile->resume/seal to a probe in order."""
        durability = _durability()
        events: list[str] = []
        durability.recover_run(_identity(), event_log=events)
        assert events[0] == "load"
        assert events.index("verify") < events.index("reconcile")
        assert events.index("reconcile") < events.index("resume_or_seal")

    def test_f2_recovery_is_provenance_not_attempt(self) -> None:
        """I17: recovery events are audit entries; consume no attempt slots/cap/provenance."""
        durability = _durability()
        event = durability.recovery_event(_identity())
        assert event.consumes_attempt_number is False
        assert event.counts_against_retry_cap is False
        assert event.carries_provider_provenance is False

    def test_adversarial_blind_auto_retry_forbidden(self) -> None:
        """I18: UNKNOWN retries only via TRANSIENT+cap+budget gates; TERMINAL/budget seals."""
        durability = _durability()
        assert durability.retry_unknown(_identity(), gated=False) is False
        assert durability.retry_unknown(_identity(), gated=True).gates == (
            "transient",
            "cap",
            "budget",
        )


# ---------------------------------------------------------------------------
# G — Concurrency: serialization, isolation, scoped key (I19, I20)
# ---------------------------------------------------------------------------


class TestGConcurrency:
    def test_g1_same_identity_serializes_distinct_isolated(self) -> None:
        """I19: second caller observes recorded/in-progress run; distinct ids share nothing."""
        durability = _durability()
        assert durability.concurrent_submit(_identity()).duplicated is False
        assert durability.shares_state("run-p803-001", "run-p803-002") is False

    def test_adversarial_concurrent_duplicate_forbidden(self) -> None:
        """I19: concurrent submissions under one identity never start two executions."""
        durability = _durability()
        assert durability.concurrent_submit(_identity()).live_executions <= 1

    def test_adversarial_scope_escape_forbidden(self) -> None:
        """I19: tenant+situation scope fixed at intake; retry/replay/recovery never widen."""
        durability = _durability()
        assert durability.scope_after(_identity(), op="recovery") == durability.intake_scope(
            _identity()
        )

    def test_adversarial_quarantined_identity_refuses_execution(self) -> None:
        """I20: quarantined identity refuses execute_run/resume/replay-as-success/invoke."""
        durability = _durability()
        assert durability.quarantine(_identity()).executable is False
        assert durability.execute_run(_identity()) is False
        assert durability.resume_run(_identity()) is False
        assert durability.replay_quarantined_as_success(_identity()) is False
        assert durability.invoke_provider(_identity()) is False
        assert durability.replay_durable(_identity()).outcome is None
        assert durability.quarantine(_identity()).executable is False


# ---------------------------------------------------------------------------
# H — Integrity seal + quarantine (I21, I22, I23)
# ---------------------------------------------------------------------------


class TestHIntegritySeal:
    def test_h1_seal_over_canonical_allowlist_no_new_crypto(self) -> None:
        """I21: seal hashes canonical I4 projection; p8-03-seal domain; no keys/secrets."""
        durability = _durability()
        assert durability.seal_domain == "p8-03-seal"
        assert durability.seal_has_secrets() is False
        assert durability.new_crypto_infra is False

    def test_h1b_seal_canonical_key_order_independent(self) -> None:
        """I21: seal hashes canonically-serialized fields; key order never changes it."""
        durability = _durability()
        fields_a = {
            "run_id": "run-p803-001",
            "scope": {"tenant": "meridian", "situation": "sit-p803-001"},
        }
        fields_b = {
            "scope": {"situation": "sit-p803-001", "tenant": "meridian"},
            "run_id": "run-p803-001",
        }
        assert durability.seal_fields(fields_a) == durability.seal_fields(fields_b)
        assert durability.verify_seal(fields_b, durability.seal_fields(fields_a)) is True

    def test_h2_mismatch_quarantines_distinct_non_executable(self) -> None:
        """I22: mismatch enters quarantine: not SUCCEEDED/FAILED, not an ExecutionState member."""
        durability = _durability()
        state = durability.quarantine(_identity())
        assert state.marker not in TERMINAL_STATES
        assert state.marker not in {"CREATED", "RUNNING"}
        assert state.executable is False

    def test_adversarial_seal_strip_or_auto_heal_forbidden(self) -> None:
        """I22: quarantine persists for humans; never auto-heals/retries/seals terminal."""
        durability = _durability()
        state = durability.quarantine(_identity())
        assert state.auto_healed is False
        assert state.auto_retried is False
        assert state.auto_sealed_terminal is False

    def test_h4_quarantine_observable_scoped(self) -> None:
        """I23: quarantine flag + seal-verdict in state/audit; no widen/leak/cross-run writes."""
        durability = _durability()
        assert durability.quarantine(_identity()).observable is True
        assert durability.quarantine(_identity()).widens_scope is False


# ---------------------------------------------------------------------------
# I — Append-only audit + minimization (I24, I25)
# ---------------------------------------------------------------------------


class TestIAudit:
    def test_i1_audit_append_only(self) -> None:
        """I24: per-attempt Provenance + recovery events; never mutated/reordered/deleted."""
        durability = _durability()
        assert durability.append_audit(_identity(), "resume").mutated_prior is False
        assert durability.audit_ordered(_identity()) is True

    def test_i2_minimization_no_raw_bodies_or_secrets(self) -> None:
        """I25: no raw prompt bodies beyond fingerprints, no secrets; observations observer-only."""
        durability = _durability()
        assert durability.audit_has_raw_bodies(_identity()) is False
        assert durability.audit_has_secrets(_identity()) is False


# ---------------------------------------------------------------------------
# J — P7 compatibility + ownership seam + Gate 1 acceptance (I26-I30, I1-I3)
# ---------------------------------------------------------------------------


class TestJCompatibilitySeam:
    def test_j1_recovered_shape_identical_p7_sees_no_recovery(self) -> None:
        """I26: recovered output shape-identical via frozen seams; no P7 recovery internals."""
        durability = _durability()
        assert durability.recovered_shape(_identity()) == "frozen-seam-identical"
        path = Path("agents/p8_runtime/durability.py")
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("agents.p7")

    def test_adversarial_p7_types_never_redefined(self) -> None:
        """I26/I1: durability never redefines P7 results, Budget/Kind/State/Record/replay."""
        durability = _durability()
        for name in (*P7_TYPE_NAMES, "Budget", "FailureKind", "ExecutionState", "RunRecord"):
            assert not hasattr(durability, name), f"RED: rival type: {name}"

    def test_j1b_future_surface_avoids_banned_authority_names(self) -> None:
        """I1/I26: durability exposes none of the frozen banned authority/type names."""
        durability = _durability()
        public = {name for name in dir(durability) if not name.startswith("_")}
        assert public.isdisjoint(BANNED_DURABILITY_NAMES)

    def test_j3_ownership_seam_and_doc_only_gate(self) -> None:
        """I27/I28/I30/I2/I3: P8-03 owns durability only; backend-free; no impl/frozen changes."""
        durability = _durability()
        assert durability.owns == ("durability", "recovery", "integrity", "audit")
        assert BACKEND_TOKENS.isdisjoint(set(durability.backend_tokens()))
        assert durability.defines_only == ("durability", "recovery", "integrity", "audit")

    def test_j4_red_for_intended_reasons_only(self) -> None:
        """I29: durability surface present and complete; contracted seams exposed."""
        durability = _durability()
        for name in (
            "seal_fields",
            "verify_seal",
            "recover_run",
            "resubmit",
            "replay_durable",
            "append_audit",
        ):
            assert callable(getattr(durability, name)), f"missing seam: {name}"
