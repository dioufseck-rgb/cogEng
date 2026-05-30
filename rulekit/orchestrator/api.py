"""Optional FastAPI surface for RuleKit Orchestrator workflows."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from rulekit.orchestrator.workflow import (
    apply_persisted_program_edits,
    export_review_bundle,
    inspect_persisted_run,
    list_branches,
    list_persisted_runs,
    load_program_edit_operations,
    mark_branch_status,
    record_persisted_reviewer_hint,
    reexercise_latest_snapshot,
    run_policy_seed_file,
)
from rulekit.orchestrator.projections import (
    build_trajectory_projection,
    build_workspace_index_projection,
)


def create_app(root: str | Path = ".rulekit_workspaces"):
    """Create the optional FastAPI app.

    Install `rulekit[api]` to use this surface. Imports are intentionally
    lazy so the core orchestrator package has no mandatory web dependency.
    """
    try:
        from fastapi import FastAPI
        from pydantic import BaseModel, Field
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("Install rulekit[api] to use the orchestrator API") from exc

    app = FastAPI(title="RuleKit Orchestrator API", version="0.1")
    root_path = Path(root)

    class RunSeedRequest(BaseModel):
        seed_path: str
        k: int = 2
        program_id: str | None = None
        program_version: str = "0.1"

    class EditRequest(BaseModel):
        operations_path: str
        snapshot_id: str | None = None

    class ReexerciseRequest(BaseModel):
        snapshot_id: str | None = None

    class HintRequest(BaseModel):
        message: str = Field(min_length=1)
        target_step_id: str | None = None
        case_id: str | None = None
        atom_ids: list[str] = Field(default_factory=list)
        reviewer_id: str | None = None
        reason: str | None = None
        reexercise: bool = False
        snapshot_id: str | None = None

    class ExportRequest(BaseModel):
        output_dir: str

    class MarkBranchRequest(BaseModel):
        status: str = Field(pattern="^(settled|abandoned)$")
        reviewer_id: str | None = None
        reason: str | None = None

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/runs")
    def runs() -> dict[str, Any]:
        items = list_persisted_runs(root_path)
        return {"count": len(items), "runs": items}

    @app.get("/projection")
    def projection_index() -> dict[str, Any]:
        return build_workspace_index_projection(root_path)

    @app.post("/runs")
    def run_seed(request: RunSeedRequest) -> dict[str, Any]:
        result = run_policy_seed_file(
            request.seed_path,
            root_path,
            k=request.k,
            program_id=request.program_id,
            program_version=request.program_version,
        )
        return {"ok": result.validation.ok, **result.summary()}

    @app.get("/workspaces/{workspace_id}/trajectories/{trajectory_id}")
    def inspect(workspace_id: str, trajectory_id: str) -> dict[str, Any]:
        return inspect_persisted_run(root_path, workspace_id, trajectory_id)

    @app.get("/workspaces/{workspace_id}/trajectories/{trajectory_id}/projection")
    def trajectory_projection(workspace_id: str, trajectory_id: str) -> dict[str, Any]:
        return build_trajectory_projection(root_path, workspace_id, trajectory_id)

    @app.get("/workspaces/{workspace_id}/trajectories/{trajectory_id}/branches")
    def branches(workspace_id: str, trajectory_id: str) -> dict[str, Any]:
        items = list_branches(root_path, workspace_id, trajectory_id)
        return {"count": len(items), "branches": items}

    @app.post("/workspaces/{workspace_id}/trajectories/{trajectory_id}/branches/{branch_id}")
    def mark_branch(
        workspace_id: str,
        trajectory_id: str,
        branch_id: str,
        request: MarkBranchRequest,
    ) -> dict[str, Any]:
        return mark_branch_status(
            root_path,
            workspace_id,
            trajectory_id,
            branch_id,
            request.status,
            reviewer_id=request.reviewer_id,
            reason=request.reason,
        )

    @app.post("/workspaces/{workspace_id}/trajectories/{trajectory_id}/edit")
    def edit(
        workspace_id: str,
        trajectory_id: str,
        request: EditRequest,
    ) -> dict[str, Any]:
        operations = load_program_edit_operations(request.operations_path)
        result = apply_persisted_program_edits(
            root_path,
            workspace_id,
            trajectory_id,
            operations,
            snapshot_id=request.snapshot_id,
        )
        return {"ok": result.validation.ok, **result.summary()}

    @app.post("/workspaces/{workspace_id}/trajectories/{trajectory_id}/reexercise")
    def reexercise(
        workspace_id: str,
        trajectory_id: str,
        request: ReexerciseRequest,
    ) -> dict[str, Any]:
        result = reexercise_latest_snapshot(
            root_path,
            workspace_id,
            trajectory_id,
            snapshot_id=request.snapshot_id,
        )
        return {"ok": result.validation.ok, **result.summary()}

    @app.post("/workspaces/{workspace_id}/trajectories/{trajectory_id}/hints")
    def hint(
        workspace_id: str,
        trajectory_id: str,
        request: HintRequest,
    ) -> dict[str, Any]:
        result = record_persisted_reviewer_hint(
            root_path,
            workspace_id,
            trajectory_id,
            message=request.message,
            target_step_id=request.target_step_id,
            case_id=request.case_id,
            atom_ids=request.atom_ids,
            reviewer_id=request.reviewer_id,
            reason=request.reason,
        )
        payload: dict[str, Any] = {"ok": result.validation.ok, **result.summary()}
        if request.reexercise:
            rerun = reexercise_latest_snapshot(
                root_path,
                workspace_id,
                trajectory_id,
                snapshot_id=request.snapshot_id,
            )
            payload["reexercise"] = {"ok": rerun.validation.ok, **rerun.summary()}
            payload["ok"] = payload["ok"] and rerun.validation.ok
        return payload

    @app.post("/workspaces/{workspace_id}/trajectories/{trajectory_id}/export")
    def export(
        workspace_id: str,
        trajectory_id: str,
        request: ExportRequest,
    ) -> dict[str, Any]:
        result = export_review_bundle(
            root_path,
            workspace_id,
            trajectory_id,
            request.output_dir,
        )
        return {"ok": result["validation_ok"], **result}

    return app


__all__ = ["create_app"]
