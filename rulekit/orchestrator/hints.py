"""Reviewer hints for governed reruns."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rulekit.orchestrator.ids import event_id as new_event_id
from rulekit.orchestrator.ids import hint_id as new_hint_id
from rulekit.orchestrator.ids import intervention_id as new_intervention_id
from rulekit.orchestrator.intervention import Intervention, InterventionKind
from rulekit.orchestrator.step import utc_now
from rulekit.orchestrator.trajectory import (
    Trajectory,
    TrajectoryEvent,
    TrajectoryEventKind,
)


class ReviewerHint(BaseModel):
    """Natural-language reviewer guidance for a later governed rerun."""

    model_config = ConfigDict(extra="forbid")

    hint_id: str = Field(default_factory=new_hint_id)
    message: str = Field(min_length=1)
    target_step_id: str | None = None
    case_id: str | None = None
    atom_ids: list[str] = Field(default_factory=list)
    reviewer_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def applies_to_case(self, case_id: str) -> bool:
        return self.case_id is None or self.case_id == case_id


def record_reviewer_hint(
    trajectory: Trajectory,
    *,
    message: str,
    target_step_id: str | None = None,
    case_id: str | None = None,
    atom_ids: list[str] | None = None,
    reviewer_id: str | None = None,
    branch_id: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[ReviewerHint, Intervention]:
    """Persist a natural-language hint as an intervention event."""
    branch_id = branch_id or trajectory.active_branch_id
    hint = ReviewerHint(
        message=message,
        target_step_id=target_step_id,
        case_id=case_id,
        atom_ids=atom_ids or [],
        reviewer_id=reviewer_id,
        metadata=metadata or {},
    )
    intervention = Intervention(
        intervention_id=new_intervention_id(),
        kind=InterventionKind.REVIEWER_NATURAL_HINT,
        branch_id=branch_id,
        step_id=target_step_id,
        reviewer_id=reviewer_id,
        payload={"hint": hint.model_dump(mode="json")},
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
    return hint, intervention


def reviewer_hints_from_trajectory(trajectory: Trajectory) -> list[ReviewerHint]:
    """Rehydrate reviewer hints recorded as trajectory interventions."""
    hints: list[ReviewerHint] = []
    for event in trajectory.events:
        if event.kind != TrajectoryEventKind.INTERVENTION:
            continue
        payload = event.payload
        if payload.get("kind") != InterventionKind.REVIEWER_NATURAL_HINT.value:
            continue
        hint_payload = payload.get("payload", {}).get("hint")
        if isinstance(hint_payload, dict):
            hints.append(ReviewerHint.model_validate(hint_payload))
    return hints


__all__ = [
    "ReviewerHint",
    "record_reviewer_hint",
    "reviewer_hints_from_trajectory",
]
