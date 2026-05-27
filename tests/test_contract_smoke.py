"""
Smoke tests for the contract module.

Exercises model construction, JSON round-trip, and the cross-model
validators. Designed to be run with plain `python tests/test_contract_smoke.py`
without pytest — keeps the test surface small while the contract is
being introduced.

When the existing test suite is migrated, these checks should be
absorbed into proper unit tests under `tests/test_contract_*.py`.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal


sys.path.insert(0, ".")  # so `rulekit` resolves when run from repo root


from rulekit.contract import (
    AndNodeSpec,
    AtomRef,
    BinaryArithmeticSpec,
    BooleanAtom,
    CaseInput,
    CaseInputSchema,
    ComparisonSpec,
    ConditionalNumericSpec,
    ConstantSpec,
    DeterminationProgram,
    DeterminationSpec,
    EvaluationMode,
    ExpectedOutcome,
    MapSpec,
    NamedQuantitySpec,
    NotNodeSpec,
    NumericAtom,
    NumericAtomRef,
    OrNodeSpec,
    ProductionRecord,
    ProgramMetadata,
    Provenance,
    TestCase,
    UnaryArithmeticSpec,
    VariadicArithmeticSpec,
    validate_program,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def build_minimal_valid_program() -> DeterminationProgram:
    """The smallest interesting program: one AND over two boolean atoms,
    one determination, one test case. Should pass all validators.
    """
    atoms = {
        "demo.a": BooleanAtom(
            id="demo.a", statement="A holds.", source_span="S1",
            evaluation_mode=EvaluationMode.CHARACTERIZED,
        ),
        "demo.b": BooleanAtom(
            id="demo.b", statement="B holds.", source_span="S2",
            evaluation_mode=EvaluationMode.CHARACTERIZED,
        ),
    }
    nodes = {
        "n1": AtomRef(node_id="n1", provenance=Provenance.TRANSCRIBED,
                       source_span="S1", atom_id="demo.a"),
        "n2": AtomRef(node_id="n2", provenance=Provenance.TRANSCRIBED,
                       source_span="S2", atom_id="demo.b"),
        "n3": AndNodeSpec(node_id="n3", provenance=Provenance.STRUCTURAL,
                           children=["n1", "n2"]),
    }
    dets = {
        "demo.D1": DeterminationSpec(
            id="demo.D1", description="Both hold.", source_span="Sec1",
            composition="derived", root_node="n3",
        ),
        "demo.D2": DeterminationSpec(
            id="demo.D2", description="At least one fails.",
            source_span="Sec1", composition="complement", linked_to="demo.D1",
        ),
    }
    tcs = [
        TestCase(
            case_id="c1",
            input=CaseInput(case_id="c1", narrative="A and B both hold."),
            expected_outcomes=[
                ExpectedOutcome(determination_id="demo.D1",
                                 expected_value="true"),
            ],
        ),
    ]
    return DeterminationProgram(
        metadata=ProgramMetadata(name="Demo", version="0.1"),
        nodes=nodes,
        map_spec=MapSpec(atoms=atoms),
        determinations=dets,
        case_input_schema=CaseInputSchema(has_narrative=True),
        test_cases=tcs,
    )


def build_typed_program() -> DeterminationProgram:
    """A program exercising numeric atoms, constants, comparison,
    conditional numeric. Mirrors the FCBA notice-validity pattern from
    the hand-built test:
        timely := days_between_first_statement_and_notice <= 60
        content_complete := dollar_amount AND reason AND type AND date
        valid := timely AND content_complete
    """
    atoms = {
        "fcba.days": NumericAtom(
            id="fcba.days",
            statement="Days between first statement and notice.",
            source_span="1026.13(b)",
            evaluation_mode=EvaluationMode.CHARACTERIZED,
            numeric_unit="days",
        ),
        "fcba.dollar": BooleanAtom(
            id="fcba.dollar", statement="Notice states dollar amount.",
            source_span="1026.13(b)(2)",
            evaluation_mode=EvaluationMode.CHARACTERIZED,
        ),
        "fcba.reason": BooleanAtom(
            id="fcba.reason", statement="Notice states reason for belief.",
            source_span="1026.13(b)(3)",
            evaluation_mode=EvaluationMode.CHARACTERIZED,
        ),
    }
    nodes = {
        "days": NumericAtomRef(
            node_id="days", provenance=Provenance.TRANSCRIBED,
            source_span="1026.13(b)", atom_id="fcba.days",
        ),
        "sixty": ConstantSpec(
            node_id="sixty", provenance=Provenance.TRANSCRIBED,
            source_span="1026.13(b)", literal_value=Decimal("60"),
        ),
        "timely": ComparisonSpec(
            node_id="timely", provenance=Provenance.TRANSCRIBED,
            source_span="1026.13(b)", operator="leq",
            left="days", right="sixty",
        ),
        "dollar": AtomRef(
            node_id="dollar", provenance=Provenance.TRANSCRIBED,
            source_span="1026.13(b)(2)", atom_id="fcba.dollar",
        ),
        "reason": AtomRef(
            node_id="reason", provenance=Provenance.TRANSCRIBED,
            source_span="1026.13(b)(3)", atom_id="fcba.reason",
        ),
        "content": AndNodeSpec(
            node_id="content", provenance=Provenance.STRUCTURAL,
            children=["dollar", "reason"],
        ),
        "valid": AndNodeSpec(
            node_id="valid", provenance=Provenance.STRUCTURAL,
            children=["timely", "content"],
        ),
    }
    dets = {
        "fcba.D1": DeterminationSpec(
            id="fcba.D1", description="Notice is valid under 1026.13(b).",
            source_span="1026.13(b)", composition="derived", root_node="valid",
        ),
    }
    return DeterminationProgram(
        metadata=ProgramMetadata(name="FCBA notice subset", version="0.1"),
        nodes=nodes,
        map_spec=MapSpec(atoms=atoms),
        determinations=dets,
        case_input_schema=CaseInputSchema(has_narrative=True),
        test_cases=[],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_minimal_valid_program_passes():
    prog = build_minimal_valid_program()
    report = validate_program(prog)
    assert report.ok, report.summary()
    print("test_minimal_valid_program_passes: OK")


def test_round_trip_preserves_subclasses():
    prog = build_minimal_valid_program()
    js = prog.model_dump_json()
    prog2 = DeterminationProgram.model_validate_json(js)
    assert prog == prog2
    assert type(prog2.map_spec.atoms["demo.a"]).__name__ == "BooleanAtom"
    assert type(prog2.nodes["n3"]).__name__ == "AndNodeSpec"
    print("test_round_trip_preserves_subclasses: OK")


def test_typed_program_passes():
    prog = build_typed_program()
    report = validate_program(prog)
    assert report.ok, report.summary()
    print("test_typed_program_passes: OK")


def test_typed_program_round_trip():
    prog = build_typed_program()
    js = prog.model_dump_json()
    prog2 = DeterminationProgram.model_validate_json(js)
    assert prog == prog2
    # Concrete subclasses preserved
    assert type(prog2.nodes["timely"]).__name__ == "ComparisonSpec"
    assert type(prog2.nodes["sixty"]).__name__ == "ConstantSpec"
    assert prog2.nodes["sixty"].literal_value == Decimal("60")
    print("test_typed_program_round_trip: OK")


def test_atom_ref_to_missing_atom_fails():
    prog = build_minimal_valid_program()
    # Replace n1 with an AtomRef pointing to a nonexistent atom
    prog.nodes["n1"] = AtomRef(
        node_id="n1", provenance=Provenance.TRANSCRIBED,
        source_span="S1", atom_id="demo.ghost",
    )
    report = validate_program(prog)
    assert not report.ok
    assert any("demo.ghost" in e for e in report.errors), report.summary()
    print("test_atom_ref_to_missing_atom_fails: OK")


def test_atom_ref_to_wrong_type_fails():
    prog = build_typed_program()
    # Make 'dollar' (currently boolean) accidentally point to a numeric atom
    prog.nodes["dollar"] = AtomRef(
        node_id="dollar", provenance=Provenance.TRANSCRIBED,
        source_span="x", atom_id="fcba.days",   # numeric atom
    )
    report = validate_program(prog)
    assert not report.ok
    assert any("must reference a boolean atom" in e for e in report.errors), report.summary()
    print("test_atom_ref_to_wrong_type_fails: OK")


def test_node_ref_to_missing_node_fails():
    prog = build_minimal_valid_program()
    prog.nodes["n3"] = AndNodeSpec(
        node_id="n3", provenance=Provenance.STRUCTURAL,
        children=["n1", "ghost"],
    )
    report = validate_program(prog)
    assert not report.ok
    assert any("'ghost'" in e for e in report.errors), report.summary()
    print("test_node_ref_to_missing_node_fails: OK")


def test_comparison_with_boolean_operand_fails():
    prog = build_typed_program()
    # Swap the comparison's left operand to a boolean node
    prog.nodes["timely"] = ComparisonSpec(
        node_id="timely", provenance=Provenance.TRANSCRIBED,
        source_span="x", operator="leq",
        left="dollar",  # boolean!
        right="sixty",
    )
    report = validate_program(prog)
    assert not report.ok
    assert any("not numeric-valued" in e for e in report.errors), report.summary()
    print("test_comparison_with_boolean_operand_fails: OK")


def test_cycle_detected():
    """Two-node cycle: A -> B -> A."""
    atoms = {
        "demo.x": BooleanAtom(
            id="demo.x", statement="X.", source_span="S",
            evaluation_mode=EvaluationMode.CHARACTERIZED,
        ),
    }
    # Build cycle via NotNodeSpec(child=Not(child=...))
    # AndNodeSpec accepts a list of NodeRefs; we can make A point to B and B point to A.
    nodes = {
        "leaf": AtomRef(node_id="leaf", provenance=Provenance.TRANSCRIBED,
                        source_span="S", atom_id="demo.x"),
        "A": AndNodeSpec(node_id="A", provenance=Provenance.STRUCTURAL,
                         children=["B", "leaf"]),
        "B": AndNodeSpec(node_id="B", provenance=Provenance.STRUCTURAL,
                         children=["A", "leaf"]),
    }
    dets = {
        "demo.D1": DeterminationSpec(
            id="demo.D1", description="x", source_span="S",
            composition="derived", root_node="A",
        ),
    }
    prog = DeterminationProgram(
        metadata=ProgramMetadata(name="Cyc", version="0.1"),
        nodes=nodes,
        map_spec=MapSpec(atoms=atoms),
        determinations=dets,
    )
    report = validate_program(prog)
    assert not report.ok
    assert any("cycle" in e for e in report.errors), report.summary()
    print("test_cycle_detected: OK")


def test_orphan_node_is_error_by_default():
    prog = build_minimal_valid_program()
    # Add an unreachable extra node
    prog.nodes["orphan"] = AtomRef(
        node_id="orphan", provenance=Provenance.TRANSCRIBED,
        source_span="S", atom_id="demo.a",
    )
    report = validate_program(prog)
    assert not report.ok
    assert any("orphan" in e for e in report.errors), report.summary()
    # And as warning when allowed
    report2 = validate_program(prog, orphans_are_errors=False)
    assert report2.ok
    assert any("orphan" in w for w in report2.warnings), report2.summary()
    print("test_orphan_node_is_error_by_default: OK")


def test_constant_label_resolution():
    atoms = {
        "x.q": NumericAtom(
            id="x.q", statement="Q.", source_span="S",
            evaluation_mode=EvaluationMode.CHARACTERIZED,
        ),
    }
    nodes = {
        "q": NumericAtomRef(node_id="q", provenance=Provenance.TRANSCRIBED,
                             source_span="S", atom_id="x.q"),
        "k": ConstantSpec(node_id="k", provenance=Provenance.TRANSCRIBED,
                          source_span="S", constant_label="threshold"),
        "cmp": ComparisonSpec(node_id="cmp", provenance=Provenance.TRANSCRIBED,
                              source_span="S", operator="leq",
                              left="q", right="k"),
    }
    dets = {
        "x.D1": DeterminationSpec(
            id="x.D1", description="Q below threshold.", source_span="S",
            composition="derived", root_node="cmp",
        ),
    }
    # Missing constant
    prog = DeterminationProgram(
        metadata=ProgramMetadata(name="K", version="0.1"),
        nodes=nodes,
        map_spec=MapSpec(atoms=atoms),
        determinations=dets,
    )
    report = validate_program(prog)
    assert not report.ok
    assert any("threshold" in e for e in report.errors), report.summary()

    # Now provide the constant
    prog2 = prog.model_copy(update={"constants": {"threshold": Decimal("60")}})
    report2 = validate_program(prog2)
    assert report2.ok, report2.summary()
    print("test_constant_label_resolution: OK")


def test_named_quantity_must_be_computed_or_lookup():
    """NamedQuantitySpec referencing an atom with evaluation_mode=CHARACTERIZED
    should fail validation."""
    atoms = {
        "x.q": NumericAtom(
            id="x.q", statement="Q.", source_span="S",
            evaluation_mode=EvaluationMode.CHARACTERIZED,  # wrong for NQ
        ),
    }
    nodes = {
        "nq": NamedQuantitySpec(
            node_id="nq", provenance=Provenance.TRANSCRIBED, source_span="S",
            atom_id="x.q",
        ),
        "k": ConstantSpec(node_id="k", provenance=Provenance.STRUCTURAL,
                          literal_value=Decimal("100")),
        "cmp": ComparisonSpec(node_id="cmp", provenance=Provenance.TRANSCRIBED,
                              source_span="S", operator="leq",
                              left="nq", right="k"),
    }
    dets = {
        "x.D1": DeterminationSpec(
            id="x.D1", description="Q below k.", source_span="S",
            composition="derived", root_node="cmp",
        ),
    }
    prog = DeterminationProgram(
        metadata=ProgramMetadata(name="NQ", version="0.1"),
        nodes=nodes,
        map_spec=MapSpec(atoms=atoms),
        determinations=dets,
    )
    report = validate_program(prog)
    assert not report.ok
    assert any("evaluation_mode" in e and "x.q" in e for e in report.errors), report.summary()
    print("test_named_quantity_must_be_computed_or_lookup: OK")


def test_complement_link_validation():
    prog = build_minimal_valid_program()
    # Self-reference
    prog.determinations["demo.D2"] = DeterminationSpec(
        id="demo.D2", description="self complement",
        composition="complement", linked_to="demo.D2",
    )
    report = validate_program(prog)
    assert not report.ok
    assert any("link to itself" in e for e in report.errors), report.summary()
    print("test_complement_link_validation: OK")


def test_test_case_conformance():
    prog = build_minimal_valid_program()
    # Add a test case referencing a non-existent determination
    prog.test_cases.append(TestCase(
        case_id="bad", input=CaseInput(case_id="bad", narrative="x"),
        expected_outcomes=[
            ExpectedOutcome(determination_id="demo.ghost", expected_value="true"),
        ],
    ))
    report = validate_program(prog)
    assert not report.ok
    assert any("demo.ghost" in e for e in report.errors), report.summary()
    print("test_test_case_conformance: OK")


def test_test_case_structured_fields_must_be_declared():
    atoms = {
        "x.a": BooleanAtom(id="x.a", statement="A.", source_span="S",
                           evaluation_mode=EvaluationMode.CHARACTERIZED),
    }
    nodes = {
        "n1": AtomRef(node_id="n1", provenance=Provenance.TRANSCRIBED,
                      source_span="S", atom_id="x.a"),
    }
    dets = {"x.D1": DeterminationSpec(id="x.D1", description="A.",
                                       source_span="S",
                                       composition="derived", root_node="n1")}
    schema = CaseInputSchema(
        has_narrative=False, structured_fields={"yos": "number"}
    )
    tc = TestCase(
        case_id="t1",
        input=CaseInput(case_id="t1", structured={"yos": 5, "extra": 1}),
        expected_outcomes=[ExpectedOutcome(determination_id="x.D1",
                                            expected_value="true")],
    )
    prog = DeterminationProgram(
        metadata=ProgramMetadata(name="S", version="0.1"),
        nodes=nodes, map_spec=MapSpec(atoms=atoms),
        determinations=dets, case_input_schema=schema, test_cases=[tc],
    )
    report = validate_program(prog)
    assert not report.ok
    assert any("extra" in e for e in report.errors), report.summary()
    print("test_test_case_structured_fields_must_be_declared: OK")


# ---------------------------------------------------------------------------
# Run all
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_minimal_valid_program_passes,
        test_round_trip_preserves_subclasses,
        test_typed_program_passes,
        test_typed_program_round_trip,
        test_atom_ref_to_missing_atom_fails,
        test_atom_ref_to_wrong_type_fails,
        test_node_ref_to_missing_node_fails,
        test_comparison_with_boolean_operand_fails,
        test_cycle_detected,
        test_orphan_node_is_error_by_default,
        test_constant_label_resolution,
        test_named_quantity_must_be_computed_or_lookup,
        test_complement_link_validation,
        test_test_case_conformance,
        test_test_case_structured_fields_must_be_declared,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            print(f"{t.__name__}: FAIL — {e}")
            failed += 1
        except Exception as e:
            print(f"{t.__name__}: ERROR — {type(e).__name__}: {e}")
            failed += 1
    if failed:
        print(f"\n{failed}/{len(tests)} tests failed")
        sys.exit(1)
    print(f"\nall {len(tests)} tests passed")
