"""Governed Map step protocol for case-to-atom extraction."""
from __future__ import annotations

from enum import Enum
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from rulekit.contract import BindingBasis
from rulekit.contract import DeterminationProgram
from rulekit.engine.boolean import Kleene
from rulekit.engine.typed import AtomType, NumericValue
from rulekit.map.typed import TypedAtom, TypedNarrativeLLMSubstrate
from rulekit.orchestrator.cases import CaseExample
from rulekit.orchestrator.hints import ReviewerHint
from rulekit.orchestrator.ids import new_id
from rulekit.orchestrator.map_record import (
    AtomBindingRecord,
    AtomBindingStatus,
    MapExtractionRecord,
)
from rulekit.schema import Atom


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
    reviewer_hints: list[ReviewerHint] = Field(default_factory=list)
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
        binding_bases = _dict_from_structured(case.structured_fields, "binding_bases")
        binding_source_ids = _dict_from_structured(case.structured_fields, "binding_source_ids")
        binding_explanations = _dict_from_structured(
            case.structured_fields,
            "binding_explanations",
        )
        reviewer_hints = [
            hint for hint in context.reviewer_hints if hint.applies_to_case(case.case_id)
        ]
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
                basis=_basis_for(raw, status, binding_bases.get(atom_id)),
                source_ids=_source_ids_for(binding_source_ids.get(atom_id)),
                explanation=(
                    str(binding_explanations[atom_id])
                    if atom_id in binding_explanations
                    else None
                ),
                source=context.substrate_id,
            )
        default_count = apply_case_default_bindings(
            program,
            case,
            bindings,
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
                    "default_binding_count": default_count,
                    "reviewer_hint_count": len(reviewer_hints),
                    "reviewer_hints": [
                        hint.model_dump(mode="json") for hint in reviewer_hints
                    ],
                },
            )
        )


class TypedNarrativeMapStep:
    """Map step that binds case narrative to boolean and numeric atoms.

    This is the orchestrator bridge to the existing typed LLM substrate:
    natural case text is converted into a typed FactBundle, then persisted
    as a governed MapExtractionRecord for downstream deterministic engine
    evaluation.
    """

    def __init__(
        self,
        llm: Any,
        *,
        map_step_id: str = "map_typed_narrative",
        batch_size: int | None = None,
    ):
        self.substrate = TypedNarrativeLLMSubstrate(llm=llm, batch_size=batch_size)
        self.spec = MapStepSpec(
            map_step_id=map_step_id,
            name="Typed narrative Map step",
            description="Binds natural-language case narratives to boolean and numeric atoms.",
            kind=MapStepKind.STOCHASTIC,
            input_schema={"case": "narrative", "program": "DeterminationProgram"},
            output_schema={"map_record": "MapExtractionRecord"},
        )

    def run(
        self,
        program: DeterminationProgram,
        case: CaseExample,
        context: MapStepContext,
    ) -> MapStepResult:
        started = perf_counter()
        typed_atoms = _typed_atoms_from_program(program)
        reviewer_hints = [
            hint for hint in context.reviewer_hints if hint.applies_to_case(case.case_id)
        ]
        evidence = _narrative_with_reviewer_hints(case.narrative, reviewer_hints)
        bundle = self.substrate.bind_typed(evidence, typed_atoms)
        bindings: dict[str, AtomBindingRecord] = {}
        for atom_id, atom in program.map_spec.atoms.items():
            raw = bundle.values.get(atom_id)
            status = _binding_status(raw)
            bindings[atom_id] = AtomBindingRecord(
                atom_id=atom_id,
                atom_type=atom.atom_type,
                value=_jsonable_binding_value(raw),
                status=status,
                basis=(
                    BindingBasis.INFERRED_FROM_RECORD
                    if status == AtomBindingStatus.BOUND
                    else BindingBasis.NOT_FOUND
                ),
                evidence=evidence if status == AtomBindingStatus.BOUND else None,
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
                    "atom_count": len(program.map_spec.atoms),
                    "case_title": case.title,
                    "reviewer_hint_count": len(reviewer_hints),
                    "reviewer_hints": [
                        hint.model_dump(mode="json") for hint in reviewer_hints
                    ],
                },
            )
        )


def facts_from_case_fields(structured_fields: dict[str, Any]) -> dict[str, Any]:
    facts = structured_fields.get("facts")
    if isinstance(facts, dict):
        return dict(facts)
    return dict(structured_fields)


def apply_case_default_bindings(
    program: DeterminationProgram,
    case: CaseExample,
    bindings: dict[str, AtomBindingRecord],
    *,
    source: str | None = None,
) -> int:
    """Apply audited case-packet defaults to missing or undetermined bindings.

    The default mechanism is intentionally data-driven: domains can enrich case
    packets with `structured_fields.default_bindings` instead of adding Python.
    Defaults still pass through normal Map validation downstream.
    """
    defaults = _case_default_binding_payloads(case.structured_fields)
    applied = 0
    for atom_id, payload in defaults.items():
        if atom_id not in program.map_spec.atoms:
            continue
        default = payload if isinstance(payload, dict) else {"value": payload}
        apply_when = str(default.get("apply_when", "missing_or_undetermined"))
        existing = bindings.get(atom_id)
        if not _should_apply_default(existing, apply_when):
            continue
        atom = program.map_spec.atoms[atom_id]
        value = default.get("value", "undetermined")
        status = _binding_status_from_value(value)
        basis = _basis_for(value, status, default.get("basis"))
        bindings[atom_id] = AtomBindingRecord(
            atom_id=atom_id,
            atom_type=atom.atom_type,
            value=value,
            status=status,
            evidence=(
                str(default["evidence"])
                if default.get("evidence") is not None
                else _evidence_for(case.structured_fields, atom_id)
            ),
            basis=basis,
            source_ids=_source_ids_for(default.get("source_ids")),
            explanation=(
                str(default["explanation"])
                if default.get("explanation") is not None
                else "case packet default binding"
            ),
            confidence=float(default["confidence"])
            if default.get("confidence") is not None
            else None,
            source=source or "case_default",
            metadata={
                "case_default": True,
                "default_apply_when": apply_when,
                "replaced_status": existing.status.value if existing else None,
                "replaced_basis": existing.basis.value if existing and existing.basis else None,
            },
        )
        applied += 1
    return applied


