from __future__ import annotations

from rulekit.orchestrator import (
    Trajectory,
    TrajectoryBranch,
    TrajectoryEvent,
    TrajectoryEventKind,
)


def test_reviewer_intervention_can_create_branch_with_lineage_events():
    trajectory = Trajectory(
        trajectory_id="traj_1",
        workspace_id="ws_1",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )
    run_event = TrajectoryEvent(
        event_id="evt_run",
        branch_id="br_main",
        kind=TrajectoryEventKind.STEP_RUN,
        payload={"run_id": "run_1"},
    )
    intervention_event = TrajectoryEvent(
        event_id="evt_intervention",
        branch_id="br_main",
        kind=TrajectoryEventKind.INTERVENTION,
        payload={"intervention_id": "int_1"},
        parent_event_id="evt_run",
    )
    trajectory.append_event(run_event)
    trajectory.append_event(intervention_event)

    branch_id = trajectory.create_branch(
        from_branch_id="br_main",
        created_by_event_id="evt_intervention",
    )
    branch_event = TrajectoryEvent(
        event_id="evt_branch_run",
        branch_id=branch_id,
        kind=TrajectoryEventKind.STEP_RUN,
        payload={"run_id": "run_branch"},
        parent_event_id="evt_intervention",
    )
    trajectory.append_event(branch_event)

    assert trajectory.branches[branch_id].parent_branch_id == "br_main"
    assert trajectory.active_branch_id == branch_id
    assert [event.event_id for event in trajectory.events_for_branch(branch_id)] == [
        "evt_run",
        "evt_intervention",
        "evt_branch_run",
    ]

