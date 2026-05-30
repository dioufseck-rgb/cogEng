"""Reusable orchestration workflows over generic policy seeds."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import to_jsonable_python

from rulekit.contract import DeterminationProgram
from rulekit.orchestrator.config import load_policy_workspace_seed
from rulekit.orchestrator.diagnostics import CaseDiagnostic, diagnose_dispositions
from rulekit.orchestrator.disposition import DispositionRecord
from rulekit.orchestrator.exercise import exercise_program_on_suite_with_map_step
from rulekit.orchestrator.factory import PolicyWorkspaceSeed, create_candidate_program, create_policy_workspace
from rulekit.orchestrator.hints import (
    ReviewerHint,
    record_reviewer_hint,
    reviewer_hints_from_trajectory,
)
from rulekit.orchestrator.ids import event_id as new_event_id
from rulekit.orchestrator.ids import intervention_id as new_intervention_id
from rulekit.orchestrator.intervention import Intervention, InterventionKind
from rulekit.orchestrator.map_record import MapExtractionRecord
from rulekit.orchestrator.map_step import PreboundFactsMapStep
from rulekit.orchestrator.persistence import (
    load_program_snapshot,
    load_trajectory,
    load_workspace,
    save_case_diagnostic,
    save_disposition,
    save_map_record,
    save_program_edit,
    save_program_snapshot,
    save_report,
    save_step_run,
    save_trajectory,
    save_workspace,
    trajectory_dir,
    workspace_dir,
)
from rulekit.orchestrator.program_edit import ProgramEditOperation, ProgramEditResult, apply_program_edits
from rulekit.orchestrator.projections import build_trajectory_projection
from rulekit.orchestrator.reports import (
    GovernanceReport,
    generate_coverage_report,
    generate_regression_report,
    generate_sensitivity_report,
    generate_source_text_coverage_report,
    generate_variance_report,
)
from rulekit.orchestrator.snapshot import ProgramSnapshot
from rulekit.orchestrator.step import ExecutionContext, StepContext, StepRunResult
from rulekit.orchestrator.steps.stub import DeterministicStubStep, StochasticStubStep, run_stochastic_step
from rulekit.orchestrator.trajectory import BranchStatus, Trajectory, TrajectoryEvent, TrajectoryEventKind
from rulekit.orchestrator.validation import OrchestratorValidationReport, validate_persisted_trajectory
from rulekit.orchestrator.workspace import Workspace


class PolicyRunResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    workspace: Workspace
    trajectory: Trajectory
    program: DeterminationProgram
    snapshot: ProgramSnapshot
    step_runs: list[StepRunResult] = Field(default_factory=list)
    map_records: list[MapExtractionRecord] = Field(default_factory=list)
    dispositions: list[DispositionRecord] = Field(default_factory=list)
    diagnostics: list[CaseDiagnostic] = Field(default_factory=list)
    reports: list[GovernanceReport] = Field(default_factory=list)
    validation: OrchestratorValidationReport
    root: str

    def summary(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace.workspace_id,
            "trajectory_id": self.trajectory.trajectory_id,
            "program_id": self.snapshot.program_id,
            "snapshot_id": self.snapshot.snapshot_id,
            "event_count": len(self.trajectory.events),
            "case_count": sum(len(suite.cases) for suite in self.workspace.case_suites.values()),
            "disposition_count": len(self.dispositions),
            "matched_disposition_count": sum(
                1 for disposition in self.dispositions if disposition.matched_expected is True
            ),
            "mismatch_count": sum(
                1 for disposition in self.dispositions if disposition.matched_expected is False
            ),
            "report_kinds": [report.kind.value for report in self.reports],
            "validation_ok": self.validation.ok,
            "validation_summary": self.validation.summary(),
            "root": self.root,
        }


class PersistedProgramEditResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    workspace_id: str
    trajectory_id: str
    branch_id: str
    source_snapshot_id: str
    new_snapshot: ProgramSnapshot
    edit_result: ProgramEditResult
    validation: OrchestratorValidationReport
    root: str

    def summary(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "trajectory_id": self.trajectory_id,
            "branch_id": self.branch_id,
            "source_snapshot_id": self.source_snapshot_id,
            "new_snapshot_id": self.new_snapshot.snapshot_id,
            "edit_id": self.edit_result.edit_id,
            "before_hash": self.edit_result.before_hash,
            "after_hash": self.edit_result.after_hash,
            "operation_count": len(self.edit_result.operations),
            "validation_ok": self.validation.ok,
            "validation_summary": self.validation.summary(),
            "root": self.root,
        }


class ReexerciseResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    workspace_id: str
    trajectory_id: str
    snapshot_id: str
    map_records: list[MapExtractionRecord] = Field(default_factory=list)
    dispositions: list[DispositionRecord] = Field(default_factory=list)
    diagnostics: list[CaseDiagnostic] = Field(default_factory=list)
    reports: list[GovernanceReport] = Field(default_factory=list)
    validation: OrchestratorValidationReport
    root: str

    def summary(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "trajectory_id": self.trajectory_id,
            "snapshot_id": self.snapshot_id,
            "map_record_count": len(self.map_records),
            "disposition_count": len(self.dispositions),
            "matched_disposition_count": sum(
                1 for disposition in self.dispositions if disposition.matched_expected is True
            ),
            "mismatch_count": sum(
                1 for disposition in self.dispositions if disposition.matched_expected is False
            ),
            "diagnostic_count": len(self.diagnostics),
            "report_kinds": [report.kind.value for report in self.reports],
            "validation_ok": self.validation.ok,
            "validation_summary": self.validation.summary(),
            "root": self.root,
        }


class PersistedReviewerHintResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    workspace_id: str
    trajectory_id: str
    branch_id: str
    hint: ReviewerHint
    validation: OrchestratorValidationReport
    root: str

    def summary(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "trajectory_id": self.trajectory_id,
            "branch_id": self.branch_id,
            "hint_id": self.hint.hint_id,
            "case_id": self.hint.case_id,
            "target_step_id": self.hint.target_step_id,
            "atom_ids": self.hint.atom_ids,
            "validation_ok": self.validation.ok,
            "validation_summary": self.validation.summary(),
            "root": self.root,
        }


def run_policy_seed_file(
    seed_path: str | Path,
    root: str | Path,
    *,
    k: int = 2,
    program_id: str | None = None,
    program_version: str = "0.1",
) -> PolicyRunResult:
    return run_policy_seed(
        load_policy_workspace_seed(seed_path),
        root,
        k=k,
        program_id=program_id,
        program_version=program_version,
    )


def run_policy_seed(
    seed: PolicyWorkspaceSeed,
    root: str | Path,
    *,
    k: int = 2,
    program_id: str | None = None,
    program_version: str = "0.1",
) -> PolicyRunResult:
    """Run the v0.1 generic orchestration cycle for a policy seed."""
    if not seed.atoms:
        raise ValueError("policy seed must declare atoms to build a candidate program")
    if not seed.determinations:
        raise ValueError("policy seed must declare determinations")

    root = Path(root)
    bundle = create_policy_workspace(seed)
    workspace = bundle.workspace
    graph = bundle.graph
    trajectory = bundle.trajectory
    policy = next(iter(workspace.policies.values()))
    suite = next(iter(workspace.case_suites.values()))
    program_id = program_id or f"prog_{workspace.workspace_id.removeprefix('ws_')}"

    context = StepContext(
        workspace_id=workspace.workspace_id,
        trajectory_id=trajectory.trajectory_id,
        branch_id=trajectory.active_branch_id,
        execution_context=ExecutionContext(
            code_version="orchestrator.workflow.v0.1",
            started_by="rulekit_orchestrator",
        ),
    )

    load_run = DeterministicStubStep(
        step_id="load_policy",
        output_payload={"policy_id": policy.policy_id, "loaded": True},
    ).run({"policy_id": policy.policy_id}, context)
    _append_step_event(trajectory, load_run)

    first_det = seed.determinations[0].determination_id
    decompose_runs, multi = run_stochastic_step(
        StochasticStubStep(step_id="decompose_policy", default_k=max(1, k)),
        {"policy_id": policy.policy_id, "determination": first_det},
        context,
        k=max(1, k),
    )
    for run in decompose_runs:
        _append_step_event(trajectory, run)

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

    program = create_candidate_program(
        program_id=program_id,
        program_name=f"{seed.policy_title} candidate",
        version=program_version,
        determinations=seed.determinations,
        atoms=seed.atoms,
        nodes=seed.nodes,
        constants=seed.constants,
    )
    snapshot = ProgramSnapshot(
        snapshot_id=f"snap_{program_id}_{program_version.replace('.', '_')}",
        program_id=program_id,
        program_version=program_version,
        program=program,
        validation_summary="candidate generated by generic seed workflow",
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

    cases = list(suite.cases.values())
    map_records, dispositions = exercise_program_on_suite_with_map_step(
        program,
        cases,
        PreboundFactsMapStep(),
        program_id=program_id,
        program_version=program_version,
        workspace_id=workspace.workspace_id,
        trajectory_id=trajectory.trajectory_id,
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

    reports = [
        generate_coverage_report(
            dispositions,
            workspace_id=workspace.workspace_id,
            trajectory_id=trajectory.trajectory_id,
            case_suite_id=suite.suite_id,
        ),
        generate_source_text_coverage_report(
            program,
            policy,
            workspace_id=workspace.workspace_id,
            trajectory_id=trajectory.trajectory_id,
        ),
        generate_sensitivity_report(
            dispositions,
            workspace_id=workspace.workspace_id,
            trajectory_id=trajectory.trajectory_id,
            case_suite_id=suite.suite_id,
        ),
        generate_variance_report(
            decompose_runs,
            workspace_id=workspace.workspace_id,
            trajectory_id=trajectory.trajectory_id,
        ),
    ]
    for report in reports:
        trajectory.append_event(
            TrajectoryEvent(
                event_id=new_event_id(),
                branch_id=trajectory.active_branch_id,
                kind=TrajectoryEventKind.REPORT_GENERATED,
                payload={"report_id": report.report_id, "kind": report.kind.value},
            )
        )

    step_runs = [load_run, *decompose_runs, validate_run]
    save_workspace(workspace, root)
    save_trajectory(trajectory, root)
    save_program_snapshot(root, workspace.workspace_id, trajectory.trajectory_id, snapshot)
    for run in step_runs:
        save_step_run(root, workspace.workspace_id, trajectory.trajectory_id, run)
    for map_record in map_records:
        save_map_record(root, workspace.workspace_id, trajectory.trajectory_id, map_record)
    for disposition in dispositions:
        save_disposition(root, workspace.workspace_id, trajectory.trajectory_id, disposition)
    for diagnostic in diagnostics:
        save_case_diagnostic(root, workspace.workspace_id, trajectory.trajectory_id, diagnostic)
    for report in reports:
        save_report(root, workspace.workspace_id, trajectory.trajectory_id, report)

    validation = validate_persisted_trajectory(root, trajectory)
    return PolicyRunResult(
        workspace=workspace,
        trajectory=trajectory,
        program=program,
        snapshot=snapshot,
        step_runs=step_runs,
        map_records=map_records,
        dispositions=dispositions,
        diagnostics=diagnostics,
        reports=reports,
        validation=validation,
        root=str(root),
    )


def inspect_persisted_run(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
) -> dict[str, Any]:
    root = Path(root)
    workspace = load_workspace(root, workspace_id)
    trajectory = load_trajectory(root, workspace_id, trajectory_id)
    base = trajectory_dir(root, workspace_id, trajectory_id)
    validation = validate_persisted_trajectory(root, trajectory)
    return {
        "workspace_id": workspace.workspace_id,
        "workspace_name": workspace.name,
        "trajectory_id": trajectory.trajectory_id,
        "active_branch_id": trajectory.active_branch_id,
        "branch_count": len(trajectory.branches),
        "event_count": len(trajectory.events),
        "policy_count": len(workspace.policies),
        "case_suite_count": len(workspace.case_suites),
        "sidecars": {
            "step_runs": _count_json(base / "step_runs"),
            "snapshots": _count_json(base / "snapshots"),
            "map_records": _count_json(base / "map_records"),
            "dispositions": _count_json(base / "dispositions"),
            "diagnostics": _count_json(base / "diagnostics"),
            "reports": _count_json(base / "reports"),
            "program_edits": _count_json(base / "program_edits"),
            "dialogues": _count_json(base / "dialogues"),
        },
        "workspace_path": str(workspace_dir(root, workspace_id)),
        "trajectory_path": str(base),
        "validation_ok": validation.ok,
        "validation_summary": validation.summary(),
    }


def list_persisted_runs(root: str | Path) -> list[dict[str, Any]]:
    root = Path(root)
    if not root.exists():
        return []
    runs: list[dict[str, Any]] = []
    for workspace_path in sorted(path for path in root.iterdir() if path.is_dir()):
        workspace_json = workspace_path / "workspace.json"
        trajectories_path = workspace_path / "trajectories"
        if not workspace_json.exists() or not trajectories_path.exists():
            continue
        workspace = load_workspace(root, workspace_path.name)
        for trajectory_path in sorted(path for path in trajectories_path.iterdir() if path.is_dir()):
            manifest_path = trajectory_path / "manifest.json"
            if not manifest_path.exists():
                continue
            inspected = inspect_persisted_run(
                root,
                workspace.workspace_id,
                trajectory_path.name,
            )
            runs.append(
                {
                    "workspace_id": workspace.workspace_id,
                    "workspace_name": workspace.name,
                    "trajectory_id": inspected["trajectory_id"],
                    "event_count": inspected["event_count"],
                    "validation_ok": inspected["validation_ok"],
                    "trajectory_path": inspected["trajectory_path"],
                }
            )
    return runs


def export_review_bundle(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Export persisted review artifacts into a simple JSON bundle."""
    root = Path(root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace = load_workspace(root, workspace_id)
    trajectory = load_trajectory(root, workspace_id, trajectory_id)
    base = trajectory_dir(root, workspace_id, trajectory_id)
    summary = inspect_persisted_run(root, workspace_id, trajectory_id)

    snapshot_payloads = _read_json_files(base / "snapshots")
    program_payload = {}
    try:
        latest_snapshot = load_program_snapshot(
            root,
            workspace_id,
            trajectory_id,
            _latest_snapshot_id(trajectory),
        )
        program_payload = latest_snapshot.program.model_dump(mode="json")
    except ValueError:
        if snapshot_payloads:
            program_payload = snapshot_payloads[-1].get("program", {})

    files = {
        "summary": _write_export_json(output_dir / "summary.json", summary),
        "workspace": _write_export_json(
            output_dir / "workspace.json",
            workspace.model_dump(mode="json"),
        ),
        "trajectory_events": _write_export_json(
            output_dir / "trajectory_events.json",
            [event.model_dump(mode="json") for event in trajectory.events],
        ),
        "program": _write_export_json(output_dir / "program.json", program_payload),
        "snapshots": _write_export_json(output_dir / "snapshots.json", snapshot_payloads),
        "reports": _write_export_json(output_dir / "reports.json", _read_json_files(base / "reports")),
        "diagnostics": _write_export_json(
            output_dir / "diagnostics.json",
            _read_json_files(base / "diagnostics"),
        ),
        "dispositions": _write_export_json(
            output_dir / "dispositions.json",
            _read_json_files(base / "dispositions"),
        ),
        "map_records": _write_export_json(
            output_dir / "map_records.json",
            _read_json_files(base / "map_records"),
        ),
    }
    return {
        "workspace_id": workspace_id,
        "trajectory_id": trajectory_id,
        "output_dir": str(output_dir),
        "files": files,
        "validation_ok": summary["validation_ok"],
        "validation_summary": summary["validation_summary"],
    }


def export_builder_ui(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Export a static Builder UI for one persisted trajectory."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    web_dir = Path(__file__).parent / "web"
    for name in ("index.html", "styles.css", "app.js"):
        shutil.copyfile(web_dir / name, output_dir / name)
    projection = build_trajectory_projection(root, workspace_id, trajectory_id)
    projection_path = output_dir / "projection.json"
    projection_path.write_text(
        json.dumps(to_jsonable_python(projection), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return {
        "workspace_id": workspace_id,
        "trajectory_id": trajectory_id,
        "output_dir": str(output_dir),
        "index": str(output_dir / "index.html"),
        "projection": str(projection_path),
        "validation_ok": projection["trajectory"]["validation_ok"],
        "validation_summary": projection["trajectory"]["validation_summary"],
    }


def apply_persisted_program_edits(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    operations: list[ProgramEditOperation],
    *,
    snapshot_id: str | None = None,
) -> PersistedProgramEditResult:
    """Apply typed edits to a persisted snapshot and create a new snapshot."""
    root = Path(root)
    workspace = load_workspace(root, workspace_id)
    trajectory = load_trajectory(root, workspace_id, trajectory_id)
    source_snapshot_id = snapshot_id or _latest_snapshot_id(trajectory)
    source_snapshot = load_program_snapshot(
        root,
        workspace_id,
        trajectory_id,
        source_snapshot_id,
    )
    source_branch_id = trajectory.active_branch_id
    intervention = Intervention(
        intervention_id=new_intervention_id(),
        kind=InterventionKind.REVIEWER_EDIT_INTERMEDIATE,
        branch_id=source_branch_id,
        payload={
            "source_snapshot_id": source_snapshot_id,
            "operation_count": len(operations),
        },
        reason="Typed persisted program edit applied.",
    )
    branch_id = trajectory.create_branch_from_intervention(intervention)
    edit_result = apply_program_edits(source_snapshot.program, operations)
    save_program_edit(root, workspace_id, trajectory_id, edit_result)
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=branch_id,
            kind=TrajectoryEventKind.PROGRAM_EDIT_APPLIED,
            payload={
                "edit_id": edit_result.edit_id,
                "source_snapshot_id": source_snapshot_id,
                "before_hash": edit_result.before_hash,
                "after_hash": edit_result.after_hash,
            },
        )
    )
    new_snapshot = ProgramSnapshot(
        snapshot_id=f"snap_{edit_result.edit_id}",
        program_id=source_snapshot.program_id,
        program_version=source_snapshot.program_version,
        program=edit_result.program,
        validation_summary=edit_result.validation_summary,
        metadata={
            "source_snapshot_id": source_snapshot_id,
            "edit_id": edit_result.edit_id,
        },
    )
    save_program_snapshot(root, workspace_id, trajectory_id, new_snapshot)
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=branch_id,
            kind=TrajectoryEventKind.PROGRAM_SNAPSHOT,
            payload={
                "snapshot_id": new_snapshot.snapshot_id,
                "program_id": new_snapshot.program_id,
                "program_version": new_snapshot.program_version,
                "source_snapshot_id": source_snapshot_id,
                "edit_id": edit_result.edit_id,
            },
        )
    )
    workspace.trajectories[trajectory.trajectory_id] = trajectory
    save_workspace(workspace, root)
    validation = validate_persisted_trajectory(root, trajectory)
    return PersistedProgramEditResult(
        workspace_id=workspace_id,
        trajectory_id=trajectory_id,
        branch_id=branch_id,
        source_snapshot_id=source_snapshot_id,
        new_snapshot=new_snapshot,
        edit_result=edit_result,
        validation=validation,
        root=str(root),
    )


