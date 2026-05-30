"""Deterministic validation for governed Map atom bindings."""
from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rulekit.contract import BindingBasis, DeterminationProgram
from rulekit.orchestrator.map_record import (
    AtomBindingRecord,
    AtomBindingStatus,
    MapExtractionRecord,
)


class EvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_type: str
    title: str = ""
    as_of_date: str | None = None
    closed_world_scopes: list[str] = Field(default_factory=list)
    limitations: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MapBindingValidationStatus(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    WARNING = "warning"


class MapBindingValidationAction(str, Enum):
    ACCEPT = "accept"
    COERCE_UNDETERMINED = "coerce_undetermined"
    HUMAN_REVIEW = "human_review"
    ERROR = "error"


class MapBindingValidationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atom_id: str
    status: MapBindingValidationStatus
    action: MapBindingValidationAction
    reason: str = ""
    original_value: Any = None
    basis: BindingBasis | None = None
    source_ids: list[str] = Field(default_factory=list)


class MapValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    case_id: str
    entries: list[MapBindingValidationEntry] = Field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        counts = Counter(entry.status.value for entry in self.entries)
        action_counts = Counter(entry.action.value for entry in self.entries)
        return {
            "ok": self.ok,
            "case_id": self.case_id,
            "entry_count": len(self.entries),
            "valid_count": counts[MapBindingValidationStatus.VALID.value],
            "invalid_count": counts[MapBindingValidationStatus.INVALID.value],
            "warning_count": counts[MapBindingValidationStatus.WARNING.value],
            "actions": dict(sorted(action_counts.items())),
        }


def validate_map_record(
    program: DeterminationProgram,
    map_record: MapExtractionRecord,
    *,
    evidence_sources: list[EvidenceSource] | None = None,
) -> MapValidationReport:
    """Check a Map record against per-atom binding policies."""
    source_types = _source_types_by_id(evidence_sources or [])
    entries: list[MapBindingValidationEntry] = []
    for atom_id, binding in sorted(map_record.bindings.items()):
        atom = program.map_spec.atoms.get(atom_id)
        if atom is None:
            entries.append(
                MapBindingValidationEntry(
                    atom_id=atom_id,
                    status=MapBindingValidationStatus.INVALID,
                    action=MapBindingValidationAction.ERROR,
                    reason="binding references an atom not present in the program",
                    original_value=binding.value,
                    basis=binding.basis,
                    source_ids=binding.source_ids,
                )
            )
            continue
        policy = getattr(atom, "binding_policy", None)
        if policy is None or binding.status != AtomBindingStatus.BOUND:
            entries.append(_valid(binding, "no policy violation"))
            continue
        value_kind = _binding_value_kind(binding)
        if value_kind == "undetermined":
            entries.append(_valid(binding, "bound value is undetermined-like"))
            continue
        basis = binding.basis
        if basis is None:
            entries.append(
                _invalid(
                    binding,
                    policy.invalid_binding_behavior,
                    "binding has no epistemic basis",
                )
            )
            continue
        if basis == BindingBasis.OPEN_WORLD_ABSENCE:
            if policy.open_world_absence_behavior == "accept":
                entries.append(_valid(binding, "open-world absence accepted by atom policy"))
            else:
                entries.append(
                    _invalid(
                        binding,
                        policy.open_world_absence_behavior,
                        "open-world absence is not sufficient for this atom",
                    )
                )
            continue
        if basis == BindingBasis.CONFLICTING_EVIDENCE:
            if policy.conflicting_evidence_behavior == "accept":
                entries.append(_valid(binding, "conflicting evidence accepted by atom policy"))
            else:
                entries.append(
                    _invalid(
                        binding,
                        policy.conflicting_evidence_behavior,
                        "conflicting evidence cannot be resolved by Map",
                    )
                )
            continue
        allowed = (
            policy.allowed_bases_for_true
            if value_kind == "true"
            else policy.allowed_bases_for_false
            if value_kind == "false"
            else []
        )
        if basis not in allowed:
            entries.append(
                _invalid(
                    binding,
                    policy.invalid_binding_behavior,
                    f"basis {basis.value!r} is not allowed for {value_kind} binding",
                )
            )
            continue
        required_source_types = (
            policy.required_source_types_for_true
            if value_kind == "true"
            else policy.required_source_types_for_false
            if value_kind == "false"
            else []
        )
        if required_source_types and not _has_required_source_type(
            binding.source_ids,
            required_source_types,
            source_types,
        ):
            entries.append(
                _invalid(
                    binding,
                    policy.invalid_binding_behavior,
                    "binding does not cite a required source type",
                )
            )
            continue
        entries.append(_valid(binding, "binding satisfies atom policy"))
    return MapValidationReport(
        ok=not any(entry.status == MapBindingValidationStatus.INVALID for entry in entries),
        case_id=map_record.case_id,
        entries=entries,
    )


def apply_map_validation(
    program: DeterminationProgram,
    map_record: MapExtractionRecord,
    *,
    evidence_sources: list[EvidenceSource] | None = None,
) -> tuple[MapExtractionRecord, MapValidationReport]:
    """Return a copy of the record with invalid bindings sanitized."""
    report = validate_map_record(
        program,
        map_record,
        evidence_sources=evidence_sources,
    )
    sanitized = map_record.model_copy(deep=True)
    entry_by_atom = {entry.atom_id: entry for entry in report.entries}
    human_review_atoms: list[str] = []
    errors: list[str] = []
    for atom_id, entry in entry_by_atom.items():
        if entry.status != MapBindingValidationStatus.INVALID:
            continue
        binding = sanitized.bindings.get(atom_id)
        if binding is None:
            continue
        binding.metadata["map_validation"] = entry.model_dump(mode="json")
        if entry.action == MapBindingValidationAction.COERCE_UNDETERMINED:
            binding.status = AtomBindingStatus.UNDETERMINED
            binding.value = "undetermined"
        elif entry.action == MapBindingValidationAction.HUMAN_REVIEW:
            binding.status = AtomBindingStatus.UNDETERMINED
            binding.value = "undetermined"
            human_review_atoms.append(atom_id)
        elif entry.action == MapBindingValidationAction.ERROR:
            binding.status = AtomBindingStatus.ERROR
            errors.append(atom_id)
    sanitized.metadata["map_validation"] = report.summary()
    if human_review_atoms:
        sanitized.metadata["human_review_required"] = True
        sanitized.metadata["human_review_atoms"] = human_review_atoms
    if errors:
        sanitized.metadata["map_validation_errors"] = errors
    return sanitized, report


def evidence_sources_from_case_fields(structured_fields: dict[str, Any]) -> list[EvidenceSource]:
    payload = structured_fields.get("evidence_sources", [])
    if not isinstance(payload, list):
        return []
    sources: list[EvidenceSource] = []
    for item in payload:
        if isinstance(item, dict):
            sources.append(EvidenceSource.model_validate(item))
    return sources


def _valid(binding: AtomBindingRecord, reason: str) -> MapBindingValidationEntry:
    return MapBindingValidationEntry(
        atom_id=binding.atom_id,
        status=MapBindingValidationStatus.VALID,
        action=MapBindingValidationAction.ACCEPT,
        reason=reason,
        original_value=binding.value,
        basis=binding.basis,
        source_ids=binding.source_ids,
    )


def _invalid(
    binding: AtomBindingRecord,
    behavior: str,
    reason: str,
) -> MapBindingValidationEntry:
    action = {
        "undetermined": MapBindingValidationAction.COERCE_UNDETERMINED,
        "human_review": MapBindingValidationAction.HUMAN_REVIEW,
        "error": MapBindingValidationAction.ERROR,
    }[behavior]
    return MapBindingValidationEntry(
        atom_id=binding.atom_id,
        status=MapBindingValidationStatus.INVALID,
        action=action,
        reason=reason,
        original_value=binding.value,
        basis=binding.basis,
        source_ids=binding.source_ids,
    )


def _binding_value_kind(binding: AtomBindingRecord) -> str:
    if binding.status != AtomBindingStatus.BOUND:
        return "undetermined"
    value = binding.value
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None or str(value).lower() == "undetermined":
        return "undetermined"
    lowered = str(value).lower()
    if lowered == "true":
        return "true"
    if lowered == "false":
        return "false"
    return "numeric"


def _source_types_by_id(sources: list[EvidenceSource]) -> dict[str, str]:
    return {source.source_id: source.source_type for source in sources}


def _has_required_source_type(
    source_ids: list[str],
    required: list[str],
    source_types: dict[str, str],
) -> bool:
    present = {source_types.get(source_id) for source_id in source_ids}
    return any(source_type in present for source_type in required)


__all__ = [
    "EvidenceSource",
    "MapBindingValidationStatus",
    "MapBindingValidationAction",
    "MapBindingValidationEntry",
    "MapValidationReport",
    "validate_map_record",
    "apply_map_validation",
    "evidence_sources_from_case_fields",
]
