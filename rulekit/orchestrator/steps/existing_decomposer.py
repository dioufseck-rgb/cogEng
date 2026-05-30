"""Adapter for the existing decomposer build path.

The adapter intentionally wraps the existing `build_from_spec` entry point
without changing decomposer internals. It returns a serializable summary
instead of embedding the in-memory DAG build result in the run payload.
"""
from __future__ import annotations

from typing import Any

from rulekit.orchestrator.ids import run_id as new_run_id
from rulekit.orchestrator.step import (
    BuildStepSpec,
    DialogueCapability,
    StepContext,
    StepKind,
    StepRunResult,
    StepRunStatus,
    utc_now,
)


class ExistingDecomposerStep:
    def __init__(self, step_id: str = "step_existing_decomposer"):
        self.spec = BuildStepSpec(
            step_id=step_id,
            name="Existing decomposer adapter",
            description="Wraps rulekit.build.decomposer.build_from_spec.",
            kind=StepKind.STOCHASTIC,
            dialogue_capability=DialogueCapability.OPTIONAL,
            default_k=1,
            max_dialogue_turns=4,
            tags=["decomposer"],
        )

    def run(
        self,
        input_payload: dict[str, Any],
        context: StepContext,
    ) -> StepRunResult:
        started_at = utc_now()
        try:
            result = self._run_decomposer(input_payload)
            status = StepRunStatus.SUCCEEDED
            output_payload = result
            metadata = {"adapter": "existing_decomposer"}
        except Exception as exc:
            status = StepRunStatus.FAILED
            output_payload = {
                "adapter": "existing_decomposer",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            metadata = {"adapter": "existing_decomposer", "failed": True}
        return StepRunResult(
            run_id=new_run_id(),
            step_id=self.spec.step_id,
            status=status,
            input_payload=input_payload,
            output_payload=output_payload,
            started_at=started_at,
            completed_at=utc_now(),
            execution_context=context.execution_context,
            metadata=metadata,
        )

    def _run_decomposer(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        from rulekit.build.decomposer import build_from_spec
        from rulekit.build.spec import load_spec_from_yaml

        build_spec = input_payload.get("build_spec")
        spec_path = input_payload.get("spec_path")
        if build_spec is None:
            if not spec_path:
                raise ValueError("ExistingDecomposerStep requires build_spec or spec_path")
            build_spec = load_spec_from_yaml(
                spec_path,
                voices_registry=input_payload.get("voices_registry"),
            )

        llm = input_payload.get("llm")
        if llm is None:
            raise ValueError(
                "ExistingDecomposerStep requires an llm object in v0.1; "
                "unit tests should pass a scripted/mock LLM"
            )

        result = build_from_spec(
            build_spec,
            llm=llm,
            refine=bool(input_payload.get("refine", True)),
            state_dir=input_payload.get("state_dir"),
        )
        return {
            "adapter": "existing_decomposer",
            "status": "built",
            "policy_name": result.spec.policy_name,
            "atom_count": len(result.atoms),
            "determination_count": len(result.determinations),
            "determination_ids": sorted(result.determinations.keys()),
            "audit_call_count": sum(len(audit) for audit in result.audit.values()),
            "refinement_count": len(result.refinement_results or {}),
        }


__all__ = ["ExistingDecomposerStep"]
