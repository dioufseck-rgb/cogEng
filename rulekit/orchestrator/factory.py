"""Generic workspace and candidate-program factories.

These helpers are the non-stub entry point for new policy domains. A
caller supplies policy text, declared determinations, cases, and optional
atom declarations; the Orchestrator creates domain-neutral workspace
objects and a basic build graph/trajectory.
"""
from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rulekit.contract import (
    AndNodeSpec,
    AtLeastNodeSpec,
    AtomRef,
    BinaryArithmeticSpec,
    BooleanAtom,
    CaseInputSchema,
    ComparisonSpec,
    ConditionalNumericSpec,
    ConstantSpec,
    DeterminationProgram,
    DeterminationSpec,
    EvaluationMode,
    MapSpec,
    NamedQuantitySpec,
    NotNodeSpec,
    NumericAtom,
    NumericAtomRef,
    OrNodeSpec,
    ProgramMetadata,
    Provenance,
    UnaryArithmeticSpec,
    VariadicArithmeticSpec,
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
    atom_type: Literal["boolean", "numeric"] = "boolean"
    evaluation_mode: EvaluationMode = EvaluationMode.CHARACTERIZED
    extraction_template: str | None = None
    undetermined_rule: str = ""
    notes: str = ""
    numeric_unit: str | None = None


class BooleanOperator(str, Enum):
    """Boolean operators this factory can emit into the RuleKit engine."""

    AND = "and"
    OR = "or"
    NOT = "not"
    AT_LEAST = "at_least"


class NodeKind(str, Enum):
    """Contract node kinds that can be authored by the generic factory."""

    ATOM_REF = "atom_ref"
    NUMERIC_ATOM_REF = "numeric_atom_ref"
    CONSTANT = "constant"
    AND = "and"
    OR = "or"
    NOT = "not"
    AT_LEAST = "at_least"
    COMPARISON = "comparison"
    UNARY_ARITHMETIC = "unary_arithmetic"
    BINARY_ARITHMETIC = "binary_arithmetic"
    VARIADIC_ARITHMETIC = "variadic_arithmetic"
    CONDITIONAL_NUMERIC = "conditional_numeric"
    NAMED_QUANTITY = "named_quantity"


class NodeDeclaration(BaseModel):
    """Domain-neutral declaration for any DeterminationProgram node.

    The field set intentionally mirrors the contract vocabulary. Only the
    fields relevant to the selected `kind` are consumed.
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str
    kind: NodeKind
    provenance: Provenance = Provenance.STRUCTURAL
    surface_label: str = ""
    source_span: str = ""
    confidence: float | None = None
    latent_type: str | None = None
    atom_id: str | None = None
    operator: str | None = None
    children: list[str] = Field(default_factory=list)
    child: str | None = None
    n: int | None = None
    left: str | None = None
    right: str | None = None
    literal_value: Decimal | None = None
    constant_label: str | None = None
    literal_constant: Decimal | None = None
    condition: str | None = None
    if_true: str | None = None
    if_false: str | None = None


class DeterminationDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    determination_id: str
    description: str
    atom_ids: list[str] = Field(default_factory=list)
    operator: BooleanOperator = BooleanOperator.AND
    n: int | None = None
    source_span: str = ""
    polarity: str = "neutral"
    composition: Literal["derived", "complement"] = "derived"
    root_node: str | None = None
    linked_to: str | None = None


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
    nodes: list[NodeDeclaration] = Field(default_factory=list)
    constants: dict[str, Decimal] = Field(default_factory=dict)
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
    return create_candidate_program(
        program_id=program_id,
        program_name=program_name,
        version=version,
        determinations=determinations,
        atoms=atoms,
    )


def create_candidate_program(
    *,
    program_id: str,
    program_name: str,
    version: str,
    determinations: list[DeterminationDeclaration],
    atoms: list[AtomDeclaration],
    nodes: list[NodeDeclaration] | None = None,
    constants: dict[str, Decimal] | None = None,
) -> DeterminationProgram:
    """Create a candidate DeterminationProgram using the full contract vocabulary.

    If `nodes` is omitted, determinations fall back to the legacy
    determination-to-boolean-atoms shape used by v0.1 seeds. If `nodes` is
    supplied, determinations should provide `root_node` or `linked_to`.
    """
    atom_specs = {
        atom.atom_id: _atom_from_decl(atom)
        for atom in atoms
    }
    node_specs: dict[str, object] = {}
    if nodes:
        node_specs.update(_node_from_decl(node) for node in nodes)
    det_specs = {}
    for det_index, det in enumerate(determinations):
        if det.composition == "complement":
            det_specs[det.determination_id] = DeterminationSpec(
                id=det.determination_id,
                description=det.description,
                polarity=det.polarity,
                source_span=det.source_span,
                composition="complement",
                linked_to=_required_det_field(det, "linked_to"),
            )
            continue
        if det.root_node is not None:
            root_node = det.root_node
        else:
            root_node = _legacy_boolean_root(det, det_index, atom_specs, node_specs)
        det_specs[det.determination_id] = DeterminationSpec(
            id=det.determination_id,
            description=det.description,
            polarity=det.polarity,
            source_span=det.source_span,
            root_node=root_node,
        )
    return DeterminationProgram(
        metadata=ProgramMetadata(name=program_name, version=version),
        constants=constants or {},
        nodes=node_specs,
        map_spec=MapSpec(atoms=atom_specs),
        determinations=det_specs,
        case_input_schema=CaseInputSchema(has_narrative=True),
    )


def _atom_from_decl(atom: AtomDeclaration):
    common = dict(
        id=atom.atom_id,
        statement=atom.statement,
        source_span=atom.source_span or atom.statement,
        evaluation_mode=atom.evaluation_mode,
        extraction_template=atom.extraction_template,
        undetermined_rule=atom.undetermined_rule,
        notes=atom.notes,
    )
    if atom.atom_type == "boolean":
        return BooleanAtom(**common)
    return NumericAtom(numeric_unit=atom.numeric_unit, **common)


def _node_from_decl(node: NodeDeclaration) -> tuple[str, object]:
    common = dict(
        node_id=node.node_id,
        provenance=node.provenance,
        surface_label=node.surface_label,
        source_span=node.source_span,
        confidence=node.confidence,
        latent_type=node.latent_type,
    )
    if node.kind == NodeKind.ATOM_REF:
        return node.node_id, AtomRef(atom_id=_required_node_field(node, "atom_id"), **common)
    if node.kind == NodeKind.NUMERIC_ATOM_REF:
        return node.node_id, NumericAtomRef(atom_id=_required_node_field(node, "atom_id"), **common)
    if node.kind == NodeKind.CONSTANT:
        return node.node_id, ConstantSpec(
            literal_value=node.literal_value,
            constant_label=node.constant_label,
            **common,
        )
    if node.kind == NodeKind.AND:
        return node.node_id, AndNodeSpec(children=node.children, **common)
    if node.kind == NodeKind.OR:
        return node.node_id, OrNodeSpec(children=node.children, **common)
    if node.kind == NodeKind.NOT:
        return node.node_id, NotNodeSpec(child=_required_node_field(node, "child"), **common)
    if node.kind == NodeKind.AT_LEAST:
        if node.n is None:
            raise ValueError(f"node {node.node_id!r}: at_least requires n")
        return node.node_id, AtLeastNodeSpec(n=node.n, children=node.children, **common)
    if node.kind == NodeKind.COMPARISON:
        return node.node_id, ComparisonSpec(
            operator=_required_node_field(node, "operator"),
            left=_required_node_field(node, "left"),
            right=_required_node_field(node, "right"),
            **common,
        )
    if node.kind == NodeKind.UNARY_ARITHMETIC:
        return node.node_id, UnaryArithmeticSpec(
            operator=_required_node_field(node, "operator"),
            literal_constant=node.literal_constant,
            constant_label=node.constant_label,
            child=_required_node_field(node, "child"),
            **common,
        )
    if node.kind == NodeKind.BINARY_ARITHMETIC:
        return node.node_id, BinaryArithmeticSpec(
            operator=_required_node_field(node, "operator"),
            left=_required_node_field(node, "left"),
            right=_required_node_field(node, "right"),
            **common,
        )
    if node.kind == NodeKind.VARIADIC_ARITHMETIC:
        return node.node_id, VariadicArithmeticSpec(
            operator=_required_node_field(node, "operator"),
            children=node.children,
            **common,
        )
    if node.kind == NodeKind.CONDITIONAL_NUMERIC:
        return node.node_id, ConditionalNumericSpec(
            condition=_required_node_field(node, "condition"),
            if_true=_required_node_field(node, "if_true"),
            if_false=_required_node_field(node, "if_false"),
            **common,
        )
    if node.kind == NodeKind.NAMED_QUANTITY:
        return node.node_id, NamedQuantitySpec(
            atom_id=_required_node_field(node, "atom_id"),
            **common,
        )
    raise ValueError(f"unsupported node kind {node.kind!r}")


def _legacy_boolean_root(
    det: DeterminationDeclaration,
    det_index: int,
    atom_specs: dict[str, object],
    nodes: dict[str, object],
) -> str:
    child_ids: list[str] = []
    for atom_index, atom_id in enumerate(det.atom_ids):
        atom = atom_specs[atom_id]
        if atom.atom_type != "boolean":
            raise ValueError(
                f"determination {det.determination_id!r} legacy atom_ids may "
                f"only reference boolean atoms; {atom_id!r} is {atom.atom_type}"
            )
        node_id = f"n_{det_index}_{atom_index}_{_safe_suffix(atom_id)}"
        nodes[node_id] = AtomRef(
            node_id=node_id,
            provenance=Provenance.TRANSCRIBED,
            source_span=atom.source_span,
            atom_id=atom_id,
        )
        child_ids.append(node_id)
    if not child_ids:
        raise ValueError(
            f"determination {det.determination_id!r} must reference at least "
            f"one atom or declare root_node"
        )
    return _make_root_node(det, det_index, child_ids, nodes)


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


def _required_node_field(node: NodeDeclaration, field_name: str) -> Any:
    value = getattr(node, field_name)
    if value is None or value == "":
        raise ValueError(f"node {node.node_id!r}: {node.kind.value} requires {field_name}")
    return value


def _required_det_field(det: DeterminationDeclaration, field_name: str) -> Any:
    value = getattr(det, field_name)
    if value is None or value == "":
        raise ValueError(
            f"determination {det.determination_id!r}: {det.composition} requires {field_name}"
        )
    return value


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
    "NodeKind",
    "NodeDeclaration",
    "DeterminationDeclaration",
    "PolicyWorkspaceSeed",
    "PolicyWorkspaceBundle",
    "create_policy_workspace",
    "create_default_build_graph",
    "create_candidate_program",
    "create_boolean_candidate_program",
]
