"""Trajectory harness — Fake/Replay/Live/E2E INPUT→...→FINAL ledger.

``TrajectoryHarness`` drives Planner → Verifier → Executor with bounded
replans while recording tenant-safe steps. See :mod:`agents.trajectory
.harness` for modes and gates.
"""

from agents.trajectory.harness import (
    TrajectoryHarness,
    TrajectoryLiveError,
    TrajectoryTenantError,
    is_live_allowed,
)
from agents.trajectory.models import (
    Trajectory,
    TrajectoryMode,
    TrajectoryStep,
    TrajectoryStepKind,
    generate_correlation_id,
    now_utc,
)
from agents.trajectory.recorder import (
    SequentialReplayProvider,
    fixture_path_for,
    load_fixture,
    recorded_model_outputs,
    save_fixture,
)

__all__ = [
    "Trajectory",
    "TrajectoryHarness",
    "TrajectoryLiveError",
    "TrajectoryMode",
    "TrajectoryStep",
    "TrajectoryStepKind",
    "TrajectoryTenantError",
    "SequentialReplayProvider",
    "fixture_path_for",
    "generate_correlation_id",
    "is_live_allowed",
    "load_fixture",
    "now_utc",
    "recorded_model_outputs",
    "save_fixture",
]
