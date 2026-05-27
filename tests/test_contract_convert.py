"""
Tests for rulekit.contract.convert.

Three things to verify:

1. Forward path (program_to_engine) produces engine objects that
   evaluate to expected Kleene values against hand-built FactBundles.

2. Reverse path (engine_to_program) dumps a hand-built engine fragment
   into a contract program that re-validates successfully.

3. Round-trip equivalence: hand-built engine fragment -> contract ->
   engine -> evaluate; compare against hand-built engine -> evaluate
   on the same FactBundle. Same answer.

These tests cover Boolean, typed-numeric, conditional-numeric, and
DAG-sharing scenarios. The FCBA-refined round-trip (the 71-node DAG
from bin/test_fcba_composite_refined.py) is a separate, larger test.
"""
from __future__ import annotations

import sys
from decimal import Decimal

sys.path.insert(0, ".")

from rulekit.contract import (
    AndNodeSpec,
    AtomRef,
    BooleanAtom,
    CaseInputSchema,
    ComparisonSpec,
    ConditionalNumericSpec,
    ConstantSpec,
    DeterminationProgram,
    DeterminationSpec,
    EvaluationMode,
    MapSpec,
    NotNodeSpec,
    NumericAtom,
    NumericAtomRef,
    OrNodeSpec,
    ProgramMetadata,
    Provenance,
    UnaryArithmeticSpec,
    validate_program,
)
from rulekit.contract.convert import (
    EngineRuntime,
    engine_to_program,
    program_to_engine,
)

