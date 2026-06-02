"""Perspective projections for multi-actor policy artifacts."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic import TypeAdapter

from rulekit.contract import AnyNodeSpec, DeterminationProgram, MapSpec


class PerspectiveSpec(BaseModel):
    """Role-scoped view over a shared policy source."""

    model_config = ConfigDict(extra="allow")

    perspective_id: str = Field(min_length=1)
    label: str = ""
    actor: str = ""
    role: str = ""
    description: str = ""
    primary_determinations: list[str] = Field(default_factory=list)
    support_determinations: list[str] = Field(default_factory=list)
    routing_determinations: list[str] = Field(default_factory=list)
    evidence_duties: list[str] = Field(default_factory=list)
    map_profile_rule_ids: list[str] = Field(default_factory=list)
    node_overrides: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def determination_ids(self) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for det_id in (
            self.primary_determinations
            + self.support_determinations
            + self.routing_determinations
        ):
            if det_id not in seen:
                seen.add(det_id)
                ordered.append(det_id)
        return ordered


def list_program_perspectives(program: DeterminationProgram) -> list[PerspectiveSpec]:
    """Return declared perspectives from program metadata."""
    raw = program.metadata.extras.get("perspectives", [])
    if not isinstance(raw, list):
        return []
    return [
        PerspectiveSpec.model_validate(item)
        for item in raw
        if isinstance(item, dict)
    ]


def get_program_perspective(
    program: DeterminationProgram,
    perspective_id: str,
) -> PerspectiveSpec:
    for perspective in list_program_perspectives(program):
        if perspective.perspective_id == perspective_id:
            return perspective
    raise ValueError(f"program does not declare perspective {perspective_id!r}")


def project_program_perspective(
    program: DeterminationProgram,
    perspective_id: str,
) -> DeterminationProgram:
    """Project a program to the DAG closure needed for one perspective.

    The projection is intentionally structural: it does not invent new policy
    logic. It keeps the declared perspective determinations, follows their
    root nodes, includes every referenced node and atom, and preserves the
    perspective metadata so the exported artifact remains traceable to the
    source policy.
    """
    perspective = get_program_perspective(program, perspective_id)
    det_ids = perspective.determination_ids
    missing = [det_id for det_id in det_ids if det_id not in program.determinations]
    if missing:
        raise ValueError(
            f"perspective {perspective_id!r} references unknown determinations: "
            f"{', '.join(missing)}"
        )

    source_nodes = dict(program.nodes)
    for override in perspective.node_overrides:
        node = TypeAdapter(AnyNodeSpec).validate_python(override)
        source_nodes[node.node_id] = node

    included_dets: set[str] = set()
    included_nodes: set[str] = set()
    included_atoms: set[str] = set()

    def include_det(det_id: str) -> None:
        if det_id in included_dets:
            return
        included_dets.add(det_id)
        det = program.determinations[det_id]
        if det.root_node is not None:
            include_node(det.root_node)
        if det.linked_to is not None:
            include_det(det.linked_to)
        if det.routing is not None:
            included_atoms.update(det.routing.trigger_atoms)

    def include_node(node_id: str) -> None:
        if node_id in included_nodes:
            return
        node = source_nodes[node_id]
        included_nodes.add(node_id)
        for atom_id in _node_atom_refs(node):
            included_atoms.add(atom_id)
        for child_id in _node_child_refs(node):
            include_node(child_id)

    for det_id in det_ids:
        include_det(det_id)

    missing_atoms = [
        atom_id for atom_id in sorted(included_atoms)
        if atom_id not in program.map_spec.atoms
    ]
    if missing_atoms:
        raise ValueError(
            f"perspective {perspective_id!r} references unknown atoms: "
            f"{', '.join(missing_atoms)}"
        )

    metadata = program.metadata.model_copy(deep=True)
    metadata.extras = dict(metadata.extras)
    metadata.extras["active_perspective"] = perspective.model_dump(mode="json")
    metadata.extras["source_program_name"] = program.metadata.name
    metadata.name = f"{program.metadata.name} [{perspective.perspective_id}]"

    return program.model_copy(
        deep=True,
        update={
            "metadata": metadata,
            "nodes": {
                node_id: source_nodes[node_id]
                for node_id in source_nodes
                if node_id in included_nodes
            },
            "map_spec": MapSpec(
                atoms={
                    atom_id: program.map_spec.atoms[atom_id]
                    for atom_id in program.map_spec.atoms
                    if atom_id in included_atoms
                },
                default_extraction_template=(
                    program.map_spec.default_extraction_template
                ),
                computed_handlers=_filter_mapping(
                    program.map_spec.computed_handlers,
                    included_atoms,
                ),
                lookup_handlers=_filter_mapping(
                    program.map_spec.lookup_handlers,
                    included_atoms,
                ),
            ),
            "determinations": {
                det_id: program.determinations[det_id]
                for det_id in program.determinations
                if det_id in included_dets
            },
            "test_cases": [
                _filter_test_case(test_case, included_dets)
                for test_case in program.test_cases
                if any(
                    outcome.determination_id in included_dets
                    for outcome in test_case.expected_outcomes
                )
            ],
        },
    )


def _node_atom_refs(node: Any) -> Iterable[str]:
    if node.kind in {"atom_ref", "numeric_atom_ref", "named_quantity"}:
        yield node.atom_id


def _node_child_refs(node: Any) -> Iterable[str]:
    if node.kind in {"and", "or", "at_least", "variadic_arithmetic"}:
        yield from node.children
    elif node.kind in {"not", "unary_arithmetic"}:
        yield node.child
    elif node.kind in {"comparison", "binary_arithmetic"}:
        yield node.left
        yield node.right
    elif node.kind == "conditional_numeric":
        yield node.condition
        yield node.if_true
        yield node.if_false


def _filter_mapping(mapping: dict[str, str], included_atoms: set[str]) -> dict[str, str]:
    return {
        atom_id: value
        for atom_id, value in mapping.items()
        if atom_id in included_atoms
    }


def _filter_test_case(test_case: Any, included_dets: set[str]) -> Any:
    outcomes = [
        outcome
        for outcome in test_case.expected_outcomes
        if outcome.determination_id in included_dets
    ]
    return test_case.model_copy(update={"expected_outcomes": outcomes})


__all__ = [
    "PerspectiveSpec",
    "get_program_perspective",
    "list_program_perspectives",
    "project_program_perspective",
]
