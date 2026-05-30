from __future__ import annotations

from rulekit.orchestrator import Intervention, InterventionKind


def test_intervention_records_reviewer_action():
    intervention = Intervention(
        intervention_id="int_1",
        kind=InterventionKind.REVIEWER_EDIT_INTERMEDIATE,
        branch_id="br_main",
        step_id="decompose",
        reviewer_id="reviewer_1",
        payload={"node_id": "n3", "change": "model as exception"},
        reason="Policy unless-clause is ambiguous.",
    )

    assert intervention.kind == InterventionKind.REVIEWER_EDIT_INTERMEDIATE
    assert intervention.payload["node_id"] == "n3"

