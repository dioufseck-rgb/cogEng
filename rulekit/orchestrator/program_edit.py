"""Typed candidate-program edit operations for governed revisions."""
from __future__ import annotations

import hashlib
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rulekit.contract import (
    AndNodeSpec,
    AtLeastNodeSpec,
    AtomRef,
    BooleanAtom,
    DeterminationProgram,
    DeterminationSpec,
    EvaluationMode,
    NotNodeSpec,
    OrNodeSpec,
    Provenance,
    validate_program,
)
from rulekit.orchestrator.factory import BooleanOperator
from rulekit.orchestrator.ids import new_id


class ProgramEditKind(str, Enum):
    ADD_BOOLEAN_ATOM = "add_boolean_atom"
    UPDATE_BOOLEAN_ATOM = "update_boolean_atom"
    ADD_ATOM_REF_NODE = "add_atom_ref_node"
    ADD_BOOLEAN_OPERATOR_NODE = "add_boolean_operator_node"
    ADD_DETERMINATION = "add_determination"
    SET_DETERMINATION_ROOT = "set_determination_root"


class ProgramEditOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ProgramEditKind
    payload: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    reviewer_id: str | None = None


class ProgramEditResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    edit_id: str
    program: DeterminationProgram
    operations: list[ProgramEditOperation]
    before_hash: str
    after_hash: str
    validation_summary: str


def apply_program_edits(
    program: DeterminationProgram,
    operations: list[ProgramEditOperation],
) -> ProgramEditResult:
    """Apply typed edits and return a validated candidate program copy."""
    edited = program.model_copy(deep=True)
    before_hash = program_hash(program)
    for operation in operations:
        _apply_operation(edited, operation)

    report = validate_program(edited)
    if not report.ok:
        raise ValueError(report.summary())

    return ProgramEditResult(
        edit_id=new_id("edit"),
        program=edited,
        operations=list(operations),
        before_hash=before_hash,
        after_hash=program_hash(edited),
        validation_summary=report.summary(),
    )


def program_hash(program: DeterminationProgram) -> str:
    payload = program.model_dump_json(by_alias=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _apply_operation(
    program: DeterminationProgram,
    operation: ProgramEditOperation,
) -> None:
    payload = operation.payload
    if operation.kind == ProgramEditKind.ADD_BOOLEAN_ATOM:
        atom_id = _required(payload, "atom_id")
        if atom_id in program.map_spec.atoms:
            raise ValueError(f"atom {atom_id!r} already exists")
        statement = _required(payload, "statement")
        program.map_spec.atoms[atom_id] = BooleanAtom(
            id=atom_id,
            statement=statement,
            source_span=payload.get("source_span") or statement,
            evaluation_mode=EvaluationMode(payload.get("evaluation_mode", "characterized")),
            extraction_template=payload.get("extraction_template"),
            undetermined_rule=payload.get("undetermined_rule", ""),
            notes=payload.get("notes", ""),
        )
    elif operation.kind == ProgramEditKind.UPDATE_BOOLEAN_ATOM:
        atom_id = _required(payload, "atom_id")
        atom = program.map_spec.atoms.get(atom_id)
        if atom is None:
            raise ValueError(f"atom {atom_id!r} does not exist")
        if atom.atom_type != "boolean":
            raise ValueError(f"atom {atom_id!r} is not boolean")
        updates = {
            key: value
            for key, value in payload.items()
            if key
            in {
                "statement",
                "source_span",
                "evaluation_mode",
                "extraction_template",
                "undetermined_rule",
                "notes",
            }
        }
        if "evaluation_mode" in updates:
            updates["evaluation_mode"] = EvaluationMode(updates["evaluation_mode"])
        program.map_spec.atoms[atom_id] = atom.model_copy(update=updates)
    elif operation.kind == ProgramEditKind.ADD_ATOM_REF_NODE:
        node_id = _required(payload, "node_id")
        atom_id = _required(payload, "atom_id")
        _ensure_new_node(program, node_id)
        atom = program.map_spec.atoms.get(atom_id)
        if atom is None:
            raise ValueError(f"atom {atom_id!r} does not exist")
        program.nodes[node_id] = AtomRef(
            node_id=node_id,
            provenance=Provenance(payload.get("provenance", Provenance.TRANSCRIBED.value)),
            source_span=payload.get("source_span") or atom.source_span,
            surface_label=payload.get("surface_label", ""),
            atom_id=atom_id,
        )
    elif operation.kind == ProgramEditKind.ADD_BOOLEAN_OPERATOR_NODE:
        node_id = _required(payload, "node_id")
        operator = BooleanOperator(_required(payload, "operator"))
        children = list(payload.get("children", []))
        _ensure_new_node(program, node_id)
        for child in children:
            if child not in program.nodes:
                raise ValueError(f"child node {child!r} does not exist")
        common = dict(
            node_id=node_id,
            provenance=Provenance(payload.get("provenance", Provenance.STRUCTURAL.value)),
            source_span=payload.get("source_span", ""),
            surface_label=payload.get("surface_label", ""),
        )
        if operator == BooleanOperator.AND:
            program.nodes[node_id] = AndNodeSpec(children=children, **common)
        elif operator == BooleanOperator.OR:
            program.nodes[node_id] = OrNodeSpec(children=children, **common)
        elif operator == BooleanOperator.NOT:
            if len(children) != 1:
                raise ValueError("not requires exactly one child")
            program.nodes[node_id] = NotNodeSpec(child=children[0], **common)
        elif operator == BooleanOperator.AT_LEAST:
            n = payload.get("n")
            if n is None:
                raise ValueError("at_least requires n")
            program.nodes[node_id] = AtLeastNodeSpec(n=n, children=children, **common)
    elif operation.kind == ProgramEditKind.ADD_DETERMINATION:
        det_id = _required(payload, "determination_id")
        if det_id in program.determinations:
            raise ValueError(f"determination {det_id!r} already exists")
        root_node = _required(payload, "root_node")
        if root_node not in program.nodes:
            raise ValueError(f"root node {root_node!r} does not exist")
        program.determinations[det_id] = DeterminationSpec(
            id=det_id,
            description=_required(payload, "description"),
            polarity=payload.get("polarity", "neutral"),
            source_span=payload.get("source_span", ""),
            root_node=root_node,
        )
    elif operation.kind == ProgramEditKind.SET_DETERMINATION_ROOT:
        det_id = _required(payload, "determination_id")
        root_node = _required(payload, "root_node")
        determination = program.determinations.get(det_id)
        if determination is None:
            raise ValueError(f"determination {det_id!r} does not exist")
        if root_node not in program.nodes:
            raise ValueError(f"root node {root_node!r} does not exist")
        program.determinations[det_id] = determination.model_copy(
            update={
                "composition": "derived",
                "root_node": root_node,
                "linked_to": None,
            }
        )
    else:
        raise ValueError(f"unsupported edit kind {operation.kind!r}")


def _required(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value is None or value == "":
        raise ValueError(f"edit payload requires {key!r}")
    return value


def _ensure_new_node(program: DeterminationProgram, node_id: str) -> None:
    if node_id in program.nodes:
        raise ValueError(f"node {node_id!r} already exists")


__all__ = [
    "ProgramEditKind",
    "ProgramEditOperation",
    "ProgramEditResult",
    "apply_program_edits",
    "program_hash",
]