def _case_default_binding_payloads(structured_fields: dict[str, Any]) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    groups = structured_fields.get("default_binding_groups")
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, dict):
                continue
            atom_ids = group.get("atom_ids")
            if not isinstance(atom_ids, list):
                continue
            payload = {key: value for key, value in group.items() if key != "atom_ids"}
            for atom_id in atom_ids:
                defaults[str(atom_id)] = dict(payload)
    defaults.update(_dict_from_structured(structured_fields, "default_bindings"))
    return defaults


def _should_apply_default(
    existing: AtomBindingRecord | None,
    apply_when: str,
) -> bool:
    if apply_when == "always":
        return True
    if existing is None:
        return True
    if apply_when == "missing":
        return False
    if apply_when == "missing_or_not_found":
        return existing.basis == BindingBasis.NOT_FOUND
    if existing.status != AtomBindingStatus.BOUND:
        return True
    return existing.basis in {
        BindingBasis.NOT_FOUND,
        BindingBasis.OPEN_WORLD_ABSENCE,
    }


def _binding_status_from_value(value: Any) -> AtomBindingStatus:
    if value is None or str(value).lower() == "undetermined":
        return AtomBindingStatus.UNDETERMINED
    return AtomBindingStatus.BOUND


def _evidence_for(structured_fields: dict[str, Any], atom_id: str) -> str | None:
    evidence = structured_fields.get("evidence")
    if isinstance(evidence, dict):
        value = evidence.get(atom_id)
        return str(value) if value is not None else None
    return None


def _dict_from_structured(structured_fields: dict[str, Any], key: str) -> dict[str, Any]:
    value = structured_fields.get(key)
    return dict(value) if isinstance(value, dict) else {}


def _basis_for(
    raw: Any,
    status: AtomBindingStatus,
    declared_basis: Any,
) -> BindingBasis | None:
    if declared_basis:
        return BindingBasis(str(declared_basis))
    if status == AtomBindingStatus.UNDETERMINED:
        return BindingBasis.NOT_FOUND
    if isinstance(raw, bool):
        return BindingBasis.EXPLICIT_POSITIVE if raw else BindingBasis.EXPLICIT_NEGATIVE
    if str(raw).lower() == "true":
        return BindingBasis.EXPLICIT_POSITIVE
    if str(raw).lower() == "false":
        return BindingBasis.EXPLICIT_NEGATIVE
    return BindingBasis.EXPLICIT_POSITIVE


def _source_ids_for(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _typed_atoms_from_program(program: DeterminationProgram) -> dict[str, TypedAtom]:
    typed_atoms: dict[str, TypedAtom] = {}
    for atom_id, atom in program.map_spec.atoms.items():
        schema_atom = Atom(
            id=atom.id,
            statement=atom.statement,
            source_span=atom.source_span,
            notes=atom.notes,
            atom_type=atom.atom_type,
        )
        atom_type = AtomType.NUMERIC if atom.atom_type == "numeric" else AtomType.BOOLEAN
        typed_atoms[atom_id] = TypedAtom(schema_atom, atom_type)
    return typed_atoms


def _narrative_with_reviewer_hints(
    narrative: str,
    reviewer_hints: list[ReviewerHint],
) -> str:
    if not reviewer_hints:
        return narrative
    lines = [narrative, "", "REVIEWER HINTS FOR THIS RERUN:"]
    for hint in reviewer_hints:
        target = f" atoms={','.join(hint.atom_ids)}" if hint.atom_ids else ""
        lines.append(f"- {hint.message}{target}")
    return "\n".join(lines)


def _binding_status(value: Any) -> AtomBindingStatus:
    if value is None:
        return AtomBindingStatus.UNDETERMINED
    if isinstance(value, NumericValue):
        return (
            AtomBindingStatus.UNDETERMINED
            if value.is_undetermined
            else AtomBindingStatus.BOUND
        )
    if isinstance(value, Kleene):
        return (
            AtomBindingStatus.UNDETERMINED
            if value == Kleene.UNDETERMINED
            else AtomBindingStatus.BOUND
        )
    return AtomBindingStatus.BOUND


def _jsonable_binding_value(value: Any) -> Any:
    if isinstance(value, NumericValue):
        return "undetermined" if value.is_undetermined else str(value.value)
    if isinstance(value, Kleene):
        return value.value
    return value


__all__ = [
    "MapStepKind",
    "MapStepSpec",
    "MapStepContext",
    "MapStepResult",
    "MapStep",
    "PreboundFactsMapStep",
    "TypedNarrativeMapStep",
    "apply_case_default_bindings",
    "facts_from_case_fields",
]
