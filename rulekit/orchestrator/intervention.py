"""Reviewer intervention records."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rulekit.orchestrator.step import utc_now


class InterventionKind(str, Enum):
    VALIDATOR_TRIGGERED_RETRY = "validator_triggered_retry"
    REVIEWER_RERUN_WITH_CONSTRAINT = "reviewer_rerun_with_constraint"
    REVIEWER_EDIT_INTERMEDIATE = "reviewer_edit_intermediate"
    REVIEWER_DIRECTED_MULTIRUN = "reviewer_directed_multirun"
    REVIEWER_REJECTED_CONSOLIDATION = "reviewer_rejected_consolidation"
    REVIEWER_OPENED_DIALOGUE = "reviewer_opened_dialogue"
    REVIEWER_DIALOGUE_TURN = "reviewer_dialogue_turn"
    REVIEWER_EXTENDED_DIALOGUE_BUDGET = "reviewer_extended_dialogue_budget"
    MARK_BRANCH_SETTLED = "mark_branch_settled"
    MARK_BRANCH_ABANDONED = "mark_branch_abandoned"


class Intervention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intervention_id: str
    kind: InterventionKind
    branch_id: str
    step_id: str | None = None
    reviewer_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


__all__ = ["InterventionKind", "Intervention"]
