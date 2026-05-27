"""
RuleKit contract: converter to and from engine objects.

This module is the bridge between the contract (Pydantic models,
JSON-serializable, no engine imports) and the engine (in-process
Python references, Kleene three-valued evaluation). It is the only
file in `rulekit/contract/` that imports from `rulekit/engine/`.

Two directions:

    program_to_engine(program) -> EngineRuntime
        Forward path. Takes a validated DeterminationProgram and
        produces engine objects ready for evaluation. Used by the
        runtime path (load a program, build the engine, run cases
        through it).

    engine_to_program(determinations, ...) -> DeterminationProgram
        Reverse path. Walks an in-memory engine DAG and produces a
        DeterminationProgram. Used by the round-trip test (take a
        hand-built engine fragment, dump to contract, validate,
        evaluate, confirm equivalent results).

Both directions are pure: no I/O, no LLM calls, no Map. The Map and
case-running are responsibilities of separate runtime code that
consumes an EngineRuntime.

Memoization
-----------

The forward path memoizes by node_id. Two contract nodes whose children
include the same NodeRef both resolve to the same engine object — DAG
sharing in the contract becomes shared Python references in the
engine, matching how hand-built fragments share sub-trees.

Atom registration
-----------------

Atoms are registered into the runtime's atoms dict as leaves are
converted. Validators ran at program-validation time, so we know every
referenced atom_id exists in map_spec.atoms; we just copy the metadata
into engine.schema.Atom shape.

Complement determinations
-------------------------

Two passes:
    1. Build engine.Determination for every composition="derived"
       contract determination. Record its tree in the determination
       dict.
    2. For each composition="complement" determination, look up the
       linked determination's tree and wrap it in NotNode. The
       NotNode's source_span is the complement's own (not the
       linked determination's).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from rulekit.engine.boolean import (
    AndNode,
    AtLeastNode,
    Determination,
    Leaf,
    NotNode,
    OrNode,
    Provenance as EngineProvenance,
)
# Import typed-engine nodes. We import them under prefixed names where
# they'd collide with contract names (Constant -> EngineConstant) and
# pass them through otherwise — the engine module uses bare names
# (TimesConstNode, ConditionalNumericNode) that don't collide with
# contract names (TimesConstSpec doesn't exist; UnaryArithmeticSpec
# is its contract analog).
from rulekit.engine.typed import (
    ConditionalNumericNode,
    Constant as EngineConstant,
    ConstDivByNode,
    ConstMinusNode,
    DivByConstNode,
    EqNode,
    GeqNode,
    GtNode,
    LeqNode,
    LtNode,
    MaxNode,
    MinNode,
    MinusConstNode,
    MinusNode,
    MulNode,
    NumericLeaf,
    PlusConstNode,
    PlusNode,
    SumNode,
    TimesConstNode,
)
from rulekit.schema import Atom

from rulekit.contract.atoms import BooleanAtom, NumericAtom
from rulekit.contract.boolean import (
    AndNodeSpec,
    AtLeastNodeSpec,
    AtomRef,
    ComparisonSpec,
    NotNodeSpec,
    OrNodeSpec,
)
from rulekit.contract.cases import TestCase
from rulekit.contract.numeric import (
    BinaryArithmeticSpec,
    ConditionalNumericSpec,
    ConstantSpec,
    NamedQuantitySpec,
    NumericAtomRef,
    UnaryArithmeticSpec,
    VariadicArithmeticSpec,
)
from rulekit.contract.program import DeterminationProgram


# ---------------------------------------------------------------------------
# Runtime container
# ---------------------------------------------------------------------------

@dataclass
class EngineRuntime:
    """The output of program_to_engine.

    Holds engine objects ready for evaluation, plus the contract-level
    test cases (carried through unchanged for the runner) and a
    back-reference to the program (so a narrator or audit tool can
    consult metadata).

    `atoms` is keyed by AtomId (str) and maps to engine.schema.Atom
    instances. The engine's FactBundle uses the same atom_id keys.

    `determinations` is keyed by determination id (AtomId in the
    contract; bare str at the engine boundary) and maps to
    engine.Determination instances ready to call .evaluate(bundle).

    `constants` is the program's named-constant registry, copied
    through. Useful for substrates that want to resolve a label at
    runtime against the same source the engine used at build time.

    `test_cases` is the contract's test suite, unchanged. The runner
    iterates it, calls Map to produce a FactBundle per case, calls
    determination.evaluate(bundle), and compares the result to each
    ExpectedOutcome.
    """
    atoms: dict[str, Atom]
    determinations: dict[str, Determination]
    constants: dict[str, Decimal]
    test_cases: list[TestCase]
    program: DeterminationProgram   # back-reference for downstream consumers


# ---------------------------------------------------------------------------
# Provenance mapping
# ---------------------------------------------------------------------------

def _engine_provenance(contract_provenance) -> EngineProvenance:
    """Map contract Provenance to engine Provenance.

    They use the same string values today, so this is a value
    round-trip. The function exists so future divergence (additional
    contract provenance kinds, e.g., COMPOSED for build-pipeline
    automation marks) can be localized here.
    """
    return EngineProvenance(contract_provenance.value)


# ---------------------------------------------------------------------------
# Forward path: program -> engine
# ---------------------------------------------------------------------------

def program_to_engine(program: DeterminationProgram) -> EngineRuntime:
    """Convert a validated DeterminationProgram to engine objects.

    The program is expected to have passed validate_program already.
    This function does not re-validate; it assumes atom references
    resolve, node refs resolve, and the DAG is acyclic. If those
    invariants are violated, the function will raise a KeyError or
    RecursionError at the offending point.

    Returns an EngineRuntime carrying the atoms dict, the
    determinations dict (with derived and complement determinations
    both resolved), the constants registry, and the test cases.
    """
    atoms: dict[str, Atom] = {}
    memo: dict[str, object] = {}
    # Register every atom up front. This is one O(n) walk rather than
    # registering lazily during node conversion; the cost is identical
    # but it makes the atoms dict a known-complete view as soon as
    # this returns.
    for atom_id, atom_spec in program.map_spec.atoms.items():
        atoms[atom_id] = _atom_spec_to_engine_atom(atom_spec)

    # Pass 1: derived determinations. Build their trees, record them.
    determinations: dict[str, Determination] = {}
    for det_id, det in program.determinations.items():
        if det.composition != "derived":
            continue
        # Validators guarantee root_node is set for derived.
        tree = _convert_node(det.root_node, program, atoms, memo)
        determinations[det_id] = Determination(
            id=det_id,
            description=det.description,
            tree=tree,
            provenance=EngineProvenance.TRANSCRIBED,  # determinations are
                                                      # institution-declared
            polarity=det.polarity,
            source_span=det.source_span,
        )

    # Pass 2: complement determinations. Wrap the linked determination's
    # tree in a NotNode, attributing the wrapper to the complement's own
    # source_span (the complement is the institution's own declaration,
    # even though the underlying tree came from elsewhere).
    for det_id, det in program.determinations.items():
        if det.composition != "complement":
            continue
        # Validators guarantee linked_to is set and resolves to a derived
        # determination that is now in `determinations`.
        linked = determinations[det.linked_to]
        not_tree = NotNode(
            child=linked.tree,
            provenance=EngineProvenance.STRUCTURAL,
            source_span=det.source_span,
        )
        determinations[det_id] = Determination(
            id=det_id,
            description=det.description,
            tree=not_tree,
            provenance=EngineProvenance.STRUCTURAL,
            polarity=det.polarity,
            linked_to=det.linked_to,
            source_span=det.source_span,
        )

    return EngineRuntime(
        atoms=atoms,
        determinations=determinations,
        constants=dict(program.constants),
        test_cases=list(program.test_cases),
        program=program,
    )


def _atom_spec_to_engine_atom(spec) -> Atom:
    """Translate a contract atom (BooleanAtom or NumericAtom) into an
    engine.schema.Atom.

    The engine Atom has fewer fields than the contract AtomSpec:
    extraction_template, undetermined_rule, numeric_unit are not part
    of the engine's runtime evaluation path — they are Map-side and
    documentation. They're preserved on the EngineRuntime via the
    program back-reference.
    """
    notes = spec.notes
    if isinstance(spec, NumericAtom) and spec.numeric_unit:
        # Carry the unit into notes for parity with prior conventions
        # (the old typed-build pipeline encoded computation_kind into
        # notes; numeric_unit is analogously orientation metadata).
        unit_note = f"unit={spec.numeric_unit}"
        notes = f"{notes}; {unit_note}" if notes else unit_note
    return Atom(
        id=spec.id,
        statement=spec.statement,
        source_span=spec.source_span,
        notes=notes,
        atom_type=spec.atom_type,
    )


def _convert_node(node_id: str,
                  program: DeterminationProgram,
                  atoms: dict[str, Atom],
                  memo: dict[str, object]) -> object:
    """Recursively convert a contract node into an engine node.

    Memoization is the load-bearing detail: a NodeRef seen by two
    parents resolves to the same engine object on both lookups. This
    is how DAG sharing in the contract becomes DAG sharing in the
    engine.
    """
    if node_id in memo:
        return memo[node_id]

    spec = program.nodes[node_id]
    result = _dispatch_node(spec, program, atoms, memo)
    memo[node_id] = result
    return result


def _dispatch_node(spec,
                   program: DeterminationProgram,
                   atoms: dict[str, Atom],
                   memo: dict[str, object]) -> object:
    """Dispatch on the spec's runtime type. One branch per kind."""

    # --- Boolean leaves --------------------------------------------------
    if isinstance(spec, AtomRef):
        return Leaf(atom_id=spec.atom_id)

    # --- Boolean composition --------------------------------------------
    if isinstance(spec, AndNodeSpec):
        children = [_convert_node(c, program, atoms, memo) for c in spec.children]
        return AndNode(
            children=children,
            provenance=_engine_provenance(spec.provenance),
            surface_label=spec.surface_label,
            source_span=spec.source_span,
            confidence=spec.confidence,
            latent_type=spec.latent_type,
            node_id=spec.node_id,
        )
    if isinstance(spec, OrNodeSpec):
        children = [_convert_node(c, program, atoms, memo) for c in spec.children]
        return OrNode(
            children=children,
            provenance=_engine_provenance(spec.provenance),
            surface_label=spec.surface_label,
            source_span=spec.source_span,
            confidence=spec.confidence,
            latent_type=spec.latent_type,
            node_id=spec.node_id,
        )
    if isinstance(spec, NotNodeSpec):
        child = _convert_node(spec.child, program, atoms, memo)
        return NotNode(
            child=child,
            provenance=_engine_provenance(spec.provenance),
            source_span=spec.source_span,
            confidence=spec.confidence,
            latent_type=spec.latent_type,
        )
    if isinstance(spec, AtLeastNodeSpec):
        children = [_convert_node(c, program, atoms, memo) for c in spec.children]
        return AtLeastNode(
            n=spec.n,
            children=children,
            provenance=_engine_provenance(spec.provenance),
            surface_label=spec.surface_label,
            source_span=spec.source_span,
            confidence=spec.confidence,
            latent_type=spec.latent_type,
            node_id=spec.node_id,
        )

    # --- Boolean comparison (bridges numeric to Kleene) ------------------
    if isinstance(spec, ComparisonSpec):
        left = _convert_node(spec.left, program, atoms, memo)
        right = _convert_node(spec.right, program, atoms, memo)
        cls = {
            "eq": EqNode, "lt": LtNode, "leq": LeqNode,
            "gt": GtNode, "geq": GeqNode,
        }[spec.operator]
        return cls(
            left=left, right=right,
            surface_label=spec.surface_label,
            source_span=spec.source_span,
            provenance=_engine_provenance(spec.provenance),
        )

    # --- Numeric leaves --------------------------------------------------
    if isinstance(spec, NumericAtomRef):
        return NumericLeaf(atom_id=spec.atom_id)

    if isinstance(spec, NamedQuantitySpec):
        # Treated identically to NumericLeaf at the engine boundary —
        # Map evaluates the atom however its declared evaluation_mode
        # specifies. The "named quantity" distinction is contract-side
        # documentation about what Map's responsibility is.
        return NumericLeaf(atom_id=spec.atom_id)

    if isinstance(spec, ConstantSpec):
        value = _resolve_constant(spec.literal_value, spec.constant_label, program)
        label = spec.constant_label or ""
        return EngineConstant(value=value, label=label)

    # --- Unary arithmetic (child OP constant) ---------------------------
    if isinstance(spec, UnaryArithmeticSpec):
        child = _convert_node(spec.child, program, atoms, memo)
        constant = _resolve_constant(spec.literal_constant, spec.constant_label, program)
        common = dict(
            surface_label=spec.surface_label,
            source_span=spec.source_span,
            provenance=_engine_provenance(spec.provenance),
        )
        if spec.operator == "times_const":
            return TimesConstNode(child=child, constant=constant, **common)
        if spec.operator == "plus_const":
            return PlusConstNode(child=child, constant=constant, **common)
        if spec.operator == "minus_const":
            return MinusConstNode(child=child, constant=constant, **common)
        if spec.operator == "const_minus":
            return ConstMinusNode(constant=constant, child=child, **common)
        if spec.operator == "div_by_const":
            return DivByConstNode(child=child, constant=constant, **common)
        if spec.operator == "const_div_by":
            return ConstDivByNode(constant=constant, child=child, **common)
        raise ValueError(
            f"Unknown unary_arithmetic operator: {spec.operator!r}"
        )

    # --- Binary arithmetic (both operands case-bound) -------------------
    if isinstance(spec, BinaryArithmeticSpec):
        left = _convert_node(spec.left, program, atoms, memo)
        right = _convert_node(spec.right, program, atoms, memo)
        common = dict(
            surface_label=spec.surface_label,
            source_span=spec.source_span,
            provenance=_engine_provenance(spec.provenance),
        )
        cls = {"plus": PlusNode, "minus": MinusNode, "mul": MulNode}[spec.operator]
        return cls(left=left, right=right, **common)

    # --- Variadic arithmetic (sum/max/min over N children) --------------
    if isinstance(spec, VariadicArithmeticSpec):
        children = [_convert_node(c, program, atoms, memo) for c in spec.children]
        common = dict(
            surface_label=spec.surface_label,
            source_span=spec.source_span,
            provenance=_engine_provenance(spec.provenance),
        )
        cls = {"sum": SumNode, "max": MaxNode, "min": MinNode}[spec.operator]
        return cls(children=children, **common)

    # --- Conditional numeric --------------------------------------------
    if isinstance(spec, ConditionalNumericSpec):
        condition = _convert_node(spec.condition, program, atoms, memo)
        if_true = _convert_node(spec.if_true, program, atoms, memo)
        if_false = _convert_node(spec.if_false, program, atoms, memo)
        return ConditionalNumericNode(
            condition=condition,
            if_true=if_true,
            if_false=if_false,
            surface_label=spec.surface_label,
            source_span=spec.source_span,
            provenance=_engine_provenance(spec.provenance),
        )

    raise TypeError(f"Unknown contract node spec type: {type(spec).__name__}")


