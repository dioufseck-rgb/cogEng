from __future__ import annotations

import json

from rulekit.orchestrator.cli import main, sample_seed
from rulekit.orchestrator.config import save_policy_workspace_seed
from rulekit.orchestrator.workflow import run_policy_seed_file
from rulekit.runtime import adjudicate_cases, load_program, load_runtime_cases


def test_runtime_runner_adjudicates_compact_prebound_cases(tmp_path):
    seed_path = tmp_path / "seed.yaml"
    root = tmp_path / "workspaces"
    save_policy_workspace_seed(sample_seed(), seed_path)
    run = run_policy_seed_file(seed_path, root, program_id="prog_sample")
    program_path = tmp_path / "program.json"
    program_path.write_text(run.program.model_dump_json(indent=2), encoding="utf-8")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "runtime_yes",
                        "title": "Runtime yes",
                        "narrative": "Both requirements are met.",
                        "facts": {
                            "sample.requirement_a": True,
                            "sample.requirement_b": True,
                        },
                        "expected_outcomes": {"sample.eligible": "true"},
                    },
                    {
                        "case_id": "runtime_no",
                        "title": "Runtime no",
                        "narrative": "Requirement B is missing.",
                        "facts": {
                            "sample.requirement_a": True,
                            "sample.requirement_b": False,
                        },
                        "expected_outcomes": {"sample.eligible": "false"},
                    },
                    {
                        "case_id": "runtime_unknown_expected",
                        "title": "Runtime case without label",
                        "narrative": "The runtime caller wants a disposition only.",
                        "facts": {
                            "sample.requirement_a": True,
                            "sample.requirement_b": True,
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = adjudicate_cases(
        load_program(program_path),
        load_runtime_cases(cases_path),
        determinations=["sample.eligible"],
    )

    assert result["case_count"] == 3
    assert result["disposition_count"] == 3
    assert result["matched_disposition_count"] == 2
    assert result["mismatch_count"] == 0
    assert [row["outcome"] for row in result["dispositions"]] == ["true", "false", "true"]
    assert result["dispositions"][2]["matched_expected"] is None


def test_adjudicate_cli_writes_runtime_artifacts(tmp_path):
    seed_path = tmp_path / "seed.yaml"
    root = tmp_path / "workspaces"
    save_policy_workspace_seed(sample_seed(), seed_path)
    run = run_policy_seed_file(seed_path, root, program_id="prog_sample")
    program_path = tmp_path / "program.json"
    program_path.write_text(run.program.model_dump_json(indent=2), encoding="utf-8")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            [
                {
                    "case_id": "runtime_yes",
                    "title": "Runtime yes",
                    "narrative": "Both requirements are met.",
                    "facts": {
                        "sample.requirement_a": True,
                        "sample.requirement_b": True,
                    },
                    "expected_outcomes": {"sample.eligible": "true"},
                }
            ]
        ),
        encoding="utf-8",
    )
    out = tmp_path / "runtime_out"

    code = main(
        [
            "adjudicate",
            "--program",
            str(program_path),
            "--cases",
            str(cases_path),
            "--determination",
            "sample.eligible",
            "--out",
            str(out),
            "--json",
        ]
    )

    assert code == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    dispositions = json.loads((out / "dispositions.json").read_text(encoding="utf-8"))
    assert summary["case_count"] == 1
    assert dispositions[0]["outcome"] == "true"
