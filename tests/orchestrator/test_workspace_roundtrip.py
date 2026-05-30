from __future__ import annotations

from rulekit.orchestrator import (
    CaseExample,
    CaseSuite,
    ExpectedOutcome,
    PolicySource,
    PolicySourceKind,
    Trajectory,
    TrajectoryBranch,
    Workspace,
)


def test_workspace_model_round_trips_through_json():
    policy = PolicySource(
        policy_id="pol_fcba",
        title="FCBA Section 1026.13",
        kind=PolicySourceKind.TEXT,
        content="Billing error means...",
    )
    suite = CaseSuite(
        suite_id="suite_fcba",
        name="FCBA cases",
        cases={
            "case_unauth": CaseExample(
                case_id="case_unauth",
                title="Unauthorized charge",
                narrative="The consumer disputes an unauthorized charge.",
                expected_outcomes=[
                    ExpectedOutcome(
                        determination_id="fcba.billing_error",
                        expected_value="true",
                    )
                ],
            )
        },
    )
    trajectory = Trajectory(
        trajectory_id="traj_fcba",
        workspace_id="ws_fcba",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )
    workspace = Workspace(
        workspace_id="ws_fcba",
        name="FCBA Orchestrator",
        policies={"pol_fcba": policy},
        case_suites={"suite_fcba": suite},
        trajectories={"traj_fcba": trajectory},
    )

    loaded = Workspace.model_validate_json(workspace.model_dump_json())

    assert loaded.workspace_id == "ws_fcba"
    assert loaded.policies["pol_fcba"].content == "Billing error means..."
    assert loaded.case_suites["suite_fcba"].cases["case_unauth"].title

