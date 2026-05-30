from __future__ import annotations

from rulekit.orchestrator import (
    ProgramEditKind,
    ProgramEditOperation,
    apply_persisted_program_edits,
    export_builder_ui,
    build_trajectory_projection,
    build_workspace_index_projection,
    load_trajectory,
    record_reviewer_hint,
    reexercise_latest_snapshot,
    run_policy_seed_file,
    save_trajectory,
)
from rulekit.orchestrator.cli import sample_seed
from rulekit.orchestrator.config import save_policy_workspace_seed


def test_workspace_and_trajectory_projections_are_ui_ready(tmp_path):
    seed_path = tmp_path / "seed.yaml"
    root = tmp_path / "workspaces"
    save_policy_workspace_seed(sample_seed(), seed_path)
    result = run_policy_seed_file(seed_path, root, program_id="prog_sample")
    edit_result = apply_persisted_program_edits(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
        [
            ProgramEditOperation(
                kind=ProgramEditKind.UPDATE_BOOLEAN_ATOM,
                payload={
                    "atom_id": "sample.requirement_b",
                    "notes": "Projection test edit.",
                },
            )
        ],
    )
    reexercise_latest_snapshot(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
    )
    trajectory = load_trajectory(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
    )
    record_reviewer_hint(
        trajectory,
        message="Reviewer hint for projection display.",
        target_step_id="map_prebound_facts",
        case_id="case_yes",
        atom_ids=["sample.requirement_a"],
        reviewer_id="reviewer_1",
    )
    save_trajectory(trajectory, root)

    index = build_workspace_index_projection(root)
    projection = build_trajectory_projection(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
    )

    assert index["workspace_count"] == 1
    assert index["workspaces"][0]["trajectory_count"] == 1
    assert projection["workspace"]["workspace_id"] == result.workspace.workspace_id
    assert projection["trajectory"]["validation_ok"] is True
    assert projection["program"]["snapshot_id"] == edit_result.new_snapshot.snapshot_id
    assert projection["program"]["atom_count"] == 2
    assert len(projection["program"]["atoms"]) == 2
    assert projection["program"]["nodes"]
    assert any(node.get("children") for node in projection["program"]["nodes"])
    assert len(projection["branches"]) == 2
    assert any(branch["is_active"] for branch in projection["branches"])
    assert any(event["kind"] == "program_edit_applied" for event in projection["timeline"])
    assert any(event["title"].startswith("Reviewer hint:") for event in projection["timeline"])
    assert projection["reviewer_hints"][0]["case_id"] == "case_yes"
    assert {row["case_id"] for row in projection["case_results"]} == {
        "case_no",
        "case_yes",
    }
    assert all("matched_expected" in row for row in projection["case_results"])
    assert {"coverage", "regression", "sensitivity", "source_text_coverage"} <= {
        report["kind"] for report in projection["reports"]
    }
    assert projection["map_records"]

    ui = export_builder_ui(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
        tmp_path / "builder_ui",
    )
    assert ui["validation_ok"] is True
    assert (tmp_path / "builder_ui" / "index.html").exists()
    assert (tmp_path / "builder_ui" / "styles.css").exists()
    assert (tmp_path / "builder_ui" / "app.js").exists()
    assert (tmp_path / "builder_ui" / "projection.json").exists()
    html = (tmp_path / "builder_ui" / "index.html").read_text(encoding="utf-8")
    app_js = (tmp_path / "builder_ui" / "app.js").read_text(encoding="utf-8")
    assert 'data-view="actions"' in html
    assert 'data-view="graph"' in html
    assert "renderDagTree" in app_js
    assert 'postAction(data.apiBase, "hints"' in app_js
    assert 'postAction(apiBase, "cases"' in app_js
