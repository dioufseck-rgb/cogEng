"""FCBA-specific orchestrator example.

The Orchestrator itself is domain-neutral. This file is one concrete
policy fixture used to exercise the generic construction substrate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from rulekit.contract import (
    AndNodeSpec,
    AtomRef,
    BooleanAtom,
    CaseInputSchema,
    DeterminationProgram,
    DeterminationSpec,
    EvaluationMode,
    MapSpec,
    OrNodeSpec,
    ProgramMetadata,
    Provenance,
)
from rulekit.orchestrator.cases import CaseExample, CaseSuite, ExpectedOutcome
from rulekit.orchestrator.dialogue import (
    AgentTurn,
    ReviewerTurn,
    ReviewerTurnKind,
    append_agent_turn,
    append_reviewer_turn,
    open_dialogue,
)
from rulekit.orchestrator.diagnostics import diagnose_dispositions
from rulekit.orchestrator.graph import BuildGraph, BuildGraphNode
from rulekit.orchestrator.ids import event_id as new_event_id
from rulekit.orchestrator.ids import intervention_id as new_intervention_id
from rulekit.orchestrator.intervention import Intervention, InterventionKind
from rulekit.orchestrator.persistence import (
    load_trajectory,
    load_workspace,
    save_dialogue,
    save_disposition,
    save_case_diagnostic,
    save_map_record,
    save_program_edit,
    save_program_snapshot,
    save_report,
    save_step_run,
    save_trajectory,
    save_workspace,
)
from rulekit.orchestrator.program_edit import (
    ProgramEditKind,
    ProgramEditOperation,
    apply_program_edits,
)
from rulekit.orchestrator.exercise import exercise_program_on_suite_with_map
from rulekit.orchestrator.reports import (
    generate_coverage_report,
    generate_sensitivity_report,
    generate_source_text_coverage_report,
    generate_variance_report,
)
from rulekit.orchestrator.snapshot import ProgramSnapshot
from rulekit.orchestrator.step import (
    BuildStepSpec,
    DialogueCapability,
    ExecutionContext,
    StepContext,
    StepKind,
)
from rulekit.orchestrator.steps.stub import (
    DeterministicStubStep,
    StochasticStubStep,
    run_stochastic_step,
)
from rulekit.orchestrator.trajectory import (
    Trajectory,
    TrajectoryBranch,
    TrajectoryEvent,
    TrajectoryEventKind,
)
from rulekit.orchestrator.workspace import PolicySource, PolicySourceKind, Workspace


def build_fcba_stub_graph() -> BuildGraph:
    load = BuildStepSpec(step_id="load_policy", name="Load policy")
    decompose = BuildStepSpec(
        step_id="decompose_policy",
        name="Decompose policy",
        kind=StepKind.STOCHASTIC,
        default_k=2,
        dialogue_capability=DialogueCapability.OPTIONAL,
        max_dialogue_turns=4,
    )
    validate = BuildStepSpec(step_id="validate_candidate", name="Validate candidate")
    return BuildGraph(
        graph_id="graph_fcba_stub",
        name="FCBA stub build graph",
        nodes={
            "load_policy": BuildGraphNode(step_id="load_policy"),
            "decompose_policy": BuildGraphNode(
                step_id="decompose_policy",
                depends_on=["load_policy"],
            ),
            "validate_candidate": BuildGraphNode(
                step_id="validate_candidate",
                depends_on=["decompose_policy"],
            ),
        },
        step_specs={
            "load_policy": load,
            "decompose_policy": decompose,
            "validate_candidate": validate,
        },
    )


def build_fcba_workspace() -> Workspace:
    policy = PolicySource(
        policy_id="pol_fcba_stub",
        title="FCBA Section 1026.13 stub",
        kind=PolicySourceKind.TEXT,
        version_label="stub",
        content=(
            "A billing error includes an unauthorized extension of credit, "
            "a charge for goods not accepted or delivered, and related "
            "enumerated disputes. The creditor acknowledges receipt within "
            "thirty days unless procedures are completed within that period."
        ),
    )
    cases = CaseSuite(
        suite_id="suite_fcba_stub",
        name="FCBA stub cases",
        cases={
            "case_unauthorized": CaseExample(
                case_id="case_unauthorized",
                title="Unauthorized charge",
                narrative="The consumer says they did not authorize the charge.",
                expected_outcomes=[
                    ExpectedOutcome(
                        determination_id="fcba.billing_error",
                        expected_value="true",
                        rationale="Unauthorized credit is a billing error.",
                    )
                ],
            ),
            "case_valid_charge": CaseExample(
                case_id="case_valid_charge",
                title="Recognized valid charge",
                narrative="The consumer recognizes the merchant and received the goods.",
                expected_outcomes=[
                    ExpectedOutcome(
                        determination_id="fcba.billing_error",
                        expected_value="false",
                        rationale="No billing-error category is implicated.",
                    )
                ],
            ),
        },
    )
    trajectory = Trajectory(
        trajectory_id="traj_fcba_stub",
        workspace_id="ws_fcba_stub",
        branches={"br_main": TrajectoryBranch(branch_id="br_main")},
        active_branch_id="br_main",
    )
    return Workspace(
        workspace_id="ws_fcba_stub",
        name="FCBA Orchestrator Stub",
        policies={policy.policy_id: policy},
        case_suites={cases.suite_id: cases},
        trajectories={trajectory.trajectory_id: trajectory},
    )


def build_fcba_candidate_program() -> DeterminationProgram:
    atoms = {
        "fcba.credit_extended": BooleanAtom(
            id="fcba.credit_extended",
            statement="The disputed transaction was an extension of credit.",
            source_span="1026.13(a)",
            evaluation_mode=EvaluationMode.CHARACTERIZED,
        ),
        "fcba.unauthorized": BooleanAtom(
            id="fcba.unauthorized",
            statement="The extension of credit was unauthorized.",
            source_span="1026.13(a)(1)",
            evaluation_mode=EvaluationMode.CHARACTERIZED,
        ),
        "fcba.goods_not_received": BooleanAtom(
            id="fcba.goods_not_received",
            statement="Goods or services were not accepted or delivered as agreed.",
            source_span="1026.13(a)(3)",
            evaluation_mode=EvaluationMode.CHARACTERIZED,
        ),
    }
    nodes = {
        "n_credit": AtomRef(
            node_id="n_credit",
            provenance=Provenance.TRANSCRIBED,
            source_span="1026.13(a)",
            atom_id="fcba.credit_extended",
        ),
        "n_unauth": AtomRef(
            node_id="n_unauth",
            provenance=Provenance.TRANSCRIBED,
            source_span="1026.13(a)(1)",
            atom_id="fcba.unauthorized",
        ),
        "n_goods": AtomRef(
            node_id="n_goods",
            provenance=Provenance.TRANSCRIBED,
            source_span="1026.13(a)(3)",
            atom_id="fcba.goods_not_received",
        ),
        "n_unauthorized_path": AndNodeSpec(
            node_id="n_unauthorized_path",
            provenance=Provenance.STRUCTURAL,
            children=["n_credit", "n_unauth"],
            surface_label="Unauthorized billing error pathway",
        ),
        "n_goods_path": AndNodeSpec(
            node_id="n_goods_path",
            provenance=Provenance.STRUCTURAL,
            children=["n_credit", "n_goods"],
            surface_label="Goods not received billing error pathway",
        ),
        "n_any_category": OrNodeSpec(
            node_id="n_any_category",
            provenance=Provenance.STRUCTURAL,
            children=["n_unauthorized_path", "n_goods_path"],
            surface_label="Any modeled billing error category",
        ),
    }
    return DeterminationProgram(
        metadata=ProgramMetadata(
            name="FCBA stub candidate",
            version="0.1",
            description="Minimal candidate used by orchestrator stub.",
        ),
        nodes=nodes,
        map_spec=MapSpec(atoms=atoms),
        determinations={
            "fcba.billing_error": DeterminationSpec(
                id="fcba.billing_error",
                description="The dispute is a billing error.",
                source_span="1026.13(a)",
                root_node="n_any_category",
            )
        },
        case_input_schema=CaseInputSchema(has_narrative=True),
    )


def run_fcba_stub(root: str | Path) -> dict[str, Any]:
    """Create, exercise, persist, reload, and return FCBA stub artifacts."""
    graph = build_fcba_stub_graph()
    workspace = build_fcba_workspace()
    trajectory = workspace.trajectories["traj_fcba_stub"]
    context = StepContext(
        workspace_id=workspace.workspace_id,
        trajectory_id=trajectory.trajectory_id,
        branch_id=trajectory.active_branch_id,
        execution_context=ExecutionContext(
            code_version="fcba_stub_v0.1",
            started_by="orchestrator_stub",
        ),
    )

    load_step = DeterministicStubStep(
        step_id="load_policy",
        output_payload={"policy_id": "pol_fcba_stub", "loaded": True},
    )
    load_run = load_step.run({"policy_id": "pol_fcba_stub"}, context)
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=trajectory.active_branch_id,
            kind=TrajectoryEventKind.STEP_RUN,
            payload={"run_id": load_run.run_id, "step_id": load_run.step_id},
        )
    )

    decompose_step = StochasticStubStep(step_id="decompose_policy", default_k=2)
    decompose_runs, multi = run_stochastic_step(
        decompose_step,
        {"policy_id": "pol_fcba_stub", "determination": "fcba.billing_error"},
        context,
        k=2,
    )
    for run in decompose_runs:
        trajectory.append_event(
            TrajectoryEvent(
                event_id=new_event_id(),
                branch_id=trajectory.active_branch_id,
                kind=TrajectoryEventKind.STEP_RUN,
                payload={"run_id": run.run_id, "step_id": run.step_id},
            )
        )

    validate_step = DeterministicStubStep(
        step_id="validate_candidate",
        output_payload={"valid": True, "candidate_run_id": multi.selected_run_id},
    )
    validate_run = validate_step.run({"selected_run_id": multi.selected_run_id}, context)
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=trajectory.active_branch_id,
            kind=TrajectoryEventKind.VALIDATION_RESULT,
            payload={"run_id": validate_run.run_id, "valid": True},
        )
    )

    candidate_program = build_fcba_candidate_program()
    edit_result = apply_program_edits(
        candidate_program,
        [
            ProgramEditOperation(
                kind=ProgramEditKind.UPDATE_BOOLEAN_ATOM,
                payload={
                    "atom_id": "fcba.unauthorized",
                    "notes": "Reviewer confirmed unauthorized-use atom wording.",
                },
                reason="Record reviewer clarification without changing logic.",
            )
        ],
    )
    candidate_program = edit_result.program
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=trajectory.active_branch_id,
            kind=TrajectoryEventKind.PROGRAM_EDIT_APPLIED,
            payload={
                "edit_id": edit_result.edit_id,
                "before_hash": edit_result.before_hash,
                "after_hash": edit_result.after_hash,
            },
        )
    )
    snapshot = ProgramSnapshot(
        snapshot_id="snap_fcba_candidate",
        program_id="prog_fcba_stub",
        program_version="0.1",
        program=candidate_program,
        created_by_event_id=trajectory.branches[trajectory.active_branch_id].head_event_id,
        validation_summary="candidate validated in stub path",
    )
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=trajectory.active_branch_id,
            kind=TrajectoryEventKind.PROGRAM_SNAPSHOT,
            payload={
                "snapshot_id": snapshot.snapshot_id,
                "program_id": snapshot.program_id,
                "program_version": snapshot.program_version,
            },
        )
    )

    suite = workspace.case_suites["suite_fcba_stub"]
    map_records, dispositions = exercise_program_on_suite_with_map(
        candidate_program,
        list(suite.cases.values()),
        {
            "case_unauthorized": {
                "fcba.credit_extended": True,
                "fcba.unauthorized": True,
                "fcba.goods_not_received": False,
            },
            "case_valid_charge": {
                "fcba.credit_extended": True,
                "fcba.unauthorized": False,
                "fcba.goods_not_received": False,
            },
        },
        program_id=snapshot.program_id,
        program_version=snapshot.program_version,
    )
    for map_record in map_records:
        trajectory.append_event(
            TrajectoryEvent(
                event_id=new_event_id(),
                branch_id=trajectory.active_branch_id,
                kind=TrajectoryEventKind.MAP_RECORDED,
                payload={
                    "map_record_id": map_record.map_record_id,
                    "case_id": map_record.case_id,
                    "substrate_id": map_record.substrate_id,
                },
            )
        )
    for disposition in dispositions:
        trajectory.append_event(
            TrajectoryEvent(
                event_id=new_event_id(),
                branch_id=trajectory.active_branch_id,
                kind=TrajectoryEventKind.DISPOSITION_RECORDED,
                payload={
                    "disposition_id": disposition.disposition_id,
                    "case_id": disposition.case_id,
                    "determination_id": disposition.determination_id,
                    "matched_expected": disposition.matched_expected,
                },
            )
        )
    diagnostics = diagnose_dispositions(dispositions, map_records)
    for diagnostic in diagnostics:
        trajectory.append_event(
            TrajectoryEvent(
                event_id=new_event_id(),
                branch_id=trajectory.active_branch_id,
                kind=TrajectoryEventKind.DIAGNOSTIC_RECORDED,
                payload={
                    "diagnostic_id": diagnostic.diagnostic_id,
                    "case_id": diagnostic.case_id,
                    "determination_id": diagnostic.determination_id,
                    "kind": diagnostic.kind.value,
                },
            )
        )

    coverage_report = generate_coverage_report(
        dispositions,
        workspace_id=workspace.workspace_id,
        trajectory_id=trajectory.trajectory_id,
        case_suite_id=suite.suite_id,
    )
    source_report = generate_source_text_coverage_report(
        candidate_program,
        workspace.policies["pol_fcba_stub"],
        workspace_id=workspace.workspace_id,
        trajectory_id=trajectory.trajectory_id,
    )
    sensitivity_report = generate_sensitivity_report(
        dispositions,
        workspace_id=workspace.workspace_id,
        trajectory_id=trajectory.trajectory_id,
        case_suite_id=suite.suite_id,
    )
    variance_report = generate_variance_report(
        decompose_runs,
        workspace_id=workspace.workspace_id,
        trajectory_id=trajectory.trajectory_id,
    )
    reports = [coverage_report, source_report, sensitivity_report, variance_report]
    for report in reports:
        trajectory.append_event(
            TrajectoryEvent(
                event_id=new_event_id(),
                branch_id=trajectory.active_branch_id,
                kind=TrajectoryEventKind.REPORT_GENERATED,
                payload={"report_id": report.report_id, "kind": report.kind.value},
            )
        )

    dialogue = open_dialogue(
        graph.step_specs["decompose_policy"],
        trajectory,
        metadata={"clause": "acknowledge within thirty days unless completed"},
    )
    append_agent_turn(
        dialogue,
        trajectory,
        AgentTurn(
            turn_id="turn_agent_1",
            dialogue_id=dialogue.dialogue_id,
            step_id="decompose_policy",
            turn_index=0,
            message="The unless clause may be modeled as an exception or substitute.",
            reasoning_summary="Audit-facing ambiguity summary only.",
            uncertainty=["exception versus conditional substitute"],
            open_questions_for_reviewer=[
                "Should completion within thirty days waive acknowledgement?"
            ],
        ),
    )
    append_reviewer_turn(
        dialogue,
        trajectory,
        ReviewerTurn(
            turn_id="turn_reviewer_1",
            dialogue_id=dialogue.dialogue_id,
            step_id="decompose_policy",
            turn_index=1,
            kind=ReviewerTurnKind.NATURAL_LANGUAGE,
            message="Model it as an exception to the acknowledgement duty.",
            reviewer_id="reviewer_stub",
        ),
    )

    edit = Intervention(
        intervention_id=new_intervention_id(),
        kind=InterventionKind.REVIEWER_EDIT_INTERMEDIATE,
        branch_id=trajectory.active_branch_id,
        step_id="decompose_policy",
        reviewer_id="reviewer_stub",
        payload={"modeling_choice": "exception"},
        reason="Reviewer resolved unless-clause ambiguity.",
    )
    branch_id = trajectory.create_branch_from_intervention(edit)

    save_workspace(workspace, root)
    save_trajectory(trajectory, root)
    save_program_edit(root, workspace.workspace_id, trajectory.trajectory_id, edit_result)
    save_program_snapshot(root, workspace.workspace_id, trajectory.trajectory_id, snapshot)
    for run in [load_run, *decompose_runs, validate_run]:
        save_step_run(root, workspace.workspace_id, trajectory.trajectory_id, run)
    save_dialogue(root, workspace.workspace_id, trajectory.trajectory_id, dialogue)
    for map_record in map_records:
        save_map_record(root, workspace.workspace_id, trajectory.trajectory_id, map_record)
    for disposition in dispositions:
        save_disposition(root, workspace.workspace_id, trajectory.trajectory_id, disposition)
    for diagnostic in diagnostics:
        save_case_diagnostic(
            root,
            workspace.workspace_id,
            trajectory.trajectory_id,
            diagnostic,
        )
    for report in reports:
        save_report(root, workspace.workspace_id, trajectory.trajectory_id, report)

    loaded_workspace = load_workspace(root, workspace.workspace_id)
    loaded_trajectory = load_trajectory(
        root,
        workspace.workspace_id,
        trajectory.trajectory_id,
    )
    return {
        "workspace": workspace,
        "trajectory": trajectory,
        "graph": graph,
        "dialogue": dialogue,
        "snapshot": snapshot,
        "edit_result": edit_result,
        "map_records": map_records,
        "dispositions": dispositions,
        "diagnostics": diagnostics,
        "reports": reports,
        "branch_id": branch_id,
        "multi_run": multi,
        "loaded_workspace": loaded_workspace,
        "loaded_trajectory": loaded_trajectory,
    }


__all__ = [
    "build_fcba_stub_graph",
    "build_fcba_workspace",
    "build_fcba_candidate_program",
    "run_fcba_stub",
]
