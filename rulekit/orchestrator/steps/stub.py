"""Deterministic and stochastic stub steps for v0.1 orchestration tests."""
from __future__ import annotations

import json
from typing import Any, Protocol

from rulekit.orchestrator.ids import multi_run_id as new_multi_run_id
from rulekit.orchestrator.ids import run_id as new_run_id
from rulekit.orchestrator.step import (
    BuildStepSpec,
    DialogueCapability,
    ExecutionContext,
    MultiRunResult,
    StepContext,
    StepKind,
    StepRunResult,
    StepRunStatus,
    utc_now,
)


class OutputComparator(Protocol):
    def compare(self, outputs: list[dict[str, Any]]) -> dict[str, Any]:
        ...


class NormalizedJsonComparator:
    """Simple exact comparator over normalized JSON."""

    def compare(self, outputs: list[dict[str, Any]]) -> dict[str, Any]:
        normalized = [
            json.dumps(output, sort_keys=True, default=str)
            for output in outputs
        ]
        return {
            "method": "normalized_json_exact",
            "output_count": len(outputs),
            "unique_output_count": len(set(normalized)),
            "all_outputs_equal": len(set(normalized)) <= 1,
        }


class DeterministicStubStep:
    def __init__(
        self,
        step_id: str = "step_stub_deterministic",
        output_payload: dict[str, Any] | None = None,
    ):
        self.spec = BuildStepSpec(
            step_id=step_id,
            name="Deterministic stub step",
            description="Echoes input plus configured output for tests.",
            kind=StepKind.DETERMINISTIC,
        )
        self.output_payload = output_payload or {"ok": True}

    def run(
        self,
        input_payload: dict[str, Any],
        context: StepContext,
    ) -> StepRunResult:
        started_at = utc_now()
        return StepRunResult(
            run_id=new_run_id(),
            step_id=self.spec.step_id,
            status=StepRunStatus.SUCCEEDED,
            input_payload=input_payload,
            output_payload={
                **self.output_payload,
                "input": input_payload,
            },
            started_at=started_at,
            completed_at=utc_now(),
            execution_context=context.execution_context,
            metadata={"stub": True, **context.metadata},
        )


class StochasticStubStep:
    def __init__(self, step_id: str = "step_stub_stochastic", default_k: int = 3):
        self.spec = BuildStepSpec(
            step_id=step_id,
            name="Stochastic stub step",
            description="Produces distinguishable candidate outputs for tests.",
            kind=StepKind.STOCHASTIC,
            default_k=default_k,
            dialogue_capability=DialogueCapability.OPTIONAL,
            max_dialogue_turns=4,
        )

    def run(
        self,
        input_payload: dict[str, Any],
        context: StepContext,
    ) -> StepRunResult:
        candidate_index = int(context.metadata.get("candidate_index", 0))
        started_at = utc_now()
        return StepRunResult(
            run_id=new_run_id(),
            step_id=self.spec.step_id,
            status=StepRunStatus.SUCCEEDED,
            input_payload=input_payload,
            output_payload={
                "candidate_index": candidate_index,
                "candidate": {
                    "normalized_input": input_payload,
                    "variant": candidate_index,
                },
            },
            started_at=started_at,
            completed_at=utc_now(),
            execution_context=context.execution_context,
            metadata={"stub": True, **context.metadata},
        )


def run_stochastic_step(
    step: StochasticStubStep,
    input_payload: dict[str, Any],
    context: StepContext | None = None,
    *,
    k: int | None = None,
    comparator: OutputComparator | None = None,
) -> tuple[list[StepRunResult], MultiRunResult]:
    """Run a stochastic step k times and summarize output variance."""
    if context is None:
        context = StepContext(execution_context=ExecutionContext())
    if k is None:
        k = step.spec.default_k
    if k < 1:
        raise ValueError("k must be >= 1")
    comparator = comparator or NormalizedJsonComparator()

    runs: list[StepRunResult] = []
    for i in range(k):
        run_context = context.model_copy(
            update={"metadata": {**context.metadata, "candidate_index": i}}
        )
        runs.append(step.run(input_payload, run_context))

    outputs = [run.output_payload or {} for run in runs]
    multi = MultiRunResult(
        multi_run_id=new_multi_run_id(),
        step_id=step.spec.step_id,
        run_ids=[run.run_id for run in runs],
        selected_run_id=runs[0].run_id,
        consolidation_method="first_candidate",
        variance_summary=comparator.compare(outputs),
    )
    return runs, multi


__all__ = [
    "OutputComparator",
    "NormalizedJsonComparator",
    "DeterministicStubStep",
    "StochasticStubStep",
    "run_stochastic_step",
]
