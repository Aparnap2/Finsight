"""State machine registry — all 8 entity state machines.

Implements every state machine defined in the data-contracts design:
PipelineRun, AgentRun, Job, ActionItem, Recommendation, Commentary,
FiscalPeriod, and the SupportLevel lattice.
"""

from business.state_machines.models import (
    GuardCondition,
    StateMachine,
    StateMachineRegistry,
)

# ---------------------------------------------------------------------------
# 1. PipelineRun — end-to-end analysis pipeline lifecycle
# ---------------------------------------------------------------------------

PIPELINE_RUN_SM = StateMachine(
    name="PipelineRun",
    states={"pending", "running", "success", "failed", "retrying", "cancelled"},
    transitions={
        "pending": ["running", "cancelled"],
        "running": ["success", "failed"],
        "failed": ["retrying"],
        "retrying": ["running", "failed"],
    },
    guard_conditions=[
        GuardCondition(
            name="pipeline_retryable_error",
            description="Pipeline can only retry if error is retryable"
            " and retry count not exhausted.",
            applies_to=[("failed", "retrying")],
            condition_fn="context.get('error_retryable', False)"
            " and context.get('retry_count', 0) < context.get('max_retries', 3)",
        ),
        GuardCondition(
            name="pipeline_retry_exhausted",
            description="A retry that fails with exhausted retries terminates.",
            applies_to=[("retrying", "failed")],
            condition_fn="context.get('retry_count', 0) >= context.get('max_retries', 3)",
        ),
    ],
    business_context=(
        "Governs the end-to-end analysis pipeline lifecycle from submission"
        " through execution, success, failure, and optional retry."
    ),
)

# ---------------------------------------------------------------------------
# 2. AgentRun — individual agent node execution
# ---------------------------------------------------------------------------

AGENT_RUN_SM = StateMachine(
    name="AgentRun",
    states={"pending", "running", "success", "failed", "retrying", "cancelled"},
    transitions={
        "pending": ["running", "cancelled"],
        "running": ["success", "failed"],
        "failed": ["retrying"],
        "retrying": ["running", "failed"],
    },
    guard_conditions=[
        GuardCondition(
            name="agent_retryable_error",
            description="Agent runs can retry from failure if the error is transient.",
            applies_to=[("failed", "retrying")],
            condition_fn="context.get('error_retryable', False)"
            " and context.get('retry_count', 0) < context.get('max_retries', 3)",
        ),
        GuardCondition(
            name="agent_retry_exhausted",
            description="Terminal failure after all retries are exhausted.",
            applies_to=[("retrying", "failed")],
            condition_fn="context.get('retry_count', 0) >= context.get('max_retries', 3)",
        ),
    ],
    business_context=(
        "Governs an individual agent node's execution within a pipeline."
        " Each agent run represents one invocation of a LangGraph node."
    ),
)

# ---------------------------------------------------------------------------
# 3. Job — compute runtime job lifecycle
# ---------------------------------------------------------------------------

JOB_SM = StateMachine(
    name="Job",
    states={
        "queued",
        "running",
        "validating",
        "executing",
        "exporting",
        "success",
        "failed",
        "retrying",
        "cancelled",
    },
    transitions={
        "queued": ["running", "cancelled"],
        "running": ["validating", "failed"],
        "validating": ["executing", "failed"],
        "executing": ["exporting", "failed"],
        "exporting": ["success", "failed"],
        "failed": ["retrying"],
        "retrying": ["running", "failed"],
    },
    guard_conditions=[
        GuardCondition(
            name="job_retryable_failure",
            description="Jobs can retry from a recoverable failure.",
            applies_to=[("failed", "retrying")],
            condition_fn="context.get('error_retryable', False)"
            " and context.get('retry_count', 0) < context.get('max_retries', 3)",
        ),
        GuardCondition(
            name="job_retry_exhausted",
            description="Job terminates after exhausting all retries.",
            applies_to=[("retrying", "failed")],
            condition_fn="context.get('retry_count', 0) >= context.get('max_retries', 3)",
        ),
        GuardCondition(
            name="validation_passed",
            description="Job proceeds from validating to executing if validation passes.",
            applies_to=[("validating", "executing")],
            condition_fn="context.get('validation_passed', False)",
        ),
        GuardCondition(
            name="export_prepared",
            description="Job proceeds from executing to exporting if results ready.",
            applies_to=[("executing", "exporting")],
            condition_fn="context.get('results_ready', False)",
        ),
    ],
    business_context=(
        "Governs the compute runtime job lifecycle from queue through"
        " validation, execution, export, and final disposition. This is"
        " the outermost state machine used by the Dispatcher."
    ),
)