from rulekit.engine import (
    AndNode,
    FactBundle,
    Kleene,
    Leaf,
    NotNode,
    OrNode,
)
from rulekit.engine.typed import (
    Constant,
    LeqNode,
    NumericLeaf,
    NumericValue,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bundle(values):
    """Quick FactBundle constructor.

    `values` maps atom_id -> either Kleene or NumericValue or a number-like.
    Strings are converted to Kleene; numbers to NumericValue.
    """
    out = {}
    for k, v in values.items():
        if isinstance(v, (Kleene, NumericValue)):
            out[k] = v
        elif isinstance(v, str):
            out[k] = Kleene(v)
        elif isinstance(v, (int, float, Decimal)):
            out[k] = NumericValue.of(v)
        else:
            raise TypeError(f"unknown fact value type: {type(v).__name__}")
    return FactBundle(values=out)


# ---------------------------------------------------------------------------
# Forward path tests
# ---------------------------------------------------------------------------

def test_forward_boolean_minimal():
    """A program with two boolean atoms and an AND determination
    evaluates correctly under all three Kleene branches.
    """
    atoms = {
        "x.a": BooleanAtom(id="x.a", statement="A", source_span="S",
                            evaluation_mode=EvaluationMode.CHARACTERIZED),
        "x.b": BooleanAtom(id="x.b", statement="B", source_span="S",
                            evaluation_mode=EvaluationMode.CHARACTERIZED),
    }
    nodes = {
        "a": AtomRef(node_id="a", provenance=Provenance.TRANSCRIBED,
                      source_span="S", atom_id="x.a"),
        "b": AtomRef(node_id="b", provenance=Provenance.TRANSCRIBED,
                      source_span="S", atom_id="x.b"),
        "both": AndNodeSpec(node_id="both", provenance=Provenance.STRUCTURAL,
                              children=["a", "b"]),
    }
    dets = {
        "x.D1": DeterminationSpec(
            id="x.D1", description="Both hold.", source_span="S",
            composition="derived", root_node="both",
        ),
    }
    program = DeterminationProgram(
        metadata=ProgramMetadata(name="X", version="0.1"),
        nodes=nodes, map_spec=MapSpec(atoms=atoms),
        determinations=dets,
        case_input_schema=CaseInputSchema(has_narrative=True),
    )
    assert validate_program(program).ok

    rt = program_to_engine(program)
    assert isinstance(rt, EngineRuntime)
    assert "x.a" in rt.atoms
    assert "x.b" in rt.atoms
    assert "x.D1" in rt.determinations

    det = rt.determinations["x.D1"]

    # Both TRUE -> TRUE
    res, _ = det.evaluate(_bundle({"x.a": "true", "x.b": "true"}))
    assert res == Kleene.TRUE

    # Either FALSE -> FALSE
    res, _ = det.evaluate(_bundle({"x.a": "false", "x.b": "true"}))
    assert res == Kleene.FALSE

    # One TRUE, one UND -> UND
    res, _ = det.evaluate(_bundle({"x.a": "true", "x.b": "undetermined"}))
    assert res == Kleene.UNDETERMINED

    print("test_forward_boolean_minimal: OK")


def test_forward_complement():
    """A composition=complement determination evaluates as NOT of the
    linked determination."""
    atoms = {
        "x.a": BooleanAtom(id="x.a", statement="A", source_span="S",
                            evaluation_mode=EvaluationMode.CHARACTERIZED),
    }
    nodes = {
        "a": AtomRef(node_id="a", provenance=Provenance.TRANSCRIBED,
                      source_span="S", atom_id="x.a"),
    }
    dets = {
        "x.D1": DeterminationSpec(id="x.D1", description="A.",
                                   source_span="S", composition="derived",
                                   root_node="a"),
        "x.D2": DeterminationSpec(id="x.D2", description="Not A.",
                                   source_span="S", composition="complement",
                                   linked_to="x.D1"),
    }
    program = DeterminationProgram(
        metadata=ProgramMetadata(name="X", version="0.1"),
        nodes=nodes, map_spec=MapSpec(atoms=atoms), determinations=dets,
        case_input_schema=CaseInputSchema(has_narrative=True),
    )
    assert validate_program(program).ok

    rt = program_to_engine(program)
    d1 = rt.determinations["x.D1"]
    d2 = rt.determinations["x.D2"]

    res1, _ = d1.evaluate(_bundle({"x.a": "true"}))
    res2, _ = d2.evaluate(_bundle({"x.a": "true"}))
    assert res1 == Kleene.TRUE
    assert res2 == Kleene.FALSE

    res1, _ = d1.evaluate(_bundle({"x.a": "undetermined"}))
    res2, _ = d2.evaluate(_bundle({"x.a": "undetermined"}))
    assert res1 == Kleene.UNDETERMINED
    assert res2 == Kleene.UNDETERMINED

    print("test_forward_complement: OK")


def test_forward_typed_comparison_with_constant_label():
    """A leq comparison against a labeled constant. Exercises the
    constants registry resolution and the comparison-to-LeqNode mapping.

    Mirrors the FCBA timing pattern: days_between_notice <= 60.
    """
    atoms = {
        "fcba.days": NumericAtom(
            id="fcba.days", statement="Days.", source_span="S",
            evaluation_mode=EvaluationMode.CHARACTERIZED, numeric_unit="days",
        ),
    }
    nodes = {
        "days": NumericAtomRef(node_id="days", provenance=Provenance.TRANSCRIBED,
                                 source_span="S", atom_id="fcba.days"),
        "limit": ConstantSpec(node_id="limit", provenance=Provenance.TRANSCRIBED,
                               source_span="S", constant_label="sixty_day_limit"),
        "timely": ComparisonSpec(node_id="timely", provenance=Provenance.TRANSCRIBED,
                                  source_span="S", operator="leq",
                                  left="days", right="limit"),
    }
    dets = {
        "fcba.D1": DeterminationSpec(id="fcba.D1", description="Timely.",
                                      source_span="S", composition="derived",
                                      root_node="timely"),
    }
    program = DeterminationProgram(
        metadata=ProgramMetadata(name="FCBA timing", version="0.1"),
        constants={"sixty_day_limit": Decimal("60")},
        nodes=nodes, map_spec=MapSpec(atoms=atoms), determinations=dets,
        case_input_schema=CaseInputSchema(has_narrative=True),
    )
    assert validate_program(program).ok

    rt = program_to_engine(program)
    det = rt.determinations["fcba.D1"]

    # 30 days -> TRUE
    res, _ = det.evaluate(_bundle({"fcba.days": 30}))
    assert res == Kleene.TRUE

    # 60 days -> TRUE (leq inclusive)
    res, _ = det.evaluate(_bundle({"fcba.days": 60}))
    assert res == Kleene.TRUE

    # 75 days -> FALSE
    res, _ = det.evaluate(_bundle({"fcba.days": 75}))
    assert res == Kleene.FALSE

    # UND days -> UND
    res, _ = det.evaluate(_bundle({"fcba.days": NumericValue.undetermined()}))
    assert res == Kleene.UNDETERMINED

    print("test_forward_typed_comparison_with_constant_label: OK")


def test_forward_dag_sharing():
    """A node referenced from two parents resolves to the same engine
    object on both lookups (memoization preserves sharing).
    """
    atoms = {
        "x.a": BooleanAtom(id="x.a", statement="A.", source_span="S",
                            evaluation_mode=EvaluationMode.CHARACTERIZED),
        "x.b": BooleanAtom(id="x.b", statement="B.", source_span="S",
                            evaluation_mode=EvaluationMode.CHARACTERIZED),
        "x.c": BooleanAtom(id="x.c", statement="C.", source_span="S",
                            evaluation_mode=EvaluationMode.CHARACTERIZED),
    }
    nodes = {
        "a": AtomRef(node_id="a", provenance=Provenance.TRANSCRIBED,
                      source_span="S", atom_id="x.a"),
        "b": AtomRef(node_id="b", provenance=Provenance.TRANSCRIBED,
                      source_span="S", atom_id="x.b"),
        "c": AtomRef(node_id="c", provenance=Provenance.TRANSCRIBED,
                      source_span="S", atom_id="x.c"),
        # shared sub-tree: a AND b
        "shared": AndNodeSpec(node_id="shared", provenance=Provenance.STRUCTURAL,
                                children=["a", "b"]),
        # Two parents, both referencing 'shared'
        "p1": AndNodeSpec(node_id="p1", provenance=Provenance.STRUCTURAL,
                            children=["shared", "c"]),
        "p2": OrNodeSpec(node_id="p2", provenance=Provenance.STRUCTURAL,
                           children=["shared", "c"]),
    }
    dets = {
        "x.D1": DeterminationSpec(id="x.D1", description="P1.",
                                   source_span="S", composition="derived",
                                   root_node="p1"),
        "x.D2": DeterminationSpec(id="x.D2", description="P2.",
                                   source_span="S", composition="derived",
                                   root_node="p2"),
    }
    program = DeterminationProgram(
        metadata=ProgramMetadata(name="Share", version="0.1"),
        nodes=nodes, map_spec=MapSpec(atoms=atoms), determinations=dets,
        case_input_schema=CaseInputSchema(has_narrative=True),
    )
    assert validate_program(program).ok

    rt = program_to_engine(program)
    # The 'shared' sub-tree should be the SAME Python object inside both
    # p1.children[0] and p2.children[0].
    p1_tree = rt.determinations["x.D1"].tree
    p2_tree = rt.determinations["x.D2"].tree
    assert p1_tree.children[0] is p2_tree.children[0], (
        "shared sub-tree must be a single Python object in both parents"
    )

    print("test_forward_dag_sharing: OK")


def test_forward_conditional_numeric():
    """Conditional numeric: salary cap by YOS bracket.

    Mirrors a simplified slice of the NBA max_salary_by_yos pattern.
    IF (yos < 7) THEN base_cap ELSE upper_cap
    Then compare contract_salary <= selected_cap.
    """
    atoms = {
        "x.yos": NumericAtom(id="x.yos", statement="YOS.", source_span="S",
                              evaluation_mode=EvaluationMode.CHARACTERIZED),
        "x.salary": NumericAtom(id="x.salary", statement="Salary.", source_span="S",
                                 evaluation_mode=EvaluationMode.CHARACTERIZED),
    }
    nodes = {
        "yos": NumericAtomRef(node_id="yos", provenance=Provenance.TRANSCRIBED,
                                source_span="S", atom_id="x.yos"),
        "seven": ConstantSpec(node_id="seven", provenance=Provenance.STRUCTURAL,
                                literal_value=Decimal("7")),
        "under7": ComparisonSpec(node_id="under7", provenance=Provenance.STRUCTURAL,
                                   operator="lt", left="yos", right="seven"),
        "base_cap": ConstantSpec(node_id="base_cap", provenance=Provenance.TRANSCRIBED,
                                   source_span="S", literal_value=Decimal("30000000")),
        "upper_cap": ConstantSpec(node_id="upper_cap", provenance=Provenance.TRANSCRIBED,
                                    source_span="S", literal_value=Decimal("40000000")),
        "selected_cap": ConditionalNumericSpec(
            node_id="selected_cap", provenance=Provenance.STRUCTURAL,
            condition="under7", if_true="base_cap", if_false="upper_cap",
        ),
        "salary": NumericAtomRef(node_id="salary", provenance=Provenance.TRANSCRIBED,
                                   source_span="S", atom_id="x.salary"),
        "within": ComparisonSpec(node_id="within", provenance=Provenance.STRUCTURAL,
                                   operator="leq", left="salary", right="selected_cap"),
    }
    dets = {
        "x.D1": DeterminationSpec(id="x.D1", description="Salary within cap.",
                                   source_span="S", composition="derived",
                                   root_node="within"),
    }
    program = DeterminationProgram(
        metadata=ProgramMetadata(name="Cap", version="0.1"),
        nodes=nodes, map_spec=MapSpec(atoms=atoms), determinations=dets,
        case_input_schema=CaseInputSchema(has_narrative=True),
    )
    assert validate_program(program).ok
    rt = program_to_engine(program)
    det = rt.determinations["x.D1"]

    # YOS=4, salary=25M -> under7 branch (cap=30M), salary <= cap -> TRUE
    res, _ = det.evaluate(_bundle({"x.yos": 4, "x.salary": 25_000_000}))
    assert res == Kleene.TRUE

    # YOS=4, salary=35M -> under7 branch (cap=30M), salary > cap -> FALSE
    res, _ = det.evaluate(_bundle({"x.yos": 4, "x.salary": 35_000_000}))
    assert res == Kleene.FALSE

    # YOS=10, salary=35M -> upper branch (cap=40M), salary <= cap -> TRUE
    res, _ = det.evaluate(_bundle({"x.yos": 10, "x.salary": 35_000_000}))
    assert res == Kleene.TRUE

    # YOS=UND -> selected_cap UND -> within UND
    res, _ = det.evaluate(_bundle({
        "x.yos": NumericValue.undetermined(),
        "x.salary": 25_000_000,
    }))
    assert res == Kleene.UNDETERMINED

    print("test_forward_conditional_numeric: OK")


# ---------------------------------------------------------------------------
# Reverse path and round-trip tests
# ---------------------------------------------------------------------------

def test_reverse_simple_boolean():
    """Hand-build a tiny engine fragment, dump to contract, validate."""
    # AND(a, NOT(b))
    tree = AndNode(children=[
        Leaf(atom_id="x.a"),
        NotNode(child=Leaf(atom_id="x.b")),
    ])
    det = type('Det', (), {})()   # ducktype; we'll use the real Determination below

    from rulekit.engine.boolean import Determination
    eng_det = Determination(
        id="x.D1", description="A and not B.", tree=tree,
        source_span="S1",
    )
    program = engine_to_program(
        [eng_det], program_name="Reverse demo",
    )
    rpt = validate_program(program)
    assert rpt.ok, rpt.summary()
    # Two atoms: x.a (referenced by the Leaf) and x.b (under NOT).
    assert set(program.map_spec.atoms.keys()) == {"x.a", "x.b"}
    print("test_reverse_simple_boolean: OK")


def test_round_trip_equivalence_boolean():
    """Hand-build a Boolean fragment, dump to contract, run back through
    program_to_engine, evaluate against a bundle, and confirm same result
    as evaluating the original hand-built fragment.
    """
    # OR(AND(a, b), NOT(c))
    original = OrNode(children=[
        AndNode(children=[Leaf(atom_id="x.a"), Leaf(atom_id="x.b")]),
        NotNode(child=Leaf(atom_id="x.c")),
    ])
    from rulekit.engine.boolean import Determination
    orig_det = Determination(id="x.D1", description="d", tree=original,
                              source_span="S")

    program = engine_to_program([orig_det], program_name="RT demo")
    rpt = validate_program(program)
    assert rpt.ok, rpt.summary()

    rt = program_to_engine(program)
    converted = rt.determinations["x.D1"]

    test_bundles = [
        ({"x.a": "true", "x.b": "true", "x.c": "true"}, Kleene.TRUE),
        ({"x.a": "false", "x.b": "true", "x.c": "true"}, Kleene.FALSE),
        ({"x.a": "false", "x.b": "true", "x.c": "false"}, Kleene.TRUE),
        ({"x.a": "true", "x.b": "undetermined", "x.c": "true"}, Kleene.UNDETERMINED),
    ]
    for facts, expected in test_bundles:
        bundle = _bundle(facts)
        orig_result, _ = orig_det.evaluate(bundle)
        converted_result, _ = converted.evaluate(bundle)
        assert orig_result == expected, (facts, orig_result, expected)
        assert converted_result == expected, (facts, converted_result, expected)
        assert orig_result == converted_result, (facts, orig_result, converted_result)
    print("test_round_trip_equivalence_boolean: OK")


def test_round_trip_equivalence_typed():
    """Hand-build a typed fragment with a comparison and a labeled
    constant, dump to contract, run back through, confirm same answer.
    """
    # LeqNode(NumericLeaf(days), Constant(60, label="sixty"))
    original = LeqNode(
        left=NumericLeaf(atom_id="fcba.days"),
        right=Constant(value=Decimal("60"), label="sixty"),
        surface_label="timely",
    )
    from rulekit.engine.boolean import Determination
    orig_det = Determination(id="fcba.D1", description="Timely.",
                              tree=original, source_span="S")

    # engine_to_program needs to know about constants to label them
    program = engine_to_program(
        [orig_det], program_name="FCBA timing RT",
    )
    # The constant gets pulled into program.constants by engine_to_program
    assert "sixty" in program.constants
    assert program.constants["sixty"] == Decimal("60")

    # The atom needs evaluation_mode set; engine_to_program defaults to
    # CHARACTERIZED. That's fine for validation.
    rpt = validate_program(program)
    assert rpt.ok, rpt.summary()

    rt = program_to_engine(program)
    converted = rt.determinations["fcba.D1"]

    for days, expected in [(30, Kleene.TRUE), (60, Kleene.TRUE), (75, Kleene.FALSE)]:
        bundle = _bundle({"fcba.days": days})
        orig_result, _ = orig_det.evaluate(bundle)
        converted_result, _ = converted.evaluate(bundle)
        assert orig_result == expected
        assert converted_result == expected
    print("test_round_trip_equivalence_typed: OK")


def test_round_trip_preserves_sharing():
    """A hand-built engine fragment with a shared sub-tree (same Python
    object referenced twice) round-trips to a contract program whose
    converted form also has shared references.
    """
    shared = AndNode(children=[Leaf(atom_id="x.a"), Leaf(atom_id="x.b")])
    p1 = AndNode(children=[shared, Leaf(atom_id="x.c")])
    p2 = OrNode(children=[shared, Leaf(atom_id="x.c")])

    from rulekit.engine.boolean import Determination
    d1 = Determination(id="x.D1", description="P1", tree=p1, source_span="S")
    d2 = Determination(id="x.D2", description="P2", tree=p2, source_span="S")

    program = engine_to_program([d1, d2], program_name="Shared RT")
    rpt = validate_program(program)
    assert rpt.ok, rpt.summary()

    # The contract program should have ONE NodeId for the shared
    # sub-tree, referenced by both d1's and d2's roots.
    p1_root = program.determinations["x.D1"].root_node
    p2_root = program.determinations["x.D2"].root_node
    p1_first_child = program.nodes[p1_root].children[0]
    p2_first_child = program.nodes[p2_root].children[0]
    assert p1_first_child == p2_first_child, (
        "shared sub-tree must have the same NodeId in both parents"
    )

    # Run program_to_engine and confirm sharing is preserved
    rt = program_to_engine(program)
    rt_p1 = rt.determinations["x.D1"].tree
    rt_p2 = rt.determinations["x.D2"].tree
    assert rt_p1.children[0] is rt_p2.children[0], (
        "shared sub-tree must remain a single Python object after round-trip"
    )

    print("test_round_trip_preserves_sharing: OK")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_forward_boolean_minimal,
        test_forward_complement,
        test_forward_typed_comparison_with_constant_label,
        test_forward_dag_sharing,
        test_forward_conditional_numeric,
        test_reverse_simple_boolean,
        test_round_trip_equivalence_boolean,
        test_round_trip_equivalence_typed,
        test_round_trip_preserves_sharing,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"{t.__name__}: FAIL — {e}")
            failed += 1
        except Exception as e:
            import traceback
            print(f"{t.__name__}: ERROR — {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    if failed:
        print(f"\n{failed}/{len(tests)} tests failed")
        sys.exit(1)
    print(f"\nall {len(tests)} tests passed")
