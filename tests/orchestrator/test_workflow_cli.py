from __future__ import annotations

import json

from rulekit.orchestrator import (
    ProgramEditKind,
    ProgramEditOperation,
    add_persisted_case,
    apply_persisted_program_edits,
    export_review_bundle,
    inspect_persisted_run,
    list_branches,
    list_persisted_runs,
    mark_branch_status,
    record_persisted_reviewer_hint,
    reexercise_latest_snapshot,
    run_policy_seed_file,
)
from rulekit.orchestrator.cli import main, sample_seed
from rulekit.orchestrator.config import save_policy_workspace_seed
from rulekit.orchestrator.examples import prior_auth_typed_seed


def test_run_policy_seed_file_persists_and_inspects(tmp_path):
    seed_path = tmp_path / "seed.yaml"
    root = tmp_path / "workspaces"
    save_policy_workspace_seed(sample_seed(), seed_path)

    result = run_policy_seed_file(seed_path, root, program_id="prog_sample")
    inspected = inspect_persisted_run(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
    )

    assert result.validation.ok
    assert result.summary()["mismatch_count"] == 0
    assert inspected["validation_ok"] is True
    assert inspected["sidecars"]["snapshots"] == 1
    assert inspected["sidecars"]["dispositions"] == 2
    assert inspected["sidecars"]["reports"] == 4
    listed = list_persisted_runs(root)
    assert listed[0]["workspace_id"] == result.workspace.workspace_id

    exported = export_review_bundle(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
        tmp_path / "review_bundle",
    )
    assert exported["validation_ok"] is True
    program = json.loads((tmp_path / "review_bundle" / "program.json").read_text())
    reports = json.loads((tmp_path / "review_bundle" / "reports.json").read_text())
    diagnostics = json.loads((tmp_path / "review_bundle" / "diagnostics.json").read_text())
    events = json.loads((tmp_path / "review_bundle" / "trajectory_events.json").read_text())
    assert program["metadata"]["name"] == "Sample eligibility policy candidate"
    assert len(reports) == 4
    assert len(diagnostics) == 2
    assert len(events) == result.summary()["event_count"]

    edit_result = apply_persisted_program_edits(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
        [
            ProgramEditOperation(
                kind=ProgramEditKind.UPDATE_BOOLEAN_ATOM,
                payload={
                    "atom_id": "sample.requirement_b",
                    "notes": "Reviewer clarified this requirement.",
                },
            )
        ],
    )
    assert edit_result.validation.ok
    assert edit_result.branch_id != "br_main"
    inspected_after_edit = inspect_persisted_run(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
    )
    branches = list_branches(root, result.workspace.workspace_id, result.trajectory.trajectory_id)
    assert len(branches) == 2
    assert any(branch["branch_id"] == edit_result.branch_id for branch in branches)
    settled = mark_branch_status(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
        edit_result.branch_id,
        "settled",
        reviewer_id="reviewer_1",
        reason="Reviewed edit branch.",
    )
    assert settled["validation_ok"] is True
    assert settled["status"] == "settled"
    assert inspected_after_edit["sidecars"]["program_edits"] == 1
    assert inspected_after_edit["sidecars"]["snapshots"] == 2
    reexercise_result = reexercise_latest_snapshot(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
    )
    assert reexercise_result.validation.ok
    assert reexercise_result.summary()["mismatch_count"] == 0
    assert "regression" in reexercise_result.summary()["report_kinds"]
    inspected_after_reexercise = inspect_persisted_run(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
    )
    assert inspected_after_reexercise["sidecars"]["dispositions"] == 4
    assert inspected_after_reexercise["sidecars"]["reports"] == 8

    hint_result = record_persisted_reviewer_hint(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
        message="Requirement B was missed in the narrative; rerun with this hint.",
        target_step_id="map_prebound_facts",
        case_id="case_yes",
        atom_ids=["sample.requirement_b"],
        reviewer_id="reviewer_1",
    )
    assert hint_result.validation.ok
    hinted_reexercise = reexercise_latest_snapshot(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
    )
    assert hinted_reexercise.validation.ok
    case_yes_map = next(
        record
        for record in hinted_reexercise.map_records
        if record.case_id == "case_yes"
    )
    assert case_yes_map.metadata["reviewer_hint_count"] == 1
    assert case_yes_map.metadata["reviewer_hints"][0]["hint_id"] == hint_result.hint.hint_id

    case_result = add_persisted_case(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
        case_id="case_added",
        title="Reviewer-added eligible case",
        narrative="Requirement A and requirement B are both met.",
        facts={"sample.requirement_a": True, "sample.requirement_b": True},
        expected_outcomes={"sample.eligible": "true"},
        reviewer_id="reviewer_1",
    )
    assert case_result.validation.ok
    case_reexercise = reexercise_latest_snapshot(
        root,
        result.workspace.workspace_id,
        result.trajectory.trajectory_id,
    )
    assert case_reexercise.validation.ok
    assert {record.case_id for record in case_reexercise.dispositions} == {
        "case_added",
        "case_no",
        "case_yes",
    }