# ---------------------------------------------------------------------------
# 4. ActionItem — action item lifecycle
# ---------------------------------------------------------------------------

ACTION_ITEM_SM = StateMachine(
    name="ActionItem",
    states={"proposed", "approved", "in_progress", "completed", "blocked", "rejected"},
    transitions={
        "proposed": ["approved", "blocked", "rejected"],
        "approved": ["in_progress", "blocked", "rejected"],
        "in_progress": ["completed", "blocked"],
        "blocked": ["proposed", "rejected"],
    },
    guard_conditions=[
        GuardCondition(
            name="policy_permitted_and_owner_identified",
            description="Action can only be approved if policy permits and owner assigned.",
            applies_to=[("proposed", "approved")],
            condition_fn="context.get('policy_permitted', False)"
            " and context.get('owner_identified', False)",
        ),
        GuardCondition(
            name="blocked_must_have_reason",
            description="Transitioning to blocked requires a documented reason.",
            applies_to=[
                ("proposed", "blocked"),
                ("approved", "blocked"),
                ("in_progress", "blocked"),
            ],
            condition_fn="bool(context.get('blocked_reason', ''))",
        ),
        GuardCondition(
            name="unblock_requires_resolution",
            description="A blocked action can only return to proposed if resolved.",
            applies_to=[("blocked", "proposed")],
            condition_fn="context.get('blocker_resolved', False)",
        ),
    ],
    business_context=(
        "Governs action items from the recommendation engine. Actions flow"
        " from proposal through approval, execution, and completion, with"
        " optional blocked and rejected states."
    ),
)

# ---------------------------------------------------------------------------
# 5. Recommendation — recommendation lifecycle
# ---------------------------------------------------------------------------

RECOMMENDATION_SM = StateMachine(
    name="Recommendation",
    states={"proposed", "reviewed", "approved", "implemented", "rejected"},
    transitions={
        "proposed": ["reviewed", "rejected"],
        "reviewed": ["approved", "rejected"],
        "approved": ["implemented", "rejected"],
    },
    guard_conditions=[
        GuardCondition(
            name="review_completed",
            description="A recommendation moves from proposed to reviewed after review.",
            applies_to=[("proposed", "reviewed")],
            condition_fn="context.get('review_completed', False)",
        ),
        GuardCondition(
            name="approval_requires_authorization",
            description="A recommendation requires proper authorisation to approve.",
            applies_to=[("reviewed", "approved")],
            condition_fn="context.get('approved_by', '') != ''",
        ),
        GuardCondition(
            name="implementation_verified",
            description="A recommendation is implemented when the change is verified.",
            applies_to=[("approved", "implemented")],
            condition_fn="context.get('implementation_verified', False)",
        ),
    ],
    business_context=(
        "Governs recommendations produced by the recommendation engine."
        " Recommendations flow from proposal through review, approval,"
        " and implementation, with rejection possible at each stage."
    ),
)

# ---------------------------------------------------------------------------
# 6. Commentary — commentary draft version lifecycle
# ---------------------------------------------------------------------------

COMMENTARY_SM = StateMachine(
    name="Commentary",
    states={"draft", "reviewing", "approved", "rejected", "published"},
    transitions={
        "draft": ["draft", "reviewing"],
        "reviewing": ["approved", "rejected"],
        "approved": ["published", "draft"],
    },
    guard_conditions=[
        GuardCondition(
            name="content_updated",
            description="A new draft version is created when content changes.",
            applies_to=[("draft", "draft")],
            condition_fn="context.get('content_changed', False)",
        ),
        GuardCondition(
            name="submission_ready",
            description="Draft can only be submitted for review when complete.",
            applies_to=[("draft", "reviewing")],
            condition_fn="context.get('is_complete', False)",
        ),
        GuardCondition(
            name="revision_requested",
            description="An approved commentary can be returned to draft for revision.",
            applies_to=[("approved", "draft")],
            condition_fn="context.get('revision_requested', False)",
        ),
    ],
    business_context=(
        "Governs commentary draft versions. Commentaries are authored in"
        " draft, submitted for review, and either approved for publication"
        " or returned for revision."
    ),
)

