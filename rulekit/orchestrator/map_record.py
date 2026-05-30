"""Map extraction records for case-to-atom bindings."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rulekit.contract import BindingBasis
from rulekit.orchestrator.step import RunCost, utc_now


class AtomBindingStatus(str, Enum):
    BOUND = "bound"
    UNDETERMINED = "undetermined"
    ERROR = "error"


class AtomBindingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atom_id: str
    atom_type: str
    value: Any = None
    status: AtomBindingStatus
    evidence: str | None = None
    basis: BindingBasis | None = None
    source_ids: list[str] = Field(default_factory=list)
    explanation: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MapExtractionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_record_id: str
    program_id: str
    program_version: str | None = None
    case_id: str
    bindings: dict[str, AtomBindingRecord] = Field(default_factory=dict)
    substrate_id: str = "prebound"
    latency_s: float | None = Field(default=None, ge=0)
    cost: RunCost | None = None
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "AtomBindingStatus",
    "AtomBindingRecord",
    "MapExtractionRecord",
]