def test_cli_template_run_and_inspect(tmp_path, capsys):
    seed_path = tmp_path / "seed.yaml"
    root = tmp_path / "workspaces"

    assert main(["template", str(seed_path), "--json"]) == 0
    template_payload = json.loads(capsys.readouterr().out)
    assert template_payload["ok"] is True
    assert seed_path.exists()

    assert main(["run", str(seed_path), "--root", str(root), "--json"]) == 0
    run_payload = json.loads(capsys.readouterr().out)
    assert run_payload["ok"] is True
    assert run_payload["disposition_count"] == 2
    assert run_payload["ui_url"].endswith(
        f"/ui/{run_payload['workspace_id']}/{run_payload['trajectory_id']}/"
    )
    assert run_payload["latest_ui_url"] == "http://127.0.0.1:8000/ui/latest/"
    assert "rulekit-orchestrator serve" in run_payload["serve_command"]

    assert (
        main(
            [
                "inspect",
                "--root",
                str(root),
                "--workspace-id",
                run_payload["workspace_id"],
                "--trajectory-id",
                run_payload["trajectory_id"],
                "--json",
            ]
        )
        == 0
    )
    inspect_payload = json.loads(capsys.readouterr().out)
    assert inspect_payload["ok"] is True
    assert inspect_payload["event_count"] == run_payload["event_count"]

    assert main(["list", "--root", str(root), "--json"]) == 0
    list_payload = json.loads(capsys.readouterr().out)
    assert list_payload["count"] == 1

    export_dir = tmp_path / "exported"
    assert (
        main(
            [
                "export",
                "--root",
                str(root),
                "--workspace-id",
                run_payload["workspace_id"],
                "--trajectory-id",
                run_payload["trajectory_id"],
                "--out",
                str(export_dir),
                "--json",
            ]
        )
        == 0
    )
    export_payload = json.loads(capsys.readouterr().out)
    assert export_payload["ok"] is True
    assert (export_dir / "summary.json").exists()
    assert (export_dir / "program.json").exists()

    ops_path = tmp_path / "ops.json"
    ops_path.write_text(
        json.dumps(
            [
                {
                    "kind": "update_boolean_atom",
                    "payload": {
                        "atom_id": "sample.requirement_b",
                        "notes": "CLI reviewer note.",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "edit",
                str(ops_path),
                "--root",
                str(root),
                "--workspace-id",
                run_payload["workspace_id"],
                "--trajectory-id",
                run_payload["trajectory_id"],
                "--json",
            ]
        )
        == 0
    )
    edit_payload = json.loads(capsys.readouterr().out)
    assert edit_payload["ok"] is True
    assert edit_payload["operation_count"] == 1
    assert edit_payload["branch_id"] != "br_main"

    assert (
        main(
            [
                "branches",
                "list",
                "--root",
                str(root),
                "--workspace-id",
                run_payload["workspace_id"],
                "--trajectory-id",
                run_payload["trajectory_id"],
                "--json",
            ]
        )
        == 0
    )
    branches_payload = json.loads(capsys.readouterr().out)
    assert branches_payload["count"] == 2

    assert (
        main(
            [
                "branches",
                "mark",
                "--root",
                str(root),
                "--workspace-id",
                run_payload["workspace_id"],
                "--trajectory-id",
                run_payload["trajectory_id"],
                "--branch-id",
                edit_payload["branch_id"],
                "--status",
                "settled",
                "--json",
            ]
        )
        == 0
    )
    branch_mark_payload = json.loads(capsys.readouterr().out)
    assert branch_mark_payload["status"] == "settled"

    assert (
        main(
            [
                "reexercise",
                "--root",
                str(root),
                "--workspace-id",
                run_payload["workspace_id"],
                "--trajectory-id",
                run_payload["trajectory_id"],
                "--json",
            ]
        )
        == 0
    )
    reexercise_payload = json.loads(capsys.readouterr().out)
    assert reexercise_payload["ok"] is True
    assert reexercise_payload["disposition_count"] == 2
    assert "regression" in reexercise_payload["report_kinds"]

    assert (
        main(
            [
                "hint",
                "Requirement B was missed; rerun Map with this hint.",
                "--root",
                str(root),
                "--workspace-id",
                run_payload["workspace_id"],
                "--trajectory-id",
                run_payload["trajectory_id"],
                "--target-step-id",
                "map_prebound_facts",
                "--case-id",
                "case_yes",
                "--atom-id",
                "sample.requirement_b",
                "--reviewer-id",
                "reviewer_1",
                "--reexercise",
                "--json",
            ]
        )
        == 0
    )
    hint_payload = json.loads(capsys.readouterr().out)
    assert hint_payload["ok"] is True
    assert hint_payload["hint_id"].startswith("hint_")
    assert hint_payload["reexercise"]["ok"] is True
    assert hint_payload["reexercise"]["mismatch_count"] == 0

    assert (
        main(
            [
                "case",
                "add",
                "--root",
                str(root),
                "--workspace-id",
                run_payload["workspace_id"],
                "--trajectory-id",
                run_payload["trajectory_id"],
                "--case-id",
                "case_cli_added",
                "--title",
                "CLI added case",
                "--narrative",
                "Requirement A is met and requirement B is met.",
                "--fact",
                "sample.requirement_a=true",
                "--fact",
                "sample.requirement_b=true",
                "--expected",
                "sample.eligible=true",
                "--reviewer-id",
                "reviewer_1",
                "--reexercise",
                "--json",
            ]
        )
        == 0
    )
    case_payload = json.loads(capsys.readouterr().out)
    assert case_payload["ok"] is True
    assert case_payload["case_id"] == "case_cli_added"
    assert case_payload["reexercise"]["ok"] is True
    assert case_payload["reexercise"]["case_count"] == 3

    export_dir_after_edit = tmp_path / "exported_after_edit"
    assert (
        main(
            [
                "export",
                "--root",
                str(root),
                "--workspace-id",
                run_payload["workspace_id"],
                "--trajectory-id",
                run_payload["trajectory_id"],
                "--out",
                str(export_dir_after_edit),
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    edited_program = json.loads((export_dir_after_edit / "program.json").read_text())
    assert edited_program["map_spec"]["atoms"]["sample.requirement_b"]["notes"] == (
        "CLI reviewer note."
    )

    ui_dir = tmp_path / "ui"
    assert (
        main(
            [
                "ui",
                "--root",
                str(root),
                "--workspace-id",
                run_payload["workspace_id"],
                "--trajectory-id",
                run_payload["trajectory_id"],
                "--out",
                str(ui_dir),
                "--json",
            ]
        )
        == 0
    )
    ui_payload = json.loads(capsys.readouterr().out)
    assert ui_payload["ok"] is True
    assert (ui_dir / "index.html").exists()
    assert (ui_dir / "projection.json").exists()


def test_typed_prior_auth_seed_runs_full_workflow(tmp_path):
    seed_path = tmp_path / "prior_auth.yaml"
    root = tmp_path / "workspaces"
    save_policy_workspace_seed(prior_auth_typed_seed(), seed_path)

    result = run_policy_seed_file(seed_path, root, program_id="prog_prior_auth")
    outcomes = {
        (disposition.case_id, disposition.determination_id): disposition.outcome
        for disposition in result.dispositions
    }

    assert result.validation.ok
    assert result.summary()["mismatch_count"] == 0
    assert result.summary()["case_count"] == 4
    assert result.summary()["disposition_count"] == 8
    assert result.program.map_spec.atoms["pa.prior_therapy_weeks"].atom_type == "numeric"
    assert result.program.nodes["n_pain_improvement"].kind == "binary_arithmetic"
    assert outcomes[("case_standard_approved", "pa.approved")] == "true"
    assert outcomes[("case_materially_improved_denied", "pa.denied")] == "true"
    assert outcomes[("case_exception_approved", "pa.approved")] == "true"
    assert outcomes[("case_missing_duration_review", "pa.approved")] == "undetermined"
    assert outcomes[("case_missing_duration_review", "pa.denied")] == "undetermined"

    standard = next(
        disposition
        for disposition in result.dispositions
        if disposition.case_id == "case_standard_approved"
        and disposition.determination_id == "pa.approved"
    )
    assert "pa.prior_therapy_weeks" in standard.load_bearing_path
    assert "pa.baseline_pain_score" in standard.load_bearing_path
    assert "pa.current_pain_score" in standard.load_bearing_path


def test_cli_can_write_and_run_typed_prior_auth_template(tmp_path, capsys):
    seed_path = tmp_path / "prior_auth.yaml"
    root = tmp_path / "workspaces"

    assert (
        main(
            [
                "template",
                str(seed_path),
                "--example",
                "prior-auth-typed",
                "--json",
            ]
        )
        == 0
    )
    template_payload = json.loads(capsys.readouterr().out)
    assert template_payload["ok"] is True
    assert template_payload["example"] == "prior-auth-typed"

    assert main(["run", str(seed_path), "--root", str(root), "--json"]) == 0
    run_payload = json.loads(capsys.readouterr().out)
    assert run_payload["ok"] is True
    assert run_payload["case_count"] == 4
    assert run_payload["disposition_count"] == 8
    assert run_payload["mismatch_count"] == 0
    assert run_payload["ui_url"].endswith(
        f"/ui/{run_payload['workspace_id']}/{run_payload['trajectory_id']}/"
    )
