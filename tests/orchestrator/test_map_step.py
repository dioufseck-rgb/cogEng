from __future__ import annotations

from rulekit.orchestrator import (
    MapStepContext,
    PreboundFactsMapStep,
    exercise_program_on_case_with_map_record,
    exercise_program_on_suite_with_map_step,
    fact_values_from_map_record,
)

from tests.orchestrator.test_exercise import _case, _program


def test_prebound_facts_map_step_produces_map_record():
    case = _case("case_1", "true")
    case.structured_fields = {
        "facts": {
            "fcba.credit_extended": True,
            "fcba.unauthorized": True,
        },
        "evidence": {
            "fcba.credit_extended": "account statement",
        },
    }

    result = PreboundFactsMapStep().run(
        _program(),
        case,
        MapStepContext(program_id="prog_fcba", substrate_id="prebound_test"),
    )

    assert result.map_record.substrate_id == "prebound_test"
    assert result.map_record.bindings["fcba.credit_extended"].evidence == "account statement"
    assert fact_values_from_map_record(result.map_record)["fcba.unauthorized"] is True


def test_exercise_program_on_case_with_map_record_evaluates_result():
    case = _case("case_1", "true")
    case.structured_fields = {
        "facts": {
            "fcba.credit_extended": True,
            "fcba.unauthorized": True,
        }
    }
    map_record = PreboundFactsMapStep().run(
        _program(),
        case,
        MapStepContext(program_id="prog_fcba"),
    ).map_record

    records = exercise_program_on_case_with_map_record(
        _program(),
        case,
        map_record,
        program_id="prog_fcba",
    )

    assert records[0].outcome == "true"
    assert records[0].metadata["map_record_id"] == map_record.map_record_id


def test_exercise_program_on_suite_with_map_step_runs_cases():
    case_yes = _case("case_yes", "true")
    case_yes.structured_fields = {
        "facts": {
            "fcba.credit_extended": True,
            "fcba.unauthorized": True,
        }
    }
    case_no = _case("case_no", "false")
    case_no.structured_fields = {
        "facts": {
            "fcba.credit_extended": True,
            "fcba.unauthorized": False,
        }
    }

    map_records, records = exercise_program_on_suite_with_map_step(
        _program(),
        [case_yes, case_no],
        PreboundFactsMapStep(),
        program_id="prog_fcba",
    )

    assert len(map_records) == 2
    assert [record.outcome for record in records] == ["true", "false"]
