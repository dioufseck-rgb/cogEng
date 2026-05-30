from __future__ import annotations

import pytest

from rulekit.contract import validate_program
from rulekit.orchestrator import (
    AtomDeclaration,
    BooleanOperator,
    CaseDeclaration,
    NodeDeclaration,
    NodeKind,
    OrchestratorDeterminationDeclaration,
    PolicyWorkspaceSeed,
    create_boolean_candidate_program,
    create_candidate_program,
    create_policy_workspace,
    load_policy_workspace_seed,
    save_policy_workspace_seed,
)
from rulekit.orchestrator.exercise import exercise_program_on_suite


def _seed() -> PolicyWorkspaceSeed:
    return PolicyWorkspaceSeed(
        workspace_name="Any Policy Workspace",
        policy_title="Any Policy",
        policy_text="Approve when requirement A and requirement B are met.",
        determinations=[
            OrchestratorDeterminationDeclaration(
                determination_id="any.approved",
                description="The request is approved.",
                atom_ids=["any.a", "any.b"],
                operator=BooleanOperator.AND,
            )
        ],
        atoms=[
            AtomDeclaration(atom_id="any.a", statement="Requirement A is met."),
            AtomDeclaration(atom_id="any.b", statement="Requirement B is met."),
        ],
        cases=[
            CaseDeclaration(
                case_id="case_yes",
                title="All requirements",
                narrative="A and B are met.",
                expected_outcomes={"any.approved": "true"},
            )
        ],
    )


def test_create_policy_workspace_is_domain_neutral():
    bundle = create_policy_workspace(_seed())

    assert bundle.workspace.name == "Any Policy Workspace"
    assert bundle.graph.topological_order() == [
        "load_policy",
        "decompose_policy",
        "validate_candidate",
    ]
    assert bundle.trajectory.workspace_id == bundle.workspace.workspace_id


def test_create_boolean_candidate_program_can_exercise_any_policy():
    seed = _seed()
    program = create_boolean_candidate_program(
        program_id="prog_any",
        program_name="Any Policy Candidate",
        version="0.1",
        determinations=seed.determinations,
        atoms=seed.atoms,
    )
    cases = list(create_policy_workspace(seed).workspace.case_suites.values())[0].cases

    assert validate_program(program).ok
    records = exercise_program_on_suite(
        program,
        list(cases.values()),
        {"case_yes": {"any.a": True, "any.b": True}},
        program_id="prog_any",
    )

    assert records[0].outcome == "true"
    assert records[0].matched_expected is True


def test_boolean_candidate_program_supports_engine_or_operator():
    seed = PolicyWorkspaceSeed(
        workspace_name="Any Policy Workspace",
        policy_title="Any Policy",
        policy_text="Approve when either A or B is met.",
        determinations=[
            OrchestratorDeterminationDeclaration(
                determination_id="any.approved",
                description="The request is approved.",
                atom_ids=["any.a", "any.b"],
                operator=BooleanOperator.OR,
            )
        ],
        atoms=[
            AtomDeclaration(atom_id="any.a", statement="Requirement A is met."),
            AtomDeclaration(atom_id="any.b", statement="Requirement B is met."),
        ],
        cases=[
            CaseDeclaration(
                case_id="case_or",
                title="One requirement",
                narrative="Only B is met.",
                expected_outcomes={"any.approved": "true"},
            )
        ],
    )
    program = create_boolean_candidate_program(
        program_id="prog_any",
        program_name="Any Policy Candidate",
        version="0.1",
        determinations=seed.determinations,
        atoms=seed.atoms,
    )
    cases = list(create_policy_workspace(seed).workspace.case_suites.values())[0].cases
    records = exercise_program_on_suite(
        program,
        list(cases.values()),
        {"case_or": {"any.a": False, "any.b": True}},
        program_id="prog_any",
    )

    assert records[0].outcome == "true"


