"""Runtime runner for deployable RuleKit programs."""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic_core import to_jsonable_python

from rulekit.contract import BindingBasis, DeterminationProgram, safe_program_to_engine, validate_program
from rulekit.orchestrator.cases import CaseExample, ExpectedOutcome
from rulekit.orchestrator.disposition import DispositionRecord
from rulekit.orchestrator.evaluation import evaluate_determination_with_map_record
from rulekit.orchestrator.exercise import (
    extract_leaf_path,
    fact_bundle_from_values,
    fact_values_from_map_record,
)
from rulekit.orchestrator.ids import new_id
from rulekit.orchestrator.llm_config import create_map_step
from rulekit.orchestrator.map_record import AtomBindingStatus, MapExtractionRecord
from rulekit.orchestrator.map_step import MapStep, MapStepContext
from rulekit.orchestrator.map_validation import (
    MapValidationReport,
    apply_map_validation,
    evidence_sources_from_case_fields,
)


def load_program(path: str | Path) -> DeterminationProgram:
    """Load a deployable DeterminationProgram JSON artifact."""
    return DeterminationProgram.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_runtime_cases(path: str | Path) -> list[CaseExample]:
    """Load runtime cases from JSON/YAML.

    Accepted shapes:
    - a list of case objects
    - {"cases": [...]} for CLI-friendly files

    Each case can be a full CaseExample or a compact runtime case with
    top-level ``facts`` and dict-shaped ``expected_outcomes``.
    """
    path = Path(path)
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "cases" in payload:
        payload = payload["cases"]
    if not isinstance(payload, list):
        raise ValueError("cases file must be a list or an object with a 'cases' list")
    return [_case_from_payload(item, index) for index, item in enumerate(payload)]


def adjudicate_cases(
    program: DeterminationProgram,
    cases: list[CaseExample],
    *,
    determinations: list[str] | None = None,
    map_step: MapStep | None = None,
    program_id: str | None = None,
    program_version: str | None = None,
    repair_unresolved: bool = False,
    max_repair_atoms: int = 12,
) -> dict[str, Any]:
    """Run cases through Map and the deterministic RuleKit engine."""
    report = validate_program(program)
    if not report.ok:
        raise ValueError(report.summary())
    selected_determinations = determinations or list(program.determinations)
    runtime = safe_program_to_engine(program)
    unknown = [det_id for det_id in selected_determinations if det_id not in runtime.determinations]
    if unknown:
        raise ValueError(f"unknown determination ids: {', '.join(unknown)}")

    resolved_program_id = program_id or program.metadata.name
    resolved_program_version = program_version or program.metadata.version
    active_map_step = map_step or create_map_step(map_mode="prebound")
    context = MapStepContext(
        program_id=resolved_program_id,
        program_version=resolved_program_version,
        substrate_id=active_map_step.spec.map_step_id,
        metadata={"determinations": selected_determinations},
    )
    map_records: list[MapExtractionRecord] = []
    map_validation_reports: list[MapValidationReport] = []
    dispositions: list[DispositionRecord] = []

    for case in cases:
        map_result = active_map_step.run(program, case, context)
        evidence_sources = evidence_sources_from_case_fields(case.structured_fields)
        map_record, map_validation = apply_map_validation(
            program,
            map_result.map_record,
            evidence_sources=evidence_sources,
        )
        expected = {
            item.determination_id: item.expected_value
            for item in case.expected_outcomes
        }
        case_dispositions = _evaluate_case_dispositions(
            program,
            runtime,
            case,
            selected_determinations,
            map_record,
            map_validation,
            resolved_program_id,
            resolved_program_version,
            expected,
        )
        repair_atoms: list[str] = []
        if repair_unresolved and hasattr(active_map_step, "repair_bindings"):
            repair_atoms, repair_reasons = _select_trace_guided_repair_atoms(
                map_record,
                map_validation,
                case_dispositions,
                max_atoms=max_repair_atoms,
            )
            if repair_atoms:
                repaired_raw = active_map_step.repair_bindings(
                    program,
                    case,
                    map_record,
                    repair_atoms,
                    reasons=repair_reasons,
                )
                map_record, map_validation = apply_map_validation(
                    program,
                    repaired_raw,
                    evidence_sources=evidence_sources,
                )
                case_dispositions = _evaluate_case_dispositions(
                    program,
                    runtime,
                    case,
                    selected_determinations,
                    map_record,
                    map_validation,
                    resolved_program_id,
                    resolved_program_version,
                    expected,
                )
                for disposition in case_dispositions:
                    disposition.metadata["repair"] = {
                        "attempted": True,
                        "atom_ids": repair_atoms,
                    }
        map_records.append(map_record)
        map_validation_reports.append(map_validation)
        dispositions.extend(case_dispositions)

    return {
        "program": {
            "name": program.metadata.name,
            "version": program.metadata.version,
            "determination_count": len(program.determinations),
            "atom_count": len(program.map_spec.atoms),
            "node_count": len(program.nodes),
        },
        "case_count": len(cases),
        "map_mode": active_map_step.spec.map_step_id,
        "disposition_count": len(dispositions),
        "matched_disposition_count": sum(
            1 for disposition in dispositions if disposition.matched_expected is True
        ),
        "mismatch_count": sum(
            1 for disposition in dispositions if disposition.matched_expected is False
        ),
        "map_records": [record.model_dump(mode="json") for record in map_records],
        "map_validation_reports": [
            report.model_dump(mode="json") for report in map_validation_reports
        ],
        "dispositions": [record.model_dump(mode="json") for record in dispositions],
    }


