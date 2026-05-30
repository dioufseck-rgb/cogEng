"""Build step protocols and auditable run records."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from rulekit.orchestrator.dialogue import AgentTurn, ReviewerTurn


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StepKind(str, Enum):
    DETERMINISTIC = "deterministic"
    STOCHASTIC = "stochastic"


class DialogueCapability(str, Enum):
    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


class StepRunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    VALIDATION_FAILED = "validation_failed"
    CANCELLED = "cancelled"


class ValidationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1)
    severity: ValidationSeverity = ValidationSeverity.ERROR
    path: str | None = None
    code: str | None = None


class ExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code_version: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    temperature: float | None = None
    seed: int | None = None
    started_by: str | None = None
    environment: dict[str, str] = Field(default_factory=dict)


class RunCost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
    latency_s: float | None = Field(default=None, ge=0)


class BuildStepSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    kind: StepKind = StepKind.DETERMINISTIC
    dialogue_capability: DialogueCapability = DialogueCapability.NONE
    default_k: int = Field(default=1, ge=1)
    max_dialogue_turns: int = Field(default=0, ge=0)
    timeout_s: int | None = Field(default=None, ge=1)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_dialogue_budget(self):
        if self.dialogue_capability == DialogueCapability.NONE:
            if self.max_dialogue_turns != 0:
                raise ValueError(
                    "max_dialogue_turns must be 0 when dialogue_capability=none"
                )
        elif self.max_dialogue_turns < 1:
            raise ValueError(
                "dialogue-capable steps require max_dialogue_turns >= 1"
            )
        return self


class StepContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str | None = None
    trajectory_id: str | None = None
    branch_id: str | None = None
    execution_context: ExecutionContext = Field(default_factory=ExecutionContext)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StepRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    step_id: str
    status: StepRunStatus
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None = None
    validation_messages: list[ValidationMessage] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    execution_context: ExecutionContext = Field(default_factory=ExecutionContext)
    cost: RunCost | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_completed_after_started(self):
        if self.completed_at is not None and self.completed_at < self.started_at:
            raise ValueError("completed_at cannot be before started_at")
        return self


class MultiRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    multi_run_id: str
    step_id: str
    run_ids: list[str] = Field(min_length=1)
    selected_run_id: str | None = None
    consolidation_method: str | None = None
    variance_summary: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_selected_run(self):
        if self.selected_run_id is not None and self.selected_run_id not in self.run_ids:
            raise ValueError("selected_run_id must be one of run_ids")
        return self


class BuildStep(Protocol):
    spec: BuildStepSpec

    def run(
        self,
        input_payload: dict[str, Any],
        context: StepContext,
    ) -> StepRunResult:
        ...


class DialogueCapableStep(BuildStep, Protocol):
    def start_dialogue(
        self,
        input_payload: dict[str, Any],
        context: StepContext,
    ) -> "AgentTurn":
        ...

    def continue_dialogue(
        self,
        dialogue_id: str,
        reviewer_turn: "ReviewerTurn",
        context: StepContext,
    ) -> "AgentTurn":
        ...


__all__ = [
    "utc_now",
    "StepKind",
    "DialogueCapability",
    "StepRunStatus",
    "ValidationSeverity",
    "ValidationMessage",
    "ExecutionContext",
    "RunCost",
    "BuildStepSpec",
    "StepContext",
    "StepRunResult",
    "MultiRunResult",
    "BuildStep",
    "DialogueCapableStep",
]
