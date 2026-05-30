from __future__ import annotations

import pytest

from rulekit.contract import validate_program
from rulekit.orchestrator import (
    ProgramEditKind,
    ProgramEditOperation,
    Trajectory,
    TrajectoryBranch,
    TrajectoryEvent,
    TrajectoryEventKind,
    apply_program_edits,
    exercise_program_on_case,
    load_program_edit,
    save_program_edit,
    validate_persisted_trajectory,
)

from tests.orchestrator.test_exercise import _case, _program


def test_apply_program_edits_adds_atom_and_revises_determination_root():
    result = apply_program_edits(
        _program(),
        [
            ProgramEditOperation(
                kind=ProgramEditKind.ADD_BOOLEAN_ATOM,
                payload={
                    "atom_id": "fcba.timely_notice",
                    "statement": "The consumer gave timely notice.",
                    "source_span": "1026.13(b)",
                },
                reason="Reviewer required a timing element.",
            ),
            ProgramEditOperation(
                kind=ProgramEditKind.ADD_ATOM_REF_NODE,
                payload={
                    "node_id": "n_notice",
                    "atom_id": "fcba.timely_notice",
                },
            ),
            ProgramEditOperation(
                kind=ProgramEditKind.ADD_BOOLEAN_OPERATOR_NODE,
                payload={
                    "node_id": "n_revised_root",
                    "operator": "and",
                    "children": ["n_root", "n_notice"],
                    "surface_label": "Billing error and timely notice",
                },
            ),
            ProgramEditOperation(
                kind=ProgramEditKind.SET_DETERMINATION_ROOT,
                payload={
                    "determination_id": "fcba.billing_error",
                    "root_node": "n_revised_root",
                },
            ),
        ],
    )

    assert result.before_hash != result.after_hash
    assert validate_program(result.program).ok
    records = exercise_program_on_case(
        result.program,
        _case("case_notice", "false"),
        {
            "fcba.credit_extended": True,
            "fcba.unauthorized": True,
            "fcba.timely_notice": False,
        },
        program_id="prog_fcba",
    )
    assert records[0].outcome == "false"


def test_apply_program_edits_supports_engine_not_operator():
    result = apply_program_edits(
        _program(),
        [
            ProgramEditOperation(
                kind=ProgramEditKind.ADD_BOOLEAN_OPERATOR_NODE,
                payload={
                    "node_id": "n_not_unauth",
                    "operator": "not",
                    "children": ["n_root"],
                },
            ),
            ProgramEditOperation(
                kind=ProgramEditKind.SET_DETERMINATION_ROOT,
                payload={
                    "determination_id": "fcba.billing_error",
                    "root_node": "n_not_unauth",
                },
            ),
        ],
    )

    records = exercise_program_on_case(
        result.program,
        _case("case_not", "true"),
        {"fcba.credit_extended": True, "fcba.unauthorized": False},
        program_id="prog_fcba",
    )

    assert records[0].outcome == "true"


def test_apply_program_edits_rejects_non_engine_operator():
    with pytest.raises(ValueError):
        apply_program_edits(
            _program(),
            [
                ProgramEditOperation(
                    kind=ProgramEditKind.ADD_BOOLEAN_OPERATOR_NODE,
                    payload={
                        "node_id": "n_xor",
                        "operator": "xor",
                        "children": ["n_credit", "n_unauth"],
                    },
                )
            ],
        )


def test_apply_program_edits_rejects_invalid_not_arity():
    with pytest.raises(ValueError, match="not requires exactly one child"):
        apply_program_edits(
            _program(),
            [
                ProgramEditOperation(
                    kind=ProgramEditKind.ADD_BOOLEAN_OPERATOR_NODE,
                    payload={
                        "node_id": "n_bad_not",
                        "operator": "not",
                        "children": ["n_credit", "n_unauth"],
                    },
                )
            ],
        )


def test_program_edit_result_roundtrips_and_validates_event(tmp_path):
    edit = apply_program_edits(
        _program(),
        [
            ProgramEditOperation(
                kind=ProgramEditKind.UPDATE_BOOLEAN_ATOM,
                payload={
                    "atom_id": "fcba.unauthorized",
                    "notes": "Reviewer clarified this atom.",
                },
            )
        ],
    )
    save_program_edit(tmp_path, "ws_1", "traj_1", edit)
    loaded = load_program_edit(tmp_path, "ws_1", "traj_1", edit.edit_id)
    trajectory = Trajectory(
        trajectory_id="traj_1",
        workspace_id="ws_1",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )
    trajectory.append_event(
        TrajectoryEvent(
            event_id="evt_edit",
            branch_id="br_main",
            kind=TrajectoryEventKind.PROGRAM_EDIT_APPLIED,
            payload={
                "edit_id": edit.edit_id,
                "before_hash": edit.before_hash,
                "after_hash": edit.after_hash,
            },
        )
    )

    assert loaded == edit
    assert validate_persisted_trajectory(tmp_path, trajectory).ok
