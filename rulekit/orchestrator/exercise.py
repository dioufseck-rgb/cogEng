"""Exercise candidate DeterminationPrograms against case examples."""
from __future__ import annotations

from decimal import Decimal
from time import perf_counter
from typing import Any

from rulekit.contract import DeterminationProgram, safe_program_to_engine, validate_program
from rulekit.engine.boolean import FactBundle, Kleene
from rulekit.engine.typed import NumericValue
from rulekit.orchestrator.cases import CaseExample
from rulekit.orchestrator.disposition import DispositionRecord
from rulekit.orchestrator.ids import new_id
from rulekit.orchestrator.map_step import MapStep, MapStepContext
from rulekit.orchestrator.map_record import (
    AtomBindingRecord,
    AtomBindingStatus,
    MapExtractionRecord,
)


def fact_bundle_from_values(
    program: DeterminationProgram,
    values: dict[str, Any],
    *,
    evidence: dict[str, str] | None = None,
) -> FactBundle:
    """Build a typed FactBundle using the program atom catalog."""
    bound: dict[str, Any] = {}
    for atom_id, raw in values.items():
        atom = program.map_spec.atoms.get(atom_id)
        if atom is None:
            raise ValueError(f"fact value references unknown atom {atom_id!r}")
        if atom.atom_type == "boolean":
            bound[atom_id] = _coerce_kleene(raw)
        elif atom.atom_type == "numeric":
            bound[atom_id] = _coerce_numeric(raw)
        else:
            raise ValueError(f"unknown atom_type {atom.atom_type!r}")
    return FactBundle(values=bound, evidence=evidence or {})


def exercise_program_on_case(
    program: DeterminationProgram,
    case: CaseExample,
    fact_values: dict[str, Any],
    *,
    program_id: str,
    program_version: str | None = None,
    evidence: dict[str, str] | None = None,
) -> list[DispositionRecord]:
    """Evaluate all expected determinations for one case.

    The fact values are pre-bound atom values. This keeps v0.1 focused on
    orchestration and runtime exercise while Map remains a separate stage.
    """
    report = validate_program(program)
    if not report.ok:
        raise ValueError(report.summary())

    map_record, records = exercise_program_on_case_with_map(
        program,
        case,
        fact_values,
        program_id=program_id,
        program_version=program_version,
        evidence=evidence,
    )
    return records


def map_record_from_values(
    program: DeterminationProgram,
    case: CaseExample,
    fact_values: dict[str, Any],
    *,
    program_id: str,
    program_version: str | None = None,
    evidence: dict[str, str] | None = None,
    substrate_id: str = "prebound",
) -> MapExtractionRecord:
    bindings: dict[str, AtomBindingRecord] = {}
    evidence = evidence or {}
    for atom_id, atom in program.map_spec.atoms.items():
        raw = fact_values.get(atom_id)
        status = (
            AtomBindingStatus.UNDETERMINED
            if raw is None or str(raw).lower() == "undetermined"
            else AtomBindingStatus.BOUND
        )
        bindings[atom_id] = AtomBindingRecord(
            atom_id=atom_id,
            atom_type=atom.atom_type,
            value=_jsonable_value(raw),
            status=status,
            evidence=evidence.get(atom_id),
            source=substrate_id,
        )
    return MapExtractionRecord(
        map_record_id=new_id("map"),
        program_id=program_id,
        program_version=program_version,
        case_id=case.case_id,
        bindings=bindings,
        substrate_id=substrate_id,
        latency_s=0.0,
        metadata={"prebound_fact_count": len(fact_values)},
    )


def exercise_program_on_case_with_map(
    program: DeterminationProgram,
    case: CaseExample,
    fact_values: dict[str, Any],
    *,
    program_id: str,
    program_version: str | None = None,
    evidence: dict[str, str] | None = None,
) -> tuple[MapExtractionRecord, list[DispositionRecord]]:
    """Evaluate one case and return the Map record plus dispositions."""
    report = validate_program(program)
    if not report.ok:
        raise ValueError(report.summary())

    started = perf_counter()
    map_record = map_record_from_values(
        program,
        case,
        fact_values,
        program_id=program_id,
        program_version=program_version,
        evidence=evidence,
    )
    bundle = fact_bundle_from_values(program, fact_values, evidence=evidence)
    runtime = safe_program_to_engine(program)
    records: list[DispositionRecord] = []
    for expected in case.expected_outcomes:
        determination = runtime.determinations[expected.determination_id]
        eval_started = perf_counter()
        outcome, trace = determination.evaluate(bundle)
        engine_latency_ms = (perf_counter() - eval_started) * 1000
        records.append(
            DispositionRecord(
                disposition_id=new_id("disp"),
                program_id=program_id,
                program_version=program_version,
                case_id=case.case_id,
                determination_id=expected.determination_id,
                outcome=str(outcome),
                expected_outcome=expected.expected_value,
                matched_expected=str(outcome) == expected.expected_value,
                trace={"trace": trace},
                load_bearing_path=extract_leaf_path(trace),
                map_latency_s=0.0,
                engine_latency_ms=engine_latency_ms,
                metadata={
                    "case_title": case.title,
                    "map_record_id": map_record.map_record_id,
                    "prebound_fact_count": len(fact_values),
                    "exercise_latency_s": perf_counter() - started,
                },
            )
        )
    return map_record, records


