from __future__ import annotations

from rulekit.orchestrator.examples.fcba_stub import run_fcba_stub
from rulekit.orchestrator import validate_persisted_trajectory


def test_fcba_stub_trajectory_roundtrip(tmp_path):
    result = run_fcba_stub(tmp_path)

    trajectory = result["trajectory"]
    loaded_workspace = result["loaded_workspace"]
    loaded_trajectory = result["loaded_trajectory"]

    assert loaded_workspace.workspace_id == "ws_fcba_stub"
    assert loaded_trajectory.trajectory_id == "traj_fcba_stub"
    assert result["branch_id"] in trajectory.branches
    assert result["dialogue"].turn_count == 2
    assert result["snapshot"].program_id == "prog_fcba_stub"
    assert result["edit_result"].before_hash != result["edit_result"].after_hash
    assert len(result["map_records"]) == 2
    assert [d.matched_expected for d in result["dispositions"]] == [True, True]
    assert [d.kind.value for d in result["diagnostics"]] == ["match", "match"]
    assert {r.kind.value for r in result["reports"]} == {
        "coverage",
        "source_text_coverage",
        "sensitivity",
        "variance",
    }
    assert result["multi_run"].variance_summary["unique_output_count"] == 2
    assert any(event.kind.value == "branch_created" for event in trajectory.events)
    assert any(event.kind.value == "program_snapshot" for event in trajectory.events)
    assert any(event.kind.value == "program_edit_applied" for event in trajectory.events)
    assert any(event.kind.value == "map_recorded" for event in trajectory.events)
    assert any(event.kind.value == "disposition_recorded" for event in trajectory.events)
    assert any(event.kind.value == "diagnostic_recorded" for event in trajectory.events)
    assert any(event.kind.value == "report_generated" for event in trajectory.events)
    assert validate_persisted_trajectory(tmp_path, trajectory).ok
    assert (
        tmp_path
        / "ws_fcba_stub"
        / "trajectories"
        / "traj_fcba_stub"
        / "events.jsonl"
    ).exists()
