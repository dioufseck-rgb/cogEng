"""Canonical proposition layer for source-posture-aware Map binding."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rulekit.contract import BindingBasis, DeterminationProgram
from rulekit.orchestrator.cases import CaseExample
from rulekit.orchestrator.map_record import (
    AtomBindingRecord,
    AtomBindingStatus,
)


class AssertionStatus(str, Enum):
    """Whether a proposition is merely asserted or evidentially established."""

    ASSERTED = "asserted"
    ESTABLISHED = "established"
    SUPPORTED = "supported"
    CONFIRMED = "confirmed"
    DOCUMENTED = "documented"
    CONTRADICTED = "contradicted"
    CONFLICTING = "conflicting"
    NOT_ADDRESSED = "not_addressed"


class SourcePosture(str, Enum):
    """Generic stance of a source toward a proposition."""

    CLAIMANT_ASSERTION = "claimant_assertion"
    RESPONDENT_ASSERTION = "respondent_assertion"
    INSTITUTIONAL_RECORD = "institutional_record"
    OFFICIAL_RECORD = "official_record"
    THIRD_PARTY_RECORD = "third_party_record"
    EXPERT_RECORD = "expert_record"
    SYSTEM_LOG = "system_log"
    UNKNOWN = "unknown"


class CanonicalProposition(BaseModel):
    """A normalized case proposition with provenance and evidentiary posture."""

    model_config = ConfigDict(extra="allow")

    proposition_id: str = Field(min_length=1)
    canonical_concept: str | None = None
    atom_id: str | None = None
    value: Any = True
    assertion_status: AssertionStatus = AssertionStatus.ASSERTED
    source_posture: SourcePosture | str = SourcePosture.UNKNOWN
    speaker: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    evidence_text: str = ""
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


DEFAULT_BINDING_ASSERTION_STATUSES = {
    AssertionStatus.ESTABLISHED.value,
    AssertionStatus.SUPPORTED.value,
    AssertionStatus.CONFIRMED.value,
    AssertionStatus.DOCUMENTED.value,
}


def propositions_from_case(case: CaseExample) -> list[CanonicalProposition]:
    """Load canonical propositions from a case packet."""
    payload = (
        case.structured_fields.get("propositions")
        or case.structured_fields.get("canonical_propositions")
        or []
    )
    if not isinstance(payload, list):
        return []
    propositions: list[CanonicalProposition] = []
    for item in payload:
        if isinstance(item, dict):
            propositions.append(CanonicalProposition.model_validate(item))
    return propositions


def apply_case_proposition_bindings(
    program: DeterminationProgram,
    case: CaseExample,
    bindings: dict[str, AtomBindingRecord],
    *,
    source: str | None = None,
) -> int:
    """Apply canonical propositions to atom bindings where policy permits.

    Claimant/member/customer assertions are intentionally not treated as facts by
    default. They are recorded as undetermined bindings with provenance metadata
    unless a profile concept rule explicitly accepts that assertion status and
    source posture.
    """
    propositions = propositions_from_case(case)
    if not propositions:
        return 0
    applied = 0
    concept_rules = _concept_rules(program)
    for proposition in propositions:
        targets = _targets_for_proposition(program, proposition, concept_rules)
        for target in targets:
            atom_id = str(target.get("atom_id") or "")
            if atom_id not in program.map_spec.atoms:
                continue
            existing = bindings.get(atom_id)
            apply_when = str(target.get("apply_when", "missing_or_undetermined"))
            if not _should_apply(existing, apply_when):
                continue
            binding = _binding_for_target(
                program,
                proposition,
                target,
                source=source,
            )
            bindings[atom_id] = binding
            applied += 1
    return applied


def _targets_for_proposition(
    program: DeterminationProgram,
    proposition: CanonicalProposition,
    concept_rules: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    if proposition.atom_id:
        targets.append({
            "atom_id": proposition.atom_id,
            "value": proposition.value,
        })
    if proposition.canonical_concept:
        targets.extend(concept_rules.get(proposition.canonical_concept, []))
    return [
        target for target in targets
        if isinstance(target, dict) and str(target.get("atom_id") or "") in program.map_spec.atoms
    ]


def _binding_for_target(
    program: DeterminationProgram,
    proposition: CanonicalProposition,
    target: dict[str, Any],
    *,
    source: str | None,
) -> AtomBindingRecord:
    atom_id = str(target["atom_id"])
    atom = program.map_spec.atoms[atom_id]
    allowed_statuses = {
        str(item)
        for item in target.get(
            "accepted_assertion_statuses",
            target.get("accepted_statuses", DEFAULT_BINDING_ASSERTION_STATUSES),
        )
    }
    allowed_postures = {
        str(item)
        for item in target.get(
            "accepted_source_postures",
            target.get("accepted_postures", []),
        )
    }
    assertion_status = proposition.assertion_status.value
    source_posture = _source_posture_value(proposition)
    bindable = assertion_status in allowed_statuses
    if allowed_postures:
        bindable = bindable and source_posture in allowed_postures
    if assertion_status == AssertionStatus.CONFLICTING.value:
        bindable = False
    if assertion_status == AssertionStatus.CONTRADICTED.value and not target.get(
        "bind_when_contradicted",
        False,
    ):
        bindable = False

    metadata = {
        "case_proposition": True,
        "proposition_id": proposition.proposition_id,
        "canonical_concept": proposition.canonical_concept,
        "assertion_status": assertion_status,
        "source_posture": source_posture,
        "speaker": proposition.speaker,
        "target_rule_id": target.get("id"),
    }
    if not bindable:
        return AtomBindingRecord(
            atom_id=atom_id,
            atom_type=atom.atom_type,
            value="undetermined",
            status=AtomBindingStatus.UNDETERMINED,
            basis=(
                BindingBasis.CONFLICTING_EVIDENCE
                if assertion_status == AssertionStatus.CONFLICTING.value
                else BindingBasis.NOT_FOUND
            ),
            source_ids=list(proposition.source_ids),
            evidence=proposition.evidence_text or None,
            explanation=_unbound_explanation(proposition),
            confidence=proposition.confidence,
            source=source or "case_proposition",
            metadata=metadata,
        )
    value = target.get("value", proposition.value)
    status = (
        AtomBindingStatus.UNDETERMINED
        if value is None or str(value).lower() == "undetermined"
        else AtomBindingStatus.BOUND
    )
    return AtomBindingRecord(
        atom_id=atom_id,
        atom_type=atom.atom_type,
        value=value,
        status=status,
        basis=_basis_for_target(value, target),
        source_ids=list(proposition.source_ids),
        evidence=target.get("evidence") or proposition.evidence_text or None,
        explanation=target.get("explanation") or _bound_explanation(proposition),
        confidence=proposition.confidence,
        source=source or "case_proposition",
        metadata=metadata,
    )


def _concept_rules(program: DeterminationProgram) -> dict[str, list[dict[str, Any]]]:
    profile = program.metadata.extras.get("map_profile")
    if not isinstance(profile, dict):
        return {}
    rules: dict[str, list[dict[str, Any]]] = {}
    concepts = profile.get("concepts", {})
    if isinstance(concepts, dict):
        iterable = concepts.items()
    elif isinstance(concepts, list):
        iterable = [
            (str(item.get("concept_id") or item.get("id") or ""), item)
            for item in concepts
            if isinstance(item, dict)
        ]
    else:
        iterable = []
    for concept_id, concept in iterable:
        if not concept_id or not isinstance(concept, dict):
            continue
        raw_bindings = (
            concept.get("atom_bindings")
            or concept.get("entails")
            or concept.get("bindings")
            or []
        )
        rules[concept_id] = _normalize_binding_rules(raw_bindings)
    proposition_bindings = profile.get("proposition_bindings", {})
    if isinstance(proposition_bindings, dict):
        for concept_id, raw_bindings in proposition_bindings.items():
            rules.setdefault(str(concept_id), []).extend(
                _normalize_binding_rules(raw_bindings)
            )
    return rules


def _normalize_binding_rules(raw_bindings: Any) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    if isinstance(raw_bindings, dict):
        for atom_id, value in raw_bindings.items():
            if isinstance(value, dict):
                rule = dict(value)
                rule.setdefault("atom_id", atom_id)
            else:
                rule = {"atom_id": atom_id, "value": value}
            rules.append(rule)
    elif isinstance(raw_bindings, list):
        for item in raw_bindings:
            if isinstance(item, dict):
                rules.append(dict(item))
    return rules


def _basis_for_target(value: Any, target: dict[str, Any]) -> BindingBasis:
    if target.get("basis"):
        return BindingBasis(str(target["basis"]))
    if value is False or str(value).lower() == "false":
        return BindingBasis.EXPLICIT_NEGATIVE
    if value is None or str(value).lower() == "undetermined":
        return BindingBasis.NOT_FOUND
    return BindingBasis.EXPLICIT_POSITIVE


def _should_apply(existing: AtomBindingRecord | None, apply_when: str) -> bool:
    if apply_when == "always":
        return True
    if existing is None:
        return True
    if apply_when == "missing":
        return existing.value is None
    if apply_when == "missing_or_not_found":
        return existing.basis == BindingBasis.NOT_FOUND
    if existing.status != AtomBindingStatus.BOUND:
        return True
    return existing.basis in {
        BindingBasis.NOT_FOUND,
        BindingBasis.OPEN_WORLD_ABSENCE,
    }


def _unbound_explanation(proposition: CanonicalProposition) -> str:
    return (
        "canonical proposition was preserved but not bound as an atom because "
        f"assertion_status={proposition.assertion_status.value!r} and "
        f"source_posture={_source_posture_value(proposition)!r} are not accepted "
        "for factual binding by default"
    )


def _bound_explanation(proposition: CanonicalProposition) -> str:
    return (
        "canonical proposition was accepted for atom binding with "
        f"assertion_status={proposition.assertion_status.value!r} and "
        f"source_posture={_source_posture_value(proposition)!r}"
    )


def _source_posture_value(proposition: CanonicalProposition) -> str:
    posture = proposition.source_posture
    if isinstance(posture, SourcePosture):
        return posture.value
    return str(posture)


__all__ = [
    "AssertionStatus",
    "CanonicalProposition",
    "SourcePosture",
    "apply_case_proposition_bindings",
    "propositions_from_case",
]
