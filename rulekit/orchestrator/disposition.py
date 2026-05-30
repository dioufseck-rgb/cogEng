"""Disposition records from exercising cases against candidate programs."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rulekit.orchestrator.step import RunCost, utc_now


class DispositionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disposition_id: str
    program_id: str
    program_version: str | None = None
    case_id: str
    determination_id: str
    outcome: str
    expected_outcome: str | None = None
    matched_expected: bool | None = None
    trace: dict[str, Any] | None = None
    load_bearing_path: list[str] = Field(default_factory=list)
    map_latency_s: float | None = Field(default=None, ge=0)
    engine_latency_ms: float | None = Field(default=None, ge=0)
    cost: RunCost | None = None
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = ["DispositionRecord"]
