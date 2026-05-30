from __future__ import annotations

import json

from rulekit.orchestrator import (
    AtomDeclaration,
    NodeDeclaration,
    NodeKind,
    OrchestratorDeterminationDeclaration,
    CaseDeclaration,
    MapStepContext,
    PolicyWorkspaceSeed,
    PreboundFactsMapStep,
    ReviewerHint,
    TypedNarrativeMapStep,
    create_candidate_program,
    create_policy_workspace,
    exercise_program_on_case_with_map_record,
    exercise_program_on_suite_with_map_step,
    fact_values_from_map_record,
)

from tests.orchestrator.test_exercise import _case, _program


class ScriptedLLM:
    def __init__(self, responses: dict[str, dict]):
        self.responses = responses
        self.prompts: list[tuple[str, str]] = []

    def call(self, stage_name: str, prompt: str) -> str:
        self.prompts.append((stage_name, prompt))
        return json.dumps(self.responses[stage_name])


class HintAwareLLM:
    def __init__(self):
        self.prompts: list[tuple[str, str]] = []

    def call(self, stage_name: str, prompt: str) -> str:
        self.prompts.append((stage_name, prompt))
        if stage_name == "map_bind_boolean":
            return json.dumps({"pa.functional_limitation": "true"})
        if "completed eight weeks" in prompt:
            return json.dumps({"pa.therapy_weeks": 8})
        return json.dumps({"pa.therapy_weeks": "undetermined"})


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


def test_typed_narrative_map_step_binds_and_evaluates_natural_case_text():
    program = create_candidate_program(
        program_id="prog_pa",
        program_name="Prior auth typed demo",
        version="0.1",
        atoms=[
            AtomDeclaration(
                atom_id="pa.functional_limitation",
                statement="The patient has a documented functional limitation.",
            ),
            AtomDeclaration(
                atom_id="pa.therapy_weeks",
                statement="The number of weeks of conservative therapy completed.",
                atom_type="numeric",
                numeric_unit="weeks",
            ),
        ],
        nodes=[
            NodeDeclaration(
                node_id="n_function",
                kind=NodeKind.ATOM_REF,
                atom_id="pa.functional_limitation",
            ),
            NodeDeclaration(
                node_id="n_weeks",
                kind=NodeKind.NUMERIC_ATOM_REF,
                atom_id="pa.therapy_weeks",
            ),
            NodeDeclaration(
                node_id="n_six",
                kind=NodeKind.CONSTANT,
                literal_value=6,
            ),
            NodeDeclaration(
                node_id="n_weeks_ok",
                kind=NodeKind.COMPARISON,
                operator="geq",
                left="n_weeks",
                right="n_six",
            ),
            NodeDeclaration(
                node_id="n_root",
                kind=NodeKind.AND,
                children=["n_function", "n_weeks_ok"],
            ),
        ],
        determinations=[
            OrchestratorDeterminationDeclaration(
                determination_id="pa.approved",
                description="The request is approved.",
                root_node="n_root",
            )
        ],
    )
    seed_bundle = create_policy_workspace(
        PolicyWorkspaceSeed(
            workspace_name="PA",
            policy_title="PA",
            policy_text="Approve if limitation and six weeks therapy.",
            determinations=[],
            atoms=[],
            cases=[
                CaseDeclaration(
                    case_id="case_pa",
                    title="Narrative PA case",
                    narrative=(
                        "The patient has functional limitations and completed "
                        "8 weeks of conservative therapy."
                    ),
                    expected_outcomes={"pa.approved": "true"},
                )
            ],
        )
    )
    case = next(iter(next(iter(seed_bundle.workspace.case_suites.values())).cases.values()))
    llm = ScriptedLLM(
        {
            "map_bind_boolean": {"pa.functional_limitation": "true"},
            "map_bind_numeric": {"pa.therapy_weeks": 8},
        }
    )
    step = TypedNarrativeMapStep(llm, map_step_id="typed_test")
    result = step.run(
        program,
        case,
        MapStepContext(program_id="prog_pa", substrate_id="typed_test"),
    )

    assert result.map_record.bindings["pa.functional_limitation"].value == "true"
    assert result.map_record.bindings["pa.therapy_weeks"].value == "8"
    assert [stage for stage, _ in llm.prompts] == ["map_bind_boolean", "map_bind_numeric"]

    records = exercise_program_on_case_with_map_record(
        program,
        case,
        result.map_record,
        program_id="prog_pa",
    )

    assert records[0].outcome == "true"
    assert set(records[0].load_bearing_path) == {
        "pa.functional_limitation",
        "pa.therapy_weeks",
    }