def list_branches(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
) -> list[dict[str, Any]]:
    trajectory = load_trajectory(root, workspace_id, trajectory_id)
    return [
        {
            "branch_id": branch.branch_id,
            "parent_branch_id": branch.parent_branch_id,
            "created_by_event_id": branch.created_by_event_id,
            "status": branch.status.value,
            "head_event_id": branch.head_event_id,
            "is_active": branch.branch_id == trajectory.active_branch_id,
        }
        for branch in trajectory.branches.values()
    ]


def mark_branch_status(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    branch_id: str,
    status: BranchStatus | str,
    *,
    reviewer_id: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    workspace = load_workspace(root, workspace_id)
    trajectory = load_trajectory(root, workspace_id, trajectory_id)
    status = BranchStatus(status)
    if branch_id not in trajectory.branches:
        raise ValueError(f"branch {branch_id!r} does not exist")
    kind = {
        BranchStatus.SETTLED: InterventionKind.MARK_BRANCH_SETTLED,
        BranchStatus.ABANDONED: InterventionKind.MARK_BRANCH_ABANDONED,
    }.get(status)
    if kind is None:
        raise ValueError("only settled or abandoned branch status can be marked")
    intervention = Intervention(
        intervention_id=new_intervention_id(),
        kind=kind,
        branch_id=branch_id,
        reviewer_id=reviewer_id,
        reason=reason,
        payload={"status": status.value},
    )
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=branch_id,
            kind=TrajectoryEventKind.INTERVENTION,
            payload=intervention.model_dump(mode="json"),
        )
    )
    trajectory.branches[branch_id].status = status
    workspace.trajectories[trajectory.trajectory_id] = trajectory
    save_workspace(workspace, root)
    validation = validate_persisted_trajectory(root, trajectory)
    return {
        "workspace_id": workspace_id,
        "trajectory_id": trajectory_id,
        "branch_id": branch_id,
        "status": status.value,
        "validation_ok": validation.ok,
        "validation_summary": validation.summary(),
    }


