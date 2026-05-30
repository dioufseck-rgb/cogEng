from __future__ import annotations

import json

from rulekit.orchestrator.config import save_policy_workspace_seed
from rulekit.orchestrator.examples.fcra_dispute import fcra_dispute_seed
from rulekit.orchestrator.workflow import export_review_bundle, run_policy_seed_file
from rulekit.runtime import adjudicate_cases, load_program, load_runtime_cases


def test_fcra_dispute_example_runs_builder_export_and_runtime(tmp_path):
    seed_path = tmp_path / "fcra_dispute.yaml"
    root = tmp_path / "workspaces"
    export_dir = tmp_path / "export"
    runtime_cases_path = tmp_path / "runtime_cases.json"
    save_policy_workspace_seed(fcra_dispute_seed(), seed_path)

    run = run_policy_seed_file(seed_path, root, program_id="prog_fcra_dispute")

    assert run.validation.ok is True
    assert len(run.dispositions) == 6
    assert sum(1 for row in run.dispositions if row.matched_expected) == 6
    assert run.snapshot.program.metadata.name == (
        "FCRA dispute reinvestigation timing candidate"
    )
    assert any(
        node.kind == "conditional_numeric"
        for node in run.snapshot.program.nodes.values()
    )

    exported = export_review_bundle(
        root,
        run.workspace.workspace_id,
        run.trajectory.trajectory_id,
        export_dir,
    )
    assert exported["validation_ok"] is True
    assert (export_dir / "program.json").exists()

    runtime_cases_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": case.case_id,
                        "title": case.title,
                        "narrative": case.narrative,
                        "facts": case.structured_fields["facts"],
                        "expected_outcomes": {
                            expected.determination_id: expected.expected_value
                            for expected in case.expected_outcomes
                        },
                    }
                    for case in next(iter(run.workspace.case_suites.values())).cases.values()
                ]
            }
        ),
        encoding="utf-8",
    )

    runtime_result = adjudicate_cases(
        load_program(export_dir / "program.json"),
        load_runtime_cases(runtime_cases_path),
        determinations=["fcra.selected_dispute_obligations_satisfied"],
    )

    assert runtime_result["case_count"] == 6
    assert runtime_result["matched_disposition_count"] == 6
    assert runtime_result["mismatch_count"] == 0
    assert {row["outcome"] for row in runtime_result["dispositions"]} == {
        "false",
        "true",
        "undetermined",
    }