def _resolve_constant(literal: Optional[Decimal],
                      label: Optional[str],
                      program: DeterminationProgram) -> Decimal:
    """Resolve a constant: either a literal Decimal or a label lookup
    in the program's constants registry.

    Validators ensure exactly one is set and that labels resolve. We
    re-check defensively because this function is also called from
    the round-trip test where partial programs may pass through.
    """
    if literal is not None:
        return literal
    if label is None:
        raise ValueError(
            "constant has neither literal_value nor constant_label set"
        )
    if label not in program.constants:
        raise KeyError(
            f"constant_label {label!r} not found in program.constants "
            f"(known: {sorted(program.constants.keys())})"
        )
    return program.constants[label]


# ---------------------------------------------------------------------------
# Reverse path: engine -> program
# ---------------------------------------------------------------------------

def engine_to_program(
    determinations: list[Determination],
    *,
    program_name: str,
    program_version: str = "0.1",
    constants: Optional[dict[str, Decimal]] = None,
    atom_extras: Optional[dict[str, dict]] = None,
) -> DeterminationProgram:
    """Dump a set of in-memory engine Determinations to a contract
    DeterminationProgram.

    Used by the round-trip test: a hand-built engine fragment (like
    the FCBA refined 71-node DAG) becomes a contract program, which
    can then be validated, serialized, and run back through
    program_to_engine.

    NodeIds are generated as `n0`, `n1`, ... in depth-first traversal
    order. AtomIds are taken from the engine atoms themselves (the
    engine.Leaf and NumericLeaf nodes carry the original atom_id).
    Two engine nodes that are the same Python object share a NodeId
    via id-memoization, preserving the engine's DAG sharing in the
    contract.

    `constants`: name -> Decimal. The contract requires constants to
    have human-readable labels. If a Constant in the engine has a
    label, it's used as the constants key; if it has no label, a
    literal_value is emitted instead and no entry is added to
    constants.

    `atom_extras`: optional dict keyed by atom_id; values are dicts
    of extra fields (evaluation_mode, extraction_template,
    numeric_unit, undetermined_rule, notes) to attach to the atom
    spec. When omitted, atoms default to evaluation_mode="characterized"
    (the common case for narrative-driven Map). Used by tests that
    want to pin specific atom configurations without re-authoring
    the engine fragment.
    """
    from rulekit.contract.atoms import BooleanAtom, NumericAtom
    from rulekit.contract.base import EvaluationMode, Provenance
    from rulekit.contract.boolean import (
        AndNodeSpec, AtLeastNodeSpec, AtomRef, ComparisonSpec,
        NotNodeSpec, OrNodeSpec,
    )
    from rulekit.contract.numeric import (
        BinaryArithmeticSpec, ConditionalNumericSpec, ConstantSpec,
        NumericAtomRef, UnaryArithmeticSpec, VariadicArithmeticSpec,
    )
    from rulekit.contract.cases import CaseInputSchema
    from rulekit.contract.map import MapSpec
    from rulekit.contract.program import (
        DeterminationProgram, DeterminationSpec, ProgramMetadata,
    )

    if constants is None:
        constants = {}
    if atom_extras is None:
        atom_extras = {}

    # Memoize by Python object id so shared subtrees produce a single
    # NodeId. The engine's DAG is realized via shared references; we
    # must preserve that sharing in the contract.
    node_id_by_obj: dict[int, str] = {}
    nodes_dict: dict[str, object] = {}     # NodeId -> contract spec
    atoms_dict: dict[str, object] = {}     # AtomId -> contract atom
    counter = [0]                          # mutable so closures can bump it

    def _next_node_id() -> str:
        nid = f"n{counter[0]}"
        counter[0] += 1
        return nid

    def _register_atom(atom_id: str, atom_type: str) -> None:
        if atom_id in atoms_dict:
            return
        extra = atom_extras.get(atom_id, {})
        mode_str = extra.get("evaluation_mode", "characterized")
        common_kwargs = dict(
            id=atom_id,
            statement=extra.get("statement", f"{atom_id}"),
            source_span=extra.get("source_span", ""),
            evaluation_mode=EvaluationMode(mode_str),
            extraction_template=extra.get("extraction_template"),
            undetermined_rule=extra.get("undetermined_rule", ""),
            notes=extra.get("notes", ""),
        )
        if atom_type == "boolean":
            atoms_dict[atom_id] = BooleanAtom(**common_kwargs)
        else:
            atoms_dict[atom_id] = NumericAtom(
                numeric_unit=extra.get("numeric_unit"),
                **common_kwargs,
            )

    def _emit(engine_node) -> str:
        """Convert one engine node, return its NodeId.

        Recurses into children, returning the assigned NodeIds for use
        in the parent's children list / left+right / etc.
        """
        oid = id(engine_node)
        if oid in node_id_by_obj:
            return node_id_by_obj[oid]
        nid = _next_node_id()
        node_id_by_obj[oid] = nid

        cls_name = type(engine_node).__name__
        # Provenance: engine nodes carry Provenance enum; map back to
        # the contract enum (same string values).
        prov = (Provenance(engine_node.provenance.value)
                if hasattr(engine_node, "provenance") else Provenance.STRUCTURAL)
        common = dict(
            node_id=nid,
            provenance=prov,
            surface_label=getattr(engine_node, "surface_label", "") or "",
            source_span=getattr(engine_node, "source_span", "") or "",
            confidence=getattr(engine_node, "confidence", None),
            latent_type=getattr(engine_node, "latent_type", None),
        )

        if cls_name == "Leaf":
            _register_atom(engine_node.atom_id, "boolean")
            nodes_dict[nid] = AtomRef(atom_id=engine_node.atom_id, **common)
        elif cls_name == "AndNode":
            child_ids = [_emit(c) for c in engine_node.children]
            nodes_dict[nid] = AndNodeSpec(children=child_ids, **common)
        elif cls_name == "OrNode":
            child_ids = [_emit(c) for c in engine_node.children]
            nodes_dict[nid] = OrNodeSpec(children=child_ids, **common)
        elif cls_name == "NotNode":
            child_id = _emit(engine_node.child)
            nodes_dict[nid] = NotNodeSpec(child=child_id, **common)
        elif cls_name == "AtLeastNode":
            child_ids = [_emit(c) for c in engine_node.children]
            nodes_dict[nid] = AtLeastNodeSpec(
                n=engine_node.n, children=child_ids, **common
            )
        elif cls_name in ("EqNode", "LtNode", "LeqNode", "GtNode", "GeqNode"):
            op = {"EqNode": "eq", "LtNode": "lt", "LeqNode": "leq",
                  "GtNode": "gt", "GeqNode": "geq"}[cls_name]
            left_id = _emit(engine_node.left)
            right_id = _emit(engine_node.right)
            nodes_dict[nid] = ComparisonSpec(
                operator=op, left=left_id, right=right_id, **common
            )
        elif cls_name == "NumericLeaf":
            _register_atom(engine_node.atom_id, "numeric")
            nodes_dict[nid] = NumericAtomRef(atom_id=engine_node.atom_id, **common)
        elif cls_name == "Constant":
            label = engine_node.label or None
            if label:
                # Record the constant in the constants registry. If the
                # caller already supplied a value, prefer it (the caller
                # knows the canonical Decimal); otherwise use the engine
                # node's value.
                if label not in constants:
                    constants[label] = engine_node.value
                nodes_dict[nid] = ConstantSpec(
                    constant_label=label, **common,
                )
            else:
                nodes_dict[nid] = ConstantSpec(
                    literal_value=engine_node.value, **common,
                )
        elif cls_name in ("TimesConstNode", "PlusConstNode",
                          "MinusConstNode", "DivByConstNode"):
            op = {
                "TimesConstNode": "times_const",
                "PlusConstNode": "plus_const",
                "MinusConstNode": "minus_const",
                "DivByConstNode": "div_by_const",
            }[cls_name]
            child_id = _emit(engine_node.child)
            nodes_dict[nid] = UnaryArithmeticSpec(
                operator=op,
                literal_constant=engine_node.constant,
                child=child_id, **common,
            )
        elif cls_name in ("ConstMinusNode", "ConstDivByNode"):
            op = {"ConstMinusNode": "const_minus",
                  "ConstDivByNode": "const_div_by"}[cls_name]
            child_id = _emit(engine_node.child)
            nodes_dict[nid] = UnaryArithmeticSpec(
                operator=op,
                literal_constant=engine_node.constant,
                child=child_id, **common,
            )
        elif cls_name in ("PlusNode", "MinusNode", "MulNode"):
            op = {"PlusNode": "plus", "MinusNode": "minus",
                  "MulNode": "mul"}[cls_name]
            left_id = _emit(engine_node.left)
            right_id = _emit(engine_node.right)
            nodes_dict[nid] = BinaryArithmeticSpec(
                operator=op, left=left_id, right=right_id, **common,
            )
        elif cls_name in ("SumNode", "MaxNode", "MinNode"):
            op = {"SumNode": "sum", "MaxNode": "max", "MinNode": "min"}[cls_name]
            child_ids = [_emit(c) for c in engine_node.children]
            nodes_dict[nid] = VariadicArithmeticSpec(
                operator=op, children=child_ids, **common,
            )
        elif cls_name == "ConditionalNumericNode":
            cond_id = _emit(engine_node.condition)
            true_id = _emit(engine_node.if_true)
            false_id = _emit(engine_node.if_false)
            nodes_dict[nid] = ConditionalNumericSpec(
                condition=cond_id, if_true=true_id, if_false=false_id, **common,
            )
        else:
            raise TypeError(
                f"engine_to_program: don't know how to emit engine node "
                f"class {cls_name!r}"
            )
        return nid

    # Emit each determination's tree, recording the root NodeId.
    determinations_dict: dict[str, object] = {}
    DeterminationSpec_ = DeterminationSpec
    for det in determinations:
        if det.linked_to is not None:
            # Skip complements in pass 1; resolve after derived are emitted.
            continue
        root_id = _emit(det.tree)
        determinations_dict[det.id] = DeterminationSpec_(
            id=det.id,
            description=det.description,
            polarity=(det.polarity or "neutral"),
            source_span=det.source_span,
            composition="derived",
            root_node=root_id,
        )

    # Pass 2: complement determinations.
    for det in determinations:
        if det.linked_to is None:
            continue
        if det.id in determinations_dict:
            continue
        determinations_dict[det.id] = DeterminationSpec_(
            id=det.id,
            description=det.description,
            polarity=(det.polarity or "neutral"),
            source_span=det.source_span,
            composition="complement",
            linked_to=det.linked_to,
        )

    program = DeterminationProgram(
        metadata=ProgramMetadata(
            name=program_name, version=program_version,
        ),
        constants=constants,
        nodes=nodes_dict,
        map_spec=MapSpec(atoms=atoms_dict),
        determinations=determinations_dict,
        case_input_schema=CaseInputSchema(has_narrative=True),
        test_cases=[],
    )
    return program


__all__ = [
    "EngineRuntime",
    "program_to_engine",
    "engine_to_program",
]