def test_typed_narrative_map_step_includes_reviewer_hints_on_rerun():
    program = create_candidate_program(
        program_id="prog_pa",
        program_name="Prior auth typed demo",
        version="0.1",
        atoms=[
            AtomDeclaration(
                atom_id="pa.functional_limitation",
                statement="The patient has a documented functional limitation.",
            ),
            AtomDeclaration(
                atom_id="pa.therapy_weeks",
                statement="The number of weeks of conservative therapy completed.",
                atom_type="numeric",
                numeric_unit="weeks",
            ),
        ],
        nodes=[
            NodeDeclaration(
                node_id="n_function",
                kind=NodeKind.ATOM_REF,
                atom_id="pa.functional_limitation",
            ),
            NodeDeclaration(
                node_id="n_weeks",
                kind=NodeKind.NUMERIC_ATOM_REF,
                atom_id="pa.therapy_weeks",
            ),
            NodeDeclaration(
                node_id="n_six",
                kind=NodeKind.CONSTANT,
                literal_value=6,
            ),
            NodeDeclaration(
                node_id="n_weeks_ok",
                kind=NodeKind.COMPARISON,
                operator="geq",
                left="n_weeks",
                right="n_six",
            ),
            NodeDeclaration(
                node_id="n_root",
                kind=NodeKind.AND,
                children=["n_function", "n_weeks_ok"],
            ),
        ],
        determinations=[
            OrchestratorDeterminationDeclaration(
                determination_id="pa.approved",
                description="The request is approved.",
                root_node="n_root",
            )
        ],
    )
    seed_bundle = create_policy_workspace(
        PolicyWorkspaceSeed(
            workspace_name="PA",
            policy_title="PA",
            policy_text="Approve if limitation and six weeks therapy.",
            determinations=[],
            atoms=[],
            cases=[
                CaseDeclaration(
                    case_id="case_pa_hint",
                    title="Narrative PA case",
                    narrative="The patient has functional limitations. Visit count is unclear.",
                    expected_outcomes={"pa.approved": "true"},
                )
            ],
        )
    )
    case = next(iter(next(iter(seed_bundle.workspace.case_suites.values())).cases.values()))
    llm = HintAwareLLM()
    hint = ReviewerHint(
        message=(
            "The phrase 'completed eight weeks' was missed; bind therapy weeks as 8."
        ),
        case_id="case_pa_hint",
        atom_ids=["pa.therapy_weeks"],
        reviewer_id="reviewer_1",
    )
    result = TypedNarrativeMapStep(llm, map_step_id="typed_test").run(
        program,
        case,
        MapStepContext(
            program_id="prog_pa",
            substrate_id="typed_test",
            reviewer_hints=[hint],
        ),
    )

    assert result.map_record.bindings["pa.therapy_weeks"].value == "8"
    assert result.map_record.metadata["reviewer_hint_count"] == 1
    assert result.map_record.metadata["reviewer_hints"][0]["hint_id"] == hint.hint_id
    assert "REVIEWER HINTS FOR THIS RERUN" in llm.prompts[0][1]
    assert "pa.therapy_weeks" in llm.prompts[1][1]

    records = exercise_program_on_case_with_map_record(
        program,
        case,
        result.map_record,
        program_id="prog_pa",
    )

    assert records[0].outcome == "true"
