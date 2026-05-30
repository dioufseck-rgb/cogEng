"""Domain-neutral diagnostics for exercised candidate programs."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rulekit.orchestrator.disposition import DispositionRecord
from rulekit.orchestrator.map_record import MapExtractionRecord


class DiagnosticKind(str, Enum):
    MISMATCH = "mismatch"
    MATCH = "match"
    UNCHECKED = "unchecked"


class CandidateFixKind(str, Enum):
    REVIEW_MAP_BINDING = "review_map_binding"
    REVIEW_PROGRAM_LOGIC = "review_program_logic"
    REVIEW_EXPECTED_OUTCOME = "review_expected_outcome"
    ADD_CASE_EVIDENCE = "add_case_evidence"


class CandidateFix(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: CandidateFixKind
    title: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CaseDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnostic_id: str
    kind: DiagnosticKind
    case_id: str
    determination_id: str
    outcome: str
    expected_outcome: str | None = None
    matched_expected: bool | None = None
    load_bearing_path: list[str] = Field(default_factory=list)
    map_record_id: str | None = None
    map_statuses: dict[str, str] = Field(default_factory=dict)
    evidence_by_atom: dict[str, str] = Field(default_factory=dict)
    candidate_fixes: list[CandidateFix] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def diagnose_case_result(
    disposition: DispositionRecord,
    map_record: MapExtractionRecord | None = None,
) -> CaseDiagnostic:
    """Create the projection a builder UI needs for one exercised result."""
    kind = _diagnostic_kind(disposition)
    map_statuses: dict[str, str] = {}
    evidence_by_atom: dict[str, str] = {}
    if map_record is not None:
        for atom_id in disposition.load_bearing_path:
            binding = map_record.bindings.get(atom_id)
            if binding is None:
                continue
            map_statuses[atom_id] = binding.status.value
            if binding.evidence:
                evidence_by_atom[atom_id] = binding.evidence

    return CaseDiagnostic(
        diagnostic_id=f"diag_{disposition.disposition_id}",
        kind=kind,
        case_id=disposition.case_id,
        determination_id=disposition.determination_id,
        outcome=disposition.outcome,
        expected_outcome=disposition.expected_outcome,
        matched_expected=disposition.matched_expected,
        load_bearing_path=list(disposition.load_bearing_path),
        map_record_id=map_record.map_record_id if map_record else None,
        map_statuses=map_statuses,
        evidence_by_atom=evidence_by_atom,
        candidate_fixes=_candidate_fixes(disposition, map_record),
        metadata={
            "program_id": disposition.program_id,
            "program_version": disposition.program_version,
        },
    )


def diagnose_dispositions(
    dispositions: list[DispositionRecord],
    map_records: list[MapExtractionRecord] | None = None,
) -> list[CaseDiagnostic]:
    maps_by_id = {record.map_record_id: record for record in map_records or []}
    maps_by_case = {record.case_id: record for record in map_records or []}
    diagnostics: list[CaseDiagnostic] = []
    for disposition in dispositions:
        map_id = disposition.metadata.get("map_record_id")
        map_record = maps_by_id.get(map_id) if isinstance(map_id, str) else None
        if map_record is None:
            map_record = maps_by_case.get(disposition.case_id)
        diagnostics.append(diagnose_case_result(disposition, map_record))
    return diagnostics


def _diagnostic_kind(disposition: DispositionRecord) -> DiagnosticKind:
    if disposition.matched_expected is True:
        return DiagnosticKind.MATCH
    if disposition.matched_expected is False:
        return DiagnosticKind.MISMATCH
    return DiagnosticKind.UNCHECKED


def _candidate_fixes(
    disposition: DispositionRecord,
    map_record: MapExtractionRecord | None,
) -> list[CandidateFix]:
    if disposition.matched_expected is not False:
        return []

    fixes: list[CandidateFix] = []
    if map_record is not None:
        uncertain_atoms = [
            atom_id
            for atom_id in disposition.load_bearing_path
            if atom_id in map_record.bindings
            and map_record.bindings[atom_id].status.value != "bound"
        ]
        if uncertain_atoms:
            fixes.append(
                CandidateFix(
                    kind=CandidateFixKind.REVIEW_MAP_BINDING,
                    title="Review undetermined load-bearing atom bindings",
                    payload={"atom_ids": uncertain_atoms},
                )
            )

        missing_evidence = [
            atom_id
            for atom_id in disposition.load_bearing_path
            if atom_id in map_record.bindings
            and not map_record.bindings[atom_id].evidence
        ]
        if missing_evidence:
            fixes.append(
                CandidateFix(
                    kind=CandidateFixKind.ADD_CASE_EVIDENCE,
                    title="Add or verify evidence for load-bearing atoms",
                    payload={"atom_ids": missing_evidence},
                )
            )

    fixes.extend(
        [
            CandidateFix(
                kind=CandidateFixKind.REVIEW_PROGRAM_LOGIC,
                title="Review the program logic on the failing path",
                payload={"node_or_atom_ids": list(disposition.load_bearing_path)},
            ),
            CandidateFix(
                kind=CandidateFixKind.REVIEW_EXPECTED_OUTCOME,
                title="Review the authored expected outcome",
                payload={
                    "expected_outcome": disposition.expected_outcome,
                    "actual_outcome": disposition.outcome,
                },
            ),
        ]
    )
    return fixes


__all__ = [
    "DiagnosticKind",
    "CandidateFixKind",
    "CandidateFix",
    "CaseDiagnostic",
    "diagnose_case_result",
    "diagnose_dispositions",
]
