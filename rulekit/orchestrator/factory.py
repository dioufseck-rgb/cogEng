"""Generic workspace and candidate-program factories.

These helpers are the non-stub entry point for new policy domains. A
caller supplies policy text, declared determinations, cases, and optional
atom declarations; the Orchestrator creates domain-neutral workspace
objects and a basic build graph/trajectory.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rulekit.contract import (
    AndNodeSpec,
    AtLeastNodeSpec,
    AtomRef,
    BooleanAtom,
    CaseInputSchema,
    DeterminationProgram,
    DeterminationSpec,
    EvaluationMode,
    MapSpec,
    NotNodeSpec,
    OrNodeSpec,
    ProgramMetadata,
    Provenance,
)
from rulekit.orchestrator.cases import CaseExample, CaseSuite, ExpectedOutcome
from rulekit.orchestrator.graph import BuildGraph, BuildGraphNode
from rulekit.orchestrator.ids import new_id
from rulekit.orchestrator.step import BuildStepSpec, DialogueCapability, StepKind
from rulekit.orchestrator.trajectory import Trajectory, TrajectoryBranch
from rulekit.orchestrator.workspace import PolicySource, PolicySourceKind, Workspace


class CaseDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str | None = None
    title: str
    narrative: str
    expected_outcomes: dict[str, str] = Field(default_factory=dict)
    structured_fields: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AtomDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atom_id: str
    statement: str
    source_span: str = ""
    atom_type: Literal["boolean"] = "boolean"
    evaluation_mode: EvaluationMode = EvaluationMode.CHARACTERIZED
    notes: str = ""


class BooleanOperator(str, Enum):
    """Boolean operators this factory can emit into the RuleKit engine."""

    AND = "and"
    OR = "or"
    NOT = "not"
    AT_LEAST = "at_least"


class DeterminationDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    determination_id: str
    description: str
    atom_ids: list[str] = Field(default_factory=list)
    operator: BooleanOperator = BooleanOperator.AND
    n: int | None = None
    source_span: str = ""
    polarity: str = "neutral"


class PolicyWorkspaceSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_name: str
    policy_title: str
    policy_text: str
    policy_id: str | None = None
    version_label: str | None = None
    determinations: list[DeterminationDeclaration]
    cases: list[CaseDeclaration] = Field(default_factory=list)
    atoms: list[AtomDeclaration] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyWorkspaceBundle(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    workspace: Workspace
    graph: BuildGraph
    trajectory: Trajectory


def create_policy_workspace(seed: PolicyWorkspaceSeed) -> PolicyWorkspaceBundle:
    """Create a domain-neutral workspace, graph, and trajectory."""
    workspace_id = new_id("ws")
    policy_id = seed.policy_id or new_id("pol")
    suite_id = new_id("suite")
    trajectory_id = new_id("traj")
    branch_id = "br_main"

    policy = PolicySource(
        policy_id=policy_id,
        title=seed.policy_title,
        kind=PolicySourceKind.TEXT,
        version_label=seed.version_label,
        content=seed.policy_text,
        metadata=seed.metadata,
    )
    case_suite = CaseSuite(
        suite_id=suite_id,
        name=f"{seed.policy_title} cases",
        cases={
            (case.case_id or new_id("case")): _case_from_decl(case)
            for case in seed.cases
        },
    )
    trajectory = Trajectory(
        trajectory_id=trajectory_id,
        workspace_id=workspace_id,
        branches={branch_id: TrajectoryBranch(branch_id=branch_id)},
        active_branch_id=branch_id,
    )
    workspace = Workspace(
        workspace_id=workspace_id,
        name=seed.workspace_name,
        policies={policy.policy_id: policy},
        case_suites={case_suite.suite_id: case_suite},
        trajectories={trajectory.trajectory_id: trajectory},
        metadata=seed.metadata,
    )
    return PolicyWorkspaceBundle(
        workspace=workspace,
        graph=create_default_build_graph(),
        trajectory=trajectory,
    )


def create_default_build_graph() -> BuildGraph:
    """Return the standard v0.1 three-step authoring topology."""
    load = BuildStepSpec(step_id="load_policy", name="Load policy")
    decompose = BuildStepSpec(
        step_id="decompose_policy",
        name="Decompose policy",
        kind=StepKind.STOCHASTIC,
        default_k=2,
        dialogue_capability=DialogueCapability.OPTIONAL,
        max_dialogue_turns=4,
    )
    validate = BuildStepSpec(step_id="validate_candidate", name="Validate candidate")
    return BuildGraph(
        graph_id="graph_default_policy_build",
        name="Default policy build graph",
        nodes={
            "load_policy": BuildGraphNode(step_id="load_policy"),
            "decompose_policy": BuildGraphNode(
                step_id="decompose_policy",
                depends_on=["load_policy"],
            ),
            "validate_candidate": BuildGraphNode(
                step_id="validate_candidate",
                depends_on=["decompose_policy"],
            ),
        },
        step_specs={
            "load_policy": load,
            "decompose_policy": decompose,
            "validate_candidate": validate,
        },
    )


def create_boolean_candidate_program(
    *,
    program_id: str,
    program_name: str,
    version: str,
    determinations: list[DeterminationDeclaration],
    atoms: list[AtomDeclaration],
) -> DeterminationProgram:
    """Create a simple Boolean candidate program.

    This is not a substitute for the decomposer. It is a useful import or
    hand-authoring bridge when the caller already knows the atom set and
    determination-to-atom shape. Operators intentionally mirror the
    Boolean engine/contract vocabulary: and, or, not, at_least.
    """
    atom_specs = {
        atom.atom_id: BooleanAtom(
            id=atom.atom_id,
            statement=atom.statement,
            source_span=atom.source_span or atom.statement,
            evaluation_mode=atom.evaluation_mode,
            notes=atom.notes,
        )
        for atom in atoms
    }
    nodes = {}
    det_specs = {}
    for det_index, det in enumerate(determinations):
        child_ids: list[str] = []
        for atom_index, atom_id in enumerate(det.atom_ids):
            node_id = f"n_{det_index}_{atom_index}_{_safe_suffix(atom_id)}"
            nodes[node_id] = AtomRef(
                node_id=node_id,
                provenance=Provenance.TRANSCRIBED,
                source_span=atom_specs[atom_id].source_span,
                atom_id=atom_id,
            )
            child_ids.append(node_id)
        if not child_ids:
            raise ValueError(
                f"determination {det.determination_id!r} must reference at least one atom"
            )
        root_node = _make_root_node(det, det_index, child_ids, nodes)
        det_specs[det.determination_id] = DeterminationSpec(
            id=det.determination_id,
            description=det.description,
            polarity=det.polarity,
            source_span=det.source_span,
            root_node=root_node,
        )
    return DeterminationProgram(
        metadata=ProgramMetadata(name=program_name, version=version),
        nodes=nodes,
        map_spec=MapSpec(atoms=atom_specs),
        determinations=det_specs,
        case_input_schema=CaseInputSchema(has_narrative=True),
    )


def _make_root_node(
    det: DeterminationDeclaration,
    det_index: int,
    child_ids: list[str],
    nodes: dict[str, object],
) -> str:
    if len(child_ids) == 1 and det.operator != BooleanOperator.NOT:
        return child_ids[0]

    operator = det.operator
    root_node = f"n_{det_index}_root"
    common = dict(
        node_id=root_node,
        provenance=Provenance.STRUCTURAL,
        children=child_ids,
        surface_label=f"{det.description} requirements",
        source_span=det.source_span,
    )
    if operator == BooleanOperator.AND:
        nodes[root_node] = AndNodeSpec(**common)
    elif operator == BooleanOperator.OR:
        nodes[root_node] = OrNodeSpec(**common)
    elif operator == BooleanOperator.NOT:
        if len(child_ids) != 1:
            raise ValueError(
                f"determination {det.determination_id!r} uses not but references "
                f"{len(child_ids)} atoms; not requires exactly one child"
            )
        nodes[root_node] = NotNodeSpec(
            node_id=root_node,
            provenance=Provenance.STRUCTURAL,
            child=child_ids[0],
            surface_label=f"{det.description} negation",
            source_span=det.source_span,
        )
    elif operator == BooleanOperator.AT_LEAST:
        if det.n is None:
            raise ValueError(
                f"determination {det.determination_id!r} uses at_least but n is unset"
            )
        nodes[root_node] = AtLeastNodeSpec(n=det.n, **common)
    else:
        raise ValueError(
            f"determination {det.determination_id!r} has unsupported operator "
            f"{det.operator.value!r}"
        )
    return root_node


def _case_from_decl(decl: CaseDeclaration) -> CaseExample:
    case_id = decl.case_id or new_id("case")
    return CaseExample(
        case_id=case_id,
        title=decl.title,
        narrative=decl.narrative,
        structured_fields=decl.structured_fields,
        expected_outcomes=[
            ExpectedOutcome(determination_id=det_id, expected_value=value)
            for det_id, value in decl.expected_outcomes.items()
        ],
        metadata=decl.metadata,
    )


def _safe_suffix(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in value)[-24:]


__all__ = [
    "CaseDeclaration",
    "AtomDeclaration",
    "BooleanOperator",
    "DeterminationDeclaration",
    "PolicyWorkspaceSeed",
    "PolicyWorkspaceBundle",
    "create_policy_workspace",
    "create_default_build_graph",
    "create_boolean_candidate_program",
]
