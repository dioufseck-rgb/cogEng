from __future__ import annotations

from rulekit.orchestrator import (
    ExecutionContext,
    StepContext,
    Trajectory,
    TrajectoryBranch,
    TrajectoryEvent,
    TrajectoryEventKind,
)
from rulekit.orchestrator.steps.stub import (
    DeterministicStubStep,
    StochasticStubStep,
    run_stochastic_step,
)


def test_deterministic_stub_step_produces_one_run():
    step = DeterministicStubStep(step_id="load_policy")
    result = step.run(
        {"policy_id": "pol_1"},
        StepContext(
            execution_context=ExecutionContext(
                code_version="abc123",
                started_by="tester",
            )
        ),
    )

    assert result.step_id == "load_policy"
    assert result.output_payload["input"]["policy_id"] == "pol_1"
    assert result.execution_context.code_version == "abc123"


def test_stochastic_stub_step_produces_k_runs_and_variance_summary():
    step = StochasticStubStep(step_id="decompose", default_k=3)
    runs, multi = run_stochastic_step(
        step,
        {"claim": "billing error"},
        StepContext(execution_context=ExecutionContext(seed=10)),
        k=3,
    )

    assert len(runs) == 3
    assert multi.run_ids == [run.run_id for run in runs]
    assert multi.variance_summary["unique_output_count"] == 3
    assert multi.selected_run_id == runs[0].run_id


def test_stochastic_runs_can_be_appended_to_trajectory():
    trajectory = Trajectory(
        trajectory_id="traj_1",
        workspace_id="ws_1",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )
    runs, _ = run_stochastic_step(
        StochasticStubStep(step_id="decompose", default_k=2),
        {"policy_id": "pol_1"},
        StepContext(),
        k=2,
    )

    for idx, run in enumerate(runs):
        trajectory.append_event(
            TrajectoryEvent(
                event_id=f"evt_{idx}",
                branch_id="br_main",
                kind=TrajectoryEventKind.STEP_RUN,
                payload={"run_id": run.run_id},
            )
        )

    assert len(trajectory.events) == 2
    assert trajectory.branches["br_main"].head_event_id == "evt_1"

