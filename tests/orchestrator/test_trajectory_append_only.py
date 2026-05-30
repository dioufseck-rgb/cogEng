from __future__ import annotations

import pytest
from pydantic import ValidationError

from rulekit.orchestrator import (
    Trajectory,
    TrajectoryBranch,
    TrajectoryEvent,
    TrajectoryEventKind,
)


def _trajectory() -> Trajectory:
    return Trajectory(
        trajectory_id="traj_1",
        workspace_id="ws_1",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )


def test_append_event_advances_branch_head():
    trajectory = _trajectory()
    event = TrajectoryEvent(
        event_id="evt_1",
        branch_id="br_main",
        kind=TrajectoryEventKind.STEP_RUN,
        payload={"run_id": "run_1"},
    )

    trajectory.append_event(event)

    assert trajectory.events == [event]
    assert trajectory.branches["br_main"].head_event_id == "evt_1"


def test_append_event_rejects_duplicate_event_id():
    trajectory = _trajectory()
    event = TrajectoryEvent(
        event_id="evt_1",
        branch_id="br_main",
        kind=TrajectoryEventKind.STEP_RUN,
        payload={},
    )

    trajectory.append_event(event)

    with pytest.raises(ValueError, match="duplicate"):
        trajectory.append_event(event)


def test_trajectory_event_is_frozen():
    event = TrajectoryEvent(
        event_id="evt_1",
        branch_id="br_main",
        kind=TrajectoryEventKind.STEP_RUN,
        payload={},
    )

    with pytest.raises(ValidationError):
        event.event_id = "evt_2"

