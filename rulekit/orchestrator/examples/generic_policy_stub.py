"""Domain-neutral orchestrator example for any policy.

This example is intentionally not legal, medical, sports, or finance
specific. It demonstrates that new domains should use generic
declarations and factories, not bespoke per-domain stubs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from rulekit.contract import DeterminationProgram
from rulekit.orchestrator.dialogue import (
    AgentTurn,
    ReviewerTurn,
    ReviewerTurnKind,
    append_agent_turn,
    append_reviewer_turn,
    open_dialogue,
)
from rulekit.orchestrator.diagnostics import diagnose_dispositions
from rulekit.orchestrator.exercise import exercise_program_on_suite_with_map
from rulekit.orchestrator.factory import (
    AtomDeclaration,
    CaseDeclaration,
    DeterminationDeclaration,
    PolicyWorkspaceSeed,
    create_boolean_candidate_program,
    create_policy_workspace,
)
from rulekit.orchestrator.graph import BuildGraph
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
from rulekit.orchestrator.reports import (
    generate_coverage_report,
    generate_sensitivity_report,
    generate_source_text_coverage_report,
    generate_variance_report,
)
from rulekit.orchestrator.snapshot import ProgramSnapshot
from rulekit.orchestrator.step import ExecutionContext, StepContext
from rulekit.orchestrator.steps.stub import (
    DeterministicStubStep,
    StochasticStubStep,
    run_stochastic_step,
)
from rulekit.orchestrator.trajectory import TrajectoryEvent, TrajectoryEventKind
from rulekit.orchestrator.workspace import Workspace


def build_generic_stub_graph() -> BuildGraph:
    return create_policy_workspace(_generic_seed()).graph


def build_generic_workspace() -> Workspace:
    return create_policy_workspace(_generic_seed()).workspace


def build_generic_candidate_program() -> DeterminationProgram:
    seed = _generic_seed()
    return create_boolean_candidate_program(
        program_id="prog_generic_stub",
        program_name="Generic eligibility candidate",
        version="0.1",
        determinations=seed.determinations,
        atoms=seed.atoms,
    )


def run_generic_stub(root: str | Path) -> dict[str, Any]:
    bundle = create_policy_workspace(_generic_seed())
    graph = bundle.graph
    workspace = bundle.workspace
    trajectory = bundle.trajectory
    policy = next(iter(workspace.policies.values()))
    suite = next(iter(workspace.case_suites.values()))
    context = StepContext(
        workspace_id=workspace.workspace_id,
        trajectory_id=trajectory.trajectory_id,
        branch_id=trajectory.active_branch_id,
        execution_context=ExecutionContext(
            code_version="generic_stub_v0.1",
            started_by="orchestrator_stub",
        ),
    )

    load_run = DeterministicStubStep(
        step_id="load_policy",
        output_payload={"policy_id": policy.policy_id, "loaded": True},
    ).run({"policy_id": policy.policy_id}, context)
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=trajectory.active_branch_id,
            kind=TrajectoryEventKind.STEP_RUN,
            payload={"run_id": load_run.run_id, "step_id": load_run.step_id},
        )
    )

    decompose_runs, multi = run_stochastic_step(
        StochasticStubStep(step_id="decompose_policy", default_k=2),
        {"policy_id": policy.policy_id, "determination": "generic.eligible"},
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

    validate_run = DeterministicStubStep(
        step_id="validate_candidate",
        output_payload={"valid": True, "candidate_run_id": multi.selected_run_id},
    ).run({"selected_run_id": multi.selected_run_id}, context)
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=trajectory.active_branch_id,
            kind=TrajectoryEventKind.VALIDATION_RESULT,
            payload={"run_id": validate_run.run_id, "valid": True},
        )
    )

    program = build_generic_candidate_program()
    edit_result = apply_program_edits(
        program,
        [
            ProgramEditOperation(
                kind=ProgramEditKind.UPDATE_BOOLEAN_ATOM,
                payload={
                    "atom_id": "generic.documentation_complete",
                    "notes": "Reviewer confirmed this is a required input atom.",
                },
                reason="Record reviewer clarification without changing logic.",
            )
        ],
    )
    program = edit_result.program
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
        snapshot_id="snap_generic_candidate",
        program_id="prog_generic_stub",
        program_version="0.1",
        program=program,
        validation_summary="candidate validated in generic stub path",
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

    map_records, dispositions = exercise_program_on_suite_with_map(
        program,
        list(suite.cases.values()),
        {
            "case_complete": {
                "generic.baseline_satisfied": True,
                "generic.documentation_complete": True,
            },
            "case_incomplete": {
                "generic.baseline_satisfied": True,
                "generic.documentation_complete": False,
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
        program,
        policy,
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
        metadata={"clause": "clarification may resolve incomplete documentation"},
    )
    append_agent_turn(
        dialogue,
        trajectory,
        AgentTurn(
            turn_id="turn_agent_1",
            dialogue_id=dialogue.dialogue_id,
            step_id="decompose_policy",
            turn_index=0,
            message="The clarification clause could be a cure process or a separate pathway.",
            uncertainty=["cure process versus alternate eligibility pathway"],
            open_questions_for_reviewer=[
                "Should clarification repair documentation incompleteness?"
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
            message="Treat clarification as a cure process, not direct eligibility.",
            reviewer_id="reviewer_stub",
        ),
    )

    intervention = Intervention(
        intervention_id=new_intervention_id(),
        kind=InterventionKind.REVIEWER_EDIT_INTERMEDIATE,
        branch_id=trajectory.active_branch_id,
        step_id="decompose_policy",
        reviewer_id="reviewer_stub",
        payload={"modeling_choice": "clarification_as_cure_process"},
        reason="Reviewer resolved generic ambiguity.",
    )
    branch_id = trajectory.create_branch_from_intervention(intervention)

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
    loaded_trajectory = load_trajectory(root, workspace.workspace_id, trajectory.trajectory_id)
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


def _generic_seed() -> PolicyWorkspaceSeed:
    return PolicyWorkspaceSeed(
        workspace_name="Generic Policy Orchestrator Stub",
        policy_title="Generic eligibility policy",
        policy_text=(
            "A request is eligible when the applicant satisfies the baseline "
            "requirement and supplies the required documentation. If the "
            "documentation is incomplete, reviewer clarification may resolve "
            "the defect before final adjudication."
        ),
        policy_id="pol_generic_stub",
        version_label="stub",
        determinations=[
            DeterminationDeclaration(
                determination_id="generic.eligible",
                description="The request is eligible.",
                operator="and",
                atom_ids=[
                    "generic.baseline_satisfied",
                    "generic.documentation_complete",
                ],
                source_span="eligible when baseline and documentation hold",
            )
        ],
        atoms=[
            AtomDeclaration(
                atom_id="generic.baseline_satisfied",
                statement="The applicant satisfies the baseline requirement.",
                source_span="baseline requirement",
            ),
            AtomDeclaration(
                atom_id="generic.documentation_complete",
                statement="The applicant supplied required documentation.",
                source_span="required documentation",
            ),
        ],
        cases=[
            CaseDeclaration(
                case_id="case_complete",
                title="Complete eligible request",
                narrative="The applicant satisfies the baseline requirement and submitted documents.",
                expected_outcomes={"generic.eligible": "true"},
            ),
            CaseDeclaration(
                case_id="case_incomplete",
                title="Missing documentation",
                narrative="The applicant satisfies the baseline requirement but lacks documents.",
                expected_outcomes={"generic.eligible": "false"},
            ),
        ],
    )


__all__ = [
    "build_generic_stub_graph",
    "build_generic_workspace",
    "build_generic_candidate_program",
    "run_generic_stub",
]
