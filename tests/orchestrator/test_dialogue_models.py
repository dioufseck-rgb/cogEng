from __future__ import annotations

import pytest

from rulekit.orchestrator import (
    AgentTurn,
    DialogueSession,
    DialogueStatus,
    ReviewerTurn,
    ReviewerTurnKind,
)
from rulekit.orchestrator.errors import DialogueBudgetError


def test_dialogue_session_accepts_turns_until_budget_exhausted():
    session = DialogueSession(
        dialogue_id="dlg_1",
        step_id="step_ambiguous",
        max_turns=2,
    )

    session.add_agent_turn(
        AgentTurn(
            turn_id="turn_a1",
            dialogue_id="dlg_1",
            step_id="step_ambiguous",
            turn_index=0,
            message="This clause can be modeled as an exception or substitute.",
        )
    )
    session.add_reviewer_turn(
        ReviewerTurn(
            turn_id="turn_r1",
            dialogue_id="dlg_1",
            step_id="step_ambiguous",
            turn_index=1,
            kind=ReviewerTurnKind.NATURAL_LANGUAGE,
            message="Treat it as an exception for this policy.",
        )
    )

    assert session.turn_count == 2
    assert session.status == DialogueStatus.TURN_BUDGET_EXHAUSTED

    with pytest.raises(DialogueBudgetError):
        session.add_agent_turn(
            AgentTurn(
                turn_id="turn_a2",
                dialogue_id="dlg_1",
                step_id="step_ambiguous",
                turn_index=2,
                message="Acknowledged.",
            )
        )


def test_dialogue_budget_can_be_extended():
    session = DialogueSession(
        dialogue_id="dlg_1",
        step_id="step_ambiguous",
        max_turns=1,
    )
    session.add_agent_turn(
        AgentTurn(
            turn_id="turn_a1",
            dialogue_id="dlg_1",
            step_id="step_ambiguous",
            turn_index=0,
            message="Question for reviewer.",
        )
    )

    session.extend_budget(1)
    session.add_reviewer_turn(
        ReviewerTurn(
            turn_id="turn_r1",
            dialogue_id="dlg_1",
            step_id="step_ambiguous",
            turn_index=1,
            kind=ReviewerTurnKind.STRUCTURED,
            selected_move_id="model_as_exception",
        )
    )

    assert session.turn_count == 2


def test_dialogue_rejects_turn_for_other_step():
    session = DialogueSession(
        dialogue_id="dlg_1",
        step_id="step_ambiguous",
        max_turns=1,
    )

    with pytest.raises(DialogueBudgetError):
        session.add_agent_turn(
            AgentTurn(
                turn_id="turn_a1",
                dialogue_id="dlg_1",
                step_id="other_step",
                turn_index=0,
                message="Wrong step.",
            )
        )

