"""Small synchronous execution helpers for orchestrator steps."""
from __future__ import annotations

from rulekit.orchestrator.ids import event_id as new_event_id
from rulekit.orchestrator.persistence import save_step_run
from rulekit.orchestrator.step import BuildStep, StepContext, StepRunResult
from rulekit.orchestrator.steps.stub import StochasticStubStep, run_stochastic_step
from rulekit.orchestrator.trajectory import (
    Trajectory,
    TrajectoryEvent,
    TrajectoryEventKind,
)


def run_step_and_record(
    step: BuildStep,
    input_payload: dict,
    context: StepContext,
    trajectory: Trajectory,
    *,
    persist_root: str | None = None,
) -> StepRunResult:
    """Run one step, append a STEP_RUN event, and optionally persist the run."""
    run = step.run(input_payload, context)
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=context.branch_id or trajectory.active_branch_id,
            kind=TrajectoryEventKind.STEP_RUN,
            payload={"run_id": run.run_id, "step_id": run.step_id},
        )
    )
    if persist_root is not None:
        save_step_run(
            persist_root,
            trajectory.workspace_id,
            trajectory.trajectory_id,
            run,
        )
    return run


def run_stochastic_step_and_record(
    step: StochasticStubStep,
    input_payload: dict,
    context: StepContext,
    trajectory: Trajectory,
    *,
    k: int | None = None,
    persist_root: str | None = None,
):
    """Run k stochastic candidates, append events, and optionally persist runs."""
    runs, multi = run_stochastic_step(step, input_payload, context, k=k)
    for run in runs:
        trajectory.append_event(
            TrajectoryEvent(
                event_id=new_event_id(),
                branch_id=context.branch_id or trajectory.active_branch_id,
                kind=TrajectoryEventKind.STEP_RUN,
                payload={
                    "run_id": run.run_id,
                    "step_id": run.step_id,
                    "multi_run_id": multi.multi_run_id,
                },
            )
        )
        if persist_root is not None:
            save_step_run(
                persist_root,
                trajectory.workspace_id,
                trajectory.trajectory_id,
                run,
            )
    return runs, multi


__all__ = ["run_step_and_record", "run_stochastic_step_and_record"]
