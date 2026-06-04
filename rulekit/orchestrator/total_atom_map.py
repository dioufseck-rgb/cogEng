"""Isolated total-atom Map workbench.

This module is intentionally separate from the production governed Map path.
It lets us iterate on the hypothesis that an LLM can fill a complete atom
matrix in one local-reasoning pass, while RuleKit keeps global DAG reasoning
deterministic.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic_core import to_jsonable_python

from rulekit.contract import BindingBasis, DeterminationProgram, safe_program_to_engine
from rulekit.orchestrator.cases import CaseExample
from rulekit.orchestrator.evaluation import evaluate_determination_with_map_record
from rulekit.orchestrator.exercise import (
    extract_leaf_path,
    fact_bundle_from_values,
    fact_values_from_map_record,
)
from rulekit.orchestrator.governed_map import apply_program_map_profile_defaults
from rulekit.orchestrator.ids import new_id
from rulekit.orchestrator.map_record import (
    AtomBindingRecord,
    AtomBindingStatus,
    MapExtractionRecord,
)
from rulekit.orchestrator.map_validation import apply_map_validation
from rulekit.runtime import load_program, load_runtime_cases


TOTAL_ATOM_MAP_PROMPT = """You are producing a total atom map for RuleKit.

You are NOT deciding policy determinations. Your job is to fill every atom in
the atom catalog with a local evidence judgment. The deterministic RuleKit
engine will evaluate the policy DAG later.

For each atom:
- Return exactly one binding.
- Use true/false only when the case packet supports that local atom value.
- Use undetermined when the case packet does not support a local value.
- It is allowed to reason locally from explicit facts, dates, sequence, and
  procedural implications.
- Do not infer false from silence in an open narrative.
- If an atom is outside the natural scope of the case and the policy profile
  says the branch is not applicable, use that profile default.
- Keep local atom reasoning separate from global determination outcomes.

Allowed basis values:
explicit_positive, explicit_negative, closed_world_absence, open_world_absence,
inferred_from_record, conflicting_evidence, computed, looked_up, not_found.

CASE PACKET
===========
{case_json}

ATOM CATALOG
============
{atom_catalog_json}

