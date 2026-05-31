from __future__ import annotations

from rulekit.orchestrator.cases import CaseExample
from rulekit.orchestrator.direct_disposition_eval import (
    _expected_outcomes_from_cases,
    build_direct_disposition_prompt,
    summarize_direct_run,
)
from tests.orchestrator.test_map_governance import _program


def test_direct_disposition_prompt_contains_case_and_determinations():
    program = _program()
    case = CaseExample(
        case_id="case_1",
        title="Example",
        narrative="The record contains no aggravated felony conviction.",
        structured_fields={},
        expected_outcomes=[],
    )

    prompt = build_direct_disposition_prompt(
        program=program,
        policy_text="Naturalization benchmark policy.",
        case=case,
        determinations=["n400.no_aggravated_felony_bar"],
    )

    assert "Naturalization benchmark policy." in prompt
    assert "n400.no_aggravated_felony_bar" in prompt
    assert "The record contains no aggravated felony conviction." in prompt


def test_governed_direct_prompt_requests_uncertainty_and_source_checks():
    program = _program()
    case = CaseExample(
        case_id="case_1",
        title="Example",
        narrative="The record contains no aggravated felony conviction.",
        structured_fields={},
        expected_outcomes=[],
    )

    prompt = build_direct_disposition_prompt(
        program=program,
        policy_text="Naturalization benchmark policy.",
        case=case,
        determinations=["n400.no_aggravated_felony_bar"],
        prompt_style="governed",
    )

    assert "governed-style direct baseline" in prompt
    assert "uncertainty_flags" in prompt
    assert "anti_overclaim_check" in prompt
    assert "closed-world scope" in prompt


def test_direct_summary_reports_reference_agreement_and_costs():
    result = {
        "case_count": 1,
        "prompt_style": "governed",
        "case_runs": [
            {
                "cost": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "estimated_cost_usd": 0.003,
                    "latency_s": 2.0,
                }
            }
        ],
        "dispositions": [
            {
                "outcome": "true",
                "reference_outcome": "true",
            },
            {
                "outcome": "false",
                "reference_outcome": "true",
            },
        ],
    }

    summary = summarize_direct_run("anthropic", "fake", result)

    assert summary["reference_agreement"]["reference_agree_count"] == 1
    assert summary["reference_agreement"]["reference_disagree_count"] == 1
    assert summary["reference_agreement"]["agreement_rate"] == 0.5
    assert summary["prompt_style"] == "governed"
    assert summary["cost_metrics"]["llm_call_count"] == 1
    assert summary["cost_metrics"]["estimated_cost_usd"] == 0.003


def test_direct_eval_can_use_case_expected_outcomes_as_references():
    case = CaseExample(
        case_id="case_1",
        title="Example",
        narrative="Example narrative.",
        structured_fields={},
        expected_outcomes=[
            {
                "determination_id": "sample.eligible",
                "expected_value": "true",
            }
        ],
    )

    references = _expected_outcomes_from_cases([case])

    assert references == {("case_1", "sample.eligible"): "true"}
