from __future__ import annotations

from rulekit.orchestrator import (
    Trajectory,
    TrajectoryBranch,
    TrajectoryEvent,
    TrajectoryEventKind,
    validate_persisted_trajectory,
    validate_trajectory,
)


def test_validate_trajectory_accepts_branch_created_event():
    trajectory = Trajectory(
        trajectory_id="traj_1",
        workspace_id="ws_1",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )
    event = TrajectoryEvent(
        event_id="evt_1",
        branch_id="br_main",
        kind=TrajectoryEventKind.STEP_RUN,
        payload={"run_id": "run_1"},
    )
    trajectory.append_event(event)

    report = validate_trajectory(trajectory)

    assert report.ok


def test_validate_persisted_trajectory_reports_missing_step_run(tmp_path):
    trajectory = Trajectory(
        trajectory_id="traj_1",
        workspace_id="ws_1",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )
    trajectory.append_event(
        TrajectoryEvent(
            event_id="evt_1",
            branch_id="br_main",
            kind=TrajectoryEventKind.STEP_RUN,
            payload={"run_id": "run_missing"},
        )
    )

    report = validate_persisted_trajectory(tmp_path, trajectory)

    assert not report.ok
    assert "run_missing" in report.summary()


def test_validate_persisted_trajectory_reports_missing_diagnostic(tmp_path):
    trajectory = Trajectory(
        trajectory_id="traj_1",
        workspace_id="ws_1",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )
    trajectory.append_event(
        TrajectoryEvent(
            event_id="evt_1",
            branch_id="br_main",
            kind=TrajectoryEventKind.DIAGNOSTIC_RECORDED,
            payload={"diagnostic_id": "diag_missing"},
        )
    )

    report = validate_persisted_trajectory(tmp_path, trajectory)

    assert not report.ok
    assert "diag_missing" in report.summary()


def test_validate_persisted_trajectory_reports_missing_program_edit(tmp_path):
    trajectory = Trajectory(
        trajectory_id="traj_1",
        workspace_id="ws_1",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )
    trajectory.append_event(
        TrajectoryEvent(
            event_id="evt_1",
            branch_id="br_main",
            kind=TrajectoryEventKind.PROGRAM_EDIT_APPLIED,
            payload={"edit_id": "edit_missing"},
        )
    )

    report = validate_persisted_trajectory(tmp_path, trajectory)

    assert not report.ok
    assert "edit_missing" in report.summary()