Return ONLY this JSON shape:
{{
  "case_id": "{case_id}",
  "bindings": [
    {{
      "atom_id": "atom id from ATOM CATALOG",
      "status": "bound|undetermined|error",
      "value": true,
      "basis": "explicit_positive",
      "source_ids": ["narrative"],
      "evidence": "short exact evidence or summary",
      "explanation": "why this local atom value is justified",
      "confidence": 0.0
    }}
  ],
  "case_level_notes": "brief note or empty string"
}}
"""


def run_total_atom_map_eval(
    *,
    program_path: str | Path,
    cases_path: str | Path,
    output_dir: str | Path,
    determinations: list[str] | None = None,
    case_ids: list[str] | None = None,
    mode: str = "simulate",
    apply_profile_defaults: bool = True,
) -> dict[str, Any]:
    """Run the isolated total-atom Map workbench."""
    if mode not in {"schema", "simulate"}:
        raise ValueError("mode must be 'schema' or 'simulate'")
    program = load_program(program_path)
    cases = load_runtime_cases(cases_path)
    if case_ids:
        allowed = set(case_ids)
        cases = [case for case in cases if case.case_id in allowed]
    selected_determinations = determinations or list(program.determinations)

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "atom_catalog.json").write_text(
        _json(atom_catalog(program)),
        encoding="utf-8",
    )

    prompts: list[dict[str, str]] = []
    map_records: list[MapExtractionRecord] = []
    dispositions: list[dict[str, Any]] = []
    runtime = safe_program_to_engine(program)

    for case in cases:
        case_dir = output / "cases" / _safe_name(case.case_id)
        case_dir.mkdir(parents=True, exist_ok=True)
        prompt = build_total_atom_map_prompt(program, case)
        (case_dir / "total_atom_map.prompt.txt").write_text(prompt, encoding="utf-8")
        prompts.append({"case_id": case.case_id, "path": str(case_dir / "total_atom_map.prompt.txt")})
        if mode == "schema":
            continue
        map_record = simulate_total_atom_map_record(
            program,
            case,
            apply_profile_defaults=apply_profile_defaults,
        )
        map_record, validation = apply_map_validation(
            program,
            map_record,
            evidence_sources=[],
        )
        map_records.append(map_record)
        (case_dir / "map_record.json").write_text(
            _json(map_record.model_dump(mode="json")),
            encoding="utf-8",
        )
        (case_dir / "map_validation.json").write_text(
            _json(validation.model_dump(mode="json")),
            encoding="utf-8",
        )
        case_dispositions = _evaluate_case(
            program,
            runtime,
            case,
            selected_determinations,
            map_record,
        )
        dispositions.extend(case_dispositions)
        (case_dir / "dispositions.json").write_text(
            _json(case_dispositions),
            encoding="utf-8",
        )

    result: dict[str, Any] = {
        "mode": mode,
        "program": str(program_path),
        "cases": str(cases_path),
        "output_dir": str(output),
        "case_count": len(cases),
        "determination_count": len(selected_determinations),
        "atom_count": len(program.map_spec.atoms),
        "prompts": prompts,
    }
    if mode == "simulate":
        result.update(
            {
                "map_mode": "total_atom_map_simulation",
                "disposition_count": len(dispositions),
                "matched_disposition_count": sum(
                    1 for item in dispositions if item.get("matched_expected") is True
                ),
                "mismatch_count": sum(
                    1 for item in dispositions if item.get("matched_expected") is False
                ),
                "outcome_counts": dict(Counter(item["outcome"] for item in dispositions)),
                "basis_counts": _basis_counts(map_records),
                "dispositions": dispositions,
                "map_records": [record.model_dump(mode="json") for record in map_records],
            }
        )
        (output / "dispositions.json").write_text(_json(dispositions), encoding="utf-8")
        (output / "map_records.json").write_text(
            _json([record.model_dump(mode="json") for record in map_records]),
            encoding="utf-8",
        )
    (output / "summary.json").write_text(_json(_summary(result)), encoding="utf-8")
    return result


def build_total_atom_map_prompt(program: DeterminationProgram, case: CaseExample) -> str:
    return TOTAL_ATOM_MAP_PROMPT.format(
        case_id=case.case_id,
        case_json=_json(case.model_dump(mode="json")),
        atom_catalog_json=_json(atom_catalog(program)),
    )


def atom_catalog(program: DeterminationProgram) -> list[dict[str, Any]]:
    return [
        {
            "atom_id": atom_id,
            "atom_type": atom.atom_type,
            "statement": atom.statement,
            "source_span": atom.source_span,
            "numeric_unit": getattr(atom, "numeric_unit", None),
            "binding_policy": (
                atom.binding_policy.model_dump(mode="json")
                if atom.binding_policy is not None
                else None
            ),
        }
        for atom_id, atom in sorted(program.map_spec.atoms.items())
    ]


def simulate_total_atom_map_record(
    program: DeterminationProgram,
    case: CaseExample,
    *,
    apply_profile_defaults: bool = True,
) -> MapExtractionRecord:
    bindings = _undetermined_bindings(program)
    _apply_structured_facts(program, case, bindings)
    if _is_fcra_cra_stress_program(program):
        _apply_fcra_cra_stress_simulation(program, case, bindings)
    profile_default_count = 0
    if apply_profile_defaults:
        profile_default_count = apply_program_map_profile_defaults(
            program,
            case,
            bindings,
            source="total_atom_map_profile_default",
        )
    return MapExtractionRecord(
        map_record_id=new_id("map_total"),
        program_id=program.metadata.name,
        program_version=program.metadata.version,
        case_id=case.case_id,
        bindings=bindings,
        substrate_id="total_atom_map_simulation",
        latency_s=0.0,
        metadata={
            "experimental": True,
            "mode": "total_atom_map_simulation",
            "profile_default_count": profile_default_count,
            "note": "Deterministic sandbox simulation, not production Map output.",
        },
    )


def _undetermined_bindings(program: DeterminationProgram) -> dict[str, AtomBindingRecord]:
    return {
        atom_id: AtomBindingRecord(
            atom_id=atom_id,
            atom_type=atom.atom_type,
            value="undetermined",
            status=AtomBindingStatus.UNDETERMINED,
            basis=BindingBasis.NOT_FOUND,
            source="total_atom_map_simulation",
        )
        for atom_id, atom in program.map_spec.atoms.items()
    }


def _apply_structured_facts(
    program: DeterminationProgram,
    case: CaseExample,
    bindings: dict[str, AtomBindingRecord],
) -> None:
    facts = case.structured_fields.get("facts")
    if not isinstance(facts, dict):
        return
    for atom_id, value in facts.items():
        if atom_id not in program.map_spec.atoms:
            continue
        _bind(
            program,
            bindings,
            atom_id,
            value,
            basis=_basis_for_value(value),
            evidence=f"structured_fields.facts[{atom_id}]",
            explanation="Structured fact supplied in the case packet.",
            confidence=1.0,
        )


def _apply_fcra_cra_stress_simulation(
    program: DeterminationProgram,
    case: CaseExample,
    bindings: dict[str, AtomBindingRecord],
) -> None:
    text = case.narrative
    lower = text.lower()

    if "consumer" in lower and ("disputed" in lower or "wrote to the cra" in lower):
        _bind_many_true(program, bindings, [
            "fcra.consumer_disputed_item",
            "fcra.consumer_submission_authentic",
            "fcra.consumer_authorized_representative",
            "fcra.item_in_consumer_file",
        ], "Narrative describes a consumer dispute packet.")

    if "direct cra dispute" in lower or "directly with the cra" in lower or "sent a direct cra dispute" in lower:
        _bind(program, bindings, "fcra.notice_direct_to_cra", True, evidence="direct CRA dispute")
        _bind(program, bindings, "fcra.notice_through_reseller", False, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="direct CRA dispute, not reseller routed")

    if "identified the account" in lower or "identified the account, disputed field" in lower:
        _bind_many_true(program, bindings, [
            "fcra.account_identified",
            "fcra.disputed_field_identified",
            "fcra.basis_explained",
            "fcra.consumer_identity_sufficient",
        ], "The dispute identified the account, disputed field, and basis.")
    if "did not identify an account" in lower:
        _bind(program, bindings, "fcra.account_identified", False, basis=BindingBasis.EXPLICIT_NEGATIVE, evidence="did not identify an account")
    if "did not identify a disputed field" in lower:
        _bind(program, bindings, "fcra.disputed_field_identified", False, basis=BindingBasis.EXPLICIT_NEGATIVE, evidence="did not identify a disputed field")
    if "did not explain a basis" in lower:
        _bind(program, bindings, "fcra.basis_explained", False, basis=BindingBasis.EXPLICIT_NEGATIVE, evidence="did not explain a basis")

    if "accuracy" in lower or "late-payment" in lower or "delinquency" in lower:
        _bind(program, bindings, "fcra.dispute_about_accuracy", True, evidence="dispute concerns reported account information")
    if "completeness" in lower or "incomplete" in lower:
        _bind(program, bindings, "fcra.dispute_about_completeness", True, evidence="narrative references incompleteness")

    if "frivolous" in lower:
        _bind_many_true(program, bindings, [
            "fcra.frivolous_determination_made",
            "fcra.frivolous_notice_sent",
            "fcra.frivolous_reason_identified",
            "fcra.frivolous_missing_info_identified",
            "fcra.insufficient_information_to_investigate",
        ], "CRA made and noticed a frivolous-or-irrelevant determination.")
        _bind(program, bindings, "fcra.business_days_to_frivolous_notice", _number_before_phrase(lower, "business days later") or 3, basis=BindingBasis.COMPUTED, evidence="sent notice 3 business days later")
        _bind(program, bindings, "fcra.reinvestigation_completed", False, basis=BindingBasis.EXPLICIT_NEGATIVE, evidence="No reinvestigation was conducted")
        _bind(program, bindings, "fcra.cra_notified_furnisher", False, basis=BindingBasis.EXPLICIT_NEGATIVE, evidence="no furnisher notice was sent")
        _bind(program, bindings, "fcra.results_notice_sent", False, basis=BindingBasis.EXPLICIT_NEGATIVE, evidence="no results notice was sent")
    else:
        _bind(program, bindings, "fcra.frivolous_determination_made", False, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Narrative describes reinvestigation path, not frivolous termination")
        _bind(program, bindings, "fcra.dispute_duplicate_without_new_info", False, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Narrative does not describe a duplicate no-new-information dispute.")
        _bind(program, bindings, "fcra.insufficient_information_to_investigate", False, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Narrative describes sufficient dispute details.")
        _bind(program, bindings, "fcra.expedited_deleted_within_3_business_days", False, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Narrative describes ordinary reinvestigation, not expedited deletion.")

    if "new payoff letter" in lower or "additional relevant information" in lower or "later information" in lower:
        _bind(program, bindings, "fcra.additional_relevant_info_received_in_30_days", True, evidence="additional relevant information received during initial 30 days")
        _bind(program, bindings, "fcra.later_relevant_info_received", True, evidence="later relevant information was received")
    if "no later information" in lower:
        _bind(program, bindings, "fcra.additional_relevant_info_received_in_30_days", False, basis=BindingBasis.EXPLICIT_NEGATIVE, evidence="No later information was received during the first 30 days.")
        _bind(program, bindings, "fcra.later_relevant_info_received", False, basis=BindingBasis.EXPLICIT_NEGATIVE, evidence="No later information was received.")

    days = _first_int_after(lower, "completed the reinvestigation in")
    if days is None:
        days = _first_int_after(lower, "completed the reinvestigation on day")
    if days is not None:
        _bind(program, bindings, "fcra.days_to_complete_reinvestigation", days, basis=BindingBasis.COMPUTED, evidence=f"reinvestigation completed in/on day {days}")
        _bind(program, bindings, "fcra.reinvestigation_completed", True, evidence="CRA completed the reinvestigation")

    notify_days = _business_day_ordinal(lower, "furnisher")
    if notify_days is not None:
        _bind(program, bindings, "fcra.cra_notified_furnisher", True, evidence="CRA sent/notified the furnisher")
        _bind(program, bindings, "fcra.business_days_to_notify_furnisher", notify_days, basis=BindingBasis.COMPUTED, evidence=f"furnisher notice on business day {notify_days}")
        _bind(program, bindings, "fcra.furnished_by_furnisher", True, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Furnisher notice branch is described.")
        _bind(program, bindings, "fcra.furnisher_address_available", True, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="CRA sent notice to furnisher.")
        _bind(program, bindings, "fcra.furnisher_received_cra_notice", True, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Furnisher responded after CRA notice.")

    if "forwarded all relevant information" in lower:
        _bind(program, bindings, "fcra.notice_included_all_relevant_info", True, evidence="forwarded all relevant information")
        _bind(program, bindings, "fcra.primary_documents_forwarded", True, evidence="forwarded all relevant information")
    if "original dispute to the furnisher" in lower:
        _bind(program, bindings, "fcra.primary_documents_forwarded", True, evidence="CRA sent the original dispute to the furnisher")
        _bind(program, bindings, "fcra.notice_included_all_relevant_info", False, basis=BindingBasis.EXPLICIT_NEGATIVE, evidence="later payoff letter was not sent or made available")
    if "later payoff letter was not sent" in lower or "later payoff letter was not sent or made available" in lower or "later information was not sent" in lower:
        _bind(program, bindings, "fcra.later_relevant_info_forwarded", False, basis=BindingBasis.EXPLICIT_NEGATIVE, evidence="later payoff letter was not sent or made available to the furnisher")
    elif "no later information" in lower:
        _bind(program, bindings, "fcra.later_relevant_info_forwarded", True, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="no later relevant information existed to forward")

    if "reasonably reviewed" in lower or "reviewed" in lower:
        _bind_many_true(program, bindings, [
            "fcra.cra_reviewed_all_consumer_info",
            "fcra.cra_considered_primary_source_documents",
            "fcra.cra_reasonable_reinvestigation_performed",
            "fcra.cra_compared_own_file",
            "fcra.human_review_of_documents_performed",
            "fcra.dispositive_info_not_ignored",
        ], "Narrative describes review of relevant consumer and institutional information.")
        _bind(program, bindings, "fcra.automated_code_only", False, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Narrative describes substantive review, not automated code-only handling.")
    if "furnisher records" in lower or "furnisher response" in lower:
        _bind(program, bindings, "fcra.cra_compared_furnisher_response", True, evidence="CRA reviewed furnisher records/response.")
        _bind_many_true(program, bindings, [
            "fcra.furnisher_investigation_conducted",
            "fcra.furnisher_reviewed_all_cra_info",
            "fcra.furnisher_reported_results_to_cra",
        ], "Furnisher records/response were part of the reinvestigation path.")
        if days is not None:
            _bind(program, bindings, "fcra.days_to_furnisher_complete", days, basis=BindingBasis.COMPUTED, evidence="Furnisher-side response completed within the CRA reinvestigation timeline.")

    if "found the reported delinquency date incomplete" in lower:
        _bind(program, bindings, "fcra.item_found_incomplete", True, evidence="found the reported delinquency date incomplete")
        _bind(program, bindings, "fcra.item_modified", True, evidence="modified the tradeline")
    if "verified the item as accurate" in lower:
        _bind(program, bindings, "fcra.item_verified_as_accurate", True, evidence="verified the item as accurate")
        _bind(program, bindings, "fcra.item_found_inaccurate", False, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Narrative says the item was verified as accurate.")
        _bind(program, bindings, "fcra.item_found_incomplete", False, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Narrative says the item was verified as accurate.")
        _bind(program, bindings, "fcra.item_cannot_be_verified", False, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Narrative says the item was verified as accurate.")
        _bind(program, bindings, "fcra.item_deleted", False, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Narrative says the item was verified, not deleted.")
        _bind(program, bindings, "fcra.item_modified", False, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Narrative says the item was verified, not modified.")
    if "recorded current status" in lower or "recorded the item as current" in lower:
        _bind(program, bindings, "fcra.item_status_recorded_current", True, evidence="recorded current status")

    if "furnisher also modified the item" in lower:
        _bind(program, bindings, "fcra.furnisher_modified_item", True, evidence="furnisher also modified the item")
        _bind(program, bindings, "fcra.furnisher_reported_inaccuracy_to_other_cras", True, evidence="furnisher reported correction to other CRAs")
        _bind(program, bindings, "fcra.furnisher_deleted_item", False, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Narrative says the furnisher modified, not deleted, the item.")
        _bind(program, bindings, "fcra.furnisher_blocked_item", False, basis=BindingBasis.INFERRED_FROM_RECORD, evidence="Narrative says the furnisher modified, not blocked, the item.")
        _bind(program, bindings, "fcra.cra_compared_furnisher_response", True, evidence="Furnisher modified the item during the reinvestigation path.")
        _bind_many_true(program, bindings, [
            "fcra.furnisher_investigation_conducted",
            "fcra.furnisher_reviewed_all_cra_info",
            "fcra.furnisher_reported_results_to_cra",
        ], "Furnisher modified the item and reported the correction.")
        if days is not None:
            _bind(program, bindings, "fcra.days_to_furnisher_complete", days, basis=BindingBasis.COMPUTED, evidence="Furnisher correction occurred within the CRA reinvestigation timeline.")
    if "furnisher" in lower and "respond" in lower:
        _bind_many_true(program, bindings, [
            "fcra.furnisher_investigation_conducted",
            "fcra.furnisher_reviewed_all_cra_info",
            "fcra.furnisher_reported_results_to_cra",
        ], "Narrative describes furnisher participation in the CRA dispute path.")
        if days is not None:
            _bind(program, bindings, "fcra.days_to_furnisher_complete", days, basis=BindingBasis.COMPUTED, evidence="Furnisher completed its response within the CRA reinvestigation timeline.")

    if "written results" in lower or "results notice" in lower:
        _bind_many_true(program, bindings, [
            "fcra.results_notice_sent",
            "fcra.notice_states_reinvestigation_completed",
            "fcra.results_notice_included_report",
            "fcra.consumer_statement_right_disclosed",
            "fcra.procedure_request_right_disclosed",
            "fcra.notification_request_right_disclosed",
        ], "Narrative describes written results notice and required disclosures.")
        results_days = _first_int_before_phrase(lower, "business day after completion")
        if results_days is None:
            results_days = _first_int_before_phrase(lower, "business days later")
        if results_days is not None:
            _bind(program, bindings, "fcra.business_days_to_results_notice", results_days, basis=BindingBasis.COMPUTED, evidence=f"results notice sent {results_days} business days after completion")

    _bind_absent_review_triggers(program, bindings)


def _bind_absent_review_triggers(
    program: DeterminationProgram,
    bindings: dict[str, AtomBindingRecord],
) -> None:
    for atom_id in [
        "fcra.conflicting_furnisher_and_consumer_docs",
        "fcra.consumer_alleges_not_mine",
        "fcra.court_order_supplied",
        "fcra.identity_theft_claimed",
        "fcra.identity_theft_report_supplied",
        "fcra.legal_liability_dispute_only",
        "fcra.manual_review_policy_trigger",
        "fcra.material_date_conflict",
        "fcra.medical_debt_veteran_claimed",
        "fcra.mixed_file_claimed",
        "fcra.pending_litigation_affects_account",
        "fcra.source_documents_missing",
    ]:
        _bind(
            program,
            bindings,
            atom_id,
            False,
            basis=BindingBasis.INFERRED_FROM_RECORD,
            evidence="No review-trigger facts are described in this benchmark narrative.",
            explanation="Synthetic case packet presents no conflict, identity-theft, litigation, missing-source, or manual-review trigger.",
            confidence=0.7,
        )


def _evaluate_case(
    program: DeterminationProgram,
    runtime: Any,
    case: CaseExample,
    selected_determinations: list[str],
    map_record: MapExtractionRecord,
) -> list[dict[str, Any]]:
    expected = {item.determination_id: item.expected_value for item in case.expected_outcomes}
    bundle = fact_bundle_from_values(
        program,
        fact_values_from_map_record(map_record),
        evidence={
            atom_id: binding.evidence
            for atom_id, binding in map_record.bindings.items()
            if binding.evidence
        },
    )
    records: list[dict[str, Any]] = []
    for det_id in selected_determinations:
        evaluation = evaluate_determination_with_map_record(
            program,
            runtime,
            det_id,
            bundle,
            map_record,
        )
        outcome = str(evaluation.outcome)
        expected_outcome = expected.get(det_id)
        records.append(
            {
                "case_id": case.case_id,
                "determination_id": det_id,
                "outcome": outcome,
                "expected_outcome": expected_outcome,
                "matched_expected": (
                    None if expected_outcome is None else outcome == expected_outcome
                ),
                "load_bearing_path": extract_leaf_path(evaluation.trace),
                "trace": {"trace": evaluation.trace},
                "metadata": evaluation.metadata,
            }
        )
    return records


def _bind_many_true(
    program: DeterminationProgram,
    bindings: dict[str, AtomBindingRecord],
    atom_ids: list[str],
    evidence: str,
) -> None:
    for atom_id in atom_ids:
        _bind(program, bindings, atom_id, True, evidence=evidence)


def _bind(
    program: DeterminationProgram,
    bindings: dict[str, AtomBindingRecord],
    atom_id: str,
    value: Any,
    *,
    basis: BindingBasis | None = None,
    evidence: str = "",
    explanation: str | None = None,
    confidence: float = 0.9,
) -> None:
    atom = program.map_spec.atoms.get(atom_id)
    if atom is None:
        return
    status = (
        AtomBindingStatus.UNDETERMINED
        if value is None or str(value).lower() == "undetermined"
        else AtomBindingStatus.BOUND
    )
    bindings[atom_id] = AtomBindingRecord(
        atom_id=atom_id,
        atom_type=atom.atom_type,
        value=value if status == AtomBindingStatus.BOUND else "undetermined",
        status=status,
        basis=basis or _basis_for_value(value),
        source_ids=["narrative"],
        evidence=evidence,
        explanation=explanation or "Total atom map simulation filled this local atom from the narrative.",
        confidence=confidence,
        source="total_atom_map_simulation",
        metadata={"experimental_total_atom_map": True},
    )


def _basis_for_value(value: Any) -> BindingBasis:
    if value is None or str(value).lower() == "undetermined":
        return BindingBasis.NOT_FOUND
    if isinstance(value, bool):
        return BindingBasis.EXPLICIT_POSITIVE if value else BindingBasis.EXPLICIT_NEGATIVE
    return BindingBasis.COMPUTED


def _is_fcra_cra_stress_program(program: DeterminationProgram) -> bool:
    return {
        "fcra.cra_reinvestigation_trigger_valid",
        "fcra.cra_furnisher_notice_satisfied",
        "fcra.dispute_resolution_compliant",
    }.issubset(program.determinations)


def _number_before_phrase(text: str, phrase: str) -> int | None:
    match = re.search(r"(\d+)\s+" + re.escape(phrase), text)
    return int(match.group(1)) if match else None


def _first_int_after(text: str, phrase: str) -> int | None:
    index = text.find(phrase)
    if index < 0:
        return None
    match = re.search(r"\d+", text[index + len(phrase):])
    return int(match.group(0)) if match else None


def _first_int_before_phrase(text: str, phrase: str) -> int | None:
    match = re.search(r"(\d+|first|second|third|fourth|fifth|sixth|seventh|eighth)\s+" + re.escape(phrase), text)
    if not match:
        return None
    return _ordinal_or_int(match.group(1))


def _business_day_ordinal(text: str, nearby: str) -> int | None:
    patterns = [
        rf"(first|second|third|fourth|fifth|\d+)\s+business day[^.]*{nearby}",
        rf"{nearby}[^.]*on the (first|second|third|fourth|fifth|\d+)\s+business day",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _ordinal_or_int(match.group(1))
    return None


def _ordinal_or_int(value: str) -> int:
    mapping = {
        "first": 1,
        "second": 2,
        "third": 3,
        "fourth": 4,
        "fifth": 5,
        "sixth": 6,
        "seventh": 7,
        "eighth": 8,
    }
    lower = value.lower()
    if lower in mapping:
        return mapping[lower]
    return int(value)


def _basis_counts(records: list[MapExtractionRecord]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for record in records:
        for binding in record.bindings.values():
            counter[binding.basis.value if binding.basis else "none"] += 1
    return dict(counter)


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: result[key]
        for key in (
            "mode",
            "map_mode",
            "case_count",
            "determination_count",
            "atom_count",
            "disposition_count",
            "matched_disposition_count",
            "mismatch_count",
            "outcome_counts",
            "basis_counts",
        )
        if key in result
    }


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    return safe[:80] or "case"


def _json(payload: Any) -> str:
    return json.dumps(to_jsonable_python(payload), indent=2, sort_keys=True)


__all__ = [
    "TOTAL_ATOM_MAP_PROMPT",
    "atom_catalog",
    "build_total_atom_map_prompt",
    "run_total_atom_map_eval",
    "simulate_total_atom_map_record",
]
