"""Case suite models for orchestrator workspaces."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CaseProvenance(str, Enum):
    AUTHORED = "authored"
    IMPORTED = "imported"
    ANONYMIZED_REAL = "anonymized_real"


class ExpectedOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    determination_id: str = Field(min_length=1)
    expected_value: str = Field(min_length=1)
    rationale: str | None = None


class CaseExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    narrative: str = Field(min_length=1)
    structured_fields: dict[str, Any] = Field(default_factory=dict)
    expected_outcomes: list[ExpectedOutcome] = Field(default_factory=list)
    provenance: CaseProvenance = CaseProvenance.AUTHORED
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    cases: dict[str, CaseExample] = Field(default_factory=dict)
    attached_program_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "CaseProvenance",
    "ExpectedOutcome",
    "CaseExample",
    "CaseSuite",
]