def reexercise_latest_snapshot(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    *,
    snapshot_id: str | None = None,
    reviewer_hints: list[ReviewerHint] | None = None,
) -> ReexerciseResult:
    """Exercise a persisted snapshot against the workspace's case suite."""
    root = Path(root)
    workspace = load_workspace(root, workspace_id)
    trajectory = load_trajectory(root, workspace_id, trajectory_id)
    selected_snapshot_id = snapshot_id or _latest_snapshot_id(trajectory)
    snapshot = load_program_snapshot(root, workspace_id, trajectory_id, selected_snapshot_id)
    policy = next(iter(workspace.policies.values()))
    suite = next(iter(workspace.case_suites.values()))
    cases = list(suite.cases.values())
    base = trajectory_dir(root, workspace_id, trajectory_id)
    prior_dispositions = [
        DispositionRecord.model_validate(payload)
        for payload in _read_json_files(base / "dispositions")
    ]
    hints = [
        *reviewer_hints_from_trajectory(trajectory),
        *(reviewer_hints or []),
    ]

    map_records, dispositions = exercise_program_on_suite_with_map_step(
        snapshot.program,
        cases,
        PreboundFactsMapStep(),
        program_id=snapshot.program_id,
        program_version=snapshot.program_version,
        workspace_id=workspace_id,
        trajectory_id=trajectory_id,
        reviewer_hints=hints,
    )
    for map_record in map_records:
        save_map_record(root, workspace_id, trajectory_id, map_record)
        trajectory.append_event(
            TrajectoryEvent(
                event_id=new_event_id(),
                branch_id=trajectory.active_branch_id,
                kind=TrajectoryEventKind.MAP_RECORDED,
                payload={
                    "map_record_id": map_record.map_record_id,
                    "case_id": map_record.case_id,
                    "substrate_id": map_record.substrate_id,
                    "snapshot_id": selected_snapshot_id,
                },
            )
        )
    for disposition in dispositions:
        save_disposition(root, workspace_id, trajectory_id, disposition)
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
                    "snapshot_id": selected_snapshot_id,
                },
            )
        )

    diagnostics = diagnose_dispositions(dispositions, map_records)
    for diagnostic in diagnostics:
        save_case_diagnostic(root, workspace_id, trajectory_id, diagnostic)
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
                    "snapshot_id": selected_snapshot_id,
                },
            )
        )

    reports = [
        generate_coverage_report(
            dispositions,
            workspace_id=workspace_id,
            trajectory_id=trajectory_id,
            case_suite_id=suite.suite_id,
        ),
        generate_source_text_coverage_report(
            snapshot.program,
            policy,
            workspace_id=workspace_id,
            trajectory_id=trajectory_id,
        ),
        generate_sensitivity_report(
            dispositions,
            workspace_id=workspace_id,
            trajectory_id=trajectory_id,
            case_suite_id=suite.suite_id,
        ),
        generate_regression_report(
            prior_dispositions,
            dispositions,
            workspace_id=workspace_id,
            trajectory_id=trajectory_id,
        ),
    ]
    for report in reports:
        save_report(root, workspace_id, trajectory_id, report)
        trajectory.append_event(
            TrajectoryEvent(
                event_id=new_event_id(),
                branch_id=trajectory.active_branch_id,
                kind=TrajectoryEventKind.REPORT_GENERATED,
                payload={
                    "report_id": report.report_id,
                    "kind": report.kind.value,
                    "snapshot_id": selected_snapshot_id,
                },
            )
        )

    workspace.trajectories[trajectory.trajectory_id] = trajectory
    save_workspace(workspace, root)
    validation = validate_persisted_trajectory(root, trajectory)
    return ReexerciseResult(
        workspace_id=workspace_id,
        trajectory_id=trajectory_id,
        snapshot_id=selected_snapshot_id,
        map_records=map_records,
        dispositions=dispositions,
        diagnostics=diagnostics,
        reports=reports,
        validation=validation,
        root=str(root),
    )