def _evaluate_case_dispositions(
    program: DeterminationProgram,
    runtime: Any,
    case: CaseExample,
    selected_determinations: list[str],
    map_record: MapExtractionRecord,
    map_validation: MapValidationReport,
    program_id: str,
    program_version: str | None,
    expected: dict[str, str],
) -> list[DispositionRecord]:
    bundle = fact_bundle_from_values(
        program,
        fact_values_from_map_record(map_record),
        evidence={
            atom_id: binding.evidence
            for atom_id, binding in map_record.bindings.items()
            if binding.evidence
        },
    )
    records: list[DispositionRecord] = []
    for det_id in selected_determinations:
        started = perf_counter()
        evaluation = evaluate_determination_with_map_record(
            program,
            runtime,
            det_id,
            bundle,
            map_record,
        )
        outcome = evaluation.outcome
        trace = evaluation.trace
        expected_value = expected.get(det_id)
        records.append(
            DispositionRecord(
                disposition_id=new_id("disp"),
                program_id=program_id,
                program_version=program_version,
                case_id=case.case_id,
                determination_id=det_id,
                outcome=str(outcome),
                expected_outcome=expected_value,
                matched_expected=(
                    None if expected_value is None else str(outcome) == expected_value
                ),
                trace={"trace": trace},
                load_bearing_path=extract_leaf_path(trace),
                map_latency_s=map_record.latency_s,
                engine_latency_ms=(perf_counter() - started) * 1000,
                metadata={
                    "case_title": case.title,
                    "map_record_id": map_record.map_record_id,
                    "map_validation": map_validation.summary(),
                    **evaluation.metadata,
                },
            )
        )
    return records


def _select_trace_guided_repair_atoms(
    map_record: MapExtractionRecord,
    map_validation: MapValidationReport,
    dispositions: list[DispositionRecord],
    *,
    max_atoms: int,
) -> tuple[list[str], dict[str, list[str]]]:
    selected: list[str] = []
    reasons: dict[str, list[str]] = {}

    def add(atom_id: str, reason: str) -> None:
        if atom_id not in map_record.bindings:
            return
        if not _binding_needs_repair(map_record.bindings[atom_id]):
            return
        if atom_id not in selected:
            selected.append(atom_id)
        reasons.setdefault(atom_id, []).append(reason)

    for disposition in dispositions:
        if disposition.outcome != "undetermined":
            continue
        for atom_id in disposition.load_bearing_path:
            add(
                atom_id,
                (
                    f"{disposition.determination_id} evaluated to undetermined "
                    "and this atom appears in its load-bearing trace"
                ),
            )

    for entry in map_validation.entries:
        if str(entry.action.value) == "accept":
            continue
        add(entry.atom_id, f"Map validation action was {entry.action.value}: {entry.reason}")

    return selected[:max_atoms], {
        atom_id: reasons[atom_id] for atom_id in selected[:max_atoms]
    }


def _binding_needs_repair(binding: Any) -> bool:
    default_kind = binding.metadata.get("default_kind")
    if default_kind in {"evidence_gap", "out_of_scope", "branch_not_applicable"}:
        return False
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


def write_runtime_result(result: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        key: value
        for key, value in result.items()
        if key not in {"map_records", "map_validation_reports", "dispositions"}
    }
    files = {
        "summary": output_dir / "summary.json",
        "map_records": output_dir / "map_records.json",
        "dispositions": output_dir / "dispositions.json",
        "map_validation_reports": output_dir / "map_validation_reports.json",
        "results": output_dir / "results.json",
    }
    files["summary"].write_text(_json(summary), encoding="utf-8")
    files["map_records"].write_text(_json(result["map_records"]), encoding="utf-8")
    files["dispositions"].write_text(_json(result["dispositions"]), encoding="utf-8")
    files["map_validation_reports"].write_text(
        _json(result["map_validation_reports"]),
        encoding="utf-8",
    )
    files["results"].write_text(_json(result), encoding="utf-8")
    return {key: str(path) for key, path in files.items()}


def _case_from_payload(payload: dict[str, Any], index: int) -> CaseExample:
    if not isinstance(payload, dict):
        raise ValueError(f"case at index {index} must be an object")
    item = dict(payload)
    item.setdefault("case_id", f"case_{index + 1}")
    item.setdefault("title", item["case_id"])
    item.setdefault("narrative", "")
    facts = item.pop("facts", None)
    if facts is not None:
        structured = dict(item.get("structured_fields") or {})
        structured["facts"] = facts
        item["structured_fields"] = structured
    expected = item.get("expected_outcomes")
    if isinstance(expected, dict):
        item["expected_outcomes"] = [
            {
                "determination_id": det_id,
                "expected_value": str(value).lower() if isinstance(value, bool) else str(value),
            }
            for det_id, value in expected.items()
        ]
    return CaseExample.model_validate(item)


def _json(payload: Any) -> str:
    return json.dumps(to_jsonable_python(payload), indent=2, sort_keys=True)


__all__ = [
    "adjudicate_cases",
    "load_program",
    "load_runtime_cases",
    "write_runtime_result",
]
