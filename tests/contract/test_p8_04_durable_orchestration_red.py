"""RED P8-04 durable orchestration boundary — Gates A-J workflow/scheduling invariants.

Gate 1 is design-only: the P8-04 orchestration surface
(``agents.p8_runtime.orchestration``) is intentionally absent on this branch,
so these tests must fail structurally (ModuleNotFoundError/ImportError)
until workflow/scheduling semantics are implemented. Frozen P8-01
(``agents.p8_runtime.contract``), P8-02 (``agents.p8_runtime.execution``),
and P8-03 (``agents.p8_runtime.durability``) must remain GREEN. No src/
changes, no frozen-layer changes.

Expected public surface of ``agents.p8_runtime.orchestration`` (GREEN target):

- Workflow lifecycle (I4/I5/I6): exactly six states PENDING/RUNNING/SUSPENDED/
  COMPLETED/FAILED/CANCELLED; distinct from P8-02 ExecutionState and P8-03
  UNKNOWN/QUARANTINED markers; fixed transitions; terminal seal rule.
- Workflow identity (I7/I8/I9): workflow_id distinct from run_id; ordered
  child-run list + optional parent_workflow_id (metadata only); crash-stable
  id with tenant+situation scope fixed at intake.
- Scheduling vs execution (I10/I11): scheduler decides WHAT runs WHEN only;
  never invokes ProviderAdapter.complete, interprets output, reclassifies,
  or mints authority.
- Resume (I12/I13): re-enter from durable P8-03 state; recorded terminals
  replay with zero invocations; SUSPENDED resumes from recorded point.
- Timeout/cancellation (I14/I15): per-workflow vs per-run deadlines;
  cooperative recorded cancel; timeout as FailureKind.TIMEOUT input only.
- Retry ownership (I16/I17): three counters/owners/precedence; no unbounded
  cross-layer loops; exhaustion seals upward.
- Idempotency (I18): same workflow_id returns outcome or resumes, never forks.
- Concurrency (I19/I20): distinct isolated; same serializes; scope in key.
- Crash/restart (I21/I22): scheduler reconstructible from P8-03 records;
  engine plugs in BEHIND the scheduling seam only.
- Handoff/observability/seam (I23-I28): deterministic shape-identical
  handoff; observer-only workflow observations; preserved per-run
  observations; no eval-derived control; four-row seam; ambiguity to frozen.
- Gate 1 acceptance (I29/I30, I1/I2/I3): RED for intended reasons only;
  doc-only, backend-free, frozen untouched.

Every test cites its contract invariant (I1-I30). Adversarial cases (>=8)
carry an ``adversarial_`` marker. Pure pytest, Phase 1 UNIT: no network,
no filesystem writes, deterministic, no wall-clock dependence.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from agents.p8_runtime import contract as p8_01
from agents.p8_runtime import durability as p8_03
from agents.p8_runtime import execution as p8_02

WORKFLOW_STATES = frozenset(
    {"PENDING", "RUNNING", "SUSPENDED", "COMPLETED", "FAILED", "CANCELLED"}
)
EXECUTION_STATES = frozenset({"CREATED", "RUNNING", "SUCCEEDED", "FAILED", "EXHAUSTED"})
DURABILITY_MARKERS = frozenset({"UNKNOWN", "QUARANTINED"})
TERMINAL_WORKFLOW = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
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
BANNED_AUTHORITY_NAMES = frozenset(
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


def _orchestration() -> Any:
    """Import the intentionally absent P8-04 orchestration surface (RED)."""
    from agents.p8_runtime import orchestration

    return orchestration


def _identity() -> p8_01.RunIdentity:
    """Frozen P8-01 RunIdentity fixture pinning the workflow child-run seam."""
    payload = {"situation_id": "sit-p804-001", "company_id": "meridian"}
    return p8_01.RunIdentity(
        run_id="run-p804-001",
        input_fingerprint=p8_01.compute_input_fingerprint(payload),
    )


def _budget() -> p8_01.Budget:
    """Frozen P8-01 Budget fixture pinning the per-run deadline seam."""
    return p8_01.Budget(
        max_model_calls=2,
        max_tokens=1000,
        max_tool_calls=1,
        deadline_seconds=60.0,
        max_retries=1,
    )


def _terminal_run_record() -> p8_02.RunRecord:
    """Frozen P8-02 SUCCEEDED record fixture for resume/replay cross-seam pins."""
    provenance = p8_01.Provenance(
        prompt_context_id="ctx-p804-001",
        evidence_ids=["ev-1"],
        model="frozen-model",
        provider="frozen-provider",
        version="v1",
        runtime_config=p8_01.RuntimeConfig(max_tokens=100, timeout_ms=1000),
        started_at=p8_02._FIXED_AT,
        completed_at=p8_02._FIXED_AT,
        run_id="run-p804-001",
    )
    attempt = p8_02.AttemptRecord(
        run_id="run-p804-001",
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
        scope="meridian:sit-p804-001",
        intake_scope="meridian:sit-p804-001",
    )


# ---------------------------------------------------------------------------
# A — Workflow lifecycle: three distinct layers (I4, I5, I6)
# ---------------------------------------------------------------------------


class TestAWorkflowLifecycle:
    def test_a1_minimal_closed_workflow_state_set(self) -> None:
        """I4: workflow layer defines exactly six states PENDING..CANCELLED."""
        orch = _orchestration()
        assert set(orch.WORKFLOW_STATES) == set(WORKFLOW_STATES)
        assert orch.WorkflowState is not p8_02.ExecutionState

    def test_a2_three_layers_never_merge(self) -> None:
        """I5: workflow states vs ExecutionState vs UNKNOWN/QUARANTINED distinct."""
        orch = _orchestration()
        assert DURABILITY_MARKERS.isdisjoint(set(orch.WORKFLOW_STATES))
        assert DURABILITY_MARKERS.isdisjoint(set(p8_02.ExecutionState.__members__))
        assert set(orch.WORKFLOW_STATES).isdisjoint(set(EXECUTION_STATES - {"RUNNING"}))
        assert "SUSPENDED" not in set(p8_02.ExecutionState.__members__)
        assert "QUARANTINED" not in set(orch.WORKFLOW_STATES)

    def test_a3_fixed_transitions_terminal_seal_rule(self) -> None:
        """I6: fixed transition table; COMPLETED/FAILED/CANCELLED terminal, no rewrite."""
        orch = _orchestration()
        assert orch.workflow_transitions_from("PENDING") == ("RUNNING", "CANCELLED")
        for terminal in TERMINAL_WORKFLOW:
            assert orch.workflow_transitions_from(terminal) == ()
        assert orch.rewrite_workflow_outcome("wf-p804-001", "COMPLETED") is False

    def test_adversarial_workflow_terminal_rewrite_forbidden(self) -> None:
        """I6: recorded terminal workflow outcome never rewritten/deleted/re-derived."""
        orch = _orchestration()
        assert orch.rewrite_workflow_outcome("wf-p804-001", "FAILED") is False
        assert orch.delete_workflow_outcome("wf-p804-001") is False


# ---------------------------------------------------------------------------
# B — Workflow identity (I7, I8, I9)
# ---------------------------------------------------------------------------


class TestBWorkflowIdentity:
    def test_b1_workflow_id_distinct_from_run_id(self) -> None:
        """I7: workflow_id names orchestration; run_id inside RunIdentity names execution."""
        orch = _orchestration()
        wf = orch.submit_workflow(
            workflow_id="wf-p804-001", child_runs=[_identity()], budget=_budget()
        )
        assert wf.workflow_id == "wf-p804-001"
        assert wf.workflow_id != _identity().run_id
        assert orch.run_dedup_owner() == "p8-03"

    def test_b2_parent_child_linkage_metadata_only(self) -> None:
        """I8: child-run list + parent link record order; never mutate runs."""
        orch = _orchestration()
        before = _terminal_run_record().model_dump()
        wf = orch.submit_workflow(
            workflow_id="wf-p804-001",
            child_runs=[_identity()],
            parent_workflow_id="wf-p804-parent",
        )
        assert wf.child_runs[0].run_id == _identity().run_id
        assert wf.parent_workflow_id == "wf-p804-parent"
        assert _terminal_run_record().model_dump() == before

    def test_b3_identity_stable_across_crash_scope_in_key(self) -> None:
        """I9: same workflow_id/children/point recovered; tenant+situation in key."""
        orch = _orchestration()
        rebuilt = orch.reconstruct_scheduler(descriptors=["wf-p804-001"])
        assert rebuilt.workflow_ids == ["wf-p804-001"]
        assert "meridian" in orch.workflow_key("wf-p804-001", "sit-p804-001")
        assert orch.scope_after("wf-p804-001", op="resume") == orch.intake_scope("wf-p804-001")


# ---------------------------------------------------------------------------
# C — Scheduling vs execution separation (I10, I11)
# ---------------------------------------------------------------------------


class TestCSchedulingSeparation:
    def test_c1_scheduling_decides_what_runs_when_only(self) -> None:
        """I10: ordering/priority/triggers only; never HOW runs execute or survive."""
        orch = _orchestration()
        assert orch.scheduling_decides() == ("ordering", "priority", "triggers")
        assert orch.execution_owner() == "p8-02"
        assert orch.durability_owner() == "p8-03"

    def test_c2_scheduler_prohibitions(self) -> None:
        """I11: scheduler never invokes/interprets/reclassifies/mints/widens scope."""
        orch = _orchestration()
        assert orch.scheduler_invokes_provider() is False
        assert orch.scheduler_mints_authority() is False
        assert orch.scheduler_widens_scope() is False

    def test_adversarial_scheduler_invokes_provider_forbidden(self) -> None:
        """I11: scheduler invoking ProviderAdapter.complete is breach even if silent."""
        orch = _orchestration()
        assert orch.schedule_next("wf-p804-001").provider_invocations == 0
        assert orch.scheduler_interprets_output() is False
        assert orch.scheduler_reclassifies_failure() is False


# ---------------------------------------------------------------------------
# D — Resume/recovery semantics (I12, I13)
# ---------------------------------------------------------------------------


class TestDResume:
    def test_d1_resume_replays_durable_state_reenters_schedule(self) -> None:
        """I12: resume replays P8-03 recovery order then re-enters at recorded point."""
        orch = _orchestration()
        assert orch.resume_workflow("wf-p804-001").via == ("reconcile", "resume")
        assert p8_03.RECOVERY_ORDER == ("load", "verify", "reconcile", "resume_or_seal")

    def test_d2_suspended_resumes_from_recorded_point(self) -> None:
        """I13: SUSPENDED resume continues from recorded point; reconcile never skipped."""
        orch = _orchestration()
        resumed = orch.resume_workflow("wf-p804-001")
        assert resumed.from_start is False
        assert resumed.skipped_reconcile is False
        assert resumed.suspension_point.next_run_id == _identity().run_id

    def test_adversarial_reexecute_completed_forbidden(self) -> None:
        """I12: recorded SUCCEEDED/FAILED/EXHAUSTED runs replay with zero new calls."""
        orch = _orchestration()
        assert orch.resume_workflow("wf-p804-001").new_invocations == 0
        assert orch.reinvoke_recorded_child(_identity(), attempt_number=0) is False


# ---------------------------------------------------------------------------
# E — Timeout/cancellation (I14, I15)
# ---------------------------------------------------------------------------


class TestETimeoutCancellation:
    def test_e1_workflow_vs_run_deadlines(self) -> None:
        """I14: workflow deadline gates admission only; never reshapes run Budget."""
        orch = _orchestration()
        assert orch.admit("wf-p804-001", _identity(), _budget()).checked == "admit/no-admit"
        assert orch.run_budget_unchanged(_identity(), _budget()) is True

    def test_e2_cooperative_cancellation_recorded_terminal(self) -> None:
        """I15: cancel marks CANCELLED terminal + audit; in-flight reconciles via P8-03."""
        orch = _orchestration()
        receipt = orch.cancel_workflow("wf-p804-001")
        assert receipt.state == "CANCELLED"
        assert receipt.audit_appended is True
        assert receipt.force_sealed is False

    def test_e3_timeout_feeds_p8_02_classification_only(self) -> None:
        """I15: run timeout surfaces as FailureKind.TIMEOUT input; no new authority/state."""
        orch = _orchestration()
        assert orch.timeout_kind() is p8_01.FailureKind.TIMEOUT
        assert p8_01.classify_failure(orch.timeout_kind()) is p8_01.FailureClass.TRANSIENT
        assert orch.timeout_mints_authority() is False


# ---------------------------------------------------------------------------
# F — Retry ownership: three counters, three owners (I16, I17)
# ---------------------------------------------------------------------------


class TestFRetryOwnership:
    def test_f1_three_counters_three_owners(self) -> None:
        """I16: workflow runs (P8-04) vs attempt calls (P8-01/P8-02) vs UNKNOWN (P8-03)."""
        orch = _orchestration()
        assert orch.retry_owners() == ("p8-04", "p8-01/p8-02", "p8-03")
        assert orch.counts_runs_not_calls() is True
        assert orch.recaps_p8_02_cap() is False

    def test_f2_precedence_exhaustion_seals_upward(self) -> None:
        """I17: P8-03 gates, then P8-02 cap+budget, then P8-04 run budget; EXHAUSTED->FAILED."""
        orch = _orchestration()
        assert orch.retry_precedence() == ("p8-03", "p8-02", "p8-04")
        assert orch.seal_on_exhaustion("run-p804-001") == "FAILED"

    def test_adversarial_cross_layer_unbounded_retry_forbidden(self) -> None:
        """I17: no retry loop spans layers unboundedly; same identity never re-executed."""
        orch = _orchestration()
        assert orch.cross_layer_loop_bounded() is True
        assert orch.reexecute_same_identity("run-p804-001") is False


# ---------------------------------------------------------------------------
# G — Workflow-level idempotency (I18)
# ---------------------------------------------------------------------------


class TestGIdempotency:
    def test_g1_same_workflow_id_returns_or_resumes(self) -> None:
        """I18: terminal returns outcome; non-terminal resumes from durable state."""
        orch = _orchestration()
        assert orch.resubmit_workflow("wf-p804-001").mode in {"recorded", "resumed"}

    def test_adversarial_duplicate_fork_forbidden(self) -> None:
        """I18: same workflow_id never forks a duplicate; run dedup stays P8-03 owned."""
        orch = _orchestration()
        assert orch.resubmit_workflow("wf-p804-001").forked is False
        assert orch.live_workflows("wf-p804-001") <= 1


# ---------------------------------------------------------------------------
# H — Concurrent workflows (I19, I20)
# ---------------------------------------------------------------------------


class TestHConcurrency:
    def test_h1_distinct_workflows_fully_isolated(self) -> None:
        """I19: no shared mutable state/budget visibility; provenance attributes one wf+run."""
        orch = _orchestration()
        assert orch.shares_state("wf-p804-001", "wf-p804-002") is False
        assert orch.cancel_one_alters_other("wf-p804-001", "wf-p804-002") is False

    def test_h2_same_workflow_id_serializes(self) -> None:
        """I20: second caller observes outcome/in-progress; never duplicates run."""
        orch = _orchestration()
        assert orch.concurrent_submit("wf-p804-001").duplicated is False
        assert orch.concurrent_submit("wf-p804-001").live_workflows <= 1

    def test_adversarial_scope_escape_forbidden(self) -> None:
        """I19/I9: scope fixed at intake; schedule/retry/replay/recovery/resume no widen."""
        orch = _orchestration()
        for op in ("schedule", "retry", "replay", "recovery", "resume"):
            assert orch.scope_after("wf-p804-001", op=op) == orch.intake_scope("wf-p804-001")


# ---------------------------------------------------------------------------
# I — Crash/restart and the future-engine plug point (I21, I22)
# ---------------------------------------------------------------------------


class TestICrashRestart:
    def test_i1_scheduler_reconstructible_no_store_assumed(self) -> None:
        """I21: registry/cursors/points/counters rebuilt from P8-03 records + descriptors."""
        orch = _orchestration()
        assert orch.scheduler_store_assumed() is False
        assert orch.reconstruct_scheduler(descriptors=["wf-p804-001"]).complete is True

    def test_i2_in_flight_reconciles_via_p8_03(self) -> None:
        """I22: post-crash in-flight runs reconcile via recover_run order, UNKNOWN-marked."""
        orch = _orchestration()
        assert orch.recovery_order() == p8_03.RECOVERY_ORDER
        assert orch.recover_workflow("wf-p804-001").in_flight_mark == "UNKNOWN"

    def test_adversarial_engine_inside_execution_forbidden(self) -> None:
        """I22: engine sits BEHIND scheduling seam; never in execute/complete/P6/P7."""
        orch = _orchestration()
        assert orch.engine_plug_point() == "behind-scheduling-seam"
        assert orch.engine_inside_execution() is False
        assert orch.engine_imports_p7() is False


# ---------------------------------------------------------------------------
# J — P7/P6 handoff + observability + seam table (I23-I28, I1-I3)
# ---------------------------------------------------------------------------


class TestJHandoffObservabilitySeam:
    def test_j1_deterministic_shape_identical_handoff(self) -> None:
        """I23/I24: frozen-seam shapes only; same history yields same payload, no reading."""
        orch = _orchestration()
        assert orch.handoff_shape(_identity()) == "frozen-seam-identical"
        first = orch.handoff_workflow("wf-p804-001")
        assert orch.handoff_workflow("wf-p804-001").payload == first.payload

    def test_j2_observer_only_no_eval_derived_control(self) -> None:
        """I25/I26: workflow observations carry no authority; per-run preserved; no P6."""
        orch = _orchestration()
        assert orch.workflow_observation_carries_authority() is False
        assert orch.per_run_observations_preserved("wf-p804-001") is True
        assert orch.touches_p6_execution() is False

    def test_j3_seam_table_ambiguity_resolves_frozen(self) -> None:
        """I27/I28/I1: orchestration owns identity/lifecycle/scheduling only; rest frozen."""
        orch = _orchestration()
        assert orch.owns() == ("identity", "lifecycle", "scheduling", "handoff")
        assert orch.defines_only() == ("identity", "lifecycle", "scheduling", "handoff")
        assert orch.backend_tokens() == ()
        assert BACKEND_TOKENS.isdisjoint(set(orch.backend_tokens()))

    def test_adversarial_handoff_interpretation_forbidden(self) -> None:
        """I24: handoff adds no verdict/ranking/summary rewrite/authority of any kind."""
        orch = _orchestration()
        handoff = orch.handoff_workflow("wf-p804-001")
        assert handoff.verdict is None
        assert handoff.ranking is None
        assert handoff.rewritten_summary is None
        assert handoff.minted_authority == ()

    def test_adversarial_evaluation_schedules_work_forbidden(self) -> None:
        """I26: no eval output authorizes work, mints capability, or drives priority."""
        orch = _orchestration()
        assert orch.eval_drives_scheduling() is False
        assert orch.eval_mints_capability() is False
        path = Path("agents/p8_runtime/orchestration.py")
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("agents.p7")
                assert not node.module.startswith("agents.p6")
        for name in (*P7_TYPE_NAMES, *BANNED_AUTHORITY_NAMES):
            assert name not in tree, f"RED: rival authority type: {name}"
