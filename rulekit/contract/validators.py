"""
RuleKit contract: cross-model program validators.

Validation checks that span multiple sub-models cannot be expressed as
Pydantic model_validators in isolation — they need to see the whole
program. This module collects them.

Use:

    from rulekit.contract.validators import validate_program, ValidationReport
    report = validate_program(program)
    if report.errors:
        for e in report.errors:
            print(e)
        raise ValueError(report.summary())

`validate_program` does NOT raise on errors — it returns a report so
callers can decide whether to fail hard, accumulate, or warn. Producers
that want fail-on-invalid should call `program.validate()` (defined as
a convenience method below).

The checks here correspond 1:1 with the eleven cross-model rules
enumerated in CONTRACT.md. Each check is a separate function so
failures can be located precisely and individual checks can be skipped
or extended without touching the others.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from rulekit.contract.boolean import (
    AndNodeSpec,
    AtLeastNodeSpec,
    AtomRef,
    ComparisonSpec,
    NotNodeSpec,
    OrNodeSpec,
)
from rulekit.contract.numeric import (
    BinaryArithmeticSpec,
    ConditionalNumericSpec,
    ConstantSpec,
    NamedQuantitySpec,
    NumericAtomRef,
    UnaryArithmeticSpec,
    VariadicArithmeticSpec,
)
from rulekit.contract.program import (
    BOOLEAN_NODE_KINDS,
    NUMERIC_NODE_KINDS,
    DeterminationProgram,
)


# ---------------------------------------------------------------------------
# Report shape
# ---------------------------------------------------------------------------

@dataclass
class ValidationReport:
    """The result of running validate_program.

    `errors` are fatal — a program with any error must not be passed
    to the engine. `warnings` are advisory — they indicate something
    unusual but not unsafe (e.g., an orphan node when the producer
    intentionally ships partial fragments).
    """
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if self.ok and not self.warnings:
            return "validation: ok"
        lines = []
        if self.errors:
            lines.append(f"validation: {len(self.errors)} error(s)")
            for e in self.errors:
                lines.append(f"  ERROR: {e}")
        if self.warnings:
            lines.append(f"validation: {len(self.warnings)} warning(s)")
            for w in self.warnings:
                lines.append(f"  WARN:  {w}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_node_id_consistency(program: DeterminationProgram,
                                report: ValidationReport) -> None:
    """Every node's `node_id` field equals its registry key.

    Catches the simple authoring error of constructing
    `nodes={"n1": AtomRef(node_id="n2", ...)}`.
    """
    for key, node in program.nodes.items():
        if node.node_id != key:
            report.errors.append(
                f"node registry: key {key!r} has node with "
                f"node_id={node.node_id!r}; these must be equal"
            )


def _check_atom_id_consistency(program: DeterminationProgram,
                                report: ValidationReport) -> None:
    """Every atom's `id` field equals its registry key in map_spec.atoms."""
    for key, atom in program.map_spec.atoms.items():
        if atom.id != key:
            report.errors.append(
                f"map_spec.atoms: key {key!r} has atom with "
                f"id={atom.id!r}; these must be equal"
            )


def _check_atom_id_uniqueness(program: DeterminationProgram,
                               report: ValidationReport) -> None:
    """Atom IDs and determination IDs share the same namespace.

    Validator #9 from CONTRACT.md: an AtomId may not appear both as an
    atom in map_spec.atoms and as a determination id in determinations.
    """
    atom_ids = set(program.map_spec.atoms.keys())
    det_ids = set(program.determinations.keys())
    collisions = atom_ids & det_ids
    for c in sorted(collisions):
        report.errors.append(
            f"id collision: {c!r} is both an atom and a determination"
        )


