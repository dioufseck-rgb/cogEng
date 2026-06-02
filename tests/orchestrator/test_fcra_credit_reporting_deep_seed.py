from __future__ import annotations

from pathlib import Path

from rulekit.orchestrator.cli import template_seed
from rulekit.orchestrator.config import load_policy_workspace_seed
from rulekit.orchestrator.cases import CaseExample
from rulekit.orchestrator.governed_map import (
    apply_program_map_profile_defaults,
    build_single_map_prompt,
)
from rulekit.orchestrator.map_record import AtomBindingRecord, AtomBindingStatus
from rulekit.orchestrator.perspectives import (
    list_program_perspectives,
    project_program_perspective,
)
from rulekit.orchestrator.workflow import run_policy_seed_file
from rulekit.contract import BindingBasis
from rulekit.contract.validators import validate_program
from rulekit.runtime import adjudicate_cases, load_runtime_cases


SEED_PATH = (
    Path(__file__).parents[2]
    / "rulekit"
    / "orchestrator"
    / "example_seeds"
    / "fcra_credit_reporting_dispute_deep.yaml"
)
BANK_CASES_PATH = (
    Path(__file__).parents[2]
    / "rulekit"
    / "orchestrator"
    / "example_cases"
    / "fcra_bank_customer_disputes.yaml"
)
BANK_EVAL_CASES_PATH = (
    Path(__file__).parents[2]
    / "rulekit"
    / "orchestrator"
    / "example_cases"
    / "fcra_bank_customer_disputes_eval.yaml"
)


def test_fcra_credit_reporting_deep_seed_runs_end_to_end(tmp_path):
    seed = load_policy_workspace_seed(SEED_PATH)

    assert len(seed.atoms) == 120
    assert len(seed.determinations) == 15
    assert len(seed.cases) == 11
    assert seed.metadata["primary_sources"] == [
        "15 U.S.C. 1681i",
        "15 U.S.C. 1681s-2",
        "12 CFR 1022.43",
    ]

    result = run_policy_seed_file(
        SEED_PATH,
        tmp_path / "r",
        program_id="p_fcra_deep",
    )

    summary = result.summary()
    assert summary["validation_ok"] is True
    assert summary["case_count"] == 11
    assert summary["disposition_count"] == 165
    assert summary["matched_disposition_count"] == 165
    assert summary["mismatch_count"] == 0
    assert any(
        det.determination_kind == "routing"
        for det in result.program.determinations.values()
    )
    assert len(result.program.metadata.extras["map_profile"]["default_rules"]) == 56
    assert any(
        perspective["perspective_id"] == "bank_furnisher"
        for perspective in result.program.metadata.extras["perspectives"]
    )


def test_fcra_credit_reporting_deep_template_is_available():
    seed = template_seed("fcra-credit-reporting-deep")

    assert seed.policy_id == "fcra_credit_reporting_dispute_deep"
    assert len(seed.atoms) == 120


def test_fcra_credit_reporting_map_profile_applies_without_domain_python(tmp_path):
    result = run_policy_seed_file(
        SEED_PATH,
        tmp_path / "r",
        program_id="p_fcra_deep",
    )
    program = result.program
    case = CaseExample(
        case_id="narrative_only",
        title="Narrative-only clean dispute",
        narrative=(
            "The consumer disputed a 30-day late notation. The CRA file shows "
            "the dispute was received directly and completed the reinvestigation."
        ),
    )
    bindings = {
        atom_id: AtomBindingRecord(
            atom_id=atom_id,
            atom_type=atom.atom_type,
            value="undetermined",
            status=AtomBindingStatus.UNDETERMINED,
            basis=BindingBasis.NOT_FOUND,
        )
        for atom_id, atom in program.map_spec.atoms.items()
    }

    applied = apply_program_map_profile_defaults(program, case, bindings)

    assert applied > 0
    assert bindings["fcra.consumer_disputed_item"].value is True
    assert bindings["fcra.notice_direct_to_cra"].value is True
    assert bindings["fcra.reseller_received_dispute"].value is False
    assert bindings["fcra.item_reinserted"].value is False
    assert bindings["fcra.consumer_statement_filed"].value is False
    assert bindings["fcra.reseller_received_dispute"].metadata["map_profile_default"] is True


def test_fcra_credit_reporting_bank_perspective_projects_role_scoped_program(tmp_path):
    result = run_policy_seed_file(
        SEED_PATH,
        tmp_path / "r",
        program_id="p_fcra_deep",
    )
    program = result.program

    perspectives = list_program_perspectives(program)
    assert [perspective.perspective_id for perspective in perspectives] == [
        "bank_furnisher",
        "cra_dispute",
    ]

    bank_program = project_program_perspective(program, "bank_furnisher")

    assert validate_program(bank_program).ok
    assert set(bank_program.determinations) == {
        "fcra.cra_furnisher_notice_satisfied",
        "fcra.direct_furnisher_satisfied",
        "fcra.furnisher_indirect_satisfied",
        "fcra.human_review_required",
        "fcra.item_treatment_satisfied",
    }
    assert "fcra.reseller_satisfied" not in bank_program.determinations
    assert "fcra.dispute_resolution_compliant" not in bank_program.determinations
    assert len(bank_program.nodes) < len(program.nodes)
    assert len(bank_program.map_spec.atoms) < len(program.map_spec.atoms)
    assert (
        bank_program.metadata.extras["active_perspective"]["perspective_id"]
        == "bank_furnisher"
    )
    assert "fcra.furnisher_received_cra_notice" in bank_program.map_spec.atoms
    assert "fcra.direct_dispute_received_by_furnisher" in bank_program.map_spec.atoms
    assert "n_not_furnished_by_furnisher" in bank_program.nodes[
        "n_item_treatment_satisfied"
    ].children
    assert "n_policy_deletion_treatment" in bank_program.nodes[
        "n_item_treatment_satisfied"
    ].children
    assert "n_policy_deletion_treatment" in bank_program.nodes
    assert "n_not_furnished_by_furnisher" in bank_program.nodes[
        "n_furnisher_indirect_satisfied"
    ].children


