from __future__ import annotations

from pathlib import Path

from rulekit.orchestrator.total_atom_map import (
    bindings_from_total_atom_payload,
    run_total_atom_map_eval,
)
from rulekit.runtime import load_program


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
    prompt = prompt_path.read_text(encoding="utf-8")
    assert "Return ONLY this JSON shape" in prompt
    assert "Numeric atoms must have a number" in prompt
    assert "Branch-closure rules" in prompt
    assert "Human-review trigger atoms are special routing atoms" in prompt
    assert not (tmp_path / "total_atom_map_schema" / "dispositions.json").exists()


def test_live_total_atom_payload_parser_keeps_one_binding_per_atom() -> None:
    program = load_program(PROGRAM_PATH)
    payload = {
        "case_id": "case_1",
        "bindings": [
            {
                "atom_id": "fcra.consumer_disputed_item",
                "status": "bound",
                "value": True,
                "basis": "explicit_positive",
                "source_ids": ["narrative"],
                "evidence": "consumer disputed the item",
                "explanation": "explicitly stated",
                "confidence": 0.93,
            },
            {
                "atom_id": "fcra.not_a_real_atom",
                "status": "bound",
                "value": True,
                "basis": "explicit_positive",
            },
            {
                "atom_id": "fcra.days_to_complete_reinvestigation",
                "status": "bound",
                "value": True,
                "basis": "computed",
            },
        ],
    }

    bindings = bindings_from_total_atom_payload(program, payload)

    assert len(bindings) == 120
    assert bindings["fcra.consumer_disputed_item"].status == "bound"
    assert bindings["fcra.consumer_disputed_item"].value is True
    assert bindings["fcra.consumer_disputed_item"].basis == "explicit_positive"
    assert bindings["fcra.days_to_complete_reinvestigation"].status == "undetermined"
    assert bindings["fcra.days_to_complete_reinvestigation"].value == "undetermined"
    assert bindings["fcra.account_identified"].status == "undetermined"
    assert "fcra.not_a_real_atom" not in bindings