def _check_atom_ref_integrity(program: DeterminationProgram,
                               report: ValidationReport) -> None:
    """Every atom_id referenced by a node exists in map_spec.atoms,
    and the referenced atom has the right atom_type for the kind of
    reference (boolean for AtomRef, numeric for NumericAtomRef and
    NamedQuantitySpec).
    """
    atoms = program.map_spec.atoms
    for node in program.nodes.values():
        if isinstance(node, AtomRef):
            if node.atom_id not in atoms:
                report.errors.append(
                    f"node {node.node_id!r}: atom_id {node.atom_id!r} "
                    f"not found in map_spec.atoms"
                )
            elif atoms[node.atom_id].atom_type != "boolean":
                report.errors.append(
                    f"node {node.node_id!r}: AtomRef must reference a "
                    f"boolean atom; {node.atom_id!r} is "
                    f"{atoms[node.atom_id].atom_type}"
                )
        elif isinstance(node, NumericAtomRef):
            if node.atom_id not in atoms:
                report.errors.append(
                    f"node {node.node_id!r}: atom_id {node.atom_id!r} "
                    f"not found in map_spec.atoms"
                )
            elif atoms[node.atom_id].atom_type != "numeric":
                report.errors.append(
                    f"node {node.node_id!r}: NumericAtomRef must "
                    f"reference a numeric atom; {node.atom_id!r} is "
                    f"{atoms[node.atom_id].atom_type}"
                )
        elif isinstance(node, NamedQuantitySpec):
            if node.atom_id not in atoms:
                report.errors.append(
                    f"node {node.node_id!r}: atom_id {node.atom_id!r} "
                    f"not found in map_spec.atoms"
                )
            else:
                atom = atoms[node.atom_id]
                if atom.atom_type != "numeric":
                    report.errors.append(
                        f"node {node.node_id!r}: NamedQuantitySpec must "
                        f"reference a numeric atom; {node.atom_id!r} is "
                        f"{atom.atom_type}"
                    )
                if atom.evaluation_mode.value not in ("computed", "looked_up"):
                    report.errors.append(
                        f"node {node.node_id!r}: NamedQuantitySpec must "
                        f"reference an atom with evaluation_mode in "
                        f"{{computed, looked_up}}; {node.atom_id!r} is "
                        f"{atom.evaluation_mode.value}"
                    )


def _check_node_ref_integrity(program: DeterminationProgram,
                               report: ValidationReport) -> None:
    """Every NodeRef points to a real node, and the referenced node has
    the right value-type for the position.

    Boolean positions: children of And/Or/AtLeast, child of Not,
        condition of ConditionalNumeric, root_node of derived
        determinations.
    Numeric positions: operands of Comparison, child of Unary,
        left/right of Binary, children of Variadic, if_true/if_false
        of ConditionalNumeric.
    """
    nodes = program.nodes

    def _ref_exists(ref: str, where: str) -> bool:
        if ref not in nodes:
            report.errors.append(
                f"{where}: node ref {ref!r} not found in nodes registry"
            )
            return False
        return True

    def _expect_boolean(ref: str, where: str) -> None:
        if not _ref_exists(ref, where):
            return
        kind = nodes[ref].kind
        if kind not in BOOLEAN_NODE_KINDS:
            report.errors.append(
                f"{where}: node ref {ref!r} (kind={kind}) is not "
                f"boolean-valued"
            )

    def _expect_numeric(ref: str, where: str) -> None:
        if not _ref_exists(ref, where):
            return
        kind = nodes[ref].kind
        if kind not in NUMERIC_NODE_KINDS:
            report.errors.append(
                f"{where}: node ref {ref!r} (kind={kind}) is not "
                f"numeric-valued"
            )

    for node in nodes.values():
        nid = node.node_id
        # Boolean composition nodes
        if isinstance(node, (AndNodeSpec, OrNodeSpec, AtLeastNodeSpec)):
            for i, c in enumerate(node.children):
                _expect_boolean(c, f"node {nid!r}.children[{i}]")
        elif isinstance(node, NotNodeSpec):
            _expect_boolean(node.child, f"node {nid!r}.child")
        elif isinstance(node, ComparisonSpec):
            _expect_numeric(node.left, f"node {nid!r}.left")
            _expect_numeric(node.right, f"node {nid!r}.right")
        elif isinstance(node, UnaryArithmeticSpec):
            _expect_numeric(node.child, f"node {nid!r}.child")
        elif isinstance(node, BinaryArithmeticSpec):
            _expect_numeric(node.left, f"node {nid!r}.left")
            _expect_numeric(node.right, f"node {nid!r}.right")
        elif isinstance(node, VariadicArithmeticSpec):
            for i, c in enumerate(node.children):
                _expect_numeric(c, f"node {nid!r}.children[{i}]")
        elif isinstance(node, ConditionalNumericSpec):
            _expect_boolean(node.condition, f"node {nid!r}.condition")
            _expect_numeric(node.if_true, f"node {nid!r}.if_true")
            _expect_numeric(node.if_false, f"node {nid!r}.if_false")
        # AtomRef, NumericAtomRef, ConstantSpec, NamedQuantitySpec have
        # no NodeRefs to check here.

    # Determination root_node refs (boolean)
    for det_id, det in program.determinations.items():
        if det.composition == "derived":
            _expect_boolean(det.root_node, f"determination {det_id!r}.root_node")


