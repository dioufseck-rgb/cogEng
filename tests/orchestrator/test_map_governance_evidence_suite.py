from __future__ import annotations

from pathlib import Path

from rulekit.contract import BindingBasis
from rulekit.orchestrator.cli import template_seed
from rulekit.orchestrator.map_governance_eval import summarize_governed_run
from rulekit.runtime import load_runtime_cases


SUITE_PATH = Path("rulekit/orchestrator/example_cases/uscis_n400_gmc_evidence_packets.json")


def test_uscis_gmc_evidence_packet_suite_loads_and_targets_policy_atoms():
    seed = template_seed("uscis-n400")
    cases = load_runtime_cases(SUITE_PATH)
    atom_ids = {atom.atom_id for atom in seed.atoms}

    assert len(cases) == 6
    assert {case.case_id for case in cases} >= {
        "gmc_open_world_silence_personal_statement",
        "gmc_closed_world_clean_checks",
        "gmc_conflicting_aggravated_felony_sources",
    }
    for case in cases:
        expected = case.metadata.get("expected_bindings", {})
        assert expected, case.case_id
        assert set(expected).issubset(atom_ids)


def test_uscis_n400_seed_declares_strict_gmc_binding_policies():
    seed = template_seed("uscis-n400")
    atoms = {atom.atom_id: atom for atom in seed.atoms}
    policy = atoms["n400.aggravated_felony_after_1990"].binding_policy

    assert policy is not None
    assert BindingBasis.CLOSED_WORLD_ABSENCE in policy.allowed_bases_for_false
    assert BindingBasis.OPEN_WORLD_ABSENCE not in policy.allowed_bases_for_false
    assert "criminal_history_check" in policy.required_source_types_for_false
    assert policy.open_world_absence_behavior == "undetermined"


def test_map_governance_summary_reports_expected_binding_metrics():
    cases = load_runtime_cases(SUITE_PATH)
    result = {
        "case_count": 1,
        "disposition_count": 0,
        "matched_disposition_count": 0,
        "mismatch_count": 0,
        "map_mode": "map_governed_evidence",
        "map_records": [
            {
                "case_id": "gmc_open_world_silence_personal_statement",
                "bindings": {
                    "n400.aggravated_felony_after_1990": {
                        "status": "undetermined",
                        "value": "undetermined",
                        "basis": "open_world_absence",
                    }
                },
                "metadata": {
                    "prompt_artifacts": {
                        "atoms": {
                            "n400.aggravated_felony_after_1990": {
                                "parsed": {
                                    "status": "undetermined",
                                    "value": "undetermined",
                                    "basis": "open_world_absence",
                                }
                            }
                        }
                    }
                },
            }
        ],
        "map_validation_reports": [
            {
                "ok": True,
                "case_id": "gmc_open_world_silence_personal_statement",
                "entries": [
                    {
                        "atom_id": "n400.aggravated_felony_after_1990",
                        "status": "valid",
                        "action": "accept",
                        "reason": "undetermined is acceptable",
                        "original_value": "undetermined",
                        "basis": "open_world_absence",
                        "source_ids": [],
                    }
                ],
            }
        ],
    }

    summary = summarize_governed_run("anthropic", "fake", result, cases)
    metrics = summary["expected_binding_metrics"]

    assert metrics["expected_binding_count"] >= 1
    assert metrics["raw_status_match_count"] >= 1
    assert metrics["raw_basis_match_count"] >= 1
