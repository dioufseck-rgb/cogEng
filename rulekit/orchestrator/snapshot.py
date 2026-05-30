"""Candidate program snapshots captured during orchestration."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rulekit.contract import DeterminationProgram
from rulekit.orchestrator.step import utc_now


class ProgramSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    program_id: str
    program_version: str | None = None
    program: DeterminationProgram
    created_at: datetime = Field(default_factory=utc_now)
    created_by_event_id: str | None = None
    validation_summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["ProgramSnapshot"]
