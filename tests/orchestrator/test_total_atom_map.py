from __future__ import annotations

from pathlib import Path

from rulekit.orchestrator.total_atom_map import run_total_atom_map_eval


PROGRAM_PATH = Path("audits/fcra_credit_reporting_deep/rulekit_export_profile2/program.json")
CASES_PATH = Path("rulekit/orchestrator/example_cases/fcra_cra_logic_stress_eval.yaml")
CASE_IDS = [
    "cra_logic_extension_later_info_not_forwarded",
    "cra_logic_late_results_notice_after_timely_reinvestigation",
    "cra_logic_valid_frivolous_termination_no_reinvestigation",
]


def test_total_atom_map_simulation_fills_complete_atom_matrix(tmp_path: Path) -> None:
    result = run_total_atom_map_eval(
        program_path=PROGRAM_PATH,
        cases_path=CASES_PATH,
        output_dir=tmp_path / "total_atom_map",
        case_ids=CASE_IDS,
    )

    assert result["mode"] == "simulate"
    assert result["case_count"] == 3
    assert result["atom_count"] == 120
    assert result["disposition_count"] == 45
    assert result["matched_disposition_count"] == 45
    assert result["mismatch_count"] == 0
    assert len(result["map_records"]) == 3
    assert all(len(record["bindings"]) == 120 for record in result["map_records"])
    assert (tmp_path / "total_atom_map" / "atom_catalog.json").exists()
    assert (tmp_path / "total_atom_map" / "summary.json").exists()


def test_total_atom_map_schema_mode_writes_prompt_artifacts_only(tmp_path: Path) -> None:
    result = run_total_atom_map_eval(
        program_path=PROGRAM_PATH,
        cases_path=CASES_PATH,
        output_dir=tmp_path / "total_atom_map_schema",
        case_ids=[CASE_IDS[0]],
        mode="schema",
    )

    prompt_path = Path(result["prompts"][0]["path"])
    assert result["mode"] == "schema"
    assert result["case_count"] == 1
    assert result["atom_count"] == 120
    assert prompt_path.exists()
    assert "Return ONLY this JSON shape" in prompt_path.read_text(encoding="utf-8")
    assert not (tmp_path / "total_atom_map_schema" / "dispositions.json").exists()
