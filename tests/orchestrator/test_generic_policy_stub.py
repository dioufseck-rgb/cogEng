from __future__ import annotations

from rulekit.orchestrator import validate_persisted_trajectory
from rulekit.orchestrator.examples.generic_policy_stub import run_generic_stub


def test_generic_policy_stub_full_cycle(tmp_path):
    result = run_generic_stub(tmp_path)

    assert result["loaded_workspace"].workspace_id == result["workspace"].workspace_id
    assert result["loaded_trajectory"].trajectory_id == result["trajectory"].trajectory_id
    assert result["snapshot"].program_id == "prog_generic_stub"
    assert result["edit_result"].before_hash != result["edit_result"].after_hash
    assert [d.outcome for d in result["dispositions"]] == ["true", "false"]
    assert [d.matched_expected for d in result["dispositions"]] == [True, True]
    assert [d.kind.value for d in result["diagnostics"]] == ["match", "match"]
    assert len(result["map_records"]) == 2
    assert {r.kind.value for r in result["reports"]} == {
        "coverage",
        "source_text_coverage",
        "sensitivity",
        "variance",
    }
    assert result["branch_id"] in result["trajectory"].branches
    assert validate_persisted_trajectory(tmp_path, result["trajectory"]).ok
