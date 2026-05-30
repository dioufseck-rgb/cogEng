from __future__ import annotations

from rulekit.orchestrator import (
    StepContext,
    Trajectory,
    TrajectoryBranch,
    load_step_run,
    run_step_and_record,
    run_stochastic_step_and_record,
)
from rulekit.orchestrator.steps.stub import DeterministicStubStep, StochasticStubStep


def _trajectory() -> Trajectory:
    return Trajectory(
        trajectory_id="traj_1",
        workspace_id="ws_1",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )


def test_run_step_and_record_appends_event_and_persists(tmp_path):
    trajectory = _trajectory()
    context = StepContext(
        workspace_id="ws_1",
        trajectory_id="traj_1",
        branch_id="br_main",
    )

    run = run_step_and_record(
        DeterministicStubStep(step_id="load"),
        {"policy_id": "pol_1"},
        context,
        trajectory,
        persist_root=tmp_path,
    )

    assert trajectory.events[0].payload["run_id"] == run.run_id
    loaded = load_step_run(tmp_path, "ws_1", "traj_1", run.run_id)
    assert loaded.run_id == run.run_id


def test_run_stochastic_step_and_record_appends_all_runs():
    trajectory = _trajectory()

    runs, multi = run_stochastic_step_and_record(
        StochasticStubStep(step_id="decompose", default_k=2),
        {"policy_id": "pol_1"},
        StepContext(branch_id="br_main"),
        trajectory,
        k=2,
    )

    assert len(runs) == 2
    assert len(trajectory.events) == 2
    assert all(event.payload["multi_run_id"] == multi.multi_run_id for event in trajectory.events)