def _check_determination_complement_links(program: DeterminationProgram,
                                            report: ValidationReport) -> None:
    """Complement determinations link to determinations that exist.

    Self-reference and chained complements (A links to B, B links to A,
    or A links to B which links to C) are flagged. A complement's
    linked_to must reference a `derived` determination so the
    resolution is unambiguous.
    """
    dets = program.determinations
    for det_id, det in dets.items():
        if det.composition != "complement":
            continue
        if det.linked_to == det_id:
            report.errors.append(
                f"determination {det_id!r}: complement may not link "
                f"to itself"
            )
            continue
        if det.linked_to not in dets:
            report.errors.append(
                f"determination {det_id!r}: linked_to {det.linked_to!r} "
                f"is not a determination in this program"
            )
            continue
        target = dets[det.linked_to]
        if target.composition != "derived":
            report.errors.append(
                f"determination {det_id!r}: complement must link to a "
                f"derived determination; {det.linked_to!r} is "
                f"{target.composition}"
            )


def _check_constant_label_resolution(program: DeterminationProgram,
                                       report: ValidationReport) -> None:
    """Every constant_label used by a node names a key in program.constants."""
    constants = program.constants
    for node in program.nodes.values():
        if isinstance(node, ConstantSpec):
            if node.constant_label is not None and node.constant_label not in constants:
                report.errors.append(
                    f"node {node.node_id!r}: constant_label "
                    f"{node.constant_label!r} not found in program.constants "
                    f"(known: {sorted(constants.keys())})"
                )
        elif isinstance(node, UnaryArithmeticSpec):
            if node.constant_label is not None and node.constant_label not in constants:
                report.errors.append(
                    f"node {node.node_id!r}: constant_label "
                    f"{node.constant_label!r} not found in program.constants "
                    f"(known: {sorted(constants.keys())})"
                )


def _check_dag_acyclic(program: DeterminationProgram,
                       report: ValidationReport) -> None:
    """No cycle exists in the node graph.

    DFS with WHITE/GRAY/BLACK marks. A back-edge to a GRAY node is a
    cycle; the cycle path is reported.
    """
    nodes = program.nodes
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {nid: WHITE for nid in nodes}
    parent: dict[str, str | None] = {nid: None for nid in nodes}

    def _children_of(node) -> list[str]:
        if isinstance(node, (AndNodeSpec, OrNodeSpec, AtLeastNodeSpec)):
            return list(node.children)
        if isinstance(node, NotNodeSpec):
            return [node.child]
        if isinstance(node, ComparisonSpec):
            return [node.left, node.right]
        if isinstance(node, UnaryArithmeticSpec):
            return [node.child]
        if isinstance(node, BinaryArithmeticSpec):
            return [node.left, node.right]
        if isinstance(node, VariadicArithmeticSpec):
            return list(node.children)
        if isinstance(node, ConditionalNumericSpec):
            return [node.condition, node.if_true, node.if_false]
        # leaves: AtomRef, NumericAtomRef, ConstantSpec, NamedQuantitySpec
        return []

    def _dfs(nid: str) -> None:
        if nid not in nodes:
            # Missing ref — node-ref-integrity will report this. Don't
            # walk into it.
            return
        if color[nid] == GRAY:
            # Cycle found — walk parent chain back to nid to produce path.
            path = [nid]
            cur = parent[nid]
            while cur is not None and cur != nid:
                path.append(cur)
                cur = parent.get(cur)
            if cur == nid:
                path.append(nid)
            path.reverse()
            report.errors.append(f"cycle in node graph: {' -> '.join(path)}")
            return
        if color[nid] == BLACK:
            return
        color[nid] = GRAY
        for child_id in _children_of(nodes[nid]):
            if child_id in color:
                # Track parent only if not yet visited in this DFS path,
                # so the cycle reconstruction walks back through the
                # right edges.
                if color[child_id] == WHITE:
                    parent[child_id] = nid
                _dfs(child_id)
        color[nid] = BLACK

    for nid in list(nodes.keys()):
        if color[nid] == WHITE:
            _dfs(nid)