def test_fcra_bank_map_profile_rules_are_perspective_scoped(tmp_path):
    result = run_policy_seed_file(
        SEED_PATH,
        tmp_path / "r",
        program_id="p_fcra_deep",
    )
    program = result.program
    bank_program = project_program_perspective(program, "bank_furnisher")
    case = CaseExample(
        case_id="bank_direct_short_message",
        title="Bank direct short message",
        narrative=(
            "Customer sent the bank a short message saying the credit reporting "
            "is wrong but did not identify the account."
        ),
    )

    program_bindings = {
        atom_id: AtomBindingRecord(
            atom_id=atom_id,
            atom_type=atom.atom_type,
            value="undetermined",
            status=AtomBindingStatus.UNDETERMINED,
            basis=BindingBasis.NOT_FOUND,
        )
        for atom_id, atom in program.map_spec.atoms.items()
    }
    bank_bindings = {
        atom_id: AtomBindingRecord(
            atom_id=atom_id,
            atom_type=atom.atom_type,
            value="undetermined",
            status=AtomBindingStatus.UNDETERMINED,
            basis=BindingBasis.NOT_FOUND,
        )
        for atom_id, atom in bank_program.map_spec.atoms.items()
    }

    apply_program_map_profile_defaults(program, case, program_bindings)
    apply_program_map_profile_defaults(bank_program, case, bank_bindings)

    assert program_bindings["fcra.direct_dispute_subject_within_scope"].value == "undetermined"
    assert bank_bindings["fcra.direct_dispute_subject_within_scope"].value is True
    assert bank_bindings["fcra.direct_dispute_identifies_account"].value is False


def test_fcra_bank_map_profile_handles_explicit_no_direct_dispute(tmp_path):
    result = run_policy_seed_file(
        SEED_PATH,
        tmp_path / "r",
        program_id="p_fcra_deep",
    )
    bank_program = project_program_perspective(result.program, "bank_furnisher")
    case = CaseExample(
        case_id="bank_no_direct_dispute",
        title="No direct furnisher dispute",
        narrative=(
            "The CRA notice was sent to the bank, but no direct dispute was "
            "sent to the bank."
        ),
    )
    bindings = {
        atom_id: AtomBindingRecord(
            atom_id=atom_id,
            atom_type=atom.atom_type,
            value="undetermined",
            status=AtomBindingStatus.UNDETERMINED,
            basis=BindingBasis.NOT_FOUND,
        )
        for atom_id, atom in bank_program.map_spec.atoms.items()
    }

    apply_program_map_profile_defaults(bank_program, case, bindings)

    assert bindings["fcra.direct_dispute_received_by_furnisher"].value is False
    assert bindings["fcra.direct_dispute_subject_within_scope"].value is False


def test_fcra_bank_single_map_prompt_includes_profile_vocabulary(tmp_path):
    result = run_policy_seed_file(
        SEED_PATH,
        tmp_path / "r",
        program_id="p_fcra_deep",
    )
    bank_program = project_program_perspective(result.program, "bank_furnisher")
    case = CaseExample(
        case_id="wrong_address",
        title="Wrong address",
        narrative=(
            "Customer mailed a balance dispute to the ordinary customer "
            "service lockbox, not to the published dispute address."
        ),
    )

    prompt = build_single_map_prompt(
        bank_program,
        ["fcra.direct_dispute_at_proper_address"],
        case,
        [],
        evidence_by_atom={},
    )

    assert "ACTIVE PERSPECTIVE" in prompt
    assert "PROFILE GUIDANCE" in prompt
    assert "bank_furnisher" in prompt
    assert "bank_direct_wrong_address" in prompt


def test_fcra_bank_customer_dispute_cases_run_against_bank_perspective(tmp_path):
    result = run_policy_seed_file(
        SEED_PATH,
        tmp_path / "r",
        program_id="p_fcra_deep",
    )
    bank_program = project_program_perspective(result.program, "bank_furnisher")
    cases = load_runtime_cases(BANK_CASES_PATH)

    runtime_result = adjudicate_cases(bank_program, cases)

    assert runtime_result["case_count"] == 6
    assert runtime_result["disposition_count"] == 30
    assert runtime_result["matched_disposition_count"] == 30
    assert runtime_result["mismatch_count"] == 0


def test_fcra_bank_holdout_eval_cases_are_narrative_only():
    cases = load_runtime_cases(BANK_EVAL_CASES_PATH)

    assert len(cases) == 18
    assert all(not case.structured_fields for case in cases)
    assert sum(len(case.expected_outcomes) for case in cases) == 90
    assert {
        expected.expected_value
        for case in cases
        for expected in case.expected_outcomes
    } == {"false", "true", "undetermined"}
