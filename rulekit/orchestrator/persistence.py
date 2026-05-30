"""Disk persistence for orchestrator workspaces and trajectories."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_core import to_jsonable_python

from rulekit.orchestrator.diagnostics import CaseDiagnostic
from rulekit.orchestrator.dialogue import DialogueSession
from rulekit.orchestrator.disposition import DispositionRecord
from rulekit.orchestrator.map_record import MapExtractionRecord
from rulekit.orchestrator.program_edit import ProgramEditResult
from rulekit.orchestrator.reports import GovernanceReport
from rulekit.orchestrator.snapshot import ProgramSnapshot
from rulekit.orchestrator.step import StepRunResult, utc_now
from rulekit.orchestrator.trajectory import Trajectory, TrajectoryEvent
from rulekit.orchestrator.workspace import Workspace

SCHEMA_VERSION = "orchestrator.v0.1"


def _write_json(path: Path, model_or_data: BaseModel | dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(model_or_data, BaseModel):
        payload = model_or_data.model_dump(mode="json")
    else:
        payload = to_jsonable_python(model_or_data)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def workspace_dir(root: str | Path, workspace_id: str) -> Path:
    return Path(root) / workspace_id


def trajectory_dir(root: str | Path, workspace_id: str, trajectory_id: str) -> Path:
    return workspace_dir(root, workspace_id) / "trajectories" / trajectory_id


def save_workspace(workspace: Workspace, root: str | Path) -> Path:
    """Save a workspace manifest plus top-level registries."""
    base = workspace_dir(root, workspace.workspace_id)
    base.mkdir(parents=True, exist_ok=True)
    _write_json(base / "workspace.json", workspace)
    for policy in workspace.policies.values():
        _write_json(base / "policies" / f"{policy.policy_id}.json", policy)
    for suite in workspace.case_suites.values():
        _write_json(base / "cases" / f"{suite.suite_id}.json", suite)
    for trajectory in workspace.trajectories.values():
        save_trajectory(trajectory, root)
    return base


def load_workspace(root: str | Path, workspace_id: str) -> Workspace:
    return Workspace.model_validate(
        _read_json(workspace_dir(root, workspace_id) / "workspace.json")
    )


def save_trajectory(trajectory: Trajectory, root: str | Path) -> Path:
    """Save manifest, branches, and full event JSONL for a trajectory."""
    base = trajectory_dir(root, trajectory.workspace_id, trajectory.trajectory_id)
    base.mkdir(parents=True, exist_ok=True)
    manifest = {
        "object_type": "TrajectoryManifest",
        "schema_version": SCHEMA_VERSION,
        "trajectory_id": trajectory.trajectory_id,
        "workspace_id": trajectory.workspace_id,
        "created_at": trajectory.created_at.isoformat(),
        "updated_at": utc_now().isoformat(),
        "objects": {
            "events": "events.jsonl",
            "branches": "branches.json",
        },
    }
    _write_json(base / "manifest.json", manifest)
    _write_json(base / "branches.json", {"branches": trajectory.branches})
    with (base / "events.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for event in trajectory.events:
            f.write(event.model_dump_json() + "\n")
    return base


def load_trajectory(root: str | Path, workspace_id: str, trajectory_id: str) -> Trajectory:
    base = trajectory_dir(root, workspace_id, trajectory_id)
    manifest = _read_json(base / "manifest.json")
    branches_payload = _read_json(base / manifest["objects"]["branches"])
    events: list[TrajectoryEvent] = []
    events_path = base / manifest["objects"]["events"]
    if events_path.exists():
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(TrajectoryEvent.model_validate_json(line))
    return Trajectory(
        trajectory_id=manifest["trajectory_id"],
        workspace_id=manifest["workspace_id"],
        branches=branches_payload["branches"],
        events=events,
        active_branch_id=_infer_active_branch(branches_payload["branches"], events),
        created_at=manifest["created_at"],
        updated_at=manifest["updated_at"],
    )


def _infer_active_branch(branches: dict[str, Any], events: list[TrajectoryEvent]) -> str:
    if events:
        return events[-1].branch_id
    return next(iter(branches))


def append_trajectory_event(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    event: TrajectoryEvent,
) -> None:
    base = trajectory_dir(root, workspace_id, trajectory_id)
    base.mkdir(parents=True, exist_ok=True)
    with (base / "events.jsonl").open("a", encoding="utf-8", newline="\n") as f:
        f.write(event.model_dump_json() + "\n")


def save_step_run(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    run: StepRunResult,
) -> Path:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "step_runs" / f"{run.run_id}.json"
    _write_json(path, run)
    return path


def load_step_run(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    run_id: str,
) -> StepRunResult:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "step_runs" / f"{run_id}.json"
    return StepRunResult.model_validate(_read_json(path))


def save_dialogue(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    dialogue: DialogueSession,
) -> Path:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "dialogues" / f"{dialogue.dialogue_id}.json"
    _write_json(path, dialogue)
    return path


def load_dialogue(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    dialogue_id: str,
) -> DialogueSession:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "dialogues" / f"{dialogue_id}.json"
    return DialogueSession.model_validate(_read_json(path))


def save_report(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    report: GovernanceReport,
) -> Path:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "reports" / f"{report.report_id}.json"
    _write_json(path, report)
    return path


def save_program_edit(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    edit: ProgramEditResult,
) -> Path:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "program_edits" / f"{edit.edit_id}.json"
    _write_json(path, edit)
    return path


def load_program_edit(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    edit_id: str,
) -> ProgramEditResult:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "program_edits" / f"{edit_id}.json"
    return ProgramEditResult.model_validate(_read_json(path))


def save_disposition(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    disposition: DispositionRecord,
) -> Path:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "dispositions" / f"{disposition.disposition_id}.json"
    _write_json(path, disposition)
    return path


def save_case_diagnostic(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    diagnostic: CaseDiagnostic,
) -> Path:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "diagnostics" / f"{diagnostic.diagnostic_id}.json"
    _write_json(path, diagnostic)
    return path


def load_case_diagnostic(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    diagnostic_id: str,
) -> CaseDiagnostic:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "diagnostics" / f"{diagnostic_id}.json"
    return CaseDiagnostic.model_validate(_read_json(path))


def save_map_record(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    map_record: MapExtractionRecord,
) -> Path:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "map_records" / f"{map_record.map_record_id}.json"
    _write_json(path, map_record)
    return path


def load_map_record(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    map_record_id: str,
) -> MapExtractionRecord:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "map_records" / f"{map_record_id}.json"
    return MapExtractionRecord.model_validate(_read_json(path))


def load_disposition(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    disposition_id: str,
) -> DispositionRecord:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "dispositions" / f"{disposition_id}.json"
    return DispositionRecord.model_validate(_read_json(path))


def save_program_snapshot(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    snapshot: ProgramSnapshot,
) -> Path:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "snapshots" / f"{snapshot.snapshot_id}.json"
    _write_json(path, snapshot)
    return path


def load_program_snapshot(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    snapshot_id: str,
) -> ProgramSnapshot:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "snapshots" / f"{snapshot_id}.json"
    return ProgramSnapshot.model_validate(_read_json(path))


def save_snapshot(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
    snapshot_id: str,
    payload: dict[str, Any],
) -> Path:
    path = trajectory_dir(root, workspace_id, trajectory_id) / "snapshots" / f"{snapshot_id}.json"
    _write_json(
        path,
        {
            "object_type": "ProgramSnapshot",
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "payload": payload,
        },
    )
    return path


__all__ = [
    "SCHEMA_VERSION",
    "workspace_dir",
    "trajectory_dir",
    "save_workspace",
    "load_workspace",
    "save_trajectory",
    "load_trajectory",
    "append_trajectory_event",
    "save_step_run",
    "load_step_run",
    "save_dialogue",
    "load_dialogue",
    "save_report",
    "save_program_edit",
    "load_program_edit",
    "save_case_diagnostic",
    "load_case_diagnostic",
    "save_disposition",
    "load_disposition",
    "save_map_record",
    "load_map_record",
    "save_program_snapshot",
    "load_program_snapshot",
    "save_snapshot",
]
