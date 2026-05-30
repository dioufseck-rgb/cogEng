"""UI-ready projections over persisted orchestrator state."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rulekit.orchestrator.persistence import (
    load_program_snapshot,
    load_trajectory,
    load_workspace,
    trajectory_dir,
    workspace_dir,
)
from rulekit.orchestrator.trajectory import Trajectory, TrajectoryEventKind
from rulekit.orchestrator.validation import validate_persisted_trajectory


def build_workspace_index_projection(root: str | Path) -> dict[str, Any]:
    """Return the workspace/run list shape a Builder UI can render."""
    root = Path(root)
    workspaces: list[dict[str, Any]] = []
    if not root.exists():
        return {"root": str(root), "workspace_count": 0, "workspaces": workspaces}

    for workspace_path in sorted(path for path in root.iterdir() if path.is_dir()):
        if not (workspace_path / "workspace.json").exists():
            continue
        workspace = load_workspace(root, workspace_path.name)
        trajectories: list[dict[str, Any]] = []
        trajectories_path = workspace_path / "trajectories"
        if trajectories_path.exists():
            for trajectory_path in sorted(path for path in trajectories_path.iterdir() if path.is_dir()):
                if not (trajectory_path / "manifest.json").exists():
                    continue
                trajectory = load_trajectory(root, workspace.workspace_id, trajectory_path.name)
                validation = validate_persisted_trajectory(root, trajectory)
                trajectories.append(
                    {
                        "trajectory_id": trajectory.trajectory_id,
                        "active_branch_id": trajectory.active_branch_id,
                        "branch_count": len(trajectory.branches),
                        "event_count": len(trajectory.events),
                        "updated_at": trajectory.updated_at.isoformat(),
                        "validation_ok": validation.ok,
                    }
                )
        workspaces.append(
            {
                "workspace_id": workspace.workspace_id,
                "name": workspace.name,
                "policy_count": len(workspace.policies),
                "case_suite_count": len(workspace.case_suites),
                "trajectory_count": len(trajectories),
                "updated_at": workspace.updated_at.isoformat(),
                "trajectories": trajectories,
            }
        )
    return {
        "root": str(root),
        "workspace_count": len(workspaces),
        "workspaces": workspaces,
    }


def build_trajectory_projection(
    root: str | Path,
    workspace_id: str,
    trajectory_id: str,
) -> dict[str, Any]:
    """Return a complete read-only Builder UI projection for one trajectory."""
    root = Path(root)
    workspace = load_workspace(root, workspace_id)
    trajectory = load_trajectory(root, workspace_id, trajectory_id)
    base = trajectory_dir(root, workspace_id, trajectory_id)
    validation = validate_persisted_trajectory(root, trajectory)
    snapshots = _read_json_files(base / "snapshots")
    reports = _read_json_files(base / "reports")
    diagnostics = _read_json_files(base / "diagnostics")
    dispositions = _read_json_files(base / "dispositions")
    map_records = _read_json_files(base / "map_records")

    latest_snapshot_id = _latest_snapshot_id_or_none(trajectory)
    program_summary: dict[str, Any] | None = None
    if latest_snapshot_id:
        snapshot = load_program_snapshot(root, workspace_id, trajectory_id, latest_snapshot_id)
        program_summary = {
            "snapshot_id": snapshot.snapshot_id,
            "program_id": snapshot.program_id,
            "program_version": snapshot.program_version,
            "name": snapshot.program.metadata.name,
            "determination_count": len(snapshot.program.determinations),
            "atom_count": len(snapshot.program.map_spec.atoms),
            "node_count": len(snapshot.program.nodes),
            "determinations": [
                {
                    "determination_id": det_id,
                    "description": det.description,
                    "composition": det.composition,
                    "root_node": det.root_node,
                    "linked_to": det.linked_to,
                    "polarity": det.polarity,
                }
                for det_id, det in sorted(snapshot.program.determinations.items())
            ],
            "atoms": [
                {
                    "atom_id": atom_id,
                    "atom_type": atom.atom_type,
                    "statement": atom.statement,
                    "source_span": atom.source_span,
                    "evaluation_mode": atom.evaluation_mode,
                    "extraction_template": atom.extraction_template,
                    "undetermined_rule": atom.undetermined_rule,
                    "numeric_unit": getattr(atom, "numeric_unit", None),
                }
                for atom_id, atom in sorted(snapshot.program.map_spec.atoms.items())
            ],
            "nodes": [
                {
                    **node.model_dump(mode="json"),
                    "node_id": node_id,
                    "kind": node.kind,
                    "surface_label": getattr(node, "surface_label", ""),
                    "source_span": getattr(node, "source_span", ""),
                }
                for node_id, node in sorted(snapshot.program.nodes.items())
            ],
            "validation_summary": snapshot.validation_summary,
            "metadata": snapshot.metadata,
        }

    return {
        "workspace": {
            "workspace_id": workspace.workspace_id,
            "name": workspace.name,
            "policy_count": len(workspace.policies),
            "case_suite_count": len(workspace.case_suites),
        },
        "trajectory": {
            "trajectory_id": trajectory.trajectory_id,
            "active_branch_id": trajectory.active_branch_id,
            "event_count": len(trajectory.events),
            "created_at": trajectory.created_at.isoformat(),
            "updated_at": trajectory.updated_at.isoformat(),
            "validation_ok": validation.ok,
            "validation_summary": validation.summary(),
        },
        "branches": _branch_projection(trajectory),
        "timeline": [_event_projection(event) for event in trajectory.events],
        "program": program_summary,
        "snapshots": [_snapshot_summary(snapshot) for snapshot in snapshots],
        "cases": _case_examples(workspace, dispositions),
        "case_results": _case_result_rows(dispositions, diagnostics),
        "reports": [_report_summary(report) for report in reports],
        "diagnostics": [_diagnostic_summary(diagnostic) for diagnostic in diagnostics],
        "map_records": [_map_record_summary(record) for record in map_records],
        "reviewer_hints": _reviewer_hints(trajectory),
        "paths": {
            "workspace": str(workspace_dir(root, workspace_id)),
            "trajectory": str(base),
        },
    }


def _branch_projection(trajectory: Trajectory) -> list[dict[str, Any]]:
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


def _event_projection(event) -> dict[str, Any]:
    payload = event.payload
    return {
        "event_id": event.event_id,
        "branch_id": event.branch_id,
        "kind": event.kind.value,
        "created_at": event.created_at.isoformat(),
        "parent_event_id": event.parent_event_id,
        "title": _event_title(event.kind, payload),
        "refs": {
            key: value
            for key, value in payload.items()
            if key.endswith("_id") or key in {"kind", "matched_expected"}
        },
    }


def _event_title(kind: TrajectoryEventKind, payload: dict[str, Any]) -> str:
    if kind == TrajectoryEventKind.STEP_RUN:
        return f"Step run: {payload.get('step_id', 'unknown')}"
    if kind == TrajectoryEventKind.PROGRAM_SNAPSHOT:
        return f"Snapshot: {payload.get('snapshot_id', 'unknown')}"
    if kind == TrajectoryEventKind.PROGRAM_EDIT_APPLIED:
        return f"Program edit: {payload.get('edit_id', 'unknown')}"
    if kind == TrajectoryEventKind.REPORT_GENERATED:
        return f"Report: {payload.get('kind', 'unknown')}"
    if kind == TrajectoryEventKind.DISPOSITION_RECORDED:
        return f"Disposition: {payload.get('case_id', 'unknown')}"
    if kind == TrajectoryEventKind.DIAGNOSTIC_RECORDED:
        return f"Diagnostic: {payload.get('case_id', 'unknown')}"
    if kind == TrajectoryEventKind.MAP_RECORDED:
        return f"Map: {payload.get('case_id', 'unknown')}"
    if kind == TrajectoryEventKind.BRANCH_CREATED:
        return f"Branch: {payload.get('branch_id', 'unknown')}"
    if kind == TrajectoryEventKind.INTERVENTION:
        if payload.get("kind") == "reviewer_natural_hint":
            hint = payload.get("payload", {}).get("hint", {})
            return f"Reviewer hint: {hint.get('case_id') or payload.get('step_id') or 'general'}"
        if payload.get("kind") == "reviewer_added_case":
            return f"Added case: {payload.get('payload', {}).get('case_id', 'unknown')}"
        return f"Intervention: {payload.get('kind', 'unknown')}"
    return kind.value.replace("_", " ").title()


def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    program = snapshot.get("program", {})
    return {
        "snapshot_id": snapshot.get("snapshot_id"),
        "program_id": snapshot.get("program_id"),
        "program_version": snapshot.get("program_version"),
        "created_at": snapshot.get("created_at"),
        "name": program.get("metadata", {}).get("name"),
        "determination_count": len(program.get("determinations", {})),
        "atom_count": len(program.get("map_spec", {}).get("atoms", {})),
        "node_count": len(program.get("nodes", {})),
        "metadata": snapshot.get("metadata", {}),
    }


def _case_result_rows(
    dispositions: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    latest_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for disposition in sorted(dispositions, key=lambda item: item.get("created_at", "")):
        latest_by_key[(disposition["case_id"], disposition["determination_id"])] = disposition

    diagnostics_by_key = {
        (diagnostic["case_id"], diagnostic["determination_id"]): diagnostic
        for diagnostic in sorted(diagnostics, key=lambda item: item.get("diagnostic_id", ""))
    }
    rows: list[dict[str, Any]] = []
    for key, disposition in sorted(latest_by_key.items()):
        diagnostic = diagnostics_by_key.get(key)
        rows.append(
            {
                "case_id": disposition["case_id"],
                "case_title": disposition.get("metadata", {}).get("case_title"),
                "determination_id": disposition["determination_id"],
                "outcome": disposition["outcome"],
                "expected_outcome": disposition.get("expected_outcome"),
                "matched_expected": disposition.get("matched_expected"),
                "load_bearing_path": disposition.get("load_bearing_path", []),
                "disposition_id": disposition.get("disposition_id"),
                "map_record_id": disposition.get("metadata", {}).get("map_record_id"),
                "diagnostic_id": diagnostic.get("diagnostic_id") if diagnostic else None,
                "diagnostic_kind": diagnostic.get("kind") if diagnostic else None,
            }
        )
    return rows


def _case_examples(workspace, dispositions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_case: dict[str, dict[str, dict[str, Any]]] = {}
    for disposition in sorted(dispositions, key=lambda item: item.get("created_at", "")):
        case_results = latest_by_case.setdefault(disposition["case_id"], {})
        case_results[disposition["determination_id"]] = disposition

    rows: list[dict[str, Any]] = []
    for suite_id, suite in sorted(workspace.case_suites.items()):
        for case_id, case in sorted(suite.cases.items()):
            outcomes = [
                {
                    "determination_id": disposition["determination_id"],
                    "outcome": disposition["outcome"],
                    "expected_outcome": disposition.get("expected_outcome"),
                    "matched_expected": disposition.get("matched_expected"),
                    "disposition_id": disposition.get("disposition_id"),
                    "load_bearing_path": disposition.get("load_bearing_path", []),
                }
                for disposition in sorted(
                    latest_by_case.get(case_id, {}).values(),
                    key=lambda item: item.get("determination_id", ""),
                )
            ]
            matched_values = [
                outcome["matched_expected"]
                for outcome in outcomes
                if outcome["matched_expected"] is not None
            ]
            rows.append(
                {
                    "suite_id": suite_id,
                    "case_id": case.case_id,
                    "title": case.title,
                    "narrative": case.narrative,
                    "structured_fields": case.structured_fields,
                    "expected_outcomes": {
                        expected.determination_id: expected.expected_value
                        for expected in case.expected_outcomes
                    },
                    "provenance": case.provenance.value,
                    "metadata": case.metadata,
                    "result_count": len(outcomes),
                    "outcomes": outcomes,
                    "matched_expected": (
                        None if not matched_values else all(matched_values)
                    ),
                }
            )
    return rows


def _report_summary(report: dict[str, Any]) -> dict[str, Any]:
    payload = report.get("payload", {})
    return {
        "report_id": report.get("report_id"),
        "kind": report.get("kind"),
        "created_at": report.get("created_at"),
        "headline": _report_headline(report.get("kind"), payload),
        "payload": payload,
    }


def _report_headline(kind: str | None, payload: dict[str, Any]) -> str:
    if kind == "coverage":
        return f"{payload.get('matched_count', 0)}/{payload.get('compared_count', 0)} matched"
    if kind == "regression":
        return f"{payload.get('change_count', 0)} outcome changes"
    if kind == "variance":
        return f"{payload.get('unique_output_count', 0)} unique outputs"
    if kind == "source_text_coverage":
        return f"{payload.get('matched_span_count', 0)} matched source spans"
    if kind == "sensitivity":
        return f"{payload.get('unique_load_bearing_atom_count', 0)} load-bearing atoms"
    return kind or "report"


def _diagnostic_summary(diagnostic: dict[str, Any]) -> dict[str, Any]:
    return {
        "diagnostic_id": diagnostic.get("diagnostic_id"),
        "kind": diagnostic.get("kind"),
        "case_id": diagnostic.get("case_id"),
        "determination_id": diagnostic.get("determination_id"),
        "matched_expected": diagnostic.get("matched_expected"),
        "candidate_fix_count": len(diagnostic.get("candidate_fixes", [])),
        "load_bearing_path": diagnostic.get("load_bearing_path", []),
    }


def _map_record_summary(record: dict[str, Any]) -> dict[str, Any]:
    bindings = record.get("bindings", {})
    status_counts: dict[str, int] = {}
    for binding in bindings.values():
        status = binding.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "map_record_id": record.get("map_record_id"),
        "case_id": record.get("case_id"),
        "program_id": record.get("program_id"),
        "substrate_id": record.get("substrate_id"),
        "binding_count": len(bindings),
        "status_counts": status_counts,
        "reviewer_hint_count": record.get("metadata", {}).get("reviewer_hint_count", 0),
        "reviewer_hints": record.get("metadata", {}).get("reviewer_hints", []),
        "latency_s": record.get("latency_s"),
    }


def _reviewer_hints(trajectory: Trajectory) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    for event in trajectory.events:
        if event.kind != TrajectoryEventKind.INTERVENTION:
            continue
        payload = event.payload
        if payload.get("kind") != "reviewer_natural_hint":
            continue
        hint = payload.get("payload", {}).get("hint")
        if isinstance(hint, dict):
            hints.append(
                {
                    **hint,
                    "event_id": event.event_id,
                    "branch_id": event.branch_id,
                }
            )
    return hints


def _read_json_files(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(file_path.read_text(encoding="utf-8"))
        for file_path in sorted(path.glob("*.json"))
    ]


def _latest_snapshot_id_or_none(trajectory: Trajectory) -> str | None:
    for event in reversed(trajectory.events):
        if event.kind == TrajectoryEventKind.PROGRAM_SNAPSHOT:
            snapshot_id = event.payload.get("snapshot_id")
            if isinstance(snapshot_id, str) and snapshot_id:
                return snapshot_id
    return None


__all__ = [
    "build_workspace_index_projection",
    "build_trajectory_projection",
]
