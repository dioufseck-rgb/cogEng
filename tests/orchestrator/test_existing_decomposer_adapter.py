from __future__ import annotations

from decimal import Decimal

from rulekit.build.extract import ReaderVoice
from rulekit.build.spec import BuildSpec, DeterminationDeclaration
from rulekit.orchestrator import StepContext, StepRunStatus
from rulekit.orchestrator.steps.existing_decomposer import ExistingDecomposerStep


class ScriptedLLM:
    def call(self, prompt, *args, **kwargs):
        prompt_lower = str(prompt).lower()
        if "mapping" in prompt_lower or "dedup" in prompt_lower or "consolidat" in prompt_lower:
            return "{}"
        return '{"type": "leaf", "claim": "test claim", "source_span": "test span"}'


def test_existing_decomposer_adapter_runs_with_build_spec(tmp_path):
    policy_path = tmp_path / "policy.txt"
    policy_path.write_text("Test policy. Rule A applies.", encoding="utf-8")
    spec = BuildSpec(
        policy_name="Test Policy",
        policy_source=str(policy_path),
        abbreviation="test",
        voice=ReaderVoice(
            role="test reader",
            domain="test",
            background="test",
        ),
        constants={"threshold": Decimal("1")},
        determinations=[
            DeterminationDeclaration(
                id="test.D1",
                description="Is Rule A satisfied?",
                polarity="positive",
                source_span="Rule A",
            )
        ],
    )

    result = ExistingDecomposerStep().run(
        {
            "build_spec": spec,
            "llm": ScriptedLLM(),
            "refine": False,
        },
        StepContext(),
    )

    assert result.status == StepRunStatus.SUCCEEDED
    assert result.output_payload["status"] == "built"
    assert result.output_payload["determination_ids"] == ["test.D1"]


def test_existing_decomposer_adapter_reports_missing_llm(tmp_path):
    result = ExistingDecomposerStep().run({}, StepContext())

    assert result.status == StepRunStatus.FAILED
    assert result.output_payload["error_type"] == "ValueError"

