from __future__ import annotations

import rulekit.orchestrator.branch_findings_eval as branch_eval
from rulekit.orchestrator.branch_findings_eval import (
    compose_final_from_branch_findings,
    run_branch_findings_eval,
)


PROGRAM_PATH = "audits/fcra_credit_reporting_deep/rulekit_export_profile2/program.json"
CASES_PATH = "rulekit/orchestrator/example_cases/fcra_cra_logic_stress_eval.yaml"


def test_compose_final_from_branch_findings() -> None:
    assert compose_final_from_branch_findings(
        [
            {"blocks_final": False},
            {"blocks_final": "false"},
        ]
    ) == "true"
    assert compose_final_from_branch_findings(
        [
            {"blocks_final": False},
            {"blocks_final": "undetermined"},
        ]
    ) == "undetermined"
    assert compose_final_from_branch_findings(
        [
            {"blocks_final": "undetermined"},
            {"blocks_final": True},
        ]
    ) == "false"


def test_branch_findings_eval_computes_final_from_fake_llm(tmp_path, monkeypatch) -> None:
    raw = """
{
  "case_id": "cra_logic_consumer_statement_not_carried_forward",
  "branch_findings": [
    {
      "determination_id": "fcra.consumer_statement_satisfied",
      "applicable": true,
      "satisfied": false,
      "outcome": "false",
      "blocks_final": true,
      "decisive_branch": "consumer statement subsequent reporting",
      "rationale": "Reports omitted the statement/dispute notation.",
      "critical_facts": ["consumer statement omitted"],
      "confidence": 0.9
    },
    {
      "determination_id": "fcra.frivolous_termination_valid",
      "applicable": false,
      "satisfied": false,
      "outcome": "false",
      "blocks_final": false,
      "decisive_branch": "not invoked",
      "rationale": "No frivolous termination was invoked.",
      "critical_facts": [],
      "confidence": 0.9
    }
  ],
  "routing_findings": [
    {
      "determination_id": "fcra.human_review_required",
      "outcome": "false",
      "rationale": "No routing trigger.",
      "confidence": 0.9
    }
  ],
  "case_level_notes": ""
}
"""

    class FakeLLM:
        provider = "anthropic"
        model = "fake"

        def __init__(self, **kwargs):
            pass

        def call(self, stage_name, prompt, stream=True):
            assert stage_name == "branch_findings:cra_logic_consumer_statement_not_carried_forward"
            assert "BRANCH DETERMINATIONS" in prompt
            assert "ROUTING DETERMINATIONS" in prompt
            return raw

    monkeypatch.setattr(branch_eval, "LLMCaller", FakeLLM)

    result = run_branch_findings_eval(
        program_path=PROGRAM_PATH,
        cases_path=CASES_PATH,
        model_specs=["anthropic:fake"],
        output_dir=tmp_path / "branch",
        case_ids=["cra_logic_consumer_statement_not_carried_forward"],
        determinations=[
            "fcra.consumer_statement_satisfied",
            "fcra.frivolous_termination_valid",
            "fcra.dispute_resolution_compliant",
            "fcra.human_review_required",
        ],
        final_determination="fcra.dispute_resolution_compliant",
        routing_determination="fcra.human_review_required",
    )

    run = result["runs"][0]
    assert run["final_agreement"]["reference_agree_count"] == 1
    assert run["routing_agreement"]["reference_agree_count"] == 1
    assert run["determination_agreement"]["reference_agree_count"] == 4
