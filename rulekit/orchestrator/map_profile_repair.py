"""Map-profile repair proposals for split-safe calibration runs."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any

from pydantic_core import to_jsonable_python

from rulekit.contract import BindingBasis, DeterminationProgram
from rulekit.orchestrator.cases import CaseExample
from rulekit.orchestrator.governed_map import apply_program_map_profile_defaults
from rulekit.orchestrator.ids import new_id
from rulekit.orchestrator.map_record import MapExtractionRecord
from rulekit.orchestrator.map_step import (
    MapStepContext,
    MapStepResult,
    MapStepSpec,
    PreboundFactsMapStep,
)
from rulekit.runtime import adjudicate_cases, load_program, write_runtime_result


class ProfileDefaultsMapStep:
    """Deterministic Map step that applies program map-profile defaults only."""

    def __init__(self, *, map_step_id: str = "map_profile_defaults"):
        self.spec = MapStepSpec(
            map_step_id=map_step_id,
            name="Program map-profile defaults",
            description="Applies policy-authored map_profile.default_rules without LLM calls.",
        )

    def run(
        self,
        program: DeterminationProgram,
        case: CaseExample,
        context: MapStepContext,
    ) -> MapStepResult:
        started = perf_counter()
        prebound = PreboundFactsMapStep(
            map_step_id=f"{self.spec.map_step_id}_prebind"
        ).run(program, case, context)
        bindings = {
            atom_id: binding.model_copy(deep=True)
            for atom_id, binding in prebound.map_record.bindings.items()
        }
        profile_count = apply_program_map_profile_defaults(
            program,
            case,
            bindings,
            source=context.substrate_id,
        )
        metadata = dict(prebound.map_record.metadata)
        metadata.update({
            "map_step_id": self.spec.map_step_id,
            "profile_default_binding_count": profile_count,
            "default_binding_count": (
                int(metadata.get("default_binding_count", 0)) + profile_count
            ),
        })
        record = MapExtractionRecord(
            map_record_id=new_id("map"),
            program_id=context.program_id,
            program_version=context.program_version,
            case_id=case.case_id,
            bindings=bindings,
            substrate_id=context.substrate_id,
            latency_s=perf_counter() - started,
            metadata=metadata,
        )
        return MapStepResult(map_record=record)


def build_map_profile_repair_patch(
    *,
    program: DeterminationProgram,
    repair_cases: list[CaseExample],
    repair_dispositions: list[dict[str, Any]],
    repair_map_records: list[dict[str, Any]] | None = None,
    round_id: str,
    max_rules: int = 80,
) -> dict[str, Any]:
    """Generate candidate map-profile default rules from repair-split evidence."""
    mismatches = [
        disposition
        for disposition in repair_dispositions
        if disposition.get("matched_expected") is False
    ]
    rule_candidates: list[dict[str, Any]] = []
    for case in repair_cases:
        case_mismatches = [
            disposition for disposition in mismatches
            if disposition.get("case_id") == case.case_id
        ]
        if not case_mismatches:
            continue
        rule_candidates.extend(_candidate_rules_for_case(program, case, case_mismatches))

    rules = _dedupe_rules(rule_candidates)[:max_rules]
    return {
        "status": "generated" if rules else "no_candidates",
        "repair_target": "map_profile.default_rules",
        "round_id": round_id,
        "candidate_rule_count": len(rules),
        "rules": rules,
        "source": {
            "repair_case_count": len(repair_cases),
            "repair_mismatch_count": len(mismatches),
            "mismatch_directions": _mismatch_directions(mismatches),
            "mismatch_determinations": _mismatch_determinations(mismatches),
            "map_record_count": len(repair_map_records or []),
        },
        "notes": [
            "Rules are generated only from the repair split.",
            "Validation and final-holdout cases are not used to author rules.",
            "Rules are candidate policy-pack artifacts and must be reviewed before promotion.",
        ],
    }


def apply_map_profile_repair_patch(
    program: DeterminationProgram,
    patch: dict[str, Any],
) -> DeterminationProgram:
    """Return a copy of program with candidate map-profile rules appended."""
    patched = program.model_copy(deep=True)
    extras = patched.metadata.extras
    profile = extras.setdefault("map_profile", {})
    if not isinstance(profile, dict):
        profile = {}
        extras["map_profile"] = profile
    rules = profile.setdefault("default_rules", [])
    if not isinstance(rules, list):
        rules = []
        profile["default_rules"] = rules
    existing_ids = {
        str(rule.get("id"))
        for rule in rules
        if isinstance(rule, dict) and rule.get("id") is not None
    }
    for rule in patch.get("rules", []):
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("id"))
        if rule_id in existing_ids:
            continue
        rules.append(copy.deepcopy(rule))
        existing_ids.add(rule_id)
    profile.setdefault("repair_history", [])
    if isinstance(profile["repair_history"], list):
        profile["repair_history"].append({
            "round_id": patch.get("round_id"),
            "repair_target": patch.get("repair_target"),
            "candidate_rule_count": patch.get("candidate_rule_count", 0),
        })
    return patched


def run_map_profile_repair(
    *,
    program_path: str | Path,
    output_dir: str | Path,
    round_id: str,
    repair_cases: list[CaseExample],
    validation_cases: list[CaseExample],
    repair_artifact_dir: str | Path,
    determinations: list[str] | None = None,
) -> dict[str, Any]:
    """Generate map-profile patches from repair artifacts and replay allowed splits."""
    output_dir = Path(output_dir)
    repair_artifact_dir = Path(repair_artifact_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    program = load_program(program_path)
    dispositions = _read_json(repair_artifact_dir / "dispositions.json")
    map_records = _read_json(repair_artifact_dir / "map_records.json")
    patch = build_map_profile_repair_patch(
        program=program,
        repair_cases=repair_cases,
        repair_dispositions=dispositions,
        repair_map_records=map_records,
        round_id=round_id,
    )
    (output_dir / "candidate_patches.json").write_text(
        _json(patch),
        encoding="utf-8",
    )
    patched_program = apply_map_profile_repair_patch(program, patch)
    patched_program_path = output_dir / "candidate_map_profile_program.json"
    patched_program_path.write_text(
        patched_program.model_dump_json(indent=2),
        encoding="utf-8",
    )
    baseline_replay: dict[str, Any] = {}
    replay: dict[str, Any] = {}
    for split_name, cases in (
        ("repair", repair_cases),
        ("validation", validation_cases),
    ):
        if not cases:
            continue
        baseline_result = adjudicate_cases(
            program,
            cases,
            determinations=determinations,
            map_step=ProfileDefaultsMapStep(),
            program_id=program.metadata.name,
            program_version=program.metadata.version,
        )
        baseline_files = write_runtime_result(
            baseline_result,
            output_dir / f"{split_name}_profile_baseline",
        )
        baseline_replay[split_name] = _replay_summary(baseline_result, baseline_files)
        candidate_result = adjudicate_cases(
            patched_program,
            cases,
            determinations=determinations,
            map_step=ProfileDefaultsMapStep(),
            program_id=patched_program.metadata.name,
            program_version=patched_program.metadata.version,
        )
        candidate_files = write_runtime_result(
            candidate_result,
            output_dir / f"{split_name}_profile_replay",
        )
        replay[split_name] = _replay_summary(candidate_result, candidate_files)
    validation_gate = _profile_repair_validation_gate(baseline_replay, replay)
    regression_summary = {
        "status": "run",
        "repair_target": "map_profile.default_rules",
        "candidate_rule_count": patch.get("candidate_rule_count", 0),
        "baseline_replay": baseline_replay,
        "replay": replay,
        "delta": _replay_deltas(baseline_replay, replay),
        "validation_gate": validation_gate,
        "final_holdout_used": False,
    }
    (output_dir / "regression_summary.json").write_text(
        _json(regression_summary),
        encoding="utf-8",
    )
    (output_dir / "repair_report.md").write_text(
        build_map_profile_repair_report(patch, regression_summary),
        encoding="utf-8",
    )
    return {
        "patch": patch,
        "patched_program": str(patched_program_path),
        "regression_summary": regression_summary,
    }


def build_map_profile_repair_report(
    patch: dict[str, Any],
    regression_summary: dict[str, Any],
) -> str:
    lines = [
        "# Map Profile Repair Report",
        "",
        f"Round: `{patch.get('round_id')}`",
        f"Repair target: `{patch.get('repair_target')}`",
        f"Candidate rules: `{patch.get('candidate_rule_count', 0)}`",
        "",
        "## Source Mismatches",
        "",
        "| Direction | Count |",
        "|---|---:|",
    ]
    for direction, count in sorted(patch.get("source", {}).get("mismatch_directions", {}).items()):
        lines.append(f"| `{direction}` | {count} |")
    lines.extend([
        "",
        "## Candidate Rules",
        "",
        "| Rule | Kind | Atom Count | Cue Count |",
        "|---|---|---:|---:|",
    ])
    for rule in patch.get("rules", []):
        lines.append(
            f"| `{rule.get('id')}` | `{rule.get('kind')}` | "
            f"{len(rule.get('atom_ids', []))} | "
            f"{len(rule.get('if_any', [])) + len(rule.get('if_all', [])) + len(rule.get('if_regex_any', []))} |"
        )
    lines.extend([
        "",
        "## Baseline vs Candidate",
        "",
        "| Split | Baseline Matches | Candidate Matches | Delta | Candidate Accuracy |",
        "|---|---:|---:|---:|---:|",
    ])
    baseline = regression_summary.get("baseline_replay", {})
    candidate = regression_summary.get("replay", {})
    deltas = regression_summary.get("delta", {})
    for split_name in sorted(set(baseline) | set(candidate)):
        base_summary = baseline.get(split_name, {})
        candidate_summary = candidate.get(split_name, {})
        total = candidate_summary.get("disposition_count", 0)
        matches = candidate_summary.get("matched_disposition_count", 0)
        accuracy = matches / total if total else 0.0
        lines.append(
            "| "
            f"`{split_name}` | "
            f"{base_summary.get('matched_disposition_count', 0)} | "
            f"{matches} | "
            f"{deltas.get(split_name, {}).get('matched_delta', 0):+d} | "
            f"{accuracy:.2%} |"
        )
    gate = regression_summary.get("validation_gate", {})
    lines.extend([
        "",
        "## Promotion Gate",
        "",
        f"Status: `{gate.get('status', 'unknown')}`",
        "",
        gate.get("reason", "No validation gate result was recorded."),
        "",
        "## Profile-Only Replay",
        "",
        "| Split | Matches | Mismatches | Accuracy |",
        "|---|---:|---:|---:|",
    ])
    for split_name, summary in regression_summary.get("replay", {}).items():
        total = summary.get("disposition_count", 0)
        matches = summary.get("matched_disposition_count", 0)
        mismatches = summary.get("mismatch_count", 0)
        accuracy = matches / total if total else 0.0
        lines.append(
            f"| `{split_name}` | {matches} | {mismatches} | {accuracy:.2%} |"
        )
    lines.extend([
        "",
        "The replay uses deterministic profile defaults only. It is a cheap",
        "structural check for proposed Map-profile rules, not a replacement for",
        "a governed LLM Map rerun.",
        "",
    ])
    return "\n".join(lines)


def _candidate_rules_for_case(
    program: DeterminationProgram,
    case: CaseExample,
    mismatches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    text = case.narrative.lower()
    rules: list[dict[str, Any]] = []
    rules.extend(_branch_non_applicability_rules(program, text))
    rules.extend(_ordinary_process_rules(program, text))
    rules.extend(_frivolous_rules(program, text))
    rules.extend(_expedited_deletion_rules(program, text))
    rules.extend(_reseller_rules(program, text))
    rules.extend(_routing_rules(program, text))
    return [
        _with_rule_metadata(rule, case, mismatches)
        for rule in rules
        if _rule_atoms_exist(program, rule)
    ]


def _branch_non_applicability_rules(
    program: DeterminationProgram,
    text: str,
) -> list[dict[str, Any]]:
    branches = [
        (
            "direct_furnisher",
            ["no direct-furnisher", "no direct furnisher", "no direct dispute"],
            [
                atom_id for atom_id in program.map_spec.atoms
                if (
                    ("direct_dispute" in atom_id or "direct_furnisher" in atom_id)
                    and _is_boolean_atom(program, atom_id)
                )
            ],
        ),
        (
            "reseller",
            ["no reseller", "no source-cra reinvestigation", "reseller branch does not apply"],
            [
                atom_id for atom_id in program.map_spec.atoms
                if (
                    ("reseller" in atom_id or atom_id == "fcra.notice_through_reseller")
                    and _is_boolean_atom(program, atom_id)
                )
            ],
        ),
        (
            "reinsertion",
            ["no reinsertion", "no reinsertion branch", "no reinsertion occurred"],
            [
                atom_id for atom_id in program.map_spec.atoms
                if (
                    ("reinsert" in atom_id or "reappearance" in atom_id)
                    and _is_boolean_atom(program, atom_id)
                )
            ],
        ),
        (
            "consumer_statement",
            ["no consumer statement", "no consumer-statement", "consumer-statement branch applies"],
            [
                "fcra.consumer_statement_filed",
                "fcra.subsequent_reports_note_dispute",
            ],
        ),
    ]
    rules: list[dict[str, Any]] = []
    for label, cues, atom_ids in branches:
        if any(cue in text for cue in cues):
            rules.append({
                "id": f"rk_auto_no_{label}_branch",
                "kind": "branch_not_applicable",
                "atom_ids": sorted(set(atom_ids)),
                "value": False,
                "basis": BindingBasis.EXPLICIT_NEGATIVE.value,
                "if_any": cues,
                "evidence": f"Narrative states the {label.replace('_', ' ')} branch does not apply.",
                "apply_when": "always",
            })
    return rules


def _ordinary_process_rules(program: DeterminationProgram, text: str) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    if _has_any(text, ["identified the account", "identified the item", "identified the account and disputed field"]):
        rules.append(_rule(
            "rk_auto_valid_cra_intake_identified",
            "scope_supported_true",
            [
                "fcra.consumer_disputed_item",
                "fcra.item_in_consumer_file",
                "fcra.dispute_about_accuracy",
                "fcra.notice_direct_to_cra",
                "fcra.consumer_identity_sufficient",
                "fcra.account_identified",
                "fcra.disputed_field_identified",
                "fcra.basis_explained",
                "fcra.consumer_submission_authentic",
            ],
            True,
            ["identified the account", "identified the item", "disputed field"],
            "Narrative describes a valid CRA intake packet.",
        ))
    if _has_any(text, ["notified the furnisher within 5 business days", "notified the furnisher on the second business day", "notified the furnisher on the third business day", "sent the original dispute to the furnisher on the third business day"]):
        rules.append(_rule(
            "rk_auto_timely_furnisher_notice_complete",
            "scope_supported_true",
            [
                "fcra.furnished_by_furnisher",
                "fcra.furnisher_address_available",
                "fcra.cra_notified_furnisher",
                "fcra.notice_included_all_relevant_info",
                "fcra.primary_documents_forwarded",
                "fcra.furnisher_received_cra_notice",
                "fcra.furnisher_investigation_conducted",
                "fcra.furnisher_reviewed_all_cra_info",
                "fcra.furnisher_reported_results_to_cra",
            ],
            True,
            [
                "notified the furnisher within 5 business days",
                "notified the furnisher on the second business day",
                "notified the furnisher on the third business day",
                "sent the original dispute to the furnisher on the third business day",
            ],
            "Narrative describes timely furnisher notice and ordinary furnisher response.",
        ))
        rules.append(_numeric_rule(
            "rk_auto_notify_furnisher_within_5_days",
            "fcra.business_days_to_notify_furnisher",
            5,
            [
                "notified the furnisher within 5 business days",
                "notified the furnisher on the second business day",
                "notified the furnisher on the third business day",
                "sent the original dispute to the furnisher on the third business day",
            ],
        ))
    if _has_any(text, ["completed within 30 days", "completed a reasonable reinvestigation in 24 days", "completed the reinvestigation in 26 days", "timely and reasonable reinvestigation"]):
        rules.append(_numeric_rule(
            "rk_auto_reinvestigation_completed_within_30",
            "fcra.days_to_complete_reinvestigation",
            30,
            ["completed within 30 days", "completed a reasonable reinvestigation in 24 days", "completed the reinvestigation in 26 days", "timely and reasonable reinvestigation"],
        ))
        rules.append(_rule(
            "rk_auto_reinvestigation_completed",
            "scope_supported_true",
            ["fcra.reinvestigation_completed"],
            True,
            ["completed within 30 days", "completed a reasonable reinvestigation in 24 days", "completed the reinvestigation in 26 days", "timely and reasonable reinvestigation"],
            "Narrative describes a completed reinvestigation.",
        ))
    if _has_any(text, ["complete written results", "timely results notice", "sent a timely results notice", "sent complete results"]):
        rules.append(_rule(
            "rk_auto_complete_results_notice",
            "scope_supported_true",
            [
                "fcra.results_notice_sent",
                "fcra.notice_states_reinvestigation_completed",
                "fcra.revised_consumer_report_provided",
                "fcra.procedure_description_right_disclosed",
                "fcra.furnisher_contact_disclosed_if_available",
                "fcra.consumer_statement_right_disclosed",
                "fcra.notification_right_disclosed",
            ],
            True,
            ["complete written results", "timely results notice", "sent a timely results notice", "sent complete results"],
            "Narrative describes a complete CRA results notice.",
        ))
        rules.append(_numeric_rule(
            "rk_auto_results_notice_within_5_days",
            "fcra.business_days_to_results_notice",
            5,
            ["complete written results", "timely results notice", "sent a timely results notice", "sent complete results"],
        ))
    if _has_any(text, ["verified the item", "verified that auto-loan item", "recorded the item as current and verified"]):
        rules.append(_rule(
            "rk_auto_verified_item_treatment",
            "scope_supported_true",
            ["fcra.item_verified_as_accurate", "fcra.item_status_recorded_current"],
            True,
            ["verified the item", "verified that auto-loan item", "recorded the item as current and verified"],
            "Narrative describes verified item treatment.",
        ))
    return rules


def _frivolous_rules(program: DeterminationProgram, text: str) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    if "frivolous-or-irrelevant determination" in text:
        rules.append(_rule(
            "rk_auto_frivolous_termination_made_with_notice",
            "scope_supported_true",
            [
                "fcra.frivolous_determination_made",
                "fcra.frivolous_notice_sent",
                "fcra.frivolous_reason_identified",
                "fcra.frivolous_missing_info_identified",
            ],
            True,
            ["frivolous-or-irrelevant determination"],
            "Narrative states a frivolous-or-irrelevant termination with notice.",
        ))
        rules.append(_numeric_rule(
            "rk_auto_frivolous_notice_within_5_days",
            "fcra.business_days_to_frivolous_notice",
            5,
            ["frivolous-or-irrelevant determination", "business days later"],
        ))
    if _has_any(text, ["did not identify an account", "did not identify a disputed field", "did not explain a basis"]):
        rules.append(_rule(
            "rk_auto_frivolous_insufficient_intake",
            "scope_supported_false",
            [
                "fcra.account_identified",
                "fcra.disputed_field_identified",
                "fcra.basis_explained",
                "fcra.reinvestigation_completed",
                "fcra.results_notice_sent",
            ],
            False,
            ["did not identify an account", "did not identify a disputed field", "did not explain a basis"],
            "Narrative states the intake packet lacked account, field, or basis.",
        ))
        rules.append(_rule(
            "rk_auto_insufficient_information_to_investigate",
            "scope_supported_true",
            ["fcra.insufficient_information_to_investigate"],
            True,
            ["did not identify an account", "did not identify a disputed field", "did not explain a basis"],
            "Narrative states information required to investigate was missing.",
        ))
    if _has_any(text, ["new packet included", "not previously supplied", "new letter was dispositive"]):
        rules.append(_rule(
            "rk_auto_duplicate_with_new_material_not_frivolous",
            "scope_supported_false",
            [
                "fcra.dispute_duplicate_without_new_info",
                "fcra.insufficient_information_to_investigate",
                "fcra.frivolous_missing_info_identified",
                "fcra.reinvestigation_completed",
                "fcra.cra_notified_furnisher",
                "fcra.furnisher_received_cra_notice",
                "fcra.cra_reviewed_all_consumer_info",
                "fcra.results_notice_sent",
            ],
            False,
            ["new packet included", "not previously supplied", "new letter was dispositive"],
            "Narrative states new material information was supplied despite duplicate coding.",
        ))
        rules.append(_rule(
            "rk_auto_invalid_duplicate_termination_made",
            "scope_supported_true",
            ["fcra.frivolous_determination_made", "fcra.frivolous_notice_sent", "fcra.frivolous_reason_identified"],
            True,
            ["marked the submission as duplicate and frivolous", "marked it duplicate/frivolous"],
            "Narrative states a duplicate/frivolous termination was made.",
        ))
    return rules


def _expedited_deletion_rules(program: DeterminationProgram, text: str) -> list[dict[str, Any]]:
    if not _has_any(text, ["within 3 business days", "expedited deletion"]):
        return []
    return [
        _rule(
            "rk_auto_expedited_deletion_path",
            "scope_supported_true",
            [
                "fcra.expedited_deleted_within_3_business_days",
                "fcra.consumer_telephone_notice_of_expedited_deletion",
                "fcra.expedited_written_confirmation_sent",
                "fcra.item_deleted",
                "fcra.item_status_recorded_current",
            ],
            True,
            ["within 3 business days", "expedited deletion"],
            "Narrative describes expedited deletion and consumer notices.",
        ),
        _rule(
            "rk_auto_no_furnisher_notice_for_expedited_deletion",
            "branch_not_applicable",
            ["fcra.cra_notified_furnisher", "fcra.furnisher_received_cra_notice"],
            False,
            ["before sending any furnisher notice", "no furnisher transmission was sent"],
            "Narrative states the expedited path occurred before furnisher notice.",
        ),
    ]


def _reseller_rules(program: DeterminationProgram, text: str) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    if "through a reseller" in text:
        rules.append(_rule(
            "rk_auto_reseller_dispute_received",
            "scope_supported_true",
            ["fcra.notice_through_reseller", "fcra.reseller_received_dispute"],
            True,
            ["through a reseller"],
            "Narrative describes a reseller dispute.",
        ))
    if _has_any(text, ["own transcription error", "own error"]):
        rules.append(_rule(
            "rk_auto_reseller_own_error_corrected",
            "scope_supported_true",
            ["fcra.reseller_item_due_to_reseller_error", "fcra.reseller_corrected_or_deleted"],
            True,
            ["own transcription error", "own error"],
            "Narrative states the reseller corrected its own error.",
        ))
        rules.append(_numeric_rule(
            "rk_auto_reseller_correction_within_20",
            "fcra.days_to_reseller_correct_delete",
            20,
            ["within 12 days", "within 20 days"],
        ))
    if _has_any(text, ["not due to reseller error", "was not due to reseller error"]):
        rules.append(_rule(
            "rk_auto_reseller_forwarding_late_or_missing",
            "scope_supported_false",
            ["fcra.reseller_item_due_to_reseller_error", "fcra.reseller_reconveyed_results_to_consumer"],
            False,
            ["not due to reseller error", "never reconveyed"],
            "Narrative states source-CRA path with no reconveyance.",
        ))
        rules.append(_rule(
            "rk_auto_reseller_forwarded_source_cra",
            "scope_supported_true",
            ["fcra.reseller_conveyed_to_cra"],
            True,
            ["conveyed the dispute packet to the source cra"],
            "Narrative states the reseller forwarded to the source CRA.",
        ))
        rules.append(_numeric_rule(
            "rk_auto_reseller_conveyance_late",
            "fcra.business_days_to_reseller_conveyance",
            8,
            ["eighth business day"],
        ))
    return rules


def _routing_rules(program: DeterminationProgram, text: str) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    if _has_any(text, ["manual review", "conflicting documents", "material date conflict"]):
        rules.append(_rule(
            "rk_auto_manual_review_conflict",
            "routing_trigger",
            [
                "fcra.manual_review_policy_trigger",
                "fcra.conflicting_furnisher_and_consumer_docs",
                "fcra.material_date_conflict",
            ],
            True,
            ["manual review", "conflicting documents", "material date conflict"],
            "Narrative states a manual-review conflict trigger.",
        ))
    return rules


def _rule(
    rule_id: str,
    kind: str,
    atom_ids: list[str],
    value: bool,
    if_any: list[str],
    evidence: str,
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "kind": kind,
        "atom_ids": atom_ids,
        "value": value,
        "basis": (
            BindingBasis.INFERRED_FROM_RECORD.value
            if value is True
            else BindingBasis.EXPLICIT_NEGATIVE.value
        ),
        "if_any": if_any,
        "evidence": evidence,
        "apply_when": "missing_or_undetermined",
    }


def _numeric_rule(
    rule_id: str,
    atom_id: str,
    value: int,
    if_any: list[str],
) -> dict[str, Any]:
    return {
        "id": rule_id,
        "kind": "numeric_profile_default",
        "atom_ids": [atom_id],
        "value": value,
        "basis": BindingBasis.INFERRED_FROM_RECORD.value,
        "if_any": if_any,
        "evidence": f"Narrative supports a numeric default of {value}.",
        "apply_when": "missing_or_undetermined",
    }


def _with_rule_metadata(
    rule: dict[str, Any],
    case: CaseExample,
    mismatches: list[dict[str, Any]],
) -> dict[str, Any]:
    patched = copy.deepcopy(rule)
    patched["id"] = _stable_rule_id(rule)
    patched["metadata"] = {
        "generated_by": "rulekit_map_profile_repair",
        "source_case_id": case.case_id,
        "source_split_group": case.metadata.get("split_group"),
        "source_mismatch_determinations": sorted({
            str(item.get("determination_id"))
            for item in mismatches
            if item.get("determination_id")
        }),
    }
    return patched


def _stable_rule_id(rule: dict[str, Any]) -> str:
    payload = {
        "id": rule.get("id"),
        "atom_ids": sorted(str(atom_id) for atom_id in rule.get("atom_ids", [])),
        "value": rule.get("value"),
        "if_any": sorted(str(item).lower() for item in rule.get("if_any", [])),
        "if_all": sorted(str(item).lower() for item in rule.get("if_all", [])),
        "if_regex_any": sorted(str(item).lower() for item in rule.get("if_regex_any", [])),
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:10]
    return f"{rule.get('id', 'rk_auto_profile_rule')}_{digest}"


def _rule_atoms_exist(program: DeterminationProgram, rule: dict[str, Any]) -> bool:
    atom_ids = [
        atom_id for atom_id in rule.get("atom_ids", [])
        if atom_id in program.map_spec.atoms
    ]
    if isinstance(rule.get("value"), bool):
        atom_ids = [
            atom_id for atom_id in atom_ids
            if _is_boolean_atom(program, atom_id)
        ]
    rule["atom_ids"] = atom_ids
    return bool(atom_ids)


def _is_boolean_atom(program: DeterminationProgram, atom_id: str) -> bool:
    atom = program.map_spec.atoms.get(atom_id)
    if atom is None:
        return False
    return "bool" in str(atom.atom_type).lower()


def _dedupe_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for rule in rules:
        rule_id = str(rule.get("id"))
        if rule_id in seen:
            continue
        seen.add(rule_id)
        deduped.append(rule)
    return deduped


def _has_any(text: str, cues: list[str]) -> bool:
    return any(cue in text for cue in cues)


def _mismatch_directions(mismatches: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in mismatches:
        counts[f"{item.get('outcome')}->{item.get('expected_outcome')}"] += 1
    return dict(sorted(counts.items()))


def _mismatch_determinations(mismatches: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in mismatches:
        if item.get("determination_id"):
            counts[str(item["determination_id"])] += 1
    return dict(sorted(counts.items()))


def _replay_summary(result: dict[str, Any], files: dict[str, str]) -> dict[str, Any]:
    return {
        "case_count": result["case_count"],
        "disposition_count": result["disposition_count"],
        "matched_disposition_count": result["matched_disposition_count"],
        "mismatch_count": result["mismatch_count"],
        "map_mode": result["map_mode"],
        "files": files,
    }


def _replay_deltas(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    deltas: dict[str, dict[str, Any]] = {}
    for split_name in sorted(set(baseline) | set(candidate)):
        base_summary = baseline.get(split_name, {})
        candidate_summary = candidate.get(split_name, {})
        deltas[split_name] = {
            "matched_delta": (
                int(candidate_summary.get("matched_disposition_count", 0))
                - int(base_summary.get("matched_disposition_count", 0))
            ),
            "mismatch_delta": (
                int(candidate_summary.get("mismatch_count", 0))
                - int(base_summary.get("mismatch_count", 0))
            ),
        }
    return deltas


def _profile_repair_validation_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    validation_baseline = baseline.get("validation")
    validation_candidate = candidate.get("validation")
    if not validation_baseline or not validation_candidate:
        return {
            "status": "not_evaluated",
            "reason": "No validation split replay was available.",
        }
    total = int(validation_candidate.get("disposition_count", 0))
    candidate_matches = int(validation_candidate.get("matched_disposition_count", 0))
    baseline_matches = int(validation_baseline.get("matched_disposition_count", 0))
    delta = candidate_matches - baseline_matches
    accuracy = candidate_matches / total if total else 0.0
    if delta < 0:
        return {
            "status": "reject",
            "reason": (
                "Candidate Map-profile rules reduce validation accuracy and must "
                "not be promoted."
            ),
            "validation_matched_delta": delta,
            "validation_accuracy": accuracy,
        }
    if accuracy < 0.8:
        return {
            "status": "hold_for_review",
            "reason": (
                "Candidate Map-profile rules improve or preserve validation accuracy, "
                "but validation accuracy is below the promotion threshold."
            ),
            "validation_matched_delta": delta,
            "validation_accuracy": accuracy,
            "promotion_threshold": 0.8,
        }
    return {
        "status": "eligible_for_review",
        "reason": (
            "Candidate Map-profile rules improve or preserve validation accuracy "
            "and meet the minimum promotion threshold."
        ),
        "validation_matched_delta": delta,
        "validation_accuracy": accuracy,
        "promotion_threshold": 0.8,
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json(payload: Any) -> str:
    return json.dumps(to_jsonable_python(payload), indent=2, sort_keys=True)


__all__ = [
    "ProfileDefaultsMapStep",
    "apply_map_profile_repair_patch",
    "build_map_profile_repair_patch",
    "build_map_profile_repair_report",
    "run_map_profile_repair",
]
