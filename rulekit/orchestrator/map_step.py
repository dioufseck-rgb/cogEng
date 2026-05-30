"""Governed Map step protocol for case-to-atom extraction."""
from __future__ import annotations

from enum import Enum
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from rulekit.contract import DeterminationProgram
from rulekit.orchestrator.cases import CaseExample
from rulekit.orchestrator.ids import new_id
from rulekit.orchestrator.map_record import (
    AtomBindingRecord,
    AtomBindingStatus,
    MapExtractionRecord,
)


class MapStepKind(str, Enum):
    DETERMINISTIC = "deterministic"
    STOCHASTIC = "stochastic"


class MapStepSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_step_id: str
    name: str
    description: str = ""
    kind: MapStepKind = MapStepKind.DETERMINISTIC
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MapStepContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str | None = None
    trajectory_id: str | None = None
    program_id: str
    program_version: str | None = None
    substrate_id: str = "prebound"
    metadata: dict[str, Any] = Field(default_factory=dict)


class MapStepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_record: MapExtractionRecord
    messages: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MapStep(Protocol):
    spec: MapStepSpec

    def run(
        self,
        program: DeterminationProgram,
        case: CaseExample,
        context: MapStepContext,
    ) -> MapStepResult:
        ...


class PreboundFactsMapStep:
    """Map step that reads already-bound facts from case structured fields."""

    def __init__(self, *, map_step_id: str = "map_prebound_facts"):
        self.spec = MapStepSpec(
            map_step_id=map_step_id,
            name="Prebound facts Map step",
            description="Reads atom values from structured_fields.facts or flat structured fields.",
        )

    def run(
        self,
        program: DeterminationProgram,
        case: CaseExample,
        context: MapStepContext,
    ) -> MapStepResult:
        started = perf_counter()
        facts = facts_from_case_fields(case.structured_fields)
        bindings: dict[str, AtomBindingRecord] = {}
        for atom_id, atom in program.map_spec.atoms.items():
            raw = facts.get(atom_id)
            status = (
                AtomBindingStatus.UNDETERMINED
                if raw is None or str(raw).lower() == "undetermined"
                else AtomBindingStatus.BOUND
            )
            bindings[atom_id] = AtomBindingRecord(
                atom_id=atom_id,
                atom_type=atom.atom_type,
                value=raw,
                status=status,
                evidence=_evidence_for(case.structured_fields, atom_id),
                source=context.substrate_id,
            )
        return MapStepResult(
            map_record=MapExtractionRecord(
                map_record_id=new_id("map"),
                program_id=context.program_id,
                program_version=context.program_version,
                case_id=case.case_id,
                bindings=bindings,
                substrate_id=context.substrate_id,
                latency_s=perf_counter() - started,
                metadata={
                    "map_step_id": self.spec.map_step_id,
                    "fact_count": len(facts),
                },
            )
        )


def facts_from_case_fields(structured_fields: dict[str, Any]) -> dict[str, Any]:
    facts = structured_fields.get("facts")
    if isinstance(facts, dict):
        return dict(facts)
    return dict(structured_fields)


def _evidence_for(structured_fields: dict[str, Any], atom_id: str) -> str | None:
    evidence = structured_fields.get("evidence")
    if isinstance(evidence, dict):
        value = evidence.get(atom_id)
        return str(value) if value is not None else None
    return None


__all__ = [
    "MapStepKind",
    "MapStepSpec",
    "MapStepContext",
    "MapStepResult",
    "MapStep",
    "PreboundFactsMapStep",
    "facts_from_case_fields",
]
