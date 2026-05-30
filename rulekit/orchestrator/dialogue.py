"""Bounded dialogue models for governed build steps."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rulekit.orchestrator.errors import DialogueBudgetError
from rulekit.orchestrator.ids import dialogue_id as new_dialogue_id
from rulekit.orchestrator.ids import event_id as new_event_id
from rulekit.orchestrator.ids import intervention_id as new_intervention_id
from rulekit.orchestrator.intervention import Intervention, InterventionKind
from rulekit.orchestrator.step import BuildStepSpec, DialogueCapability, utc_now
from rulekit.orchestrator.trajectory import (
    Trajectory,
    TrajectoryEvent,
    TrajectoryEventKind,
)


class SuggestedMoveKind(str, Enum):
    BUTTON = "button"
    PROMPT_PREFIX = "prompt_prefix"


class SuggestedMove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    move_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: SuggestedMoveKind
    payload: dict[str, Any] = Field(default_factory=dict)
    prompt_prefix: str | None = None


class AgentTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str
    dialogue_id: str
    step_id: str
    turn_index: int = Field(ge=0)
    work_product: dict[str, Any] | None = None
    message: str = Field(min_length=1)
    reasoning_summary: str | None = None
    uncertainty: list[str] = Field(default_factory=list)
    suggested_next_moves: list[SuggestedMove] = Field(default_factory=list)
    open_questions_for_reviewer: list[str] = Field(default_factory=list)
    actual_prompt: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewerTurnKind(str, Enum):
    STRUCTURED = "structured"
    NATURAL_LANGUAGE = "natural_language"
    MIXED = "mixed"


class ReviewerTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn_id: str
    dialogue_id: str
    step_id: str
    turn_index: int = Field(ge=0)
    kind: ReviewerTurnKind
    selected_move_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None
    reviewer_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class DialogueStatus(str, Enum):
    OPEN = "open"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    TURN_BUDGET_EXHAUSTED = "turn_budget_exhausted"


class DialogueSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dialogue_id: str
    step_id: str
    status: DialogueStatus = DialogueStatus.OPEN
    max_turns: int = Field(ge=0)
    agent_turns: list[AgentTurn] = Field(default_factory=list)
    reviewer_turns: list[ReviewerTurn] = Field(default_factory=list)
    opened_at: datetime = Field(default_factory=utc_now)
    closed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_turns_match_session(self):
        for turn in [*self.agent_turns, *self.reviewer_turns]:
            if turn.dialogue_id != self.dialogue_id:
                raise ValueError("all turns must match DialogueSession.dialogue_id")
            if turn.step_id != self.step_id:
                raise ValueError("all turns must match DialogueSession.step_id")
        if self.turn_count > self.max_turns:
            raise ValueError("dialogue already exceeds max_turns")
        return self

    @property
    def turn_count(self) -> int:
        return len(self.agent_turns) + len(self.reviewer_turns)

    def has_budget(self) -> bool:
        return self.turn_count < self.max_turns

    def extend_budget(self, additional_turns: int) -> None:
        if additional_turns < 1:
            raise ValueError("additional_turns must be >= 1")
        self.max_turns += additional_turns
        if self.status == DialogueStatus.TURN_BUDGET_EXHAUSTED:
            self.status = DialogueStatus.OPEN

    def _ensure_can_append(self, turn) -> None:
        if self.status != DialogueStatus.OPEN:
            raise DialogueBudgetError("cannot append turns to a non-open dialogue")
        if turn.dialogue_id != self.dialogue_id or turn.step_id != self.step_id:
            raise DialogueBudgetError("turn does not belong to this dialogue")
        if not self.has_budget():
            self.status = DialogueStatus.TURN_BUDGET_EXHAUSTED
            raise DialogueBudgetError("dialogue turn budget exhausted")

    def add_agent_turn(self, turn: AgentTurn) -> None:
        self._ensure_can_append(turn)
        self.agent_turns.append(turn)
        if not self.has_budget():
            self.status = DialogueStatus.TURN_BUDGET_EXHAUSTED

    def add_reviewer_turn(self, turn: ReviewerTurn) -> None:
        self._ensure_can_append(turn)
        self.reviewer_turns.append(turn)
        if not self.has_budget():
            self.status = DialogueStatus.TURN_BUDGET_EXHAUSTED

    def close(self, status: DialogueStatus = DialogueStatus.COMPLETED) -> None:
        if status == DialogueStatus.OPEN:
            raise ValueError("close status cannot be OPEN")
        self.status = status
        self.closed_at = utc_now()


def open_dialogue(
    step_spec: BuildStepSpec,
    trajectory: Trajectory,
    *,
    branch_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> DialogueSession:
    """Open a dialogue and append a trajectory event."""
    if step_spec.dialogue_capability == DialogueCapability.NONE:
        raise DialogueBudgetError(
            f"step {step_spec.step_id!r} does not support dialogue"
        )
    branch_id = branch_id or trajectory.active_branch_id
    session = DialogueSession(
        dialogue_id=new_dialogue_id(),
        step_id=step_spec.step_id,
        max_turns=step_spec.max_dialogue_turns,
        metadata=metadata or {},
    )
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=branch_id,
            kind=TrajectoryEventKind.DIALOGUE_OPENED,
            payload={"dialogue_id": session.dialogue_id, "step_id": step_spec.step_id},
        )
    )
    return session


def append_agent_turn(
    session: DialogueSession,
    trajectory: Trajectory,
    turn: AgentTurn,
    *,
    branch_id: str | None = None,
) -> None:
    session.add_agent_turn(turn)
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=branch_id or trajectory.active_branch_id,
            kind=TrajectoryEventKind.AGENT_TURN,
            payload={"dialogue_id": session.dialogue_id, "turn_id": turn.turn_id},
        )
    )


def append_reviewer_turn(
    session: DialogueSession,
    trajectory: Trajectory,
    turn: ReviewerTurn,
    *,
    branch_id: str | None = None,
) -> Intervention:
    session.add_reviewer_turn(turn)
    branch_id = branch_id or trajectory.active_branch_id
    intervention = Intervention(
        intervention_id=new_intervention_id(),
        kind=InterventionKind.REVIEWER_DIALOGUE_TURN,
        branch_id=branch_id,
        step_id=session.step_id,
        reviewer_id=turn.reviewer_id,
        payload={"dialogue_id": session.dialogue_id, "turn_id": turn.turn_id},
    )
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=branch_id,
            kind=TrajectoryEventKind.REVIEWER_TURN,
            payload={"dialogue_id": session.dialogue_id, "turn_id": turn.turn_id},
        )
    )
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=branch_id,
            kind=TrajectoryEventKind.INTERVENTION,
            payload=intervention.model_dump(mode="json"),
        )
    )
    return intervention


def extend_dialogue_budget(
    session: DialogueSession,
    trajectory: Trajectory,
    *,
    additional_turns: int,
    reviewer_id: str | None = None,
    reason: str | None = None,
    branch_id: str | None = None,
) -> Intervention:
    branch_id = branch_id or trajectory.active_branch_id
    session.extend_budget(additional_turns)
    intervention = Intervention(
        intervention_id=new_intervention_id(),
        kind=InterventionKind.REVIEWER_EXTENDED_DIALOGUE_BUDGET,
        branch_id=branch_id,
        step_id=session.step_id,
        reviewer_id=reviewer_id,
        payload={
            "dialogue_id": session.dialogue_id,
            "additional_turns": additional_turns,
            "max_turns": session.max_turns,
        },
        reason=reason,
    )
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=branch_id,
            kind=TrajectoryEventKind.INTERVENTION,
            payload=intervention.model_dump(mode="json"),
        )
    )
    return intervention


__all__ = [
    "SuggestedMoveKind",
    "SuggestedMove",
    "AgentTurn",
    "ReviewerTurnKind",
    "ReviewerTurn",
    "DialogueStatus",
    "DialogueSession",
    "open_dialogue",
    "append_agent_turn",
    "append_reviewer_turn",
    "extend_dialogue_budget",
]