def test_boolean_candidate_program_supports_engine_at_least_operator():
    seed = PolicyWorkspaceSeed(
        workspace_name="Any Policy Workspace",
        policy_title="Any Policy",
        policy_text="Approve when two of three criteria are met.",
        determinations=[
            OrchestratorDeterminationDeclaration(
                determination_id="any.approved",
                description="The request is approved.",
                atom_ids=["any.a", "any.b", "any.c"],
                operator=BooleanOperator.AT_LEAST,
                n=2,
            )
        ],
        atoms=[
            AtomDeclaration(atom_id="any.a", statement="A is met."),
            AtomDeclaration(atom_id="any.b", statement="B is met."),
            AtomDeclaration(atom_id="any.c", statement="C is met."),
        ],
        cases=[
            CaseDeclaration(
                case_id="case_two",
                title="Two criteria",
                narrative="A and C are met.",
                expected_outcomes={"any.approved": "true"},
            )
        ],
    )
    program = create_boolean_candidate_program(
        program_id="prog_any",
        program_name="Any Policy Candidate",
        version="0.1",
        determinations=seed.determinations,
        atoms=seed.atoms,
    )
    cases = list(create_policy_workspace(seed).workspace.case_suites.values())[0].cases
    records = exercise_program_on_suite(
        program,
        list(cases.values()),
        {"case_two": {"any.a": True, "any.b": False, "any.c": True}},
        program_id="prog_any",
    )

    assert records[0].outcome == "true"


def test_boolean_candidate_program_supports_engine_not_operator():
    seed = PolicyWorkspaceSeed(
        workspace_name="Any Policy Workspace",
        policy_title="Any Policy",
        policy_text="Deny when the applicant is ineligible.",
        determinations=[
            OrchestratorDeterminationDeclaration(
                determination_id="any.approved",
                description="The request is approved.",
                atom_ids=["any.ineligible"],
                operator=BooleanOperator.NOT,
            )
        ],
        atoms=[
            AtomDeclaration(
                atom_id="any.ineligible",
                statement="The applicant is ineligible.",
            ),
        ],
        cases=[
            CaseDeclaration(
                case_id="case_not",
                title="No disqualifier",
                narrative="The applicant is not ineligible.",
                expected_outcomes={"any.approved": "true"},
            )
        ],
    )
    program = create_boolean_candidate_program(
        program_id="prog_any",
        program_name="Any Policy Candidate",
        version="0.1",
        determinations=seed.determinations,
        atoms=seed.atoms,
    )
    cases = list(create_policy_workspace(seed).workspace.case_suites.values())[0].cases
    records = exercise_program_on_suite(
        program,
        list(cases.values()),
        {"case_not": {"any.ineligible": False}},
        program_id="prog_any",
    )

    assert records[0].outcome == "true"


def test_boolean_candidate_program_rejects_not_with_multiple_children():
    seed = _seed()
    seed.determinations[0].operator = BooleanOperator.NOT

    with pytest.raises(ValueError, match="not requires exactly one child"):
        create_boolean_candidate_program(
            program_id="prog_any",
            program_name="Any Policy Candidate",
            version="0.1",
            determinations=seed.determinations,
            atoms=seed.atoms,
        )


def test_policy_workspace_seed_roundtrips_yaml(tmp_path):
    seed = _seed()
    path = tmp_path / "policy_seed.yaml"

    save_policy_workspace_seed(seed, path)
    loaded = load_policy_workspace_seed(path)
    bundle = create_policy_workspace(loaded)

    assert loaded.policy_title == "Any Policy"
    assert bundle.workspace.name == "Any Policy Workspace"


def test_policy_workspace_seed_rejects_non_engine_operator():
    with pytest.raises(ValueError):
        PolicyWorkspaceSeed(
            workspace_name="Bad",
            policy_title="Bad",
            policy_text="Bad",
            determinations=[
                OrchestratorDeterminationDeclaration(
                    determination_id="bad.det",
                    description="Bad",
                    atom_ids=["bad.a"],
                    operator="xor",
                )
            ],
            atoms=[AtomDeclaration(atom_id="bad.a", statement="A")],
        )


