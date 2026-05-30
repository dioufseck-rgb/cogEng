from __future__ import annotations

from rulekit.orchestrator import (
    CandidateFixKind,
    DiagnosticKind,
    diagnose_case_result,
    diagnose_dispositions,
    exercise_program_on_case_with_map,
    load_case_diagnostic,
    save_case_diagnostic,
)

from tests.orchestrator.test_exercise import _case, _program


def test_diagnose_case_result_projects_mismatch_and_fixes():
    map_record, dispositions = exercise_program_on_case_with_map(
        _program(),
        _case("case_bad", "true"),
        {"fcba.credit_extended": True},
        program_id="prog_fcba",
        evidence={"fcba.credit_extended": "credit card account statement"},
    )

    diagnostic = diagnose_case_result(dispositions[0], map_record)

    assert diagnostic.kind == DiagnosticKind.MISMATCH
    assert diagnostic.case_id == "case_bad"
    assert diagnostic.map_record_id == map_record.map_record_id
    assert diagnostic.map_statuses["fcba.unauthorized"] == "undetermined"
    assert diagnostic.evidence_by_atom["fcba.credit_extended"]
    assert CandidateFixKind.REVIEW_MAP_BINDING in {
        fix.kind for fix in diagnostic.candidate_fixes
    }
    assert CandidateFixKind.REVIEW_PROGRAM_LOGIC in {
        fix.kind for fix in diagnostic.candidate_fixes
    }


def test_diagnose_dispositions_joins_map_records_by_metadata():
    map_record, dispositions = exercise_program_on_case_with_map(
        _program(),
        _case("case_good", "true"),
        {"fcba.credit_extended": True, "fcba.unauthorized": True},
        program_id="prog_fcba",
    )

    diagnostics = diagnose_dispositions(dispositions, [map_record])

    assert diagnostics[0].kind == DiagnosticKind.MATCH
    assert diagnostics[0].map_record_id == map_record.map_record_id
    assert diagnostics[0].candidate_fixes == []


def test_case_diagnostic_roundtrips_to_disk(tmp_path):
    map_record, dispositions = exercise_program_on_case_with_map(
        _program(),
        _case("case_bad", "true"),
        {"fcba.credit_extended": True},
        program_id="prog_fcba",
    )
    diagnostic = diagnose_case_result(dispositions[0], map_record)

    save_case_diagnostic(tmp_path, "ws_1", "traj_1", diagnostic)
    loaded = load_case_diagnostic(
        tmp_path,
        "ws_1",
        "traj_1",
        diagnostic.diagnostic_id,
    )

    assert loaded == diagnostic