def _check_orphan_nodes(program: DeterminationProgram,
                         report: ValidationReport,
                         orphans_are_errors: bool) -> None:
    """Every node is reachable from at least one determination's root.

    Orphans become warnings or errors depending on the caller's
    setting. CONTRACT.md says errors for 1.0 with an explicit override.
    """
    nodes = program.nodes
    reachable: set[str] = set()

    def _walk(nid: str) -> None:
        if nid in reachable or nid not in nodes:
            return
        reachable.add(nid)
        node = nodes[nid]
        if isinstance(node, (AndNodeSpec, OrNodeSpec, AtLeastNodeSpec)):
            for c in node.children:
                _walk(c)
        elif isinstance(node, NotNodeSpec):
            _walk(node.child)
        elif isinstance(node, ComparisonSpec):
            _walk(node.left); _walk(node.right)
        elif isinstance(node, UnaryArithmeticSpec):
            _walk(node.child)
        elif isinstance(node, BinaryArithmeticSpec):
            _walk(node.left); _walk(node.right)
        elif isinstance(node, VariadicArithmeticSpec):
            for c in node.children:
                _walk(c)
        elif isinstance(node, ConditionalNumericSpec):
            _walk(node.condition); _walk(node.if_true); _walk(node.if_false)

    for det in program.determinations.values():
        if det.composition == "derived" and det.root_node is not None:
            _walk(det.root_node)

    orphans = sorted(set(nodes.keys()) - reachable)
    for o in orphans:
        msg = f"orphan node {o!r}: not reachable from any determination"
        if orphans_are_errors:
            report.errors.append(msg)
        else:
            report.warnings.append(msg)


def _check_test_case_conformance(program: DeterminationProgram,
                                   report: ValidationReport) -> None:
    """Each test case's CaseInput conforms to case_input_schema, and each
    ExpectedOutcome references a determination that exists.
    """
    schema = program.case_input_schema
    det_ids = set(program.determinations.keys())
    for tc in program.test_cases:
        # Narrative presence
        if schema.has_narrative:
            if not tc.input.narrative or not tc.input.narrative.strip():
                report.errors.append(
                    f"test_case {tc.case_id!r}: schema requires narrative "
                    f"but case has none"
                )
        else:
            if tc.input.narrative:
                report.errors.append(
                    f"test_case {tc.case_id!r}: schema forbids narrative "
                    f"but case has one"
                )
        # Structured key membership
        for k in tc.input.structured.keys():
            if k not in schema.structured_fields:
                report.errors.append(
                    f"test_case {tc.case_id!r}: structured field {k!r} not "
                    f"declared in schema.structured_fields "
                    f"(known: {sorted(schema.structured_fields.keys())})"
                )
        # Expected outcomes reference real determinations
        for eo in tc.expected_outcomes:
            if eo.determination_id not in det_ids:
                report.errors.append(
                    f"test_case {tc.case_id!r}: expected outcome references "
                    f"determination {eo.determination_id!r} which is not in "
                    f"this program"
                )
        # Expected load-bearing atoms exist
        if tc.expected_load_bearing_atoms:
            atoms = program.map_spec.atoms
            for aid in tc.expected_load_bearing_atoms:
                if aid not in atoms:
                    report.errors.append(
                        f"test_case {tc.case_id!r}: expected_load_bearing_atoms "
                        f"includes {aid!r} which is not in map_spec.atoms"
                    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def validate_program(program: DeterminationProgram,
                      orphans_are_errors: bool = True) -> ValidationReport:
    """Run all cross-model validators against a program.

    Returns a ValidationReport. Does not raise. Callers that want to
    fail hard should check `report.ok` and raise themselves.

    `orphans_are_errors`: when False, orphan nodes are reported as
    warnings rather than errors. Default True per CONTRACT.md.
    """
    report = ValidationReport()
    _check_node_id_consistency(program, report)
    _check_atom_id_consistency(program, report)
    _check_atom_id_uniqueness(program, report)
    _check_atom_ref_integrity(program, report)
    _check_node_ref_integrity(program, report)
    _check_determination_complement_links(program, report)
    _check_constant_label_resolution(program, report)
    _check_dag_acyclic(program, report)
    _check_orphan_nodes(program, report, orphans_are_errors=orphans_are_errors)
    _check_test_case_conformance(program, report)
    return report


__all__ = [
    "ValidationReport",
    "validate_program",
]
