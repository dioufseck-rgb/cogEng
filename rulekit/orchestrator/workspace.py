"""Workspace and policy source models."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rulekit.orchestrator.cases import CaseSuite
from rulekit.orchestrator.step import utc_now
from rulekit.orchestrator.trajectory import Trajectory


class PolicySourceKind(str, Enum):
    TEXT = "text"
    FILE = "file"
    URL = "url"
    REGULATOR_PUBLICATION = "regulator_publication"


class PolicySource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    title: str = Field(min_length=1)
    kind: PolicySourceKind
    version_label: str | None = None
    content: str | None = None
    content_hash: str | None = None
    source_uri: str | None = None
    loaded_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProgramRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: str
    version: str | None = None
    path: str | None = None
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class Workspace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    name: str = Field(min_length=1)
    policies: dict[str, PolicySource] = Field(default_factory=dict)
    case_suites: dict[str, CaseSuite] = Field(default_factory=dict)
    program_refs: dict[str, ProgramRef] = Field(default_factory=dict)
    trajectories: dict[str, Trajectory] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_registry_keys(self):
        for key, policy in self.policies.items():
            if key != policy.policy_id:
                raise ValueError(f"policy key {key!r} does not match policy_id")
        for key, suite in self.case_suites.items():
            if key != suite.suite_id:
                raise ValueError(f"case suite key {key!r} does not match suite_id")
        for key, program in self.program_refs.items():
            if key != program.program_id:
                raise ValueError(f"program ref key {key!r} does not match program_id")
        for key, trajectory in self.trajectories.items():
            if key != trajectory.trajectory_id:
                raise ValueError(
                    f"trajectory key {key!r} does not match trajectory_id"
                )
            if trajectory.workspace_id != self.workspace_id:
                raise ValueError(
                    f"trajectory {key!r} belongs to workspace "
                    f"{trajectory.workspace_id!r}, not {self.workspace_id!r}"
                )
        return self


__all__ = [
    "PolicySourceKind",
    "PolicySource",
    "ProgramRef",
    "Workspace",
]
