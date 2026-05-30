"""Static build graph topology for orchestrated construction."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rulekit.orchestrator.errors import OrchestratorValidationError
from rulekit.orchestrator.step import BuildStepSpec


class BuildGraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)


class BuildGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    nodes: dict[str, BuildGraphNode]
    step_specs: dict[str, BuildStepSpec]
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_static_shape(self):
        self.validate_acyclic()
        missing_specs = sorted(set(self.nodes) - set(self.step_specs))
        if missing_specs:
            raise ValueError(f"missing step_specs for nodes: {missing_specs}")
        for key, node in self.nodes.items():
            if node.step_id != key:
                raise ValueError(
                    f"node key {key!r} does not match node.step_id {node.step_id!r}"
                )
            if self.step_specs[key].step_id != key:
                raise ValueError(
                    f"step_specs key {key!r} does not match spec.step_id "
                    f"{self.step_specs[key].step_id!r}"
                )
        return self

    def validate_acyclic(self) -> None:
        """Validate references and reject dependency cycles."""
        for step_id, node in self.nodes.items():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    raise OrchestratorValidationError(
                        f"step {step_id!r} depends on missing step {dep!r}"
                    )
        self.topological_order()

    def topological_order(self) -> list[str]:
        """Return step IDs in dependency-first order."""
        order: list[str] = []
        state: dict[str, str] = {}

        def visit(step_id: str, stack: list[str]) -> None:
            current = state.get(step_id)
            if current == "done":
                return
            if current == "visiting":
                cycle = " -> ".join(stack + [step_id])
                raise OrchestratorValidationError(f"cycle in build graph: {cycle}")
            if step_id not in self.nodes:
                raise OrchestratorValidationError(f"unknown step {step_id!r}")
            state[step_id] = "visiting"
            for dep in self.nodes[step_id].depends_on:
                visit(dep, stack + [step_id])
            state[step_id] = "done"
            order.append(step_id)

        for step_id in self.nodes:
            visit(step_id, [])
        return order


__all__ = ["BuildGraphNode", "BuildGraph"]