def test_create_candidate_program_supports_typed_nodes_and_arithmetic():
    program = create_candidate_program(
        program_id="prog_typed",
        program_name="Typed Policy Candidate",
        version="0.1",
        atoms=[
            AtomDeclaration(
                atom_id="pa.functional_limitation",
                statement="The patient has a documented functional limitation.",
            ),
            AtomDeclaration(
                atom_id="pa.requested_amount",
                statement="The requested amount in dollars.",
                atom_type="numeric",
                numeric_unit="usd",
            ),
            AtomDeclaration(
                atom_id="pa.annual_income",
                statement="The patient's annual income in dollars.",
                atom_type="numeric",
                numeric_unit="usd",
            ),
            AtomDeclaration(
                atom_id="pa.bonus_amount",
                statement="A supplemental requested amount in dollars.",
                atom_type="numeric",
                numeric_unit="usd",
            ),
            AtomDeclaration(
                atom_id="pa.floor_amount",
                statement="The looked-up minimum allowed amount.",
                atom_type="numeric",
                evaluation_mode="looked_up",
                numeric_unit="usd",
            ),
        ],
        nodes=[
            NodeDeclaration(
                node_id="n_function",
                kind=NodeKind.ATOM_REF,
                atom_id="pa.functional_limitation",
            ),
            NodeDeclaration(
                node_id="n_requested",
                kind=NodeKind.NUMERIC_ATOM_REF,
                atom_id="pa.requested_amount",
            ),
            NodeDeclaration(
                node_id="n_income",
                kind=NodeKind.NUMERIC_ATOM_REF,
                atom_id="pa.annual_income",
            ),
            NodeDeclaration(
                node_id="n_bonus",
                kind=NodeKind.NUMERIC_ATOM_REF,
                atom_id="pa.bonus_amount",
            ),
            NodeDeclaration(
                node_id="n_requested_total",
                kind=NodeKind.BINARY_ARITHMETIC,
                operator="plus",
                left="n_requested",
                right="n_bonus",
            ),
            NodeDeclaration(
                node_id="n_income_pct",
                kind=NodeKind.UNARY_ARITHMETIC,
                operator="times_const",
                literal_constant="0.2",
                child="n_income",
            ),
            NodeDeclaration(
                node_id="n_floor",
                kind=NodeKind.NAMED_QUANTITY,
                atom_id="pa.floor_amount",
            ),
            NodeDeclaration(
                node_id="n_allowed_cap",
                kind=NodeKind.VARIADIC_ARITHMETIC,
                operator="max",
                children=["n_income_pct", "n_floor"],
            ),
            NodeDeclaration(
                node_id="n_zero",
                kind=NodeKind.CONSTANT,
                literal_value="0",
            ),
            NodeDeclaration(
                node_id="n_selected_cap",
                kind=NodeKind.CONDITIONAL_NUMERIC,
                condition="n_function",
                if_true="n_allowed_cap",
                if_false="n_zero",
            ),
            NodeDeclaration(
                node_id="n_within_cap",
                kind=NodeKind.COMPARISON,
                operator="leq",
                left="n_requested_total",
                right="n_selected_cap",
            ),
            NodeDeclaration(
                node_id="n_root",
                kind=NodeKind.AND,
                children=["n_function", "n_within_cap"],
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

    assert validate_program(program).ok
    seed = PolicyWorkspaceSeed(
        workspace_name="Typed Workspace",
        policy_title="Typed Policy",
        policy_text="Approve if functional limitation exists and amount is within cap.",
        atoms=[],
        nodes=[],
        determinations=[],
        cases=[
            CaseDeclaration(
                case_id="case_typed",
                title="Typed case",
                narrative="Functional limitation and amount within cap.",
                expected_outcomes={"pa.approved": "true"},
            )
        ],
    )
    cases = list(create_policy_workspace(seed).workspace.case_suites.values())[0].cases
    records = exercise_program_on_suite(
        program,
        list(cases.values()),
        {
            "case_typed": {
                "pa.functional_limitation": True,
                "pa.requested_amount": 19000,
                "pa.bonus_amount": 500,
                "pa.annual_income": 100000,
                "pa.floor_amount": 10000,
            }
        },
        program_id="prog_typed",
    )

    assert records[0].outcome == "true"
