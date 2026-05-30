"""Load and save orchestrator workspace seeds from JSON or YAML."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic_core import to_jsonable_python

from rulekit.orchestrator.factory import PolicyWorkspaceSeed


def load_policy_workspace_seed(path: str | Path) -> PolicyWorkspaceSeed:
    path = Path(path)
    data = _load_mapping(path)
    return PolicyWorkspaceSeed.model_validate(data)


def save_policy_workspace_seed(seed: PolicyWorkspaceSeed, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = to_jsonable_python(seed.model_dump(mode="json"))
    if path.suffix.lower() in (".yaml", ".yml"):
        import yaml

        path.write_text(
            yaml.safe_dump(payload, sort_keys=False),
            encoding="utf-8",
        )
    else:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _load_mapping(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        import yaml

        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    elif suffix == ".json":
        loaded = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError(
            f"Unsupported seed file extension {path.suffix!r}; use .json, .yaml, or .yml"
        )
    if not isinstance(loaded, dict):
        raise ValueError("policy workspace seed file must contain an object/mapping")
    return loaded


__all__ = ["load_policy_workspace_seed", "save_policy_workspace_seed"]
