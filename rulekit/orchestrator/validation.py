"""Validation helpers for orchestrator graphs and trajectories."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rulekit.orchestrator.dialogue import DialogueSession
from rulekit.orchestrator.persistence import trajectory_dir
from rulekit.orchestrator.trajectory import (
    Trajectory,
    TrajectoryEventKind,
)


@dataclass
class OrchestratorValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if self.ok and not self.warnings:
            return "validation: ok"
        lines: list[str] = []
        for error in self.errors:
            lines.append(f"ERROR: {error}")
        for warning in self.warnings:
            lines.append(f"WARN: {warning}")
        return "\n".join(lines)


def validate_trajectory(trajectory: Trajectory) -> OrchestratorValidationReport:
    """Run semantic checks not covered by Pydantic construction."""
    report = OrchestratorValidationReport()
    event_ids = [event.event_id for event in trajectory.events]
    if len(event_ids) != len(set(event_ids)):
        report.errors.append("event IDs must be unique")
    branch_ids = set(trajectory.branches)
    for event in trajectory.events:
        if event.branch_id not in branch_ids:
            report.errors.append(
                f"event {event.event_id!r} references missing branch {event.branch_id!r}"
            )
        if event.kind == TrajectoryEventKind.BRANCH_CREATED:
            branch_id = event.payload.get("branch_id")
            if branch_id not in branch_ids:
                report.errors.append(
                    f"branch_created event {event.event_id!r} references "
                    f"missing branch {branch_id!r}"
                )
    for branch_id, branch in trajectory.branches.items():
        if branch.head_event_id is not None and branch.head_event_id not in event_ids:
            report.errors.append(
                f"branch {branch_id!r} head_event_id {branch.head_event_id!r} "
                "is not an event"
            )
    return report


def validate_dialogue_session(
    dialogue: DialogueSession,
    *,
    extension_interventions: int = 0,
) -> OrchestratorValidationReport:
    """Validate dialogue budget, allowing explicit reviewer extensions."""
    report = OrchestratorValidationReport()
    allowed_turns = dialogue.max_turns + max(0, extension_interventions)
    if dialogue.turn_count > allowed_turns:
        report.errors.append(
            f"dialogue {dialogue.dialogue_id!r} has {dialogue.turn_count} turns "
            f"but only {allowed_turns} are allowed"
        )
    return report


def validate_persisted_trajectory(
    root: str | Path,
    trajectory: Trajectory,
) -> OrchestratorValidationReport:
    """Check that persisted sidecar files referenced by events exist."""
    report = validate_trajectory(trajectory)
    base = trajectory_dir(root, trajectory.workspace_id, trajectory.trajectory_id)
    for event in trajectory.events:
        if event.kind == TrajectoryEventKind.STEP_RUN:
            run_id = event.payload.get("run_id")
            if run_id and not (base / "step_runs" / f"{run_id}.json").exists():
                report.errors.append(
                    f"step_run event {event.event_id!r} references missing "
                    f"step_runs/{run_id}.json"
                )
        elif event.kind == TrajectoryEventKind.DIALOGUE_OPENED:
            dialogue_id = event.payload.get("dialogue_id")
            if dialogue_id and not (base / "dialogues" / f"{dialogue_id}.json").exists():
                report.warnings.append(
                    f"dialogue_opened event {event.event_id!r} has no persisted "
                    f"dialogues/{dialogue_id}.json yet"
                )
        elif event.kind == TrajectoryEventKind.PROGRAM_SNAPSHOT:
            snapshot_id = event.payload.get("snapshot_id")
            if snapshot_id and not (base / "snapshots" / f"{snapshot_id}.json").exists():
                report.errors.append(
                    f"program_snapshot event {event.event_id!r} references "
                    f"missing snapshots/{snapshot_id}.json"
                )
        elif event.kind == TrajectoryEventKind.PROGRAM_EDIT_APPLIED:
            edit_id = event.payload.get("edit_id")
            if edit_id and not (base / "program_edits" / f"{edit_id}.json").exists():
                report.errors.append(
                    f"program_edit_applied event {event.event_id!r} references "
                    f"missing program_edits/{edit_id}.json"
                )
        elif event.kind == TrajectoryEventKind.REPORT_GENERATED:
            report_id = event.payload.get("report_id")
            if report_id and not (base / "reports" / f"{report_id}.json").exists():
                report.errors.append(
                    f"report_generated event {event.event_id!r} references "
                    f"missing reports/{report_id}.json"
                )
        elif event.kind == TrajectoryEventKind.DISPOSITION_RECORDED:
            disposition_id = event.payload.get("disposition_id")
            if disposition_id and not (base / "dispositions" / f"{disposition_id}.json").exists():
                report.errors.append(
                    f"disposition_recorded event {event.event_id!r} references "
                    f"missing dispositions/{disposition_id}.json"
                )
        elif event.kind == TrajectoryEventKind.DIAGNOSTIC_RECORDED:
            diagnostic_id = event.payload.get("diagnostic_id")
            if diagnostic_id and not (base / "diagnostics" / f"{diagnostic_id}.json").exists():
                report.errors.append(
                    f"diagnostic_recorded event {event.event_id!r} references "
                    f"missing diagnostics/{diagnostic_id}.json"
                )
        elif event.kind == TrajectoryEventKind.MAP_RECORDED:
            map_record_id = event.payload.get("map_record_id")
            if map_record_id and not (base / "map_records" / f"{map_record_id}.json").exists():
                report.errors.append(
                    f"map_recorded event {event.event_id!r} references "
                    f"missing map_records/{map_record_id}.json"
                )
    return report


__all__ = [
    "OrchestratorValidationReport",
    "validate_trajectory",
    "validate_dialogue_session",
    "validate_persisted_trajectory",
]
