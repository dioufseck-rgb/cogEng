from __future__ import annotations

import pytest

from rulekit.orchestrator import BuildGraph, BuildGraphNode, BuildStepSpec


def _spec(step_id: str) -> BuildStepSpec:
    return BuildStepSpec(step_id=step_id, name=step_id)


def test_build_graph_topological_order_dependency_first():
    graph = BuildGraph(
        graph_id="graph_fcba",
        name="FCBA build",
        nodes={
            "load": BuildGraphNode(step_id="load"),
            "decompose": BuildGraphNode(step_id="decompose", depends_on=["load"]),
            "validate": BuildGraphNode(step_id="validate", depends_on=["decompose"]),
        },
        step_specs={
            "load": _spec("load"),
            "decompose": _spec("decompose"),
            "validate": _spec("validate"),
        },
    )

    assert graph.topological_order() == ["load", "decompose", "validate"]


def test_build_graph_rejects_missing_dependency():
    with pytest.raises(ValueError, match="missing step"):
        BuildGraph(
            graph_id="graph_bad",
            name="Bad",
            nodes={
                "decompose": BuildGraphNode(
                    step_id="decompose",
                    depends_on=["load"],
                ),
            },
            step_specs={"decompose": _spec("decompose")},
        )


def test_build_graph_rejects_cycles():
    with pytest.raises(ValueError, match="cycle"):
        BuildGraph(
            graph_id="graph_cycle",
            name="Cycle",
            nodes={
                "a": BuildGraphNode(step_id="a", depends_on=["b"]),
                "b": BuildGraphNode(step_id="b", depends_on=["a"]),
            },
            step_specs={"a": _spec("a"), "b": _spec("b")},
        )

