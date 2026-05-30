from __future__ import annotations

from tests.orchestrator.test_exercise import _program

from rulekit.orchestrator import (
    ProgramSnapshot,
    Trajectory,
    TrajectoryBranch,
    TrajectoryEvent,
    TrajectoryEventKind,
    load_program_snapshot,
    save_program_snapshot,
    validate_persisted_trajectory,
)


def test_program_snapshot_persistence_and_validation(tmp_path):
    snapshot = ProgramSnapshot(
        snapshot_id="snap_1",
        program_id="prog_fcba",
        program_version="0.1",
        program=_program(),
    )
    trajectory = Trajectory(
        trajectory_id="traj_1",
        workspace_id="ws_1",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )
    trajectory.append_event(
        TrajectoryEvent(
            event_id="evt_snapshot",
            branch_id="br_main",
            kind=TrajectoryEventKind.PROGRAM_SNAPSHOT,
            payload={"snapshot_id": "snap_1", "program_id": "prog_fcba"},
        )
    )

    save_program_snapshot(tmp_path, "ws_1", "traj_1", snapshot)
    loaded = load_program_snapshot(tmp_path, "ws_1", "traj_1", "snap_1")
    report = validate_persisted_trajectory(tmp_path, trajectory)

    assert loaded.program_id == "prog_fcba"
    assert loaded.program.metadata.name == "FCBA tiny"
    assert report.ok