def exercise_program_on_case_with_map_record(
    program: DeterminationProgram,
    case: CaseExample,
    map_record: MapExtractionRecord,
    *,
    program_id: str,
    program_version: str | None = None,
) -> list[DispositionRecord]:
    """Evaluate one case using an already-produced MapExtractionRecord."""
    report = validate_program(program)
    if not report.ok:
        raise ValueError(report.summary())

    started = perf_counter()
    bundle = fact_bundle_from_values(
        program,
        fact_values_from_map_record(map_record),
        evidence={
            atom_id: binding.evidence
            for atom_id, binding in map_record.bindings.items()
            if binding.evidence
        },
    )
    runtime = safe_program_to_engine(program)
    records: list[DispositionRecord] = []
    for expected in case.expected_outcomes:
        determination = runtime.determinations[expected.determination_id]
        eval_started = perf_counter()
        outcome, trace = determination.evaluate(bundle)
        engine_latency_ms = (perf_counter() - eval_started) * 1000
        records.append(
            DispositionRecord(
                disposition_id=new_id("disp"),
                program_id=program_id,
                program_version=program_version,
                case_id=case.case_id,
                determination_id=expected.determination_id,
                outcome=str(outcome),
                expected_outcome=expected.expected_value,
                matched_expected=str(outcome) == expected.expected_value,
                trace={"trace": trace},
                load_bearing_path=extract_leaf_path(trace),
                map_latency_s=map_record.latency_s,
                engine_latency_ms=engine_latency_ms,
                metadata={
                    "case_title": case.title,
                    "map_record_id": map_record.map_record_id,
                    "exercise_latency_s": perf_counter() - started,
                },
            )
        )
    return records


def exercise_program_on_suite(
    program: DeterminationProgram,
    cases: list[CaseExample],
    facts_by_case_id: dict[str, dict[str, Any]],
    *,
    program_id: str,
    program_version: str | None = None,
) -> list[DispositionRecord]:
    records: list[DispositionRecord] = []
    for case in cases:
        records.extend(
            exercise_program_on_case(
                program,
                case,
                facts_by_case_id.get(case.case_id, {}),
                program_id=program_id,
                program_version=program_version,
            )
        )
    return records


def exercise_program_on_suite_with_map(
    program: DeterminationProgram,
    cases: list[CaseExample],
    facts_by_case_id: dict[str, dict[str, Any]],
    *,
    program_id: str,
    program_version: str | None = None,
) -> tuple[list[MapExtractionRecord], list[DispositionRecord]]:
    map_records: list[MapExtractionRecord] = []
    dispositions: list[DispositionRecord] = []
    for case in cases:
        map_record, case_records = exercise_program_on_case_with_map(
            program,
            case,
            facts_by_case_id.get(case.case_id, {}),
            program_id=program_id,
            program_version=program_version,
        )
        map_records.append(map_record)
        dispositions.extend(case_records)
    return map_records, dispositions


def exercise_program_on_suite_with_map_step(
    program: DeterminationProgram,
    cases: list[CaseExample],
    map_step: MapStep,
    *,
    program_id: str,
    program_version: str | None = None,
    workspace_id: str | None = None,
    trajectory_id: str | None = None,
) -> tuple[list[MapExtractionRecord], list[DispositionRecord]]:
    map_records: list[MapExtractionRecord] = []
    dispositions: list[DispositionRecord] = []
    context = MapStepContext(
        workspace_id=workspace_id,
        trajectory_id=trajectory_id,
        program_id=program_id,
        program_version=program_version,
        substrate_id=map_step.spec.map_step_id,
    )
    for case in cases:
        result = map_step.run(program, case, context)
        map_records.append(result.map_record)
        dispositions.extend(
            exercise_program_on_case_with_map_record(
                program,
                case,
                result.map_record,
                program_id=program_id,
                program_version=program_version,
            )
        )
    return map_records, dispositions


def extract_leaf_path(trace: list[dict[str, Any]]) -> list[str]:
    """Extract atom IDs present in an engine trace.

    Mixed typed traces can place numeric leaves under comparison
    `left_trace` / `right_trace`, arithmetic `child_trace`, and
    conditional numeric branch traces. Walk all known trace containers so
    appeal/review records include both boolean and numeric load-bearing
    facts.
    """
    leaves: list[str] = []

    def walk(entries):
        for entry in entries or []:
            if isinstance(entry, list):
                walk(entry)
                continue
            if entry.get("type") in {"leaf", "numeric_leaf"}:
                leaves.append(entry.get("atom_id", ""))
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
    return [leaf for leaf in leaves if leaf]


def fact_values_from_map_record(map_record: MapExtractionRecord) -> dict[str, Any]:
    return {
        atom_id: binding.value
        for atom_id, binding in map_record.bindings.items()
        if binding.status == AtomBindingStatus.BOUND
    }


def _coerce_kleene(value: Any) -> Kleene:
    if isinstance(value, Kleene):
        return value
    if isinstance(value, bool):
        return Kleene.TRUE if value else Kleene.FALSE
    if value is None:
        return Kleene.UNDETERMINED
    return Kleene(str(value).lower())


def _coerce_numeric(value: Any) -> NumericValue:
    if isinstance(value, NumericValue):
        return value
    if value is None or str(value).lower() == "undetermined":
        return NumericValue.undetermined()
    if isinstance(value, Decimal):
        return NumericValue.of(value)
    return NumericValue.of(value)


def _jsonable_value(value: Any) -> Any:
    if isinstance(value, Kleene):
        return value.value
    if isinstance(value, NumericValue):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    return value


__all__ = [
    "fact_bundle_from_values",
    "map_record_from_values",
    "exercise_program_on_case",
    "exercise_program_on_case_with_map",
    "exercise_program_on_case_with_map_record",
    "exercise_program_on_suite",
    "exercise_program_on_suite_with_map",
    "exercise_program_on_suite_with_map_step",
    "extract_leaf_path",
    "fact_values_from_map_record",
]
