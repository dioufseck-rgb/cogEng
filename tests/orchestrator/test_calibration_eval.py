from __future__ import annotations

import json
from pathlib import Path

from rulekit.orchestrator.calibration_eval import (
    build_calibration_report,
    case_split_group,
    make_case_split,
    mismatch_direction_counts,
    run_calibration_eval,
)
from rulekit.orchestrator.cases import CaseExample, ExpectedOutcome
from rulekit.orchestrator.map_profile_repair import (
    ProfileDefaultsMapStep,
    apply_map_profile_repair_patch,
    build_map_profile_repair_patch,
)
from rulekit.runtime import adjudicate_cases, load_program


FCRA_PROFILE_PROGRAM_PATH = (
    Path(__file__).parents[2]
    / "audits"
    / "fcra_credit_reporting_deep"
    / "rulekit_export_profile2"
    / "program.json"
)


def _case(index: int, *, split_group: str | None = None) -> CaseExample:
    return CaseExample(
        case_id=f"case_{index}",
        title=f"Case {index}",
        narrative=f"Narrative {index}",
        metadata={"split_group": split_group} if split_group else {},
        expected_outcomes=[
            ExpectedOutcome(
                determination_id="det.allowed",
                expected_value="true",
            )
        ],
    )


def test_make_case_split_is_deterministic_and_disjoint():
    cases = [_case(index) for index in range(10)]

    split_1 = make_case_split(
        cases,
        repair_count=3,
        validation_count=2,
        final_holdout_count=4,
        seed=42,
        strategy="shuffle",
    )
    split_2 = make_case_split(
        cases,
        repair_count=3,
        validation_count=2,
        final_holdout_count=4,
        seed=42,
        strategy="shuffle",
    )

    assert {
        name: [case.case_id for case in items]
        for name, items in split_1.items()
    } == {
        name: [case.case_id for case in items]
        for name, items in split_2.items()
    }
    assert {name: len(items) for name, items in split_1.items()} == {
        "repair": 3,
        "validation": 2,
        "final_holdout": 4,
        "reserve": 1,
    }
    all_ids = [
        case.case_id
        for items in split_1.values()
        for case in items
    ]
    assert len(all_ids) == len(set(all_ids))


def test_stratified_split_spreads_repeated_groups():
    cases = [
        _case(index, split_group="direct")
        for index in range(6)
    ] + [
        _case(index + 6, split_group="indirect")
        for index in range(6)
    ]

    split = make_case_split(
        cases,
        repair_count=4,
        validation_count=4,
        final_holdout_count=4,
        seed=4,
    )

    for split_name in ("repair", "validation", "final_holdout"):
        groups = {case_split_group(case) for case in split[split_name]}
        assert groups == {"direct", "indirect"}


def test_case_split_group_prefers_metadata_and_has_fallbacks():
    assert case_split_group(_case(1, split_group="Pending Review")) == "pending_review"
    assert case_split_group(CaseExample(
        case_id="bank_eval_identity_theft_missing_report",
        title="Not-mine dispute lacks completed identity theft report",
        narrative="narrative",
    )) == "identity_theft"


def test_run_calibration_eval_writes_locked_final_holdout_manifest(tmp_path):
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps({"cases": [_case(index).model_dump(mode="json") for index in range(6)]}),
        encoding="utf-8",
    )

    summary = run_calibration_eval(
        program_path="program.json",
        cases_path=cases_path,
        output_dir=tmp_path / "audit",
        repair_count=2,
        validation_count=2,
        final_holdout_count=2,
        seed=7,
        model_specs=None,
        run_final=False,
    )

    manifest = json.loads(
        (tmp_path / "audit" / "split_manifest.json").read_text(encoding="utf-8")
    )
    report = (tmp_path / "audit" / "calibration_report.md").read_text(encoding="utf-8")

    assert summary["split_counts"] == {
        "repair": 2,
        "validation": 2,
        "final_holdout": 2,
        "reserve": 0,
    }
    assert manifest["final_holdout_locked"] is True
    assert manifest["run_final"] is False
    assert manifest["split_strategy"] == "stratified"
    assert manifest["splits"]["repair"][0]["split_group"]
    assert "`final_holdout` | 2 | no |" in report
    assert "## Split Group Balance" in report
    assert (tmp_path / "audit" / "case_slices" / "final_holdout.json").exists()
    assert (tmp_path / "audit" / "candidate_patches.json").exists()


def test_build_calibration_report_marks_final_as_run_only_when_released():
    manifest = {
        "splits": {
            "repair": [{"case_id": "r1"}],
            "validation": [{"case_id": "v1"}],
            "final_holdout": [{"case_id": "f1"}],
            "reserve": [],
        }
    }
    summary = {
        "round_id": "round_x",
        "split_counts": {
            "repair": 1,
            "validation": 1,
            "final_holdout": 1,
            "reserve": 0,
        },
        "governed": {"final_holdout": [{"provider": "anthropic", "model": "m"}]},
        "direct": {},
    }

    report = build_calibration_report(summary, manifest)

    assert "`final_holdout` | 1 | yes |" in report


def test_mismatch_direction_counts_supports_governed_and_direct_shapes():
    counts = mismatch_direction_counts([
        {
            "outcome": "false",
            "expected_outcome": "undetermined",
            "matched_expected": False,
        },
        {
            "outcome": "true",
            "reference_outcome": "false",
            "matches_reference": False,
        },
        {
            "outcome": "true",
            "expected_outcome": "true",
            "matched_expected": True,
        },
    ])

    assert counts == {
        "false->undetermined": 1,
        "true->false": 1,
    }


def test_map_profile_repair_generates_replayable_branch_defaults():
    program = load_program(FCRA_PROFILE_PROGRAM_PATH)
    case = CaseExample(
        case_id="repair_case",
        title="No side branches",
        narrative=(
            "No reseller branch applies. No reinsertion branch applies. "
            "No consumer-statement branch applies. No direct-furnisher branch applies."
        ),
        expected_outcomes=[
            ExpectedOutcome(
                determination_id="fcra.reseller_satisfied",
                expected_value="true",
            ),
            ExpectedOutcome(
                determination_id="fcra.reinsertion_satisfied",
                expected_value="true",
            ),
            ExpectedOutcome(
                determination_id="fcra.direct_furnisher_satisfied",
                expected_value="true",
            ),
            ExpectedOutcome(
                determination_id="fcra.consumer_statement_satisfied",
                expected_value="true",
            ),
        ],
    )
    patch = build_map_profile_repair_patch(
        program=program,
        repair_cases=[case],
        repair_dispositions=[
            {
                "case_id": case.case_id,
                "determination_id": "fcra.reseller_satisfied",
                "outcome": "undetermined",
                "expected_outcome": "true",
                "matched_expected": False,
            }
        ],
        repair_map_records=[],
        round_id="round_x",
    )

    assert patch["repair_target"] == "map_profile.default_rules"
    assert patch["candidate_rule_count"] >= 2

    patched = apply_map_profile_repair_patch(program, patch)
    result = adjudicate_cases(
        patched,
        [case],
        determinations=[
            "fcra.reseller_satisfied",
            "fcra.reinsertion_satisfied",
            "fcra.direct_furnisher_satisfied",
            "fcra.consumer_statement_satisfied",
        ],
        map_step=ProfileDefaultsMapStep(),
    )

    assert result["matched_disposition_count"] == 4
    assert result["mismatch_count"] == 0
