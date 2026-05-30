from __future__ import annotations

from rulekit.orchestrator import (
    DispositionRecord,
    StepRunResult,
    StepRunStatus,
    generate_coverage_report,
    generate_regression_report,
    generate_sensitivity_report,
    generate_source_text_coverage_report,
    generate_variance_report,
    load_disposition,
    load_map_record,
    save_disposition,
    save_map_record,
    MapExtractionRecord,
    AtomBindingRecord,
    AtomBindingStatus,
)
from tests.orchestrator.test_exercise import _program


def test_report_skeletons_generate_simple_projections():
    old = [
        DispositionRecord(
            disposition_id="disp_1",
            program_id="prog_1",
            case_id="case_1",
            determination_id="det",
            outcome="true",
            expected_outcome="true",
            matched_expected=True,
        )
    ]
    new = [
        DispositionRecord(
            disposition_id="disp_2",
            program_id="prog_2",
            case_id="case_1",
            determination_id="det",
            outcome="false",
        )
    ]

    coverage = generate_coverage_report(old, workspace_id="ws_1")
    regression = generate_regression_report(old, new, workspace_id="ws_1")
    variance = generate_variance_report(
        [
            StepRunResult(
                run_id="run_1",
                step_id="decompose",
                status=StepRunStatus.SUCCEEDED,
                input_payload={},
                output_payload={"a": 1},
            ),
            StepRunResult(
                run_id="run_2",
                step_id="decompose",
                status=StepRunStatus.SUCCEEDED,
                input_payload={},
                output_payload={"a": 2},
            ),
        ],
        workspace_id="ws_1",
    )

    assert coverage.payload["match_rate"] == 1.0
    assert regression.payload["change_count"] == 1
    assert variance.payload["unique_output_count"] == 2


def test_source_text_coverage_report_matches_exact_spans():
    report = generate_source_text_coverage_report(
        _program(),
        "1026.13(a) 1026.13(a)(1)",
        workspace_id="ws_1",
    )

    assert report.kind.value == "source_text_coverage"
    assert report.payload["matched_span_count"] >= 2


def test_sensitivity_report_counts_load_bearing_paths():
    report = generate_sensitivity_report(
        [
            DispositionRecord(
                disposition_id="disp_1",
                program_id="prog_1",
                case_id="case_1",
                determination_id="det",
                outcome="true",
                matched_expected=True,
                load_bearing_path=["a", "b"],
            ),
            DispositionRecord(
                disposition_id="disp_2",
                program_id="prog_1",
                case_id="case_2",
                determination_id="det",
                outcome="false",
                matched_expected=False,
                load_bearing_path=["b"],
            ),
        ],
        workspace_id="ws_1",
    )

    assert report.kind.value == "sensitivity"
    assert report.payload["load_bearing_atom_counts"] == {"a": 1, "b": 2}
    assert report.payload["mismatch_load_bearing_atom_counts"] == {"b": 1}


def test_disposition_persistence_roundtrip(tmp_path):
    disposition = DispositionRecord(
        disposition_id="disp_1",
        program_id="prog_1",
        case_id="case_1",
        determination_id="det",
        outcome="true",
    )

    save_disposition(tmp_path, "ws_1", "traj_1", disposition)
    loaded = load_disposition(tmp_path, "ws_1", "traj_1", "disp_1")

    assert loaded.disposition_id == "disp_1"
    assert loaded.outcome == "true"


def test_map_record_persistence_roundtrip(tmp_path):
    record = MapExtractionRecord(
        map_record_id="map_1",
        program_id="prog_1",
        case_id="case_1",
        bindings={
            "atom_1": AtomBindingRecord(
                atom_id="atom_1",
                atom_type="boolean",
                value=True,
                status=AtomBindingStatus.BOUND,
                evidence="case says yes",
            )
        },
    )

    save_map_record(tmp_path, "ws_1", "traj_1", record)
    loaded = load_map_record(tmp_path, "ws_1", "traj_1", "map_1")

    assert loaded.bindings["atom_1"].evidence == "case says yes"
