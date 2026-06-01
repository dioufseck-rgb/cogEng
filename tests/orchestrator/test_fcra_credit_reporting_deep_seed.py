from __future__ import annotations

from pathlib import Path

from rulekit.orchestrator.cli import template_seed
from rulekit.orchestrator.config import load_policy_workspace_seed
from rulekit.orchestrator.cases import CaseExample
from rulekit.orchestrator.governed_map import apply_program_map_profile_defaults
from rulekit.orchestrator.map_record import AtomBindingRecord, AtomBindingStatus
from rulekit.orchestrator.workflow import run_policy_seed_file
from rulekit.contract import BindingBasis


SEED_PATH = (
    Path(__file__).parents[2]
    / "rulekit"
    / "orchestrator"
    / "example_seeds"
    / "fcra_credit_reporting_dispute_deep.yaml"
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
    assert len(result.program.metadata.extras["map_profile"]["default_rules"]) == 24


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
