from __future__ import annotations

import importlib.util

import pytest

from rulekit.orchestrator.api import create_app
from rulekit.orchestrator.cli import sample_seed
from rulekit.orchestrator.config import save_policy_workspace_seed
from rulekit.orchestrator.workflow import run_policy_seed_file


def test_create_app_reports_missing_optional_dependency():
    if importlib.util.find_spec("fastapi") is not None:
        app = create_app()
        assert app.title == "RuleKit Orchestrator API"
        routes = {route.path for route in app.routes}
        assert "/" in routes
        assert "/projection" in routes
        assert "/workspaces/{workspace_id}/trajectories/{trajectory_id}/projection" in routes
        assert "/ui/latest" in routes
        assert "/ui/latest/" in routes
        assert "/ui/{workspace_id}/{trajectory_id}" in routes
        assert "/ui/{workspace_id}/{trajectory_id}/" in routes
        assert "/ui/{workspace_id}/{trajectory_id}/projection.json" in routes
        assert "/ui/{workspace_id}/{trajectory_id}/app.js" in routes
        assert "/ui/{workspace_id}/{trajectory_id}/styles.css" in routes
        assert "/workspaces/{workspace_id}/trajectories/{trajectory_id}/hints" in routes
        assert "/workspaces/{workspace_id}/trajectories/{trajectory_id}/cases" in routes
        return

    with pytest.raises(RuntimeError, match=r"rulekit\[api\]"):
        create_app()


def test_live_ui_routes_resolve_latest_and_placeholders(tmp_path):
    if importlib.util.find_spec("fastapi") is None:
        pytest.skip("FastAPI optional dependency is not installed")

    from fastapi.testclient import TestClient

    seed_path = tmp_path / "seed.yaml"
    root = tmp_path / "workspaces"
    save_policy_workspace_seed(sample_seed(), seed_path)
    result = run_policy_seed_file(seed_path, root, program_id="prog_sample")
    client = TestClient(create_app(root))

    latest = client.get("/", follow_redirects=False)
    assert latest.status_code in {307, 308}
    assert latest.headers["location"] == (
        f"/ui/{result.workspace.workspace_id}/{result.trajectory.trajectory_id}/"
    )

    projection = client.get("/ui/latest/", follow_redirects=True)
    assert projection.status_code == 200
    assert "RuleKit Builder" in projection.text

    placeholder_projection = client.get(
        "/ui/%7Bworkspace_id%7D/%7Btrajectory_id%7D/projection.json"
    )
    assert placeholder_projection.status_code == 200
    assert placeholder_projection.json()["workspace"]["workspace_id"] == (
        result.workspace.workspace_id
    )
