from __future__ import annotations

import json

from rulekit.orchestrator.cli import template_seed
from rulekit.orchestrator.config import save_policy_workspace_seed
from rulekit.orchestrator.workflow import export_review_bundle, run_policy_seed_file
from rulekit.runtime import adjudicate_cases, load_program, load_runtime_cases

OVERALL_DETERMINATION = "n400.selected_n400_requirements_satisfied"


def test_uscis_n400_benchmark_runs_builder_export_and_runtime(tmp_path):
    seed = template_seed("uscis-n400")
    seed_path = tmp_path / "uscis_n400.json"
    root = tmp_path / "workspaces"
    export_dir = tmp_path / "export"
    runtime_cases_path = tmp_path / "runtime_cases.json"
    save_policy_workspace_seed(seed, seed_path)

    run = run_policy_seed_file(seed_path, root, program_id="prog_uscis_n400")

    assert len(seed.atoms) >= 100
    assert len(run.snapshot.program.nodes) >= 150
    assert len(run.snapshot.program.determinations) >= 10
    assert any(node.kind == "conditional_numeric" for node in run.snapshot.program.nodes.values())
    assert any(node.kind == "variadic_arithmetic" for node in run.snapshot.program.nodes.values())
    assert any(node.kind == "unary_arithmetic" for node in run.snapshot.program.nodes.values())
    assert run.validation.ok is True
    assert len(run.dispositions) == 14
    assert run.summary()["mismatch_count"] == 0
    assert {row.outcome for row in run.dispositions} == {"false", "true", "undetermined"}

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
                            "structured_fields": case.structured_fields,
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
        determinations=[OVERALL_DETERMINATION, "n400.human_review_required"],
    )

    assert runtime_result["case_count"] == 13
    assert runtime_result["mismatch_count"] == 0
    assert runtime_result["matched_disposition_count"] == 14
