"""Append-only construction trajectories."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rulekit.orchestrator.errors import BranchError, OrchestratorValidationError
from rulekit.orchestrator.ids import branch_id as new_branch_id
from rulekit.orchestrator.ids import event_id as new_event_id
from rulekit.orchestrator.intervention import Intervention
from rulekit.orchestrator.step import utc_now


class TrajectoryEventKind(str, Enum):
    STEP_RUN = "step_run"
    INTERVENTION = "intervention"
    DIALOGUE_OPENED = "dialogue_opened"
    AGENT_TURN = "agent_turn"
    REVIEWER_TURN = "reviewer_turn"
    BRANCH_CREATED = "branch_created"
    PROGRAM_SNAPSHOT = "program_snapshot"
    PROGRAM_EDIT_APPLIED = "program_edit_applied"
    VALIDATION_RESULT = "validation_result"
    MAP_RECORDED = "map_recorded"
    DISPOSITION_RECORDED = "disposition_recorded"
    DIAGNOSTIC_RECORDED = "diagnostic_recorded"
    REPORT_GENERATED = "report_generated"


class TrajectoryEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    branch_id: str
    kind: TrajectoryEventKind
    payload: dict[str, Any]
    created_at: datetime = Field(default_factory=utc_now)
    parent_event_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BranchStatus(str, Enum):
    ACTIVE = "active"
    SETTLED = "settled"
    ABANDONED = "abandoned"


class TrajectoryBranch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_id: str
    parent_branch_id: str | None = None
    created_by_event_id: str | None = None
    status: BranchStatus = BranchStatus.ACTIVE
    head_event_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Trajectory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trajectory_id: str
    program_id: str | None = None
    workspace_id: str
    branches: dict[str, TrajectoryBranch]
    events: list[TrajectoryEvent] = Field(default_factory=list)
    active_branch_id: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _check_integrity(self):
        if self.active_branch_id not in self.branches:
            raise ValueError("active_branch_id must reference an existing branch")
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("trajectory event IDs must be unique")
        known_events = set(event_ids)
        for event in self.events:
            if event.branch_id not in self.branches:
                raise ValueError(f"event {event.event_id!r} references missing branch")
            if event.parent_event_id is not None and event.parent_event_id not in known_events:
                raise ValueError(f"event {event.event_id!r} references missing parent")
        for branch in self.branches.values():
            if branch.parent_branch_id is not None and branch.parent_branch_id not in self.branches:
                raise ValueError(f"branch {branch.branch_id!r} references missing parent")
            if branch.head_event_id is not None and branch.head_event_id not in known_events:
                raise ValueError(f"branch {branch.branch_id!r} references missing head event")
        return self

    def append_event(self, event: TrajectoryEvent) -> None:
        """Append one event and advance the branch head."""
        if event.branch_id not in self.branches:
            raise BranchError(f"unknown branch {event.branch_id!r}")
        if any(existing.event_id == event.event_id for existing in self.events):
            raise OrchestratorValidationError(
                f"duplicate event_id {event.event_id!r}"
            )
        self.events.append(event)
        self.branches[event.branch_id].head_event_id = event.event_id
        self.updated_at = utc_now()

    def create_branch(self, from_branch_id: str, created_by_event_id: str) -> str:
        """Create a child branch from an existing branch."""
        if from_branch_id not in self.branches:
            raise BranchError(f"unknown source branch {from_branch_id!r}")
        if not any(event.event_id == created_by_event_id for event in self.events):
            raise BranchError(
                f"created_by_event_id {created_by_event_id!r} is not an event"
            )
        branch_id = new_branch_id()
        self.branches[branch_id] = TrajectoryBranch(
            branch_id=branch_id,
            parent_branch_id=from_branch_id,
            created_by_event_id=created_by_event_id,
            head_event_id=self.branches[from_branch_id].head_event_id,
        )
        self.active_branch_id = branch_id
        self.updated_at = utc_now()
        return branch_id

    def create_branch_from_intervention(
        self,
        intervention: Intervention,
        *,
        from_branch_id: str | None = None,
    ) -> str:
        """Record an intervention event, create a branch, and record the branch."""
        source_branch_id = from_branch_id or intervention.branch_id
        intervention_event = TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=source_branch_id,
            kind=TrajectoryEventKind.INTERVENTION,
            payload=intervention.model_dump(mode="json"),
        )
        self.append_event(intervention_event)
        branch_id = self.create_branch(source_branch_id, intervention_event.event_id)
        self.append_event(
            TrajectoryEvent(
                event_id=new_event_id(),
                branch_id=branch_id,
                kind=TrajectoryEventKind.BRANCH_CREATED,
                payload={
                    "branch_id": branch_id,
                    "parent_branch_id": source_branch_id,
                    "created_by_event_id": intervention_event.event_id,
                    "intervention_id": intervention.intervention_id,
                },
                parent_event_id=intervention_event.event_id,
            )
        )
        return branch_id

    def events_for_branch(self, branch_id: str) -> list[TrajectoryEvent]:
        if branch_id not in self.branches:
            raise BranchError(f"unknown branch {branch_id!r}")
        lineage: set[str] = set()
        current: str | None = branch_id
        while current is not None:
            lineage.add(current)
            current = self.branches[current].parent_branch_id
        return [event for event in self.events if event.branch_id in lineage]


__all__ = [
    "TrajectoryEventKind",
    "TrajectoryEvent",
    "BranchStatus",
    "TrajectoryBranch",
    "Trajectory",
]
