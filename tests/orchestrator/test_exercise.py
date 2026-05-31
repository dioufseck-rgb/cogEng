from __future__ import annotations

from rulekit.contract import (
    AndNodeSpec,
    AtomRef,
    BindingBasis,
    BooleanAtom,
    CaseInputSchema,
    DeterminationProgram,
    DeterminationSpec,
    EvaluationMode,
    MapSpec,
    RoutingLogicSpec,
    ProgramMetadata,
    Provenance,
)
from rulekit.orchestrator import (
    CaseExample,
    ExpectedOutcome,
    exercise_program_on_case,
    exercise_program_on_case_with_map,
    exercise_program_on_case_with_map_record,
    exercise_program_on_suite,
    fact_bundle_from_values,
    map_record_from_values,
)
from rulekit.orchestrator.map_record import AtomBindingStatus


def _program() -> DeterminationProgram:
    atoms = {
        "fcba.unauthorized": BooleanAtom(
            id="fcba.unauthorized",
            statement="The charge was unauthorized.",
            source_span="1026.13(a)(1)",
            evaluation_mode=EvaluationMode.CHARACTERIZED,
        ),
        "fcba.credit_extended": BooleanAtom(
            id="fcba.credit_extended",
            statement="The transaction was an extension of credit.",
            source_span="1026.13(a)",
            evaluation_mode=EvaluationMode.CHARACTERIZED,
        ),
    }
    nodes = {
        "n_credit": AtomRef(
            node_id="n_credit",
            provenance=Provenance.TRANSCRIBED,
            source_span="1026.13(a)",
            atom_id="fcba.credit_extended",
        ),
        "n_unauth": AtomRef(
            node_id="n_unauth",
            provenance=Provenance.TRANSCRIBED,
            source_span="1026.13(a)(1)",
            atom_id="fcba.unauthorized",
        ),
        "n_root": AndNodeSpec(
            node_id="n_root",
            provenance=Provenance.STRUCTURAL,
            children=["n_credit", "n_unauth"],
        ),
    }
    return DeterminationProgram(
        metadata=ProgramMetadata(name="FCBA tiny", version="0.1"),
        nodes=nodes,
        map_spec=MapSpec(atoms=atoms),
        determinations={
            "fcba.billing_error": DeterminationSpec(
                id="fcba.billing_error",
                description="Is billing error.",
                source_span="1026.13(a)",
                root_node="n_root",
            )
        },
        case_input_schema=CaseInputSchema(has_narrative=True),
    )


def _case(case_id: str, expected: str) -> CaseExample:
    return CaseExample(
        case_id=case_id,
        title=case_id,
        narrative="Case narrative.",
        expected_outcomes=[
            ExpectedOutcome(
                determination_id="fcba.billing_error",
                expected_value=expected,
            )
        ],
    )


def test_fact_bundle_from_values_coerces_boolean_atoms():
    bundle = fact_bundle_from_values(
        _program(),
        {"fcba.credit_extended": True, "fcba.unauthorized": None},
    )

    assert str(bundle.get("fcba.credit_extended")) == "true"
    assert str(bundle.get("fcba.unauthorized")) == "undetermined"


def test_exercise_program_on_case_produces_disposition_and_trace():
    records = exercise_program_on_case(
        _program(),
        _case("case_1", "true"),
        {"fcba.credit_extended": True, "fcba.unauthorized": True},
        program_id="prog_fcba",
        program_version="0.1",
    )

    assert len(records) == 1
    record = records[0]
    assert record.outcome == "true"
    assert record.matched_expected is True
    assert set(record.load_bearing_path) == {
        "fcba.credit_extended",
        "fcba.unauthorized",
    }
    assert record.trace["trace"]


def test_map_record_from_values_captures_atom_bindings():
    record = map_record_from_values(
        _program(),
        _case("case_1", "true"),
        {"fcba.credit_extended": True},
        program_id="prog_fcba",
        evidence={"fcba.credit_extended": "statement shows credit"},
    )

    assert record.case_id == "case_1"
    assert record.bindings["fcba.credit_extended"].status.value == "bound"
    assert record.bindings["fcba.unauthorized"].status.value == "undetermined"
    assert record.bindings["fcba.credit_extended"].evidence == "statement shows credit"


def test_exercise_program_on_case_with_map_links_dispositions():
    map_record, dispositions = exercise_program_on_case_with_map(
        _program(),
        _case("case_1", "true"),
        {"fcba.credit_extended": True, "fcba.unauthorized": True},
        program_id="prog_fcba",
    )

    assert dispositions[0].metadata["map_record_id"] == map_record.map_record_id


def test_exercise_program_on_suite_handles_multiple_cases():
    records = exercise_program_on_suite(
        _program(),
        [_case("case_yes", "true"), _case("case_no", "false")],
        {
            "case_yes": {
                "fcba.credit_extended": True,
                "fcba.unauthorized": True,
            },
            "case_no": {
                "fcba.credit_extended": True,
                "fcba.unauthorized": False,
            },
        },
        program_id="prog_fcba",
    )

    assert [record.outcome for record in records] == ["true", "false"]
    assert all(record.matched_expected for record in records)


def test_conflicting_evidence_preserves_undetermined_over_false_dag_path():
    program = _program()
    case = _case("case_conflict", "undetermined")
    map_record = map_record_from_values(
        program,
        case,
        {"fcba.credit_extended": False},
        program_id="prog_fcba",
        evidence={
            "fcba.credit_extended": "not an extension of credit",
            "fcba.unauthorized": "cardholder and merchant records conflict",
        },
    )
    conflict = map_record.bindings["fcba.unauthorized"]
    conflict.status = AtomBindingStatus.UNDETERMINED
    conflict.value = "undetermined"
    conflict.basis = BindingBasis.CONFLICTING_EVIDENCE
    conflict.evidence = "cardholder and merchant records conflict"

    records = exercise_program_on_case_with_map_record(
        program,
        case,
        map_record,
        program_id="prog_fcba",
    )

    assert records[0].outcome == "undetermined"
    assert records[0].metadata["evidence_uncertainty_override"]["force_override_atom_ids"] == [
        "fcba.unauthorized"
    ]


def test_routing_determination_treats_missing_triggers_as_false():
    program = _program().model_copy(deep=True)
    program.determinations["fcba.human_review_required"] = DeterminationSpec(
        id="fcba.human_review_required",
        description="The case requires human review.",
        root_node="n_unauth",
        determination_kind="routing",
        routing=RoutingLogicSpec(trigger_atoms=["fcba.unauthorized"]),
    )
    case = CaseExample(
        case_id="case_route",
        title="case_route",
        narrative="No review trigger is established.",
        expected_outcomes=[
            ExpectedOutcome(
                determination_id="fcba.human_review_required",
                expected_value="false",
            )
        ],
    )
    map_record = map_record_from_values(
        program,
        case,
        {"fcba.credit_extended": True},
        program_id="prog_fcba",
    )

    records = exercise_program_on_case_with_map_record(
        program,
        case,
        map_record,
        program_id="prog_fcba",
    )

    assert records[0].outcome == "false"
    assert records[0].metadata["routing"]["undetermined_triggers"] == []
