from __future__ import annotations

import importlib.util

import pytest

from rulekit.orchestrator.api import create_app


def test_create_app_reports_missing_optional_dependency():
    if importlib.util.find_spec("fastapi") is not None:
        app = create_app()
        assert app.title == "RuleKit Orchestrator API"
        routes = {route.path for route in app.routes}
        assert "/projection" in routes
        assert "/workspaces/{workspace_id}/trajectories/{trajectory_id}/projection" in routes
        assert "/workspaces/{workspace_id}/trajectories/{trajectory_id}/hints" in routes
        return

    with pytest.raises(RuntimeError, match=r"rulekit\[api\]"):
        create_app()
