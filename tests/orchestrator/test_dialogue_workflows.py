from __future__ import annotations

import pytest

from rulekit.orchestrator import (
    AgentTurn,
    BuildStepSpec,
    DialogueCapability,
    ReviewerTurn,
    ReviewerTurnKind,
    Trajectory,
    TrajectoryBranch,
    append_agent_turn,
    append_reviewer_turn,
    extend_dialogue_budget,
    open_dialogue,
)
from rulekit.orchestrator.errors import DialogueBudgetError


def _trajectory() -> Trajectory:
    return Trajectory(
        trajectory_id="traj_1",
        workspace_id="ws_1",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )


def test_optional_dialogue_step_opens_and_records_events():
    trajectory = _trajectory()
    spec = BuildStepSpec(
        step_id="decompose",
        name="Decompose",
        dialogue_capability=DialogueCapability.OPTIONAL,
        max_dialogue_turns=2,
    )

    session = open_dialogue(spec, trajectory)
    append_agent_turn(
        session,
        trajectory,
        AgentTurn(
            turn_id="turn_a",
            dialogue_id=session.dialogue_id,
            step_id="decompose",
            turn_index=0,
            message="Ambiguity found.",
        ),
    )
    intervention = append_reviewer_turn(
        session,
        trajectory,
        ReviewerTurn(
            turn_id="turn_r",
            dialogue_id=session.dialogue_id,
            step_id="decompose",
            turn_index=1,
            kind=ReviewerTurnKind.NATURAL_LANGUAGE,
            message="Use exception semantics.",
        ),
    )

    assert intervention.payload["dialogue_id"] == session.dialogue_id
    assert [event.kind.value for event in trajectory.events] == [
        "dialogue_opened",
        "agent_turn",
        "reviewer_turn",
        "intervention",
    ]


def test_non_dialogue_step_rejects_open_dialogue():
    with pytest.raises(DialogueBudgetError):
        open_dialogue(BuildStepSpec(step_id="load", name="Load"), _trajectory())


def test_reviewer_extension_permits_additional_turn():
    trajectory = _trajectory()
    spec = BuildStepSpec(
        step_id="decompose",
        name="Decompose",
        dialogue_capability=DialogueCapability.OPTIONAL,
        max_dialogue_turns=1,
    )
    session = open_dialogue(spec, trajectory)
    append_agent_turn(
        session,
        trajectory,
        AgentTurn(
            turn_id="turn_a",
            dialogue_id=session.dialogue_id,
            step_id="decompose",
            turn_index=0,
            message="Need reviewer input.",
        ),
    )

    extend_dialogue_budget(
        session,
        trajectory,
        additional_turns=1,
        reviewer_id="reviewer",
    )
    append_reviewer_turn(
        session,
        trajectory,
        ReviewerTurn(
            turn_id="turn_r",
            dialogue_id=session.dialogue_id,
            step_id="decompose",
            turn_index=1,
            kind=ReviewerTurnKind.STRUCTURED,
            selected_move_id="exception",
        ),
    )

    assert session.turn_count == 2
    assert any(
        event.payload.get("kind") == "reviewer_extended_dialogue_budget"
        for event in trajectory.events
        if event.kind.value == "intervention"
    )