# ---------------------------------------------------------------------------
# 7. FiscalPeriod — fiscal period lifecycle
# ---------------------------------------------------------------------------

FISCAL_PERIOD_SM = StateMachine(
    name="FiscalPeriod",
    states={"open", "closing", "closed", "reopened", "archived"},
    transitions={
        "open": ["closing"],
        "closing": ["closed"],
        "closed": ["reopened", "archived"],
        "reopened": ["open", "archived"],
    },
    guard_conditions=[
        GuardCondition(
            name="cfo_approval_for_reopen",
            description="A closed period can only be reopened with CFO authorisation.",
            applies_to=[("closed", "reopened")],
            condition_fn="context.get('cfo_approved', False)"
            " and bool(context.get('approval_ref', ''))",
        ),
        GuardCondition(
            name="adjustment_posting_complete",
            description="A reopened period returns to open once adjustments are done.",
            applies_to=[("reopened", "open")],
            condition_fn="context.get('adjustments_complete', False)",
        ),
        GuardCondition(
            name="downstream_processes_complete",
            description="Period can only be archived after downstream processes done.",
            applies_to=[("closed", "archived"), ("reopened", "archived")],
            condition_fn="context.get('downstream_complete', False)",
        ),
    ],
    business_context=(
        "Governs the fiscal period lifecycle from open through close and"
        " archival, with exceptional reopen capability. Periods in 'closed'"
        " state cannot accept new postings."
    ),
)

# ---------------------------------------------------------------------------
# 8. SupportLevelLattice — assertion confidence lattice
#
# This is not a classic state machine but a one-directional confidence
# lattice. Values can only move DOWN (lower confidence) — upgrades
# require re-running the full validation pipeline.
# ---------------------------------------------------------------------------

SUPPORT_LEVEL_LATTICE = StateMachine(
    name="SupportLevel",
    states={"verified", "probable", "weak", "insufficient"},
    transitions={
        "verified": ["probable", "weak", "insufficient"],
        "probable": ["weak", "insufficient"],
        "weak": ["insufficient"],
        "insufficient": [],
    },
    guard_conditions=[
        GuardCondition(
            name="lattice_downgrade_only",
            description="Support levels can only move downward in confidence."
            " Upgrades require a full re-validation pipeline run.",
            applies_to=[
                ("verified", "probable"),
                ("verified", "weak"),
                ("verified", "insufficient"),
                ("probable", "weak"),
                ("probable", "insufficient"),
                ("weak", "insufficient"),
            ],
            condition_fn="True",
        ),
        GuardCondition(
            name="no_upward_transitions",
            description="Direct upgrades within the lattice are prohibited.",
            applies_to=[
                ("probable", "verified"),
                ("weak", "verified"),
                ("weak", "probable"),
                ("insufficient", "weak"),
                ("insufficient", "probable"),
                ("insufficient", "verified"),
            ],
            condition_fn="False",
        ),
    ],
    business_context=(
        "Governs assertion support levels as a one-directional confidence"
        " lattice. Values descend from verified (highest confidence) to"
        " insufficient (lowest). Upgrades require re-running the full"
        " assertion validation pipeline."
    ),
)

# ---------------------------------------------------------------------------
# State machine registry — singleton
# ---------------------------------------------------------------------------

STATE_MACHINE_REGISTRY = StateMachineRegistry(
    machines={
        PIPELINE_RUN_SM.name: PIPELINE_RUN_SM,
        AGENT_RUN_SM.name: AGENT_RUN_SM,
        JOB_SM.name: JOB_SM,
        ACTION_ITEM_SM.name: ACTION_ITEM_SM,
        RECOMMENDATION_SM.name: RECOMMENDATION_SM,
        COMMENTARY_SM.name: COMMENTARY_SM,
        FISCAL_PERIOD_SM.name: FISCAL_PERIOD_SM,
        SUPPORT_LEVEL_LATTICE.name: SUPPORT_LEVEL_LATTICE,
    },
)