def record_persisted_reviewer_hint(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    *,
    message: str,
    target_step_id: str | None = None,
    case_id: str | None = None,
    atom_ids: list[str] | None = None,
    reviewer_id: str | None = None,
    branch_id: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PersistedReviewerHintResult:
    """Record a reviewer natural-language hint on a persisted trajectory."""
    root = Path(root)
    workspace = load_workspace(root, workspace_id)
    trajectory = load_trajectory(root, workspace_id, trajectory_id)
    hint, _intervention = record_reviewer_hint(
        trajectory,
        message=message,
        target_step_id=target_step_id,
        case_id=case_id,
        atom_ids=atom_ids,
        reviewer_id=reviewer_id,
        branch_id=branch_id,
        reason=reason,
        metadata=metadata,
    )
    workspace.trajectories[trajectory.trajectory_id] = trajectory
    save_workspace(workspace, root)
    validation = validate_persisted_trajectory(root, trajectory)
    return PersistedReviewerHintResult(
        workspace_id=workspace_id,
        trajectory_id=trajectory_id,
        branch_id=branch_id or trajectory.active_branch_id,
        hint=hint,
        validation=validation,
        root=str(root),
    )


def load_program_edit_operations(path: str | Path) -> list[ProgramEditOperation]:
    path = Path(path)
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml

        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "operations" in payload:
        payload = payload["operations"]
    if not isinstance(payload, list):
        raise ValueError("program edit file must contain a list or an object with operations")
    return [ProgramEditOperation.model_validate(item) for item in payload]


def _append_step_event(trajectory: Trajectory, run: StepRunResult) -> None:
    trajectory.append_event(
        TrajectoryEvent(
            event_id=new_event_id(),
            branch_id=trajectory.active_branch_id,
            kind=TrajectoryEventKind.STEP_RUN,
            payload={"run_id": run.run_id, "step_id": run.step_id},
        )
    )


def _count_json(path: Path) -> int:
    if not path.exists():
        return 0
    return len(list(path.glob("*.json")))


def _read_json_files(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(file_path.read_text(encoding="utf-8"))
        for file_path in sorted(path.glob("*.json"))
    ]


def _write_export_json(path: Path, payload: Any) -> str:
    path.write_text(
        json.dumps(to_jsonable_python(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return str(path)


def _latest_snapshot_id(trajectory: Trajectory) -> str:
    for event in reversed(trajectory.events):
        if event.kind == TrajectoryEventKind.PROGRAM_SNAPSHOT:
            snapshot_id = event.payload.get("snapshot_id")
            if isinstance(snapshot_id, str) and snapshot_id:
                return snapshot_id
    raise ValueError(f"trajectory {trajectory.trajectory_id!r} has no program snapshot")


__all__ = [
    "PolicyRunResult",
    "PersistedProgramEditResult",
    "PersistedReviewerHintResult",
    "ReexerciseResult",
    "run_policy_seed",
    "run_policy_seed_file",
    "inspect_persisted_run",
    "list_persisted_runs",
    "export_review_bundle",
    "export_builder_ui",
    "apply_persisted_program_edits",
    "list_branches",
    "mark_branch_status",
    "record_persisted_reviewer_hint",
    "reexercise_latest_snapshot",
    "load_program_edit_operations",
]
