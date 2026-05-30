from __future__ import annotations

import pytest

from rulekit.contract import validate_program
from rulekit.orchestrator import (
    AtomDeclaration,
    BooleanOperator,
    CaseDeclaration,
    OrchestratorDeterminationDeclaration,
    PolicyWorkspaceSeed,
    create_boolean_candidate_program,
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
