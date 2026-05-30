from __future__ import annotations

from rulekit.orchestrator import (
    Intervention,
    InterventionKind,
    Trajectory,
    TrajectoryBranch,
    record_reviewer_hint,
)


def test_intervention_records_reviewer_action():
    intervention = Intervention(
        intervention_id="int_1",
        kind=InterventionKind.REVIEWER_EDIT_INTERMEDIATE,
        branch_id="br_main",
        step_id="decompose",
        reviewer_id="reviewer_1",
        payload={"node_id": "n3", "change": "model as exception"},
        reason="Policy unless-clause is ambiguous.",
    )

    assert intervention.kind == InterventionKind.REVIEWER_EDIT_INTERMEDIATE
    assert intervention.payload["node_id"] == "n3"


def test_record_reviewer_hint_appends_intervention_event():
    trajectory = Trajectory(
        trajectory_id="traj_1",
        workspace_id="ws_1",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )

    hint, intervention = record_reviewer_hint(
        trajectory,
        message="The therapy-duration concept was missed; rerun Map with this hint.",
        target_step_id="map_typed_narrative",
        case_id="case_1",
        atom_ids=["pa.therapy_weeks"],
        reviewer_id="reviewer_1",
    )

    assert hint.applies_to_case("case_1") is True
    assert hint.applies_to_case("case_2") is False
    assert intervention.kind == InterventionKind.REVIEWER_NATURAL_HINT
    assert intervention.payload["hint"]["hint_id"] == hint.hint_id
    assert trajectory.events[0].payload["payload"]["hint"]["message"].startswith(
        "The therapy-duration concept"
    )
