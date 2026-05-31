"""Evidence-aware determination evaluation helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rulekit.contract import BindingBasis, DeterminationProgram
from rulekit.contract.convert import EngineRuntime
from rulekit.engine.boolean import FactBundle, Kleene
from rulekit.orchestrator.map_record import (
    AtomBindingRecord,
    AtomBindingStatus,
    MapExtractionRecord,
)


@dataclass
class DeterminationEvaluation:
    outcome: Kleene
    trace: list[dict[str, Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


def evaluate_determination_with_map_record(
    program: DeterminationProgram,
    runtime: EngineRuntime,
    det_id: str,
    bundle: FactBundle,
    map_record: MapExtractionRecord,
) -> DeterminationEvaluation:
    """Evaluate a determination using both engine facts and Map evidence state.

    The engine remains pure Kleene logic. This helper adds the governed-runtime
    layer that knows whether an undetermined atom came from a conflict, absence,
    validation issue, or plain missing evidence.
    """
    spec = program.determinations[det_id]
    if spec.determination_kind == "routing":
        return _evaluate_routing_determination(program, spec, det_id, map_record)

    outcome, trace = runtime.determinations[det_id].evaluate(bundle)
    if outcome != Kleene.FALSE:
        return DeterminationEvaluation(outcome=outcome, trace=trace)

    override = _false_result_uncertainty_override(
        program,
        runtime,
        det_id,
        bundle,
        map_record,
        trace,
    )
    if override is None:
        return DeterminationEvaluation(outcome=outcome, trace=trace)

    adjusted_trace = list(trace)
    adjusted_trace.append({
        "type": "evidence_uncertainty_override",
        "original_result": str(outcome),
        "result": str(Kleene.UNDETERMINED),
        **override,
    })
    return DeterminationEvaluation(
        outcome=Kleene.UNDETERMINED,
        trace=adjusted_trace,
        metadata={"evidence_uncertainty_override": override},
    )


def _evaluate_routing_determination(
    program: DeterminationProgram,
    spec: Any,
    det_id: str,
    map_record: MapExtractionRecord,
) -> DeterminationEvaluation:
    routing = spec.routing
    trigger_atoms = list(routing.trigger_atoms) or _atoms_for_determination(program, det_id)
    trigger_entries: list[dict[str, Any]] = []
    saw_undetermined = False
    saw_true = False

    for atom_id in trigger_atoms:
        binding = map_record.bindings.get(atom_id)
        entry = _routing_trigger_entry(atom_id, binding, routing)
        trigger_entries.append(entry)
        if entry["route_value"] == "true":
            saw_true = True
        elif entry["route_value"] == "undetermined":
            saw_undetermined = True

    if saw_true:
        outcome = Kleene.TRUE
    elif saw_undetermined:
        outcome = Kleene.UNDETERMINED
    else:
        outcome = Kleene.FALSE

    return DeterminationEvaluation(
        outcome=outcome,
        trace=[
            {
                "type": "routing",
                "determination_id": det_id,
                "mode": routing.mode,
                "trigger_count": len(trigger_entries),
                "true_trigger_count": sum(
                    1 for entry in trigger_entries if entry["route_value"] == "true"
                ),
                "undetermined_trigger_count": sum(
                    1
                    for entry in trigger_entries
                    if entry["route_value"] == "undetermined"
                ),
                "result": str(outcome),
                "children_trace": trigger_entries,
            }
        ],
        metadata={
            "routing": {
                "mode": routing.mode,
                "trigger_atoms": trigger_atoms,
                "true_triggers": [
                    entry["atom_id"]
                    for entry in trigger_entries
                    if entry["route_value"] == "true"
                ],
                "undetermined_triggers": [
                    entry["atom_id"]
                    for entry in trigger_entries
                    if entry["route_value"] == "undetermined"
                ],
            }
        },
    )


def _routing_trigger_entry(
    atom_id: str,
    binding: AtomBindingRecord | None,
    routing: Any,
) -> dict[str, Any]:
    if binding is None:
        route_value = "false"
        status = "missing"
        value = None
        basis = None
        evidence = None
    else:
        status = binding.status.value
        value = binding.value
        basis = binding.basis.value if binding.basis else None
        evidence = binding.evidence
        if binding.status == AtomBindingStatus.ERROR:
            route_value = routing.error_behavior
        elif binding.basis == BindingBasis.CONFLICTING_EVIDENCE:
            route_value = routing.conflict_behavior
        elif binding.status == AtomBindingStatus.BOUND:
            route_value = "true" if _truthy(value) else "false"
        else:
            route_value = routing.missing_behavior
    return {
        "type": "leaf",
        "atom_id": atom_id,
        "value": route_value,
        "route_value": route_value,
        "binding_status": status,
        "binding_value": value,
        "basis": basis,
        "evidence": evidence,
    }


def _false_result_uncertainty_override(
    program: DeterminationProgram,
    runtime: EngineRuntime,
    det_id: str,
    bundle: FactBundle,
    map_record: MapExtractionRecord,
    trace: list[dict[str, Any]],
) -> dict[str, Any] | None:
    atoms = _uncertain_atoms_in_trace(program, map_record, trace)
    if not atoms:
        return None

    optimistic_values = dict(bundle.values)
    for atom_id in atoms:
        atom = program.map_spec.atoms.get(atom_id)
        if atom is None or atom.atom_type != "boolean":
            continue
        optimistic_values[atom_id] = Kleene.TRUE
    optimistic_bundle = FactBundle(values=optimistic_values, evidence=bundle.evidence)
    optimistic_outcome, _ = runtime.determinations[det_id].evaluate(optimistic_bundle)
    force_atoms = [
        atom_id
        for atom_id in atoms
        if _forces_false_uncertainty_override(map_record.bindings[atom_id])
    ]
    if optimistic_outcome == Kleene.FALSE and not force_atoms:
        return None
    return {
        "reason": "false outcome is not stable under unresolved evidence",
        "uncertain_atom_ids": atoms,
        "force_override_atom_ids": force_atoms,
        "optimistic_outcome": str(optimistic_outcome),
    }


def _uncertain_atoms_in_trace(
    program: DeterminationProgram,
    map_record: MapExtractionRecord,
    trace: list[dict[str, Any]],
) -> list[str]:
    atoms = []
    seen = set()
    for atom_id in _leaf_atoms(trace):
        if atom_id in seen:
            continue
        seen.add(atom_id)
        atom = program.map_spec.atoms.get(atom_id)
        binding = map_record.bindings.get(atom_id)
        if atom is None or binding is None:
            continue
        if _is_uncertain(binding):
            atoms.append(atom_id)
    return atoms


def _is_uncertain(binding: AtomBindingRecord) -> bool:
    if binding.status == AtomBindingStatus.ERROR:
        return True
    if binding.status != AtomBindingStatus.BOUND:
        return True
    if binding.basis in {
        BindingBasis.CONFLICTING_EVIDENCE,
        BindingBasis.OPEN_WORLD_ABSENCE,
        BindingBasis.NOT_FOUND,
    }:
        return True
    value = binding.value
    return value is None or str(value).lower() == "undetermined"


def _forces_false_uncertainty_override(binding: AtomBindingRecord) -> bool:
    if binding.basis == BindingBasis.CONFLICTING_EVIDENCE:
        return True
    if binding.status != AtomBindingStatus.BOUND and binding.evidence:
        return True
    return False


def _leaf_atoms(trace: list[dict[str, Any]]) -> list[str]:
    leaves: list[str] = []

    def walk(entries):
        for entry in entries or []:
            if isinstance(entry, list):
                walk(entry)
                continue
            if not isinstance(entry, dict):
                continue
            if entry.get("type") in {"leaf", "numeric_leaf"} and entry.get("atom_id"):
                leaves.append(str(entry["atom_id"]))
            for key in (
                "children_trace",
                "children_traces",
                "child_trace",
                "left_trace",
                "right_trace",
                "condition_trace",
                "if_true_trace",
                "if_false_trace",
            ):
                walk(entry.get(key))

    walk(trace)
    return leaves


def _atoms_for_determination(program: DeterminationProgram, det_id: str) -> list[str]:
    det = program.determinations[det_id]
    root = det.root_node
    if root is None and det.linked_to:
        linked = program.determinations.get(det.linked_to)
        root = linked.root_node if linked else None
    if root is None:
        return []
    return _atoms_for_node(program, root, set())


def _atoms_for_node(
    program: DeterminationProgram,
    node_id: str,
    seen_nodes: set[str],
) -> list[str]:
    if node_id in seen_nodes:
        return []
    seen_nodes.add(node_id)
    node = program.nodes.get(node_id)
    if node is None:
        return []
    atom_id = getattr(node, "atom_id", None)
    if atom_id is not None:
        return [str(atom_id)]
    atoms: list[str] = []
    for child_id in _child_node_ids(node):
        atoms.extend(_atoms_for_node(program, child_id, seen_nodes))
    return atoms


def _child_node_ids(node: Any) -> list[str]:
    child_ids: list[str] = []
    for field_name in ("child", "left", "right", "condition", "if_true", "if_false"):
        value = getattr(node, field_name, None)
        if isinstance(value, str):
            child_ids.append(value)
    children = getattr(node, "children", None)
    if isinstance(children, list):
        child_ids.extend(str(child) for child in children)
    return child_ids


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


__all__ = ["DeterminationEvaluation", "evaluate_determination_with_map_record"]
