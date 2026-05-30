from __future__ import annotations

from rulekit.orchestrator import (
    Trajectory,
    TrajectoryBranch,
    TrajectoryEvent,
    TrajectoryEventKind,
    Workspace,
    load_trajectory,
    load_workspace,
    save_trajectory,
    save_workspace,
)


def test_workspace_and_trajectory_persistence_roundtrip(tmp_path):
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
            payload={"run_id": "run_1"},
        )
    )
    workspace = Workspace(
        workspace_id="ws_1",
        name="Workspace",
        trajectories={"traj_1": trajectory},
    )

    save_workspace(workspace, tmp_path)
    save_trajectory(trajectory, tmp_path)

    loaded_workspace = load_workspace(tmp_path, "ws_1")
    loaded_trajectory = load_trajectory(tmp_path, "ws_1", "traj_1")

    assert loaded_workspace.workspace_id == "ws_1"
    assert loaded_trajectory.events[0].event_id == "evt_1"
    assert loaded_trajectory.branches["br_main"].head_event_id == "evt_1"
    assert (tmp_path / "ws_1" / "trajectories" / "traj_1" / "events.jsonl").exists()

