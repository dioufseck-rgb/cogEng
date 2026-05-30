from __future__ import annotations

import pytest

from rulekit.orchestrator import (
    DialogueCapability,
    ExecutionContext,
    StepKind,
    StepRunResult,
    StepRunStatus,
    BuildStepSpec,
)


def test_build_step_spec_defaults_to_deterministic_no_dialogue():
    spec = BuildStepSpec(
        step_id="step_load_policy",
        name="Load policy",
    )

    assert spec.kind == StepKind.DETERMINISTIC
    assert spec.dialogue_capability == DialogueCapability.NONE
    assert spec.default_k == 1
    assert spec.max_dialogue_turns == 0


def test_stochastic_step_requires_positive_k():
    with pytest.raises(ValueError):
        BuildStepSpec(
            step_id="step_bad",
            name="Bad",
            kind=StepKind.STOCHASTIC,
            default_k=0,
        )


def test_dialogue_capable_step_requires_turn_budget():
    with pytest.raises(ValueError):
        BuildStepSpec(
            step_id="step_ambiguous",
            name="Resolve ambiguity",
            dialogue_capability=DialogueCapability.OPTIONAL,
            max_dialogue_turns=0,
        )


def test_no_dialogue_step_rejects_turn_budget():
    with pytest.raises(ValueError):
        BuildStepSpec(
            step_id="step_no_dialogue",
            name="No dialogue",
            dialogue_capability=DialogueCapability.NONE,
            max_dialogue_turns=2,
        )


def test_step_run_result_records_execution_context():
    result = StepRunResult(
        run_id="run_1",
        step_id="step_load_policy",
        status=StepRunStatus.SUCCEEDED,
        input_payload={"policy_id": "pol_1"},
        output_payload={"loaded": True},
        execution_context=ExecutionContext(
            code_version="abc123",
            started_by="reviewer@example.com",
            environment={"python": "3.12"},
        ),
    )

    assert result.execution_context.code_version == "abc123"
    assert result.execution_context.environment["python"] == "3.12"

